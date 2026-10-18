#!/usr/bin/env python3
"""
qBittorrent stall/slow torrent cleanup with arr requeue.
- Stalled (stalledDL, no activity > STALL_MINUTES): blocklist + retry via arr, else delete
- Metadata stuck (metaDL > 30 min): treated as dead, blocklist + retry
- Slow (< SLOW_BYTES for SLOW_MINUTES): same
- Completed/seeding: untouched
- Blacklisted hashes (cleanup-blacklist.json): always skipped
"""
import json, urllib.request, urllib.parse, time, logging

LOG            = "/var/log/qbt-cleanup.log"
BLACKLIST_FILE = "/opt/arr/cleanup-blacklist.json"
QBT            = "http://localhost:8080"
STALL_MIN      = 120    # 2 hrs no activity (with seeders)
STALL_MIN_DEAD = 30     # 30 min if zero seeders/leechers
SLOW_MIN       = 360    # 6 hrs below speed threshold
SLOW_BYTES     = 2048   # 2 KB/s — truly glacial, not just thin seeders
BLACKLIST_TTL  = 30 * 86400  # prune entries older than 30 days

ARR = {
    "sonarr":  {"url": "http://sonarr:8989",  "key": "api/v3/queue", "apikey": open("/opt/appdata/sonarr/config.xml").read().split("<ApiKey>")[1].split("</ApiKey>")[0]},
    "radarr":  {"url": "http://radarr:7878",  "key": "api/v3/queue", "apikey": open("/opt/appdata/radarr/config.xml").read().split("<ApiKey>")[1].split("</ApiKey>")[0]},
    "lidarr":  {"url": "http://lidarr:8686",  "key": "api/v1/queue", "apikey": open("/opt/appdata/lidarr/config.xml").read().split("<ApiKey>")[1].split("</ApiKey>")[0]},
}

logging.basicConfig(filename=LOG, level=logging.INFO,
    format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

def load_blacklist():
    try:
        with open(BLACKLIST_FILE) as f:
            bl = json.load(f)
        # prune old entries
        cutoff = int(time.time()) - BLACKLIST_TTL
        return {h: v for h, v in bl.items() if v.get("at", 0) >= cutoff}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_blacklist(bl):
    with open(BLACKLIST_FILE, "w") as f:
        json.dump(bl, f, indent=2)

def blacklist_add(bl, hash_upper, name, reason):
    bl[hash_upper] = {"name": name[:80], "reason": reason, "at": int(time.time())}
    save_blacklist(bl)

def get(url, headers={}):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def post(url, data=b"", headers={}):
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()

def delete(url, headers={}):
    req = urllib.request.Request(url, method="DELETE", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()

def qbt_login():
    req = urllib.request.Request(QBT + "/api/v2/auth/login",
        data=b"username=admin&password=adminadmin", method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        for h in r.headers.get_all("Set-Cookie") or []:
            if "SID=" in h:
                return h.split("SID=")[1].split(";")[0]
    return ""  # auth bypass active — no SID needed

def qbt_delete(sid, hashes, delete_files=False):
    body = ("hashes=" + "|".join(hashes) + "&deleteFiles=" + str(delete_files).lower()).encode()
    hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
    if sid:
        hdrs["Cookie"] = "SID=" + sid
    req = urllib.request.Request(QBT + "/api/v2/torrents/delete", data=body, method="POST", headers=hdrs)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()

def build_arr_index():
    """Return dict of hash.upper() -> (app_name, queue_id) for all arr queues."""
    index = {}
    for app, cfg in ARR.items():
        try:
            url = f"{cfg['url']}/{cfg['key']}?pageSize=500&includeUnknownMovieItems=true"
            data = get(url, {"X-Api-Key": cfg["apikey"]})
            records = data.get("records", data) if isinstance(data, dict) else data
            for item in records:
                dl_id = (item.get("downloadId") or "").upper()
                if dl_id:
                    index[dl_id] = (app, item["id"])
        except Exception as e:
            logging.warning("arr index %s: %s", app, e)
    return index

def arr_blocklist_retry(app, queue_id):
    """Remove from arr queue with blocklist=true, triggering a re-search."""
    cfg = ARR[app]
    url = f"{cfg['url']}/{cfg['key']}/{queue_id}?removeFromClient=true&blocklist=true&skipRedownload=false"
    try:
        delete(url, {"X-Api-Key": cfg["apikey"]})
        return True
    except Exception as e:
        logging.warning("  arr blocklist %s id=%s: %s", app, queue_id, e)
        return False

def main():
    now = int(time.time())
    blacklist = load_blacklist()

    try:
        sid = qbt_login()
        if sid is None:
            logging.error("qbt login failed")
            return
        hdrs = {"Cookie": "SID=" + sid} if sid else {}
        torrents = get(QBT + "/api/v2/torrents/info", hdrs)
    except Exception as e:
        logging.error("qbt connect: %s", e)
        return

    candidates = []
    for t in torrents:
        state    = t.get("state", "")
        last_act = t.get("last_activity", 0)
        added    = t.get("added_on", 0)
        dlspeed  = t.get("dlspeed", 0)
        progress = t.get("progress", 0)
        seeders  = t.get("num_seeds", 0) + t.get("num_leechs", 0)
        h        = t["hash"].upper()

        # Skip hashes we already processed
        if h in blacklist:
            continue

        # Leave seeding/completed alone
        if state in ("uploading","stalledUP","seeding","checkingUP","checkingDL",
                     "pausedUP","queuedUP","forcedUP","pausedDL"):
            continue

        if state == "stalledDL":
            threshold = STALL_MIN_DEAD if seeders == 0 else STALL_MIN
            inactive = (now - last_act) / 60 if last_act else (now - added) / 60
            if inactive >= threshold:
                candidates.append((t, f"stalledDL {inactive:.0f}min", progress < 0.01))

        elif state == "metaDL":
            age = (now - added) / 60
            if age >= STALL_MIN_DEAD:
                candidates.append((t, f"metaDL {age:.0f}min", True))

        # queuedDL excluded: queued torrents always report 0 seeds, so they'd look dead
        elif state in ("downloading","forcedDL"):
            age = (now - added) / 60
            # Skip if seeders are present — slow but alive, give it time
            if seeders == 0 and dlspeed < SLOW_BYTES and age >= SLOW_MIN:
                candidates.append((t, f"{dlspeed//1024}KB/s {seeders}seeds for {age:.0f}min", progress < 0.01))

    if not candidates:
        return

    logging.info("=== cleanup: %d candidate(s) ===", len(candidates))
    arr_index = build_arr_index()

    for t, reason, empty in candidates:
        h    = t["hash"].upper()
        name = t["name"][:60]

        if h in arr_index:
            app, qid = arr_index[h]
            ok = arr_blocklist_retry(app, qid)
            if ok:
                logging.info("  REQUEUE [%s] via %s: %s", reason, app, name)
                blacklist_add(blacklist, h, name, f"requeue/{app}")
                continue
            # fallthrough to direct delete if arr call failed

        # Not in any arr queue or arr call failed — delete directly
        del_files = empty  # only nuke files if nothing was downloaded
        qbt_delete(sid, [t["hash"]], delete_files=del_files)
        logging.info("  DELETE [%s] del_files=%s: %s", reason, del_files, name)
        blacklist_add(blacklist, h, name, f"delete/{reason}")

    logging.info("  done.")

if __name__ == "__main__":
    main()
