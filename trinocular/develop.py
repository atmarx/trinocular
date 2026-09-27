"""Turn an unpacked sweep into things a person can look at.

Per color camera (cam0 up, cam1 level, cam2 down): the six frames are six
headings 60° apart, so lay them side by side as a ring.  No stitching yet.
Per depth sensor (0 up, 1 level, 2 down): turbo-colored depth strip and an IR
strip, 3600 px = 360° of azimuth, flipped to run the same way as the rings.
Everything lands next to the raw parts as JPEGs plus a small manifest.
"""
import glob
import json
import os

import cv2
import numpy as np

THUMB_W = 480
RING_H = 720        # ring height; 6 frames at 4:3 -> 5760 px wide
# Frames come off the sensor upright (landscape) on a mounted Pro2.  The old
# "portrait, rotate cw" came from sweeps shot with the rig on its side.
ROTATE = {"cw": cv2.ROTATE_90_CLOCKWISE, "ccw": cv2.ROTATE_90_COUNTERCLOCKWISE,
          "180": cv2.ROTATE_180}.get(os.environ.get("TRINOCULAR_ROTATE", "none"))


def _wb_gains(stack):
    # Gray world over the whole stack — the per-frame WB coefficients in
    # field 14 are the proper fix once we know their order.
    m = np.mean([f.reshape(-1, 3).mean(0) for f in stack], axis=0)
    return m.mean() / np.maximum(m, 1e-6)


def ring(tifs):
    """Six 16-bit RGB headings -> one 8-bit BGR strip, frames side by side.

    Frames come off the camera already auto-exposed (their means barely move),
    and dividing by the protobuf's exposure x gain makes a uniform rug swing
    30x, so those numbers don't map to frames the way we'd assume.  Shared
    white balance, per-frame stretch.
    """
    frames = [cv2.imread(t, cv2.IMREAD_UNCHANGED) for t in tifs]
    frames = [f.astype(np.float32) for f in frames if f is not None]
    if not frames:
        return None
    gains = _wb_gains(frames)
    out = []
    for f in frames:
        f *= gains
        lo, hi = np.percentile(f[::4, ::4], (0.5, 99.7))
        f = np.power(np.clip((f - lo) / max(hi - lo, 1e-6), 0, 1), 1 / 1.8)
        f = (f * 255).astype(np.uint8)
        if ROTATE is not None:
            f = cv2.rotate(f, ROTATE)
        h, w = f.shape[:2]
        out.append(cv2.resize(f, (w * RING_H // h, RING_H), interpolation=cv2.INTER_AREA))
    return np.hstack(out)


def depth_strip(path):
    d = _flip(cv2.imread(path, cv2.IMREAD_UNCHANGED))
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


def _flip(img):
    # Raw depth columns run opposite to the color frame order (couch, chair,
    # desk, chair left-to-right in depth = color f5..f2).  Flip for display so
    # both read the same way; the PNGs on disk stay as the camera sent them.
    return None if img is None else cv2.flip(img, 1)


def blend(depth_img, valid, ir):
    """Depth hue over IR texture — same sensor, same pixel grid, no registration."""
    ir = cv2.equalizeHist(ir).astype(np.float32)[..., None] / 255
    out = depth_img.astype(np.float32) * (0.25 + 0.75 * ir)
    out[~valid] = ir[~valid] * 90   # keep texture where depth dropped out
    return out.astype(np.uint8)


def _save(img, path, quality=90, thumb_w=THUMB_W):
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    h, w = img.shape[:2]
    t = cv2.resize(img, (thumb_w, max(1, h * thumb_w // w)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(path.replace(".jpg", ".thumb.jpg"), t, [cv2.IMWRITE_JPEG_QUALITY, 82])


def develop(d):
    """Process an unpacked sweep dir in place.  Returns the manifest dict."""
    man = {"rings": [], "depth": [], "ir": [], "blend": []}
    cams = sorted({os.path.basename(p).split("_")[0] for p in glob.glob(f"{d}/cam*_f*.tif")})
    for cam in cams:
        img = ring(sorted(glob.glob(f"{d}/{cam}_f*.tif")))
        if img is not None:
            _save(img, f"{d}/{cam}_ring.jpg", thumb_w=1600)
            man["rings"].append(f"{cam}_ring.jpg")
    for rng in sorted(glob.glob(f"{d}/depth*_range.png")):
        s = os.path.basename(rng).split("_")[0]
        img, cov, valid = depth_strip(rng)
        if img is not None:
            _save(img, f"{d}/{s}_depth.jpg")
            man["depth"].append({"file": f"{s}_depth.jpg", "coverage": round(cov, 3)})
        ir = _flip(cv2.imread(f"{d}/{s}_ir.png", cv2.IMREAD_GRAYSCALE))
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
