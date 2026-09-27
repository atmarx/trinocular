#!/bin/bash
# Join the Pro2's AP and relay LAN:8443 -> 10.77.80.1:443.  Run as root; idempotent.
#   ./setup.sh <camera SSID> <wifi iface> <LAN address to listen on>
set -euo pipefail
cd "$(dirname "$0")"
SSID="${1:?camera SSID, e.g. 'Matterport P1xx'}"
IFACE="${2:?wifi interface, e.g. wlan0}"
BIND="${3:?LAN address to listen on}"

command -v socat >/dev/null || apt-get install -y socat

# Join the camera's open AP whenever it's up, but never let it touch routing
# or DNS — the real uplink stays where it is.
if ! nmcli -t -f NAME con show | grep -qxF "$SSID"; then
  nmcli con add type wifi ifname "$IFACE" con-name "$SSID" ssid "$SSID"
fi
nmcli con modify "$SSID" connection.autoconnect yes connection.autoconnect-retries 0 \
  ipv4.method auto ipv4.never-default yes ipv4.ignore-auto-dns yes ipv6.method disabled

sed "s/@BIND@/$BIND/" trinocular-relay.service > /etc/systemd/system/trinocular-relay.service
systemctl daemon-reload
systemctl enable --now trinocular-relay.service
systemctl restart trinocular-relay.service
systemctl --no-pager --lines=3 status trinocular-relay.service
