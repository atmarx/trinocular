#!/usr/bin/env python3
"""sweepfmt - Parse a Pro2 /getSweep protobuf and unpack it into plain files.

CLI:  python3 -m trinocular.sweepfmt sweep-<uuid>.bin [outdir]

Writes, per depth sensor s (field 5) and color camera c (field 6):
  depth{s}_range.png   16-bit depth map, 3600 x ~458
  depth{s}_ir.png      8-bit IR intensity
  depth{s}_aux.png     8-bit third channel (confidence/pattern?)
  depth{s}_thumb.jpg   3600 x ~458 strip (all black on FW 1.1.620)
  cam{c}_f{j}.jxr      color frame j (JPEG XR, 2560x1920, sensor is portrait-rotated)
  cam{c}_f{j}.tif      decoded 16-bit RGB, if JxrDecApp (libjxr-tools) is on PATH
  meta.txt             serials, FOV, per-frame exposure/gain

Stdlib only.  Field numbers per PROTOCOL.md.
"""
import os
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass, field


def varint(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def walk(b):
    """Flat protobuf decode: list of (field, wiretype, value)."""
    i, out = 0, []
    while i < len(b):
        k, i = varint(b, i)
        f, t = k >> 3, k & 7
        if t == 0:
            v, i = varint(b, i)
        elif t == 1:
            v, i = b[i:i + 8], i + 8
        elif t == 5:
            v, i = struct.unpack("<f", b[i:i + 4])[0], i + 4
        elif t == 2:
            n, i = varint(b, i)
            v, i = b[i:i + n], i + n
        else:
            raise ValueError(f"wire type {t} at offset {i}")
        out.append((f, t, v))
    return out


@dataclass
class ColorCam:
    serial: str
    fov: float
    frames: list          # raw JPEG XR bytes
    exposure: list        # seconds, per frame
    gain: list


@dataclass
class Sweep:
    depth: list = field(default_factory=list)   # dicts: range/ir/aux/thumb -> bytes
    color: list = field(default_factory=list)   # ColorCam


DEPTH_PARTS = {4: "range.png", 5: "ir.png", 6: "aux.png", 7: "thumb.jpg"}


def parse(data: bytes) -> Sweep:
    sw = Sweep()
    for f, _, v in walk(data):
        if f == 5:
            sw.depth.append({DEPTH_PARTS[sf]: sv for sf, _, sv in walk(v) if sf in DEPTH_PARTS})
        elif f == 6:
            sub = walk(v)
            sw.color.append(ColorCam(
                serial=next((x.decode() for sf, _, x in sub if sf == 1), "?"),
                fov=next((x for sf, _, x in sub if sf == 4), 0.0),
                frames=[x for sf, _, x in sub if sf == 5],
                exposure=[x for sf, _, x in sub if sf == 11],
                gain=[x for sf, _, x in sub if sf == 12],
            ))
    return sw


def decode_jxr(src, dst):
    """JPEG XR -> 16-bit RGB TIFF.  Returns False if JxrDecApp is missing or fails."""
    jxr = shutil.which("JxrDecApp")
    if not jxr:
        return False
    r = subprocess.run([jxr, "-i", src, "-o", dst],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0 and os.path.exists(dst)


def unpack(sw: Sweep, out: str, decode=True):
    """Write every part of a parsed sweep to `out`.  Returns meta lines."""
    os.makedirs(out, exist_ok=True)
    meta = []
    for s, parts in enumerate(sw.depth):
        for name, blob in parts.items():
            open(os.path.join(out, f"depth{s}_{name}"), "wb").write(blob)
    for c, cam in enumerate(sw.color):
        meta.append(f"cam{c} serial={cam.serial} fov={cam.fov:.4f}rad frames={len(cam.frames)}")
        for j, fr in enumerate(cam.frames):
            p = os.path.join(out, f"cam{c}_f{j}.jxr")
            open(p, "wb").write(fr)
            e = cam.exposure[j] if j < len(cam.exposure) else float("nan")
            g = cam.gain[j] if j < len(cam.gain) else float("nan")
            meta.append(f"  f{j} exposure={e:.5f}s gain={g:.3f} bytes={len(fr)}")
            if decode:
                decode_jxr(p, p[:-4] + ".tif")
    open(os.path.join(out, "meta.txt"), "w").write("\n".join(meta) + "\n")
    return meta


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0]
    sw = parse(open(src, "rb").read())
    print("\n".join(unpack(sw, out)))
    print(f"{len(sw.depth)} depth sensors, {len(sw.color)} color cameras -> {out}/"
          + ("" if shutil.which("JxrDecApp") else "  (JxrDecApp not found; .jxr left undecoded)"))


if __name__ == "__main__":
    main()
