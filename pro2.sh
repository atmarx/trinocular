#!/bin/bash
# pro2.sh - Talk to a Matterport Pro2 (MC250) camera
# Requires: curl, mTLS certs in ./certs/
#
# Usage: ./pro2.sh <command> [args...]
#   ./pro2.sh state              # get camera state
#   ./pro2.sh logs               # download all logs (tar)
#   ./pro2.sh log                # current session log
#   ./pro2.sh sweep <uuid> <mode> [hSpeed] [vRpm]  # start sweep
#   ./pro2.sh cancel             # cancel sweep
#   ./pro2.sh wait <timeout> <sweepState>           # wait for sweep
#   ./pro2.sh get <uuid>         # download sweep data
#   ./pro2.sh image <uuid> <idx> # download single image
#   ./pro2.sh time               # sync camera clock
#   ./pro2.sh raw <path>         # raw GET request

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CAMERA="https://10.77.80.1"
CERT="--cert $SCRIPT_DIR/certs/mcp_client_cert_crt"
KEY="--key $SCRIPT_DIR/certs/mcp_client_cert_key"
CA="--cacert $SCRIPT_DIR/certs/mattercam_crt"
CURL="curl -sk $CERT $KEY $CA"

case "${1:-help}" in
  state)
    STATE=$($CURL "$CAMERA/getState")
    echo "$STATE" | python3 -m json.tool
    BLOCKED=$(echo "$STATE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('blockedFlags',0))" 2>/dev/null)
    if [ "$BLOCKED" -gt 0 ] 2>/dev/null; then
      echo "--- BLOCKED ---"
      [ $((BLOCKED & 1)) -ne 0 ] && echo "  bit 0: PLUGGED_IN (unplug charger)"
      [ $((BLOCKED & 2)) -ne 0 ] && echo "  bit 1: WARMING_UP (wait for warmupProgress)"
      [ $((BLOCKED & 4)) -ne 0 ] && echo "  bit 2: UPDATING (firmware update in progress)"
      [ $((BLOCKED & 8)) -ne 0 ] && echo "  bit 3: BATTERY_LOW"
      [ $((BLOCKED & 16)) -ne 0 ] && echo "  bit 4: MOTOR_FAULT"
      [ $((BLOCKED & 32)) -ne 0 ] && echo "  bit 5: SENSOR_FAULT"
      [ $((BLOCKED & 64)) -ne 0 ] && echo "  bit 6: CONFIG_FAULT"
      [ $((BLOCKED & 128)) -ne 0 ] && echo "  bit 7: INTERNAL_FAULT"
      [ $((BLOCKED & 256)) -ne 0 ] && echo "  bit 8: SHUTTING_DOWN"
    fi
    ;;
  logs)
    OUT="${2:-pro2-logs-$(date +%Y%m%d-%H%M%S).tar}"
    $CURL "$CAMERA/getAllLogs" -o "$OUT"
    echo "Saved to $OUT ($(stat -c%s "$OUT") bytes)"
    ;;
  log)
    $CURL "$CAMERA/getLog"
    ;;
  sweep)
    UUID="${2:?uuid required}"
    MODE="${3:?captureMode required}"
    PARAMS="uuid=$UUID&captureMode=$MODE"
    [ -n "${4:-}" ] && PARAMS="$PARAMS&hDriveSpeed=$4"
    [ -n "${5:-}" ] && PARAMS="$PARAMS&vDriveRpm=$5"
    $CURL "$CAMERA/startSweep?$PARAMS" | python3 -m json.tool
    ;;
  cancel)
    $CURL "$CAMERA/cancelSweep" | python3 -m json.tool
    ;;
  wait)
    TIMEOUT="${2:?timeout required}"
    SSTATE="${3:?sweepState required}"
    $CURL "$CAMERA/waitForSweep?timeout=$TIMEOUT&sweepState=$SSTATE" | python3 -m json.tool
    ;;
  get)
    UUID="${2:?uuid required}"
    OUT="${3:-sweep-$UUID.bin}"
    $CURL "$CAMERA/getSweep?uuid=$UUID" -o "$OUT"
    echo "Saved to $OUT ($(stat -c%s "$OUT") bytes)"
    ;;
  image)
    UUID="${2:?uuid required}"
    IDX="${3:?imageIndex required}"
    OUT="${4:-image-$UUID-$IDX.bin}"
    $CURL "$CAMERA/getImage?uuid=$UUID&imageIndex=$IDX" -o "$OUT"
    echo "Saved to $OUT ($(stat -c%s "$OUT") bytes)"
    ;;
  time)
    $CURL "$CAMERA/setTime?currentTime=$(date +%s)" | python3 -m json.tool
    ;;
  raw)
    $CURL "$CAMERA/${2:?path required}"
    ;;
  help|*)
    sed -n '2,15p' "$0"
    ;;
esac
