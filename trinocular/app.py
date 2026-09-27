"""trinocular — fire the Pro2, pull the sweep, develop it, show it.

    uvicorn trinocular.app:app --port 8796

Env:
  CAMERA_URL          https://10.77.80.1 (on the camera's WiFi) or a relay, e.g.
                      https://192.168.1.50:8443 (contrib/wifi-relay)
  TRINOCULAR_CERTS    dir holding the three APK cert files (default ./certs)
  TRINOCULAR_DATA     where sweeps live (default ./data)
  TRINOCULAR_ROTATE   cw | ccw | 180 | none  (see develop.py)
"""
import asyncio
import json
import os
import shutil
import time
import uuid as uuidlib
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import sweepfmt
from .camera import CAPTURE_MODES, SWEEP_DONE, SWEEP_TERMINAL, Camera
from .develop import develop

DATA = Path(os.environ.get("TRINOCULAR_DATA", "data")).resolve()
SWEEPS = DATA / "sweeps"
SWEEPS.mkdir(parents=True, exist_ok=True)
STATIC = Path(__file__).parent / "static"
SWEEP_TIMEOUT = 15 * 60
ACTIVE = {"rotating", "downloading", "developing"}

app = FastAPI(title="trinocular")
cam = Camera()
capture_lock = asyncio.Lock()
_state_cache = {"t": 0.0, "v": None}


# ---- sweep records --------------------------------------------------------

def _path(sid):
    p = (SWEEPS / sid).resolve()
    if p.parent != SWEEPS:
        raise HTTPException(404)
    return p


def load(sid):
    try:
        return json.loads((_path(sid) / "sweep.json").read_text())
    except FileNotFoundError:
        raise HTTPException(404, "no such sweep")


def save(rec):
    d = _path(rec["id"])
    d.mkdir(exist_ok=True)
    tmp = d / "sweep.json.tmp"
    tmp.write_text(json.dumps(rec, indent=1))
    tmp.replace(d / "sweep.json")
    return rec


def new_record(source, mode=None, sweep_uuid=None):
    sweep_uuid = sweep_uuid or str(uuidlib.uuid4())
    sid = time.strftime("%Y%m%d-%H%M%S") + "-" + sweep_uuid[:8]
    return save({"id": sid, "uuid": sweep_uuid, "source": source, "mode": mode,
                 "modeName": CAPTURE_MODES.get(mode), "created": time.time(),
                 "status": "new", "progress": 0.0, "message": "", "camera": None,
                 "bytes": 0, "develop": None})


def update(rec, **kw):
    rec.update(kw)
    return save(rec)


@app.on_event("startup")
def _recover():
    # Anything mid-flight when we died stays dead — say so instead of spinning.
    for f in SWEEPS.glob("*/sweep.json"):
        rec = json.loads(f.read_text())
        if rec.get("status") in ACTIVE:
            update(rec, status="interrupted", message="service restarted mid-capture")


# ---- pipeline -------------------------------------------------------------

def _develop_sync(rec):
    d = _path(rec["id"])
    sw = sweepfmt.parse((d / "raw.bin").read_bytes())
    sweepfmt.unpack(sw, str(d))
    man = develop(str(d))
    man["cams"] = [{"serial": c.serial, "fov": c.fov, "frames": len(c.frames),
                    "exposure": c.exposure, "gain": c.gain} for c in sw.color]
    return man


async def run_develop(rec):
    update(rec, status="developing", message="unpacking + HDR fusion")
    try:
        man = await asyncio.to_thread(_develop_sync, rec)
        update(rec, status="done", develop=man, message="", finished=time.time())
    except Exception as e:  # noqa: BLE001 — surface anything to the page
        update(rec, status="error", message=f"develop failed: {e}")


async def run_capture(rec):
    async with capture_lock:
        try:
            try:
                await cam.set_time(time.time())
            except Exception:  # noqa: BLE001 — 404 on FW 1.1.620; clock is cosmetic
                pass
            r = await cam.start_sweep(rec["uuid"], rec["mode"])
            if r.get("status") not in (0, None):
                return update(rec, status="error",
                              message=f"startSweep refused: status {r.get('status')} {r.get('sweepMessage', '')}")
            update(rec, status="rotating", message="sweep started")

            # sweepState can still read 'complete' from the previous sweep for
            # a beat, so only trust a terminal state once it's about us.
            seen_live, deadline, s = False, time.time() + SWEEP_TIMEOUT, {}
            while time.time() < deadline:
                await asyncio.sleep(2)
                try:
                    s = await cam.state()
                except Exception as e:  # noqa: BLE001 — wifi blips happen
                    update(rec, message=f"lost camera for a moment: {e}")
                    continue
                ours = s.get("sweepUuid") == rec["uuid"]
                seen_live |= s.get("sweepState") not in SWEEP_TERMINAL
                update(rec, progress=s.get("sweepProgress", 0.0),
                       message=s.get("sweepMessage") or s.get("sweepStateName", ""))
                if s.get("sweepState") in SWEEP_TERMINAL and (ours or seen_live):
                    break
            else:
                return update(rec, status="error", message="sweep timed out")

            rec["camera"] = {k: s.get(k) for k in
                             ("chargePercent", "firmwareVersion", "cameraSerial", "gpsStatus")}
            if s.get("sweepState") != SWEEP_DONE:
                return update(rec, status="error", message=f"sweep ended: {s.get('sweepStateName')}")

            update(rec, status="downloading", progress=1.0, message="pulling sweep")
            n = await cam.get_sweep(rec["uuid"], _path(rec["id"]) / "raw.bin")
            update(rec, bytes=n)
        except Exception as e:  # noqa: BLE001
            return update(rec, status="error", message=str(e) or type(e).__name__)
    await run_develop(rec)


# ---- API ------------------------------------------------------------------

@app.get("/api/state")
async def state():
    # Many tabs, one camera: don't let every poll become a request over WiFi.
    if time.time() - _state_cache["t"] < 2 and _state_cache["v"]:
        return _state_cache["v"]
    try:
        v = {"online": True, **await asyncio.wait_for(cam.state(), 5)}
    except Exception as e:  # noqa: BLE001
        v = {"online": False, "error": str(e) or type(e).__name__}
    v["busy"] = capture_lock.locked()
    v["cameraUrl"] = cam.url
    _state_cache.update(t=time.time(), v=v)
    return v


class SweepReq(BaseModel):
    mode: int = 2


@app.post("/api/sweeps", status_code=202)
async def fire(req: SweepReq):
    if req.mode not in CAPTURE_MODES:
        raise HTTPException(400, f"mode must be one of {sorted(CAPTURE_MODES)}")
    if capture_lock.locked():
        raise HTTPException(409, "a sweep is already running")
    try:
        s = await asyncio.wait_for(cam.state(), 5)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"camera unreachable: {e}")
    if s["blocked"]:
        raise HTTPException(409, "camera blocked: " + ", ".join(s["blocked"]))
    rec = new_record("camera", req.mode)
    asyncio.create_task(run_capture(rec))
    return rec


@app.post("/api/import", status_code=202)
async def import_bin(file: UploadFile):
    rec = new_record("import")
    with open(_path(rec["id"]) / "raw.bin", "wb") as f:
        shutil.copyfileobj(file.file, f)
    update(rec, bytes=(_path(rec["id"]) / "raw.bin").stat().st_size,
           message=f"imported {file.filename}")
    asyncio.create_task(run_develop(rec))
    return rec


@app.post("/api/cancel")
async def cancel():
    try:
        return await cam.cancel()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, str(e))


@app.get("/api/sweeps")
def list_sweeps():
    recs = [json.loads(f.read_text()) for f in SWEEPS.glob("*/sweep.json")]
    return sorted(recs, key=lambda r: r["created"], reverse=True)


@app.get("/api/sweeps/{sid}")
def get_sweep(sid: str):
    return load(sid)


@app.post("/api/sweeps/{sid}/develop", status_code=202)
async def redevelop(sid: str):
    """Re-run the darkroom on a stored raw.bin — for when develop.py learns new tricks."""
    rec = load(sid)
    if rec["status"] in ACTIVE:
        raise HTTPException(409, "still working on that one")
    if not (_path(sid) / "raw.bin").exists():
        raise HTTPException(409, "no raw.bin to develop")
    asyncio.create_task(run_develop(rec))
    return rec


@app.delete("/api/sweeps/{sid}")
def delete_sweep(sid: str):
    rec = load(sid)
    if rec["status"] in ACTIVE:
        raise HTTPException(409, "still working on that one")
    shutil.rmtree(_path(sid))
    return {"deleted": sid}


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/media", StaticFiles(directory=SWEEPS), name="media")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
