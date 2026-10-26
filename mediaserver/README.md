# Media Server — Setup & Runbook

N100 mini PC, Debian 13. Static IP `192.168.132.4`. Full arr stack running as Docker containers.

---

## Quick Reference

| Service | Port | LAN URL |
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

DNS rewrites: AdGuard Home @ `192.168.132.168`. See `../lan-dns.md`.

---

## Key Paths

| Path | What |
|---|---|
| `/opt/arr/docker-compose.yml` | All Docker services |
| `/opt/appdata/<service>/` | Per-service config & DB |
| `/data/media/` | Music, movies, TV |
| `/data/torrents/` | qBittorrent download dir |
| `/opt/arr/` | Management scripts |
| `/root/CLAUDE.md` | Claude Code context on the box |

---

## Fresh Install Steps

### 1. Prerequisites

```bash
apt-get update && apt-get install -y docker.io docker-compose-plugin python3 python3-mutagen git
```

### 2. Create data directories

```bash
mkdir -p /opt/arr /opt/appdata /data/media/{music,movies,tv} /data/torrents
```

### 3. Deploy stack

```bash
cp docker-compose.yml /opt/arr/docker-compose.yml
# Fill in <local> placeholders before deploying
cd /opt/arr && docker compose up -d
```

### 4. Credentials to fill in (`<local>` placeholders)

- `docker-compose.yml` → `SECRET_ENCRYPTION_KEY` (Homarr)
- `scripts/spotify-sync.py` → `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN`, `ND_PASS`
- `/opt/arr/gluetun.env` → VPN provider credentials (not backed up)

### 5. Scripts

Copy all scripts from `scripts/` to `/opt/arr/` and make executable:

```bash
cp scripts/*.py /opt/arr/
chmod +x /opt/arr/*.py
```

### 6. Cron jobs

```
30 4 * * *  python3 /opt/arr/spotify-sync.py >> /var/log/spotify-sync.log 2>&1
0  3 * * *  python3 /opt/arr/lrc-sync.py >> /var/log/lrc-sync.log 2>&1
*/15 * * * * python3 /opt/arr/qbt-cleanup.py >> /var/log/qbt-cleanup.log 2>&1
```

---

## claude-box Container

Privileged Docker container with host networking. SSH on port 2222. Drops into tmux `main`.

```
Port: 2222
User: root
Key:  RSA 4096 PEM (terminus_rsa) — stored locally / in Terminus app
```

The `claude-box/` Dockerfile is in `/opt/arr/claude-box/` on the server.
Phone access: connect over WireGuard, SSH to the server IP on port 2222.

---

## VPN (WireGuard)

Server runs on the media server host (not the router).
See `../wireguard/connection.md` for topology and restore instructions.
Private keys not backed up — stored in Jamie's memory.

---

## Music Library Notes

- Files: `Artist/Album (YYYY)/tracks`
- ALBUMARTIST tag must match the artist folder name or Navidrome creates duplicate album entries
- Run `fix_albumartist_global.py` after bulk imports to normalize featuring-credit tags
- Lyrics: `.lrc` files alongside audio, fetched by `lrc-sync.py` from LRCLib
- Navidrome rescan: `GET http://localhost:4533/rest/startScan.view?u=jamie&t=<md5(pass+salt)>&s=<salt>&v=1.16.0&c=mgmt&f=json`
- Search: use **Songs** section in web UI for track-title search

## Artist Blocklist (spotify-sync.py)

The following artists are permanently blocked from being re-added via Spotify sync:

```python
ARTIST_BLOCKLIST = {
    "r. kelly", "r kelly",
    "marilyn manson",
    "sean combs", "p. diddy", "diddy", "puff daddy",
}
```

---

## IoT VLAN Note

IoT VLAN (192.168.133.0/24) has DROP rule for IoT→LAN.
SSH to the media server will fail from the IoT SSID. Use main LAN SSID or WireGuard.
