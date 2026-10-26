# Media Server — Engineering Architecture

## Host

| | |
|---|---|
| **Hardware** | N100 mini PC |
| **OS** | Debian GNU/Linux 13 (trixie) |
| **IP** | <mediaserver-ip> (static, DHCP reservation) |
| **Storage** | NAS mount: `<nas-ip>:/mnt/HD/HD_a2/mediaserver` → `/data` (NFS over LAN, ~7.3TB) |
| **WireGuard** | Server on host, `/etc/wireguard/wg0.conf`, tunnel `10.13.13.0/24` |

---

## Container Architecture

All services run via Docker Compose at `/opt/arr/docker-compose.yml`.
Docker network: `arr_default` (bridge). Exceptions noted below.

```
Host (<mediaserver-ip>)
│
├── gluetun          [bridge, host ports 8080/6881]   — OpenVPN killswitch container
│   └── qbittorrent  [network_mode: service:gluetun]  — shares gluetun's network stack
│                                                         ALL torrent traffic exits via VPN
├── jellyfin         [bridge :8096]   — media player, hardware transcode via /dev/dri
├── sonarr           [bridge :8989]   — TV automation, DNS via dnscache
├── radarr           [bridge :7878]   — movie automation, DNS via dnscache
├── lidarr           [bridge :8686]   — music automation, DNS via dnscache
├── prowlarr         [bridge :9696]   — indexer proxy, DNS via dnscache
├── bazarr           [bridge :6767]   — subtitle automation, DNS via dnscache
├── flaresolverr     [bridge :8191]   — Cloudflare bypass for Prowlarr
├── jellyseerr       [bridge :5055]   — request UI (Jellyfin + arr)
├── homarr           [bridge :7575]   — dashboard, docker.sock read-only
├── navidrome        [bridge :4533]   — music streaming (Subsonic API)
├── dnscache         [host]           — CoreDNS local cache (172.18.0.1)
├── netmon           [host]           — WireGuard peer + connectivity monitor
└── claude-box       [host, privileged] — Claude Code SSH container, port 2222
```

### DNS Architecture

Arr containers (sonarr/radarr/lidarr/prowlarr/bazarr) use `dns: 172.18.0.1` (CoreDNS cache container on host network). CoreDNS forwards to AdGuard @ `<adguard-ip>`. This prevents DNS-over-container-bridge latency and gives local `.lan` resolution inside containers.

### VPN / qBittorrent Isolation

gluetun is a killswitch VPN container. qBittorrent runs in `network_mode: service:gluetun` — it shares gluetun's network namespace entirely. If the VPN drops, qBittorrent loses internet access automatically. `FIREWALL_OUTBOUND_SUBNETS=<lan-subnet>` allows qBittorrent to still reach the LAN (for arr communication) while all internet traffic goes through the VPN.

VPN provider: ExpressVPN, custom OpenVPN config at `/opt/arr/gluetun/custom.ovpn`.
`vpn-watchdog.sh` (cron every 5 min) re-resolves the endpoint hostname and restarts gluetun if the IP rotated or health check fails.

### claude-box Container

Built from `/opt/arr/claude-box/Dockerfile`. Based on `node:22-slim`. Contains:
- Claude Code (`@anthropic-ai/claude-code`) via npm
- openssh-server on port 2222 (key-only, root)
- tmux (auto-attach on SSH login via `.bashrc`)
- python3 + mutagen
- docker CLI (for managing the host stack from inside the container)

Volumes: full access to `/opt/arr`, `/opt/appdata`, `/data`, `/etc/wireguard`, `/root/.claude`, docker socket.
Network: host mode — can reach all LAN services directly.

Phone access (Terminus): RSA 4096 PEM key, forced tmux attach via `authorized_keys command=`.

---

## Data Layout

```
/data/
├── media/
│   ├── music/          Artist/Album (YYYY)/tracks + .lrc lyrics
│   ├── movies/         Movie (YYYY)/file.mkv
│   └── tv/             Series/Season XX/episodes
├── torrents/           qBittorrent download staging
└── logs/
    └── netmon/         Per-day CSV connectivity logs
```

`/opt/appdata/<service>/` — per-service config, databases, cache. Not backed up (regenerable).

---

## Scripts (`/opt/arr/`)

| Script | Purpose | Schedule |
|---|---|---|
| `spotify-sync.py` | Sync Spotify liked/recent/playlists → Navidrome playlists; auto-queue missing artists in Lidarr | Daily 3am |
| `lrc-sync.py` | Fetch synced `.lrc` lyrics from LRCLib for all music files | Daily 3am |
| `fix_albumartist_global.py` | Normalize ALBUMARTIST tags — collapses featuring-credit splits into single album entries in Navidrome | On demand |
| `normalize-tags.py` | MusicBrainz tag enrichment pass | Daily 4:30am |
| `qbt-cleanup.py` | Remove stalled/dead torrents, blocklist in arr, trigger retry | Every 15 min |
| `vpn-watchdog.sh` | Re-resolve VPN endpoint IP, restart gluetun if unhealthy | Every 5 min |
| `netmon.py` | Poll WG peer health, LAN/WAN/DNS connectivity; log to CSV | Continuous (30s) |
| `playlist-sync.py` | Navidrome playlist sync helper | Daily 3am |

---

## WireGuard

Server on media server host (not the router).
- Interface: `wg0`, `10.13.13.1/24`, port `51820`
- DDNS: `<your-ddns-hostname>` (Cloudflare, updated by router every 5 min)
- DNS split horizon: AdGuard resolves `<your-ddns-hostname>` → `<mediaserver-ip>` for LAN clients (hairpin fix)
- Peers: phone `10.13.13.2`, VM `10.13.13.3`
- Private keys: NOT backed up. Stored in Jamie's memory only.
- See `../wireguard/connection.md` for full topology.

---

## Network Context

| | |
|---|---|
| **LAN** | <lan-subnet> |
| **IoT VLAN** | <iot-subnet> — DROP IoT→LAN except Jellyfin :8096 and Navidrome :4533 |
| **WireGuard tunnel** | 10.13.13.0/24 |
| **Router** | DD-WRT R6700 @ <router-ip> |
| **DNS** | AdGuard Home @ <adguard-ip> (forced via DNAT) |
| **NAS** | WD My Cloud EX2 Ultra @ <nas-ip> |

**IoT VLAN caveat:** SSH to media server fails from the IoT SSID. Use main LAN SSID or WireGuard.

---

## Arr Stack Data Flow

```
Prowlarr (indexers)
    ↓ feeds
Sonarr / Radarr / Lidarr
    ↓ sends grabs to
qBittorrent (via gluetun VPN)
    ↓ downloads to /data/torrents
    ↓ arr imports/hardlinks to
/data/media/{tv,movies,music}
    ↓ served by
Jellyfin / Navidrome
    ↓ requested via
Jellyseerr
```

Lidarr API key location: `/opt/appdata/lidarr/config.xml` → `<ApiKey>`.
Same pattern for sonarr/radarr/prowlarr/bazarr.
