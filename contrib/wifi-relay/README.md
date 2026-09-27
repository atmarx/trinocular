# WiFi relay

The Pro2 only talks over its own WiFi AP.  If the machine running trinocular
has no WiFi (or needs it for something else), put a relay on any Linux box
that does: it joins the camera's AP and forwards raw TCP from your LAN to
`10.77.80.1:443`.  TLS stays end to end — the relay never sees the keys.

```bash
sudo ./setup.sh "Matterport P1xx" wlan0 192.168.1.50
#               ^ camera SSID     ^ wifi  ^ this box's LAN address to listen on
```

Then point trinocular at it: `CAMERA_URL=https://192.168.1.50:8443`.

The WiFi connection is set `never-default` and ignores the camera's DNS, so
the box keeps using its normal uplink.  Needs NetworkManager and systemd.

The camera AP is open (no password) and the relay listens without auth, so
keep 8443 firewalled to hosts you trust — anyone who reaches it and has the
APK certs can drive the camera.
