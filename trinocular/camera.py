"""Async client for the Pro2 local API (see PROTOCOL.md).

The camera only speaks mTLS with the client cert baked into every Matterport
Capture APK (see certs/README.md).  CAMERA_URL is the camera itself
(https://10.77.80.1) when this host is on the camera's WiFi, or a TCP relay on
a box that is (contrib/wifi-relay) — TLS stays end to end either way.
"""
import os
import ssl

import httpx

CERTS = os.environ.get("TRINOCULAR_CERTS",
                       os.path.join(os.path.dirname(__file__), "..", "certs"))

BLOCKED = ["plugged in", "warming up", "updating", "battery low", "motor fault",
           "sensor fault", "config fault", "internal fault", "shutting down"]
SWEEP_STATES = ["unknown", "empty", "rotating", "processing", "complete",
                "canceled", "aborted (physical)", "aborted (data)", "error"]
CHARGE_STATES = ["unknown", "discharging", "charging", "charged"]
CAPTURE_MODES = {1: "Simple", 2: "Complete", 3: "3D", 4: "360",
                 5: "Low density", 6: "Medium density", 7: "High density"}
SWEEP_DONE = 4
SWEEP_TERMINAL = set(range(4, 9))


CERT_FILES = ("mattercam_crt", "mcp_client_cert_crt", "mcp_client_cert_key")


def _ssl():
    missing = [f for f in CERT_FILES if not os.path.exists(os.path.join(CERTS, f))]
    if missing:
        raise RuntimeError(f"missing {', '.join(missing)} in {os.path.abspath(CERTS)} — "
                           "pull them from the Capture APK, see certs/README.md")
    # The camera cert is CN=Matterport Camera with no SAN, so hostname checks
    # can't pass through a relay.  Pinning to the camera CA still holds.
    ctx = ssl.create_default_context(cafile=os.path.join(CERTS, "mattercam_crt"))
    ctx.check_hostname = False
    # 2013-era nginx + a client cert from the same year: OpenSSL 3's default
    # security level refuses the handshake.  This link never leaves the LAN.
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    ctx.load_cert_chain(os.path.join(CERTS, "mcp_client_cert_crt"),
                        os.path.join(CERTS, "mcp_client_cert_key"))
    return ctx


def decode_blocked(flags):
    return [name for bit, name in enumerate(BLOCKED) if flags & (1 << bit)]


class Camera:
    def __init__(self, url=None):
        self.url = (url or os.environ.get("CAMERA_URL", "https://10.77.80.1")).rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.url, verify=_ssl(),
                                      timeout=httpx.Timeout(10, read=30))

    async def _get(self, path, timeout=None, **params):
        r = await self.http.get(path, params=params or None,
                                timeout=timeout or self.http.timeout)
        r.raise_for_status()
        return r

    async def state(self):
        s = (await self._get("/getState")).json()
        s["blocked"] = decode_blocked(s.get("blockedFlags", 0))
        s["sweepStateName"] = SWEEP_STATES[s.get("sweepState", 0)] \
            if 0 <= s.get("sweepState", 0) < len(SWEEP_STATES) else "?"
        s["chargeStateName"] = CHARGE_STATES[s.get("chargeState", 0)] \
            if 0 <= s.get("chargeState", 0) < len(CHARGE_STATES) else "?"
        return s

    async def set_time(self, epoch):
        return (await self._get("/setTime", currentTime=str(int(epoch)))).json()

    async def start_sweep(self, uuid, mode):
        return (await self._get("/startSweep", uuid=uuid, captureMode=mode)).json()

    async def cancel(self):
        return (await self._get("/cancelSweep")).json()

    async def get_sweep(self, uuid, dest):
        """Stream the sweep protobuf (~30MB for a 360) to `dest`."""
        async with self.http.stream("GET", "/getSweep", params={"uuid": uuid},
                                    timeout=httpx.Timeout(10, read=300)) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    f.write(chunk)
        return os.path.getsize(dest)
