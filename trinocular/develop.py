"""Turn an unpacked sweep into things a person can look at.

Per color camera: white-balance the six frames, fuse them (Mertens —
no response curve needed, works straight off the raw stack), rotate upright.
Per depth sensor: turbo-colored depth strip and an IR strip (3600 px wide,
probably 0.1°/column of azimuth — see PROTOCOL.md).

CAVEAT: the fusion assumes the six frames are one exposure stack at one
heading.  That's what they looked like from a Pro2 that never rotated; on a
mounted sweep they are more likely six 60° headings, and fusing them would
smear six views together.  See "What the six frames per camera are".
Everything lands next to the raw parts as JPEGs plus a small manifest.
"""
import glob
import json
import os

import cv2
import numpy as np

THUMB_W = 480
# Sensors are mounted portrait.  cw was upright on our (unmounted) sweeps, which
# were shot with the rig on its side — so this stays a knob until confirmed.
ROTATE = {"cw": cv2.ROTATE_90_CLOCKWISE, "ccw": cv2.ROTATE_90_COUNTERCLOCKWISE,
          "180": cv2.ROTATE_180}.get(os.environ.get("TRINOCULAR_ROTATE", "cw"))


def _wb_gains(stack):
    # Gray world over the whole stack — the per-frame WB coefficients in
    # field 14 are the proper fix once we know their order.
    m = np.mean([f.reshape(-1, 3).mean(0) for f in stack], axis=0)
    return m.mean() / np.maximum(m, 1e-6)


def fuse_camera(tifs):
    """Six 16-bit RGB exposures -> one upright 8-bit BGR image."""
    stack = [cv2.imread(t, cv2.IMREAD_UNCHANGED) for t in tifs]
    stack = [s for s in stack if s is not None]
    if not stack:
        return None
    gains = _wb_gains(stack)
    eight = [np.clip(s.astype(np.float32) * gains / 256, 0, 255).astype(np.uint8)
             for s in stack]
    if len(eight) > 1:
        fused = cv2.createMergeMertens().process(eight)
        # Mertens output is ~[0,1] but tends flat; stretch before gamma.
        lo, hi = np.percentile(fused, (0.5, 99.7))
        fused = np.clip((fused - lo) / max(hi - lo, 1e-6), 0, 1)
    else:
        fused = eight[0].astype(np.float32) / 255
    out = (np.power(fused, 1 / 1.4) * 255).astype(np.uint8)
    return cv2.rotate(out, ROTATE) if ROTATE is not None else out


def depth_strip(path):
    d = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if d is None:
        return None, 0.0, None
    valid = d > 0
    if not valid.any():
        return None, 0.0, None
    lo, hi = np.percentile(d[valid], (2, 98))
    n = np.clip((d.astype(np.float32) - lo) / max(hi - lo, 1), 0, 1)
    img = cv2.applyColorMap(((1 - n) * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    img[~valid] = 0
    return img, float(valid.mean()), valid


def blend(depth_img, valid, ir):
    """Depth hue over IR texture — same sensor, same pixel grid, no registration."""
    ir = cv2.equalizeHist(ir).astype(np.float32)[..., None] / 255
    out = depth_img.astype(np.float32) * (0.25 + 0.75 * ir)
    out[~valid] = ir[~valid] * 90   # keep texture where depth dropped out
    return out.astype(np.uint8)


def _save(img, path, quality=90):
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    h, w = img.shape[:2]
    t = cv2.resize(img, (THUMB_W, max(1, h * THUMB_W // w)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(path.replace(".jpg", ".thumb.jpg"), t, [cv2.IMWRITE_JPEG_QUALITY, 82])


def develop(d):
    """Process an unpacked sweep dir in place.  Returns the manifest dict."""
    man = {"color": [], "depth": [], "ir": [], "blend": []}
    cams = sorted({os.path.basename(p).split("_")[0] for p in glob.glob(f"{d}/cam*_f*.tif")})
    for cam in cams:
        img = fuse_camera(sorted(glob.glob(f"{d}/{cam}_f*.tif")))
        if img is not None:
            _save(img, f"{d}/{cam}.jpg")
            man["color"].append(f"{cam}.jpg")
    for rng in sorted(glob.glob(f"{d}/depth*_range.png")):
        s = os.path.basename(rng).split("_")[0]
        img, cov, valid = depth_strip(rng)
        if img is not None:
            _save(img, f"{d}/{s}_depth.jpg")
            man["depth"].append({"file": f"{s}_depth.jpg", "coverage": round(cov, 3)})
        ir = cv2.imread(f"{d}/{s}_ir.png", cv2.IMREAD_GRAYSCALE)
        if ir is not None:
            _save(cv2.cvtColor(ir, cv2.COLOR_GRAY2BGR), f"{d}/{s}_ir.jpg")
            man["ir"].append(f"{s}_ir.jpg")
            if img is not None and ir.shape == img.shape[:2]:
                _save(blend(img, valid, ir), f"{d}/{s}_blend.jpg")
                man["blend"].append(f"{s}_blend.jpg")
    # The decoded TIFFs are ~28MB each; the .jxr originals stay, those go.
    for t in glob.glob(f"{d}/cam*_f*.tif"):
        os.remove(t)
    json.dump(man, open(f"{d}/develop.json", "w"))
    return man
