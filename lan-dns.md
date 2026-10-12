# LAN DNS Shortcuts (.lan)

All entries are AdGuard Home DNS rewrites on **192.168.132.168**, pointing to the media server at **192.168.132.4** unless noted.

## Media Server (192.168.132.4) — arr stack

| Address | Port | Service |
|---|---|---|
| jf.lan / jellyfin.lan | :8096 | Jellyfin — main media player |
| seerr.lan / jellyseerr.lan | :5055 | Jellyseerr — request UI for movies/TV |
| dash.lan | :7575 | Homarr — dashboard |
| lidarr.lan | :8686 | Lidarr — music library manager |
| music.lan | :4533 | Navidrome — music streaming (Subsonic API) |
| torrent.lan | :8080 | qBittorrent — behind gluetun VPN |

## Other

| Address | Host | Notes |
|---|---|---|
| mediabox.lan | 192.168.132.4 | SSH port 2222 → claude-box container; drops into tmux `main` |
| *(no shortcut)* | 192.168.132.168 | AdGuard Home web UI — use IP directly |

## Adding a new entry

```bash
ssh -i ~/.ssh/pihole_root root@192.168.132.168
```

Edit `/opt/AdGuardHome/AdGuardHome.yaml`, append under `dns.rewrites`:

```yaml
    - domain: newname.lan
      answer: 192.168.132.4
      enabled: true
```

Then:

```bash
systemctl restart AdGuardHome
```

> **Note:** `enabled: true` is required per entry — AdGuard silently ignores rewrites without it. Edit line-by-line with Python, not `yaml.dump` (parser is fragile).
