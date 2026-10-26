#!/bin/bash
# Keeps the ExpressVPN tunnel (gluetun) healthy: re-resolves the endpoint IP
# (gluetun needs an IP, not a hostname) and restarts the tunnel if the IP
# rotated or gluetun is unhealthy. Logged to the journal (tag vpn-watchdog).
set -u
HOST="${VPN_ENDPOINT:-<your-vpn-endpoint-hostname>}"
OVPN="/opt/arr/gluetun/custom.ovpn"
PORT="1195"
cur=$(awk "/^remote /{print \$2; exit}" "$OVPN")
new=$(getent ahostsv4 "$HOST" | awk "{print \$1; exit}")
need_restart=0
if [ -n "$new" ] && [ "$new" != "$cur" ]; then
  sed -i "s/^remote .* ${PORT}/remote ${new} ${PORT}/" "$OVPN"
  logger -t vpn-watchdog "endpoint IP ${cur} -> ${new}; restarting tunnel"
  need_restart=1
fi
h=$(docker inspect -f "{{.State.Health.Status}}" gluetun 2>/dev/null || echo missing)
if [ "$h" != "healthy" ]; then
  logger -t vpn-watchdog "gluetun health=${h}; restarting tunnel"
  need_restart=1
fi
if [ "$need_restart" = "1" ]; then
  cd /opt/arr && docker compose restart gluetun qbittorrent >/dev/null 2>&1
  logger -t vpn-watchdog "restart issued"
fi
