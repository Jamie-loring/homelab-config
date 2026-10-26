#!/usr/bin/env python3
"""
netmon — connectivity poller for the WireGuard phone/VM peers and the box's own uplink.
Every POLL seconds writes one CSV row per day-file to LOGDIR, and appends state changes to events.log.
Checks: WG peer handshake age / endpoint / traffic + ping over the tunnel, LAN gateway, AdGuard DNS,
WAN (TCP to 1.1.1.1), public IP vs DDNS, qBittorrent (gluetun) reachability.
"""
import csv, os, re, socket, struct, subprocess, time, random, urllib.request, glob

LOGDIR   = "/logs"
POLL     = 30
KEEP_DAYS= 30
PEERS    = {"<phone-peer-public-key>": ("phone", "10.13.13.2"),
            "<vm-peer-public-key>":    ("vm",    "10.13.13.4")}
GATEWAY  = os.environ.get("LAN_GATEWAY",  "<lan-gateway-ip>")
ADGUARD  = os.environ.get("ADGUARD_IP",  "<adguard-ip>")
DDNS     = "<your-ddns-hostname>"
STALE    = 180   # handshake older than this = tunnel idle/down (phone keepalive is 25s)

FIELDS = ["time","phone_endpoint","phone_hs_age","phone_rx_b","phone_tx_b","phone_ping_loss","phone_rtt_ms",
          "vm_endpoint","vm_hs_age","vm_ping_loss","gw_loss","gw_rtt_ms","dns_ms","dns_ok",
          "wan_ms","wan_ok","public_ip","ddns_ip","qbt_ok"]

def ping(host, n=3):
    try:
        out = subprocess.run(["ping","-c",str(n),"-W","1",host], capture_output=True, text=True, timeout=n+3).stdout
    except Exception:
        return 100, ""
    m = re.search(r"(\d+) packets received", out)
    recv = int(m.group(1)) if m else 0
    r = re.search(r"= [\d.]+/([\d.]+)/", out)
    return round(100*(n-recv)/n), (r.group(1) if r else "")

def dns_query(server, name="google.com", timeout=2):
    qid = random.randint(0, 65535)
    q = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + b"".join(
        bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(timeout)
    t = time.time()
    try:
        s.sendto(q, (server, 53)); data, _ = s.recvfrom(512)
        rcode = data[3] & 0x0F; an = struct.unpack(">H", data[6:8])[0]
        return round((time.time()-t)*1000), (rcode == 0 and an > 0), data
    except Exception:
        return "", False, b""
    finally:
        s.close()

def dns_a(server, name):
    _, ok, data = dns_query(server, name)
    if not ok: return ""
    m = re.search(rb"\xc0.\x00\x01\x00\x01.{4}\x00\x04(.{4})", data[12:], re.S)
    return socket.inet_ntoa(m.group(1)) if m else ""

def tcp_ms(host, port, timeout=3):
    t = time.time()
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return round((time.time()-t)*1000), True
    except Exception:
        return "", False

def public_ip():
    try:
        body = urllib.request.urlopen("https://1.1.1.1/cdn-cgi/trace", timeout=6).read().decode()
        return re.search(r"^ip=(.+)$", body, re.M).group(1)
    except Exception:
        return ""

def wg_dump():
    peers = {}
    try:
        out = subprocess.run(["wg","show","wg0","dump"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return peers
    for line in out.strip().split("\n")[1:]:
        f = line.split("\t")
        if len(f) >= 7:
            peers[f[0]] = {"endpoint": f[2], "hs": int(f[4]), "rx": int(f[5]), "tx": int(f[6])}
    return peers

def event(msg):
    with open(os.path.join(LOGDIR, "events.log"), "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")

def prune():
    cutoff = time.time() - KEEP_DAYS*86400
    for p in glob.glob(os.path.join(LOGDIR, "*.csv")):
        if os.path.getmtime(p) < cutoff: os.remove(p)

def main():
    os.makedirs(LOGDIR, exist_ok=True)
    state, last = {}, {}
    pub = ddns = ""; tick = 0
    event("netmon started")
    while True:
        t0 = time.time(); now = int(t0); row = {"time": time.strftime("%Y-%m-%d %H:%M:%S")}
        peers = wg_dump()
        for key, (name, ip) in PEERS.items():
            p = peers.get(key)
            if not p: continue
            age = now - p["hs"] if p["hs"] else -1
            loss, rtt = ping(ip)
            row[f"{name}_endpoint"] = p["endpoint"]; row[f"{name}_hs_age"] = age; row[f"{name}_ping_loss"] = loss
            if name == "phone":
                prev = last.get(key, p)
                row["phone_rx_b"] = p["rx"] - prev["rx"]; row["phone_tx_b"] = p["tx"] - prev["tx"]; row["phone_rtt_ms"] = rtt
                last[key] = p
            up = (0 <= age <= STALE) or loss < 100
            if state.get(name+"_up") is not None and state[name+"_up"] != up:
                event(f"{name} tunnel {'UP' if up else 'DOWN'} (handshake {age}s ago, ping loss {loss}%, endpoint {p['endpoint']})")
            state[name+"_up"] = up
            if state.get(name+"_ep") and state[name+"_ep"] != p["endpoint"]:
                event(f"{name} endpoint changed {state[name+'_ep']} -> {p['endpoint']} (network switch / NAT rebind)")
            state[name+"_ep"] = p["endpoint"]
        row["gw_loss"], row["gw_rtt_ms"] = ping(GATEWAY, 2)
        row["dns_ms"], row["dns_ok"], _ = dns_query(ADGUARD)
        row["wan_ms"], row["wan_ok"] = tcp_ms("1.1.1.1", 443)
        row["qbt_ok"] = tcp_ms("127.0.0.1", 8080)[1]
        if tick % 10 == 0:   # every ~5 min
            pub = public_ip() or pub; ddns = dns_a(ADGUARD, DDNS) or ddns
            if pub and ddns and pub != ddns:
                event(f"DDNS MISMATCH public {pub} vs {DDNS} -> {ddns} (remote peers can't connect)")
            if state.get("pub") and pub and state["pub"] != pub:
                event(f"public IP changed {state['pub']} -> {pub}")
            if pub: state["pub"] = pub
            if tick % 2880 == 0: prune()
        row["public_ip"], row["ddns_ip"] = pub, ddns
        for k, ok in (("wan", row["wan_ok"]), ("dns", row["dns_ok"]), ("gateway", row["gw_loss"] < 100), ("qbt", row["qbt_ok"])):
            if state.get(k) is not None and state[k] != ok:
                event(f"{k} {'RECOVERED' if ok else 'FAILED'}")
            state[k] = ok
        path = os.path.join(LOGDIR, time.strftime("%Y-%m-%d") + ".csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if new: w.writeheader()
            w.writerow(row)
        tick += 1
        time.sleep(max(1, POLL - (time.time() - t0)))

if __name__ == "__main__":
    main()
