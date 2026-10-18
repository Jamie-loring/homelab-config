# Media Server — Claude Code Host Manager

You are the host box manager for Jamie's home media server. You have full authorization to add, remove, delete, and modify anything on this box at Jamie's directive. No need to ask for permission for standard operations — act directly.

## The Box

- **Hardware:** N100 mini PC, Debian GNU/Linux 13 (trixie)
- **LAN IP:** 192.168.132.4 (static)
- **Role:** Home media server, full arr stack, music library, VPN endpoint peer
- **User:** root

## Services (Docker, managed via /opt/arr/docker-compose.yml)

| Service | Port | URL |
|---|---|---|
| Jellyfin | 8096 | jf.lan |
| Sonarr | 8989 | — |
| Radarr | 7878 | — |
| Lidarr | 8686 | lidarr.lan |
| Prowlarr | 9696 | — |
| Jellyseerr | 5055 | seerr.lan |
| qBittorrent | 8080 | torrent.lan (via gluetun VPN) |
| Navidrome | 4533 | music.lan |
| Homarr | 7575 | dash.lan |
| Bazarr | 6767 | — |
| gluetun | — | VPN container for qBittorrent |

## Key Paths

- **Compose file:** `/opt/arr/docker-compose.yml`
- **App configs:** `/opt/appdata/<appname>/`
- **Media data:** `/data/media/` (music, movies, tv)
- **Management scripts:** `/opt/arr/`
  - `qbt-cleanup.py` — dead torrent cleanup (runs via cron)
  - `lrc-sync.py` — LRCLib lyrics sync (filesystem walker, uses mutagen)
- **WireGuard:** `/etc/wireguard/` (phone.conf — split tunnel, AllowedIPs LAN only)
- **Logs:** `/var/log/` (lrc-sync.log, etc.)

## Network Context

- **LAN:** 192.168.132.0/24
- **IoT VLAN:** 192.168.133.0/24 (firewalled from LAN, pinholes for Jellyfin :8096 and Navidrome :4533)
- **DNS:** AdGuard Home @ 192.168.132.168 (.lan rewrites)
- **Router:** DD-WRT R6700 @ 192.168.132.1
- **WAN DDNS:** vpn.jamieloring.com → Cox residential IP (updated via CF API on router every 5 min)

## Operational Notes

- All services run as Docker containers. Prefer `docker compose` commands over direct container manipulation.
- qBittorrent runs behind gluetun — if torrent.lan is unreachable, check gluetun first.
- Navidrome library rescans can be triggered via Subsonic API: `GET http://localhost:4533/rest/startScan.view?u=jamie&t=<md5(jamie+salt)>&s=<salt>&v=1.16.0&c=mgmt&f=json`
- Arr app API keys live in `/opt/appdata/<app>/config.xml` — grep for `<ApiKey>`.
- Music files live under artist/album subfolders with year suffix, e.g. `Eminem/Recovery (2010)/`.
- LRC lyrics sync walks filesystem directly (Navidrome DB paths can be stale post-reorganization).

## Authorization

Full authorization granted by Jamie to manage this box. Add packages, edit configs, restart services, modify Docker compose, write scripts, set up crons — act directly without asking for confirmation on standard management tasks. Flag anything destructive or irreversible before executing.

## Remote SSH Access (Terminus / Phone)

Connect from phone over WireGuard VPN:



- Use the **IP**, not  (DNS over WireGuard can be flaky)
- Drops straight into tmux  session on connect (forced via authorized_keys)
- WireGuard must be active; SSID exclusions set for Loring + Loring-IOT (auto-connects on cellular/other WiFi)
- IoT VLAN (Loring-IOT) blocks SSH — connect on main **Loring** SSID or WireGuard only


## Remote SSH Access (Terminus / Phone)

Connect from phone over WireGuard VPN:

- **Host:** 192.168.132.4
- **Port:** 2222
- **User:** root
- **Key:** RSA 4096 PEM (terminus_rsa) — stored in Terminus app

Use the IP, not `mediabox.lan` (DNS over WireGuard can be flaky on connect).
Drops straight into tmux `main` session on connect (forced via authorized_keys).
WireGuard must be active; SSID exclusions set for Loring + Loring-IOT (auto-connects on cellular/other WiFi).
IoT VLAN (Loring-IOT) blocks SSH to LAN — connect on main Loring SSID or via WireGuard only.
