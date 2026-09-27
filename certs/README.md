# Certs (bring your own)

The Pro2 only answers clients that present Matterport's client certificate
(mutual TLS).  That certificate and its private key ship inside every copy of
the Matterport Capture Android app.  This repo does **not** include them — pull
them from an APK you downloaded yourself.

You need three files in this directory, names exactly as below:

| File | What it is |
|------|------------|
| `mattercam_crt` | CA that signed the camera's server cert (CN=Matterport Camera) |
| `mcp_client_cert_crt` | Client certificate (CN=MCP client cert) |
| `mcp_client_cert_key` | Its RSA private key (PKCS8 PEM) |

## Extracting

They live under `res/raw/` in the app's APK (we used v2.82.0).  Android resource
names have no extension, so they come out exactly as named above.

```bash
# Plain APK:
unzip -j MatterportCapture.apk 'res/raw/mattercam_crt' 'res/raw/mcp_client_cert_*' -d certs/

# XAPK / split-APK bundle (APKPure etc.) — it's a zip of APKs; the
# resources are in the base one (the big one, not config.*.apk):
unzip -l bundle.xapk '*.apk'
unzip -o bundle.xapk '<base>.apk' -d /tmp/mp
unzip -j '/tmp/mp/<base>.apk' 'res/raw/mattercam_crt' 'res/raw/mcp_client_cert_*' -d certs/
```

If the paths have moved in a newer build, list the archive and look for them:
`unzip -l app.apk | grep -E 'mattercam|mcp_client'`.

## Check

```bash
openssl x509 -in certs/mattercam_crt -noout -subject -dates
openssl x509 -in certs/mcp_client_cert_crt -noout -subject -dates
./pro2.sh state        # while joined to the camera's WiFi
```

The client cert says it's valid through 2030.  After that, expect the
handshake to fail unless the camera doesn't check dates (untested).
