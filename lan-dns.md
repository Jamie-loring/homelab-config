# LAN DNS Shortcuts (.lan)

All entries are AdGuard Home DNS rewrites on **<adguard-ip>**, pointing to the media server at **<mediaserver-ip>** unless noted.

## Media Server (<mediaserver-ip>) — arr stack

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
| mediabox.lan | <mediaserver-ip> | SSH port 2222 → claude-box container; drops into tmux `main` |
| *(no shortcut)* | <adguard-ip> | AdGuard Home web UI — use IP directly |

## Adding a new entry

```bash
ssh root@<adguard-ip>
```

Edit `/opt/AdGuardHome/AdGuardHome.yaml`, append under `dns.rewrites`:

```yaml
    - domain: newname.lan
      answer: <mediaserver-ip>
      enabled: true
```

Then:

```bash
systemctl restart AdGuardHome
```

> **Note:** `enabled: true` is required per entry — AdGuard silently ignores rewrites without it. Edit line-by-line with Python, not `yaml.dump` (parser is fragile).
