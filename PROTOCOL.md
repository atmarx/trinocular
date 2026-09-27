# Matterport Pro2 (MC250) Local API Protocol

Reverse-engineered from the Matterport Capture Android app v2.82.0 (APKPure)
and one Pro2 on firmware `1.1.620.16618.35abb9f-P`.  Everything here was seen on
that one camera; other firmware may differ.  Claims marked **unconfirmed** are
our best reading, not verified.

## Network

The Pro2 creates an open WiFi AP named after its serial, e.g.
`Matterport P1xx` (no PSK).  Camera IP is `10.77.80.1`; clients get DHCP in
`10.77.80.0/24`.
The AP does NOT isolate clients.

Ports open: **80** (nginx/1.1.19, redirects to 443), **443** (HTTPS API).
No ADB (5555 closed).  No other services found.

## Authentication: Mutual TLS

The API requires mTLS.  Without the client certificate, every command returns
`HTTP 400` / `{"status":1}`.

Three files are embedded in every copy of the Matterport Capture APK at
`res/raw/`:

| File | Purpose |
|------|---------|
| `mattercam_crt` | Camera CA cert (self-signed, CN=Matterport Camera, O=Matterport, OU=Production, valid 2013-2033) |
| `mcp_client_cert_crt` | Client cert (CN=MCP client cert, serial=01, valid 1970-2030) |
| `mcp_client_cert_key` | Client RSA private key (PKCS8 PEM) |

### curl example

```bash
curl -sk \
  --cert certs/mcp_client_cert_crt \
  --key certs/mcp_client_cert_key \
  --cacert certs/mattercam_crt \
  "https://10.77.80.1/getState"
```

## API Endpoints

All endpoints are GET with query parameters unless noted.  The Retrofit
service interface is `Mp2CameraService.kt` (obfuscated to `hf/a.java`).

### Camera State

| Endpoint | Parameters | Response |
|----------|-----------|----------|
| `/getState` | — | Full camera state JSON (battery, firmware, sweep state, GPS, etc.) |
| `/getCapabilities` | — | Camera capabilities string + revision (404 on FW 1.1.620) |
| `/setTime` | `currentTime` (unix epoch string) | `{timeStamp, status}` (404 on FW 1.1.620) |
| `/getAllLogs` | — | POSIX TAR archive of all log files |
| `/getLog` | — | Current session log (plain text) |

### Sweep Operations

| Endpoint | Parameters | Response |
|----------|-----------|----------|
| `/startSweep` | `uuid` (string), `captureMode` (int), `hDriveSpeed` (int, optional), `vDriveRpm` (int, optional) | Camera state + image count |
| `/waitForSweep` | `timeout` (int), `sweepState` (int) | Blocks until sweep reaches target state |
| `/getSweep` | `uuid` (string) | Raw sweep data (binary ResponseBody) |
| `/getImage` | `uuid` (string), `imageIndex` (int) | Raw image data (binary, 404 on FW 1.1.620) |
| `/cancelSweep` | — | Camera state |

### Firmware Update

| Endpoint | Method | Parameters | Response |
|----------|--------|-----------|----------|
| `/submitUpdate` | **POST** (multipart) | `size` (long), `Content-Length` header, file part | Upload status |
| `/waitForVerifyUpdate` | GET | `timeout` (int) | Validation result |
| `/applyUpdate` | GET | — | Apply result + camera state |

### Power

| Endpoint | Parameters | Response |
|----------|-----------|----------|
| `/powerCycle` | — | Reboot (404 on FW 1.1.620) |

## Response Status Codes (`status` field)

From `McpResponseStatus.kt`:

| Value | Name | Meaning |
|-------|------|---------|
| -1 | MCP_RESPONSE_UNKNOWN | Unknown |
| 0 | MCP_RESPONSE_SUCCESS | Success |
| 1 | MCP_RESPONSE_BAD_TOKEN | Not authenticated (missing client cert) |
| 2 | MCP_RESPONSE_BAD_REQUEST | Invalid parameters |
| 3 | MCP_RESPONSE_INVALID_STATE | Camera in invalid state (check `blockedFlags`) |
| 4 | MCP_RESPONSE_TIMED_OUT | Request timed out |
| 5 | MCP_RESPONSE_ERROR | General error |
| 6 | MCP_RESPONSE_BAD_POST | Bad POST data (firmware upload) |

## Blocked Flags (bitmask)

From `BlockedFlags.kt`.  The `blockedFlags` field is a bitmask — multiple bits can
be set simultaneously.  The camera refuses `/startSweep` while any bit is set.

| Bit | Value | Name | Meaning |
|-----|-------|------|---------|
| 0 | 1 | MCP_BLOCKED_PLUGGED_IN | Charger connected — **unplug to scan** |
| 1 | 2 | MCP_BLOCKED_WARMING_UP | Depth sensor warming up (check `warmupProgress`) |
| 2 | 4 | MCP_BLOCKED_UPDATING | Firmware update in progress |
| 3 | 8 | MCP_BLOCKED_BATTERY_LOW | Battery too low to scan |
| 4 | 16 | MCP_BLOCKED_MOTOR_FAULT | Motor error |
| 5 | 32 | MCP_BLOCKED_SENSOR_FAULT | Sensor error |
| 6 | 64 | MCP_BLOCKED_CONFIG_FAULT | Configuration error |
| 7 | 128 | MCP_BLOCKED_INTERNAL_FAULT | Internal error |
| 8 | 256 | MCP_BLOCKED_SHUTTING_DOWN | Camera shutting down |

## Capture Modes

From `CaptureMode.kt`:

| Value | Name | Description |
|-------|------|-------------|
| 1 | Simple Scan | Quick scan, fewer images |
| 2 | Complete Scan | Full scan with all images |
| 3 | 3D | Standard 3D capture (generates minimap) |
| 4 | 360 | 360-degree panoramic view |
| 5 | Low Density | Fewer capture points |
| 6 | Medium Density | Moderate capture points |
| 7 | High Density | Maximum capture points |

## Sweep States

From `SweepState.kt`:

| Value | Name | Description |
|-------|------|-------------|
| 0 | MCP_SWEEP_UNKNOWN | Unknown state |
| 1 | MCP_SWEEP_EMPTY | No sweep in progress |
| 2 | MCP_SWEEP_ROTATING | Camera is rotating/capturing |
| 3 | MCP_SWEEP_PROCESSING | Processing captured data |
| 4 | MCP_SWEEP_COMPLETE | Sweep finished successfully |
| 5 | MCP_SWEEP_CANCELED | Sweep was canceled |
| 6 | MCP_SWEEP_ABORTED_PHYSICAL | Aborted due to physical interference |
| 7 | MCP_SWEEP_ABORTED_DATA | Aborted due to data error |
| 8 | MCP_SWEEP_ERROR | Sweep error |

## Charge States

From `ChargeState.kt`:

| Value | Name |
|-------|------|
| 0 | MCP_CHARGE_UNKNOWN |
| 1 | MCP_CHARGE_DISCHARGING |
| 2 | MCP_CHARGE_CHARGING |
| 3 | MCP_CHARGE_CHARGED |

## Update States

From firmware update state enum:

| Value | Name |
|-------|------|
| 0 | MCP_UPDATE_EMPTY |
| 1 | MCP_UPDATE_VERIFYING |
| 2 | MCP_UPDATE_VERIFY_FAILED |
| 3 | MCP_UPDATE_UPDATE_REFUSED |
| 4 | MCP_UPDATE_READY |
| 5 | MCP_UPDATE_APPLYING |
| 6 | MCP_UPDATE_APPLY_FAILED |

## Camera State Fields

From `Mp2CameraInfo.kt`:

| Field | Type | Notes |
|-------|------|-------|
| `analytics` | string | Analytics ID |
| `batteryFlags` | int | Battery status flags |
| `blockedFlags` | int | Blocked state bitmask (see table above) |
| `blockedMessage` | string | Human-readable block reason |
| `calibrationVersion` | string | Calibration data version |
| `cameraModel` | string | Model identifier |
| `cameraSerial` | string | Serial number (e.g. "P1xx", also the SSID suffix) |
| `cameraState` | int | Internal state machine position |
| `captureMode` | int | Current capture mode (see table above) |
| `chargePercent` | int | Battery percentage |
| `chargeState` | int | Charging state (see table above) |
| `depthFwVersion` | string | Depth sensor firmware |
| `errorCode` | int | Current error code |
| `firmwareVersion` | string | Main firmware version |
| `imageCount` | int | Images in current sweep |
| `logCount` | int | Number of log entries |
| `manufacturer` | string | Device manufacturer |
| `moduleFpga` | string | FPGA module version |
| `moduleFx3` | string | FX3 USB controller version |
| `softwareRevisionNum` | int | Software revision number |
| `softwareVersion` | string | Full software version string |
| `status` | int | API response status (see table above) |
| `sweepMessage` | string | Current sweep status message |
| `sweepProgress` | float | Sweep completion 0.0-1.0 |
| `sweepRate` | float | Sweep rate |
| `sweepState` | int | Sweep state (see table above) |
| `sweepUuid` | string | UUID of current/last sweep |
| `stageProgress` | float | Current stage progress |
| `stageRate` | float | Current stage rate |
| `updateState` | int | Firmware update state (see table above) |
| `warmupProgress` | float | Warmup progress 0.0-1.0 |
| `warmupRate` | float | Warmup rate |
| `gpsStatus` | object | GPS state/fix/lat/lon/module/time |

## Scan Workflow

From `Mp2ScanDelegateImpl.kt`.  The app's scan workflow is a WorkManager chain:

1. **Mp2SetCameraToCaptureModeWorker** — **NO-OP for Pro2** (returns hardcoded "DONE").
   No separate "set to capture mode" command is needed.
2. **Mp2StartSweepWorker** — calls `/startSweep` with uuid and captureMode.
3. **Mp2DownloadImagesWorker** + **Mp2WaitForSweepWorker** — run in parallel.
   WaitForSweep blocks until `sweepState` reaches the target value.
4. **Mp2GetStatusWorker** — calls `/getState` to confirm completion.
5. **Mp2GetSweepWorker** — calls `/getSweep` to download raw sweep data.
6. **Mp2SaveImagePathWorker** — saves data to local storage.
7. Post-processing: **GenerateMp2MinimapFilesWorker** (captureMode=3D)
   or **Mp2Add360ViewWorker** (other modes).

The camera does NOT need a mode-set command before scanning.  The `captureMode`
parameter in `/startSweep` tells the camera what kind of sweep to perform.
The ONLY thing that prevents scanning is `blockedFlags` being non-zero.

## App Architecture Notes

- The Matterport Capture app uses **Retrofit 2** over OkHttp for HTTP.
- Camera SDK is from **Arashivision** (parent company of Insta360).
- The app embeds Insta360's `com.arashivision.camera.command.*` classes.
- The `Mp2NetworkInterceptorImpl` OkHttp interceptor logs all 400 responses.
- `Mp2CameraDataSourceImpl.kt` is the MP2-specific data source. Its `setOptions()`
  method is a no-op — returns `CameraSetOptionsResponse("", "DONE")` without
  making any API call.
- `CameraSetOptionsRequest.kt` defines a JSON command `{"name": "camera.setOptions",
  "parameters": {...}}` but it is never sent to the Pro2 over HTTP.

## Sweep Data Format (`/getSweep` response)

The response from `/getSweep` is a **protobuf** container.  Structure decoded from
a captureMode=4 (360) sweep:

### Top-level protobuf fields

| Field | Type | Content |
|-------|------|---------|
| 1 | bytes(16) | Sweep UUID (raw bytes, matches the uuid from startSweep) |
| 2 | varint | 1800 (sweep parameter, possibly horizontal resolution) |
| 3 | bytes(39) | Calibration matrix (nested protobuf with 4×3 floats) |
| 4 | bytes(39) | Second calibration matrix |
| 5 | bytes (×3) | **Depth sensor data** — one per IR camera (see below) |
| 6 | bytes (×3) | **Color camera data** — one per color camera (see below) |
| 8 | bytes(735) | Metadata block |
| 9 | bytes(99) (×3) | Per-sensor metadata |
| 11 | bytes(23) | Additional metadata |
| 14 | varint (×2) | Color image dimensions? (2250, 2125) |
| 16 | bytes(14027) | Unknown data block |
| 17 | bytes(15428) | Unknown data block |

### Field 5: Depth sensor data (×3 sensors)

Each field 5 block is a nested protobuf containing three images:

| Sub-field | Format | Resolution | Description |
|-----------|--------|------------|-------------|
| (embedded PNG 1) | 16-bit grayscale PNG | 3600 × ~458 | **Depth map** — distance values |
| (embedded PNG 2) | 8-bit grayscale PNG | 3600 × ~458 | **IR intensity** — ambient/reflected IR |
| (embedded JPEG) | JFIF JPEG | small | **Thumbnail** (~26KB preview) |

The three sensors have slightly different vertical resolutions (455–459 px).
Width is always 3600 px — most likely azimuth (0.1° per column), **unconfirmed**.
Every sweep so far (Aug 1, Sep 25) was shot with the Pro2 lying on its side:
the drive turns the body against its mount, so with the mount stub in free
air the body never rotated.  That explains the depth rows being near-constant
across all 3600 columns and the three color cameras (a vertical stack) seeing
three horizontal headings.  **The Pro2 must be mounted (tripod / threaded
stud) to sweep.**  Axes and units get confirmed on the first mounted sweep.

### Field 6: Color camera data (×3 cameras)

Each field 6 block is a nested protobuf:

| Sub-field | Type | Content |
|-----------|------|---------|
| 1 | string(10) | Color sensor serial number (10 digits) |
| 2 | bytes(51) | Pose/calibration matrix (4×4 floats) |
| 3 | bytes(39) | Lens distortion parameters |
| 4 | float | Field of view: 1.0472 rad (≈ 60°) |
| 5 | bytes (×6) | **Six frames** (JPEG XR format) — see below for what they are |
| 9 | varint | Exposure mode (2) |
| 10 | varint (×6) | Per-exposure flags |
| 11 | float (×6) | Exposure times (0.0002–0.0022 sec) |
| 12 | float (×6) | Gain multipliers (0.53–1.19) |
| 13 | float (×6) | Per-channel gains |
| 14 | float (×6) | White balance coefficients |
| 17 | varint | FPGA version (176) |
| 18 | varint | FX3 version (206) |
| 19 | float (×6) | Sensor temperature (63.75°C for all) |

### JPEG XR exposure format

Each exposure frame is a **JPEG XR** (ISO/IEC 29199-2, formerly HD Photo) file:

- Magic bytes: `49 49 BC 01` (little-endian JPEG XR container)
- Resolution: **2560 × 1920** pixels (~4.9 MP), 60° FOV
- Decodes to **16-bit RGB** — full color, not luminance-only as first noted
- Sensor is mounted portrait: rotate 90° for upright
- No white balance applied — raw output has a strong green cast; the per-frame
  WB coefficients (field 14) are presumably what the app applies
- Decode with: `JxrDecApp -i file.jxr -o file.tif` (libjxr-tools), or just run
  `python3 -m trinocular.sweepfmt sweep.bin`, which carves and decodes everything

### What the six frames per camera are (**unconfirmed**)

On our sweeps all six frames from one camera share the **same viewpoint**,
taken sequentially in time (a person walking through the shot moves between
frames), with exposure/gain differing per frame in no monotonic order.  We
first read that as an exposure stack at one heading.

But those sweeps came from a Pro2 lying on its side that never rotated (see
the depth notes), and the Matterport3D dataset paper (Chang et al., 3DV 2017)
describes the rig as three color + three depth cameras pointing slightly up,
level, and slightly down, rotating to **6 orientations** and taking an HDR
photo from each color camera at every stop, with depth captured continuously.
That fits everything here: 6 frames × 60° FOV = 360°, 3600 depth columns =
0.1°/column, and 16-bit JPEG XR frames that are plausibly already-HDR.

So the likely reading is **six headings, 60° apart, each auto-exposed** — the
"same viewpoint" was just a camera that didn't turn.  The three cameras seeing
three horizontal headings is the up/level/down stack turned sideways.  A
mounted sweep settles it; until then `develop.py` fuses the six frames as a
stack, which is only right for an unrotated camera.

### Complete data inventory per sweep

| Data type | Count | Format | Resolution | Size each |
|-----------|-------|--------|------------|-----------|
| Depth maps | 3 | 16-bit grayscale PNG | 3600 × ~458 | ~1.1–1.4 MB |
| IR intensity | 3 | 8-bit grayscale PNG | 3600 × ~458 | ~630–824 KB |
| IR thumbnails | 3 | JPEG | small | ~26 KB |
| Color exposures | 18 (6×3) | 10-bit JPEG XR | 2560 × 1920 | ~1.0–1.3 MB |
| **Total** | | | | **~27 MB** |

## Open Questions

- Whether `getImage` works on other firmware versions (404 on FW 1.1.620)
- Whether the Insta360 SDK uses a separate protocol for motor/sensor control
- The exact meaning of `cameraState` integer values (firmware-side state machine)
- Whether the 6 frames per camera are 6 headings (likely) or an exposure stack
- Depth units and the exact axis mapping (needs a mounted, level sweep)
- Whether different `captureMode` values produce different data layouts
- The protobuf .proto schema (could be reconstructed from field analysis)
- What fields 16/17 contain (possibly point cloud or mesh data)
