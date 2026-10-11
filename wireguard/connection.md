# WireGuard VPN — Home Lab

## Overview

WireGuard server runs on the **media server** (`192.168.132.4`, `mediabox.lan`), not the router.
Public DNS endpoint: `vpn.jamieloring.com:51820` (Cloudflare-managed DDNS → home IP).

## Network

| Network | CIDR |
|---|---|
| LAN | 192.168.132.0/24 |
| WireGuard tunnel | 10.13.13.0/24 |
| Server tunnel IP | 10.13.13.1 |
| Split tunnel — routes | LAN + VPN only; internet goes direct |

DNS inside tunnel: `192.168.132.168` (AdGuard Home)

## Server

- **Host:** mediabox (192.168.132.4), Debian 13
- **Config:** `/etc/wireguard/wg0.conf`
- **Service:** `systemctl status wg-quick@wg0`
- **Public key:** `vXBDj0UlnAYfPtQD7PvVs9OOJWy92cWopQHEiE8nahc=`
- **Listen port:** 51820

NAT/forwarding handled by PostUp iptables rules on `enp1s0`.

## Client config template

```ini
[Interface]
Address = 10.13.13.<N>/32
DNS = 192.168.132.168
PrivateKey = <CLIENT_PRIVATE_KEY>

[Peer]
PublicKey = vXBDj0UlnAYfPtQD7PvVs9OOJWy92cWopQHEiE8nahc=
Endpoint = vpn.jamieloring.com:51820
AllowedIPs = 192.168.132.0/24, 10.13.13.0/24
PersistentKeepalive = 25
```

## Adding a new peer

On the server:
```bash
wg genkey | tee /tmp/client.key | wg pubkey > /tmp/client.pub
# Add to /etc/wireguard/wg0.conf:
# [Peer]
# PublicKey = <contents of /tmp/client.pub>
# AllowedIPs = 10.13.13.<N>/32
wg syncconf wg0 <(wg-quick strip wg0)
```

## Encrypted backup

`wireguard-backup.tar.gz.gpg` in this repo contains the full server `/etc/wireguard/` directory,
encrypted with GPG symmetric AES-256. Passphrase is known to Jamie.

To restore:
```bash
gpg -d wireguard-backup.tar.gz.gpg | tar xzf - -C /
systemctl restart wg-quick@wg0
```

To regenerate the backup from the server:
```bash
ssh -o StrictHostKeyChecking=no -i ~/.ssh/claude_mediaserver -p 22 root@192.168.132.4 \
  "tar czf - /etc/wireguard/" | gpg --symmetric --cipher-algo AES256 -o wireguard-backup.tar.gz.gpg
```
