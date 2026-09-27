# trinocular

Talk to your Matterport Pro2 directly: the local API, the raw sweep format, and
a small web app that fires sweeps and shows you what the sensors saw.  No
Matterport cloud, no subscription, no phone.

The Pro2 (MC250) is a tripod-mounted 3D camera with three color cameras and
three depth sensors stacked vertically.  Officially it only talks to the
Matterport Capture app, which ships everything off to Matterport's cloud to
get processed.  But underneath, it's an nginx server on its own open WiFi
network, speaking HTTPS to anyone holding the right client certificate.  And
that certificate ships inside every copy of the app.

## What's here

| Path | What it does |
|------|--------------|
| [`PROTOCOL.md`](PROTOCOL.md) | The API: endpoints, the mTLS setup, status/blocked/sweep enums, the scan workflow, and the `/getSweep` protobuf layout |
| [`pro2.sh`](pro2.sh) | curl wrapper — `./pro2.sh state`, `sweep`, `get`, `logs` |
| [`trinocular/sweepfmt.py`](trinocular/sweepfmt.py) | Stdlib-only parser: sweep `.bin` → depth PNGs, IR PNGs, JPEG XR color frames, metadata |
| [`trinocular/`](trinocular/) | Web app (FastAPI): fire a sweep, pull it, develop it, browse the feed |
| [`contrib/wifi-relay/`](contrib/wifi-relay/) | For when the server can't join the camera's WiFi itself |
| [`certs/`](certs/README.md) | Empty — how to pull the keys from the APK yourself |

## Status

This is from **one camera** on firmware `1.1.620`.

Works:

- mTLS handshake, `/getState`, `/startSweep`, `/cancelSweep`, `/getSweep`, `/getAllLogs`
- Parsing the sweep container: 3 depth sensors (16-bit range + IR per sensor)
  and 3 color cameras (6 JPEG XR frames each, 2560×1920, 16-bit RGB)
- The web app, end to end, including importing `.bin` files the app captured

Not yet confirmed — **read before you build on it**:

- **What the six color frames per camera are.**  Probably six headings 60°
  apart; possibly an exposure stack.  The web app currently fuses them as a
  stack, which is wrong if they're headings.
- **Depth axes and units.**  The strips are 3600 px wide, very likely
  0.1°/column of azimuth.  Units unknown.

Both are unconfirmed for the same embarrassing reason — see *Mount it* below.

Missing on FW 1.1.620: `/setTime`, `/getImage`, `/powerCycle`, `/getCapabilities`
(all 404).

## Quick start

1. **Certs.**  Put the three files from the Capture APK in `certs/` — see
   [certs/README.md](certs/README.md).
2. **Join the camera's WiFi** (`Matterport <serial>`, open).  The camera is
   `10.77.80.1`.
3. **Say hello:**

   ```bash
   ./pro2.sh state
   ```

   A non-zero `blockedFlags` means it won't sweep yet: unplug the charger (yes,
   really), wait for warm-up, check the battery.  Decoder table in PROTOCOL.md.

4. **Fire one.**  It's loud — about 15 seconds of clicks and whirs.

   ```bash
   U=$(uuidgen); ./pro2.sh sweep $U 2      # 2 = Complete
   ./pro2.sh wait 120 4                    # block until complete
   ./pro2.sh get $U                        # ~30 MB protobuf
   python3 -m trinocular.sweepfmt sweep-$U.bin
   ```

   Color frames are JPEG XR; install `libjxr-tools` (`JxrDecApp`) and
   `sweepfmt` decodes them to TIFF too.

## The web app

A dark-room page: live camera status, a *Fire sweep* button, and a feed of
developed sweeps — the three color views, false-color depth strips, IR strips,
and a depth×IR blend (same sensor, same pixel grid, so no registration needed).
You can also import `.bin` files you already have.

```bash
sudo apt install libjxr-tools
pip install -r requirements.txt
CAMERA_URL=https://10.77.80.1 uvicorn trinocular.app:app --port 8796
```

Or in Docker (certs are mounted, never baked into the image):

```bash
docker build -t trinocular .
docker run -d --name trinocular -p 8796:8796 \
  -v "$PWD/certs:/certs:ro" -v trinocular-data:/data \
  -e CAMERA_URL=https://10.77.80.1 trinocular
```

If the host can't be on the camera's WiFi, run the
[relay](contrib/wifi-relay/) on a box that can, and set `CAMERA_URL` to it.

| Env | Default | |
|-----|---------|---|
| `CAMERA_URL` | `https://10.77.80.1` | Camera, or relay |
| `TRINOCULAR_CERTS` | `./certs` (`/certs` in Docker) | The three APK files |
| `TRINOCULAR_DATA` | `./data` (`/data` in Docker) | Sweeps: `raw.bin` + developed parts |
| `TRINOCULAR_ROTATE` | `cw` | Color sensor is portrait: `cw`, `ccw`, `180`, `none` |

API: `GET /api/state`, `POST /api/sweeps {"mode": 2}`, `POST /api/import`
(multipart `.bin`), `POST /api/cancel`, `GET /api/sweeps[/{id}]`,
`POST /api/sweeps/{id}/develop`, `DELETE /api/sweeps/{id}`.

## Mount it

The Pro2 rotates by turning its body against the stub on its base, and that
stub is meant to be screwed onto a tripod.  We had ours lying on its side.
It fired, clicked, whirred, and returned perfectly valid sweeps — and the body
never turned once, because the stub was just spinning in free air.

We spent two sweeps' worth of analysis explaining the results: depth rows that
were oddly constant across all 3600 columns ("so x isn't azimuth"), six color
frames of the same view ("so it's an exposure stack"), three color cameras
looking in three horizontal directions ("strange stack geometry").  Every one
of those was a camera lying on its side, standing still.

So: tripod, or a threaded rod with a jam nut, and level it.  If your depth
strips look like smeared horizontal bands, check that before you check your
parser.

## Where this could go

Depth + known sensor poses → a point cloud per sweep; project it into the color
frames using the calibration blocks in the protobuf; align sweeps with ICP;
mesh or splat; view it in three.js.  In other words, the digital twin the
camera was built for, done on your own hardware.  None of that exists here yet.

## Notes

- Not affiliated with or endorsed by Matterport.  "Matterport" and "Pro2" are
  theirs; they're used here to say what this works with.
- This repo contains no Matterport code and none of their keys.  It documents
  a protocol, observed by talking to a camera we own, so that owners can use
  their own hardware.  You supply the certs from your own copy of the app.
- Firmware updates may change or close any of this.  We haven't updated past
  1.1.620 and can't tell you what newer builds do.
- The camera AP is open.  Anyone within WiFi range can join it; they still
  need the certs to drive it, but those aren't secret.  Don't leave it on
  somewhere you care about.

## How this was made

Reverse engineering, code, and docs were done by Andrew Marx working with
Claude (Anthropic) as a coding agent — decompiling the APK, probing the
camera, walking the protobuf, and building the app.  The mistakes above are
ours together.

MIT licensed — see [LICENSE](LICENSE).
