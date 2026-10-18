#!/usr/bin/env python3
"""
Spotify → Navidrome sync
Playlists created:
  - ❤️ Spotify Liked    (all saved/liked songs that match library)
  - 🕐 Spotify Recent   (last 50 played that match library)
Missing artists queued in Lidarr automatically.
"""
import json, urllib.request, urllib.parse, urllib.error, hashlib, base64, time, re

SPOTIFY_CLIENT_ID     = "<local>"
SPOTIFY_CLIENT_SECRET = "<local>"
SPOTIFY_REFRESH_TOKEN = "<local>"

ND_URL   = "http://localhost:4533"
ND_USER  = "jamie"
ND_PASS  = "<local>"

LIDARR_URL = "http://localhost:8686"

# ── Spotify ───────────────────────────────────────────────────────────────────

_spotify_token = None

def spotify_access_token():
    global _spotify_token
    credentials = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": SPOTIFY_REFRESH_TOKEN,
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        _spotify_token = json.loads(r.read())["access_token"]
    return _spotify_token

def spotify_get(path):
    token = _spotify_token or spotify_access_token()
    req = urllib.request.Request(
        "https://api.spotify.com/v1" + path,
        headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # Token expired, refresh and retry
            spotify_access_token()
            req.add_header("Authorization", f"Bearer {_spotify_token}")
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        raise

def _extract_tracks_from_page(data):
    """Extract track list from a paginated Spotify response (handles both old 'track' and new 'item' key)."""
    tracks = []
    for item in data.get("items", []):
        t = item.get("track") or item.get("item")
        if not t or not isinstance(t, dict) or not t.get("name"):
            continue
        artists = t.get("artists", [])
        tracks.append({
            "artist": artists[0]["name"] if artists else "",
            "title": t.get("name", ""),
            "album": t.get("album", {}).get("name", ""),
        })
    return tracks

def spotify_liked_tracks():
    """Fetch all liked/saved tracks. Returns list of {artist, title, album}."""
    tracks = []
    url = "/me/tracks?limit=50"
    while url:
        data = spotify_get(url)
        tracks.extend(_extract_tracks_from_page(data))
        next_url = data.get("next")
        url = next_url.replace("https://api.spotify.com/v1", "") if next_url else None
        time.sleep(0.1)
    return tracks

def spotify_recent_tracks():
    """Fetch last 50 recently played tracks."""
    data = spotify_get("/me/player/recently-played?limit=50")
    return _extract_tracks_from_page(data)

def spotify_playlist_tracks(playlist_id):
    """Fetch all tracks from a playlist. Returns list of {artist, title, album}."""
    tracks = []
    url = f"/playlists/{playlist_id}/items?limit=50"
    while url:
        try:
            data = spotify_get(url)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return None
            raise
        tracks.extend(_extract_tracks_from_page(data))
        next_url = data.get("next")
        url = next_url.replace("https://api.spotify.com/v1", "") if next_url else None
        time.sleep(0.1)
    return tracks

def spotify_user_playlists():
    """Fetch all user playlists. Returns list of {id, name}."""
    playlists = []
    url = "/me/playlists?limit=50"
    while url:
        data = spotify_get(url)
        for p in data.get("items", []):
            if p:
                playlists.append({"id": p["id"], "name": p["name"]})
        next_url = data.get("next")
        url = next_url.replace("https://api.spotify.com/v1", "") if next_url else None
        time.sleep(0.1)
    return playlists

# ── Navidrome ─────────────────────────────────────────────────────────────────

def _nd_token():
    salt = "abc123"
    token = hashlib.md5((ND_PASS + salt).encode()).hexdigest()
    return f"u={ND_USER}&t={token}&s={salt}&v=1.16.0&c=spotify-sync&f=json"

def nd_get(endpoint, extra=""):
    sep = "&" if extra else ""
    url = f"{ND_URL}/rest/{endpoint}?{_nd_token()}{sep}{extra}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())["subsonic-response"]

def nd_search_song(artist, title):
    query = urllib.parse.quote(title[:60])
    r = nd_get("search3.view", f"query={query}&songCount=10&albumCount=0&artistCount=0")
    songs = r.get("searchResult3", {}).get("song", [])
    artist_l = artist.lower()
    for s in songs:
        if artist_l in s.get("artist", "").lower() or s.get("artist", "").lower() in artist_l:
            return s["id"]
    return None

def nd_list_playlists():
    r = nd_get("getPlaylists.view")
    return r.get("playlists", {}).get("playlist", [])

def nd_upsert_playlist(name, song_ids):
    if not song_ids:
        print(f"  {name}: 0 matched — skipping")
        return
    existing = next((p for p in nd_list_playlists() if p["name"] == name), None)
    if existing:
        nd_get("deletePlaylist.view", f"id={existing['id']}")
    ids_qs = "&".join(f"songId={sid}" for sid in song_ids)
    nd_get("createPlaylist.view", f"name={urllib.parse.quote(name)}&{ids_qs}")
    print(f"  {name}: {len(song_ids)} tracks")

# ── Lidarr ────────────────────────────────────────────────────────────────────

LIDARR_KEY = None

def _lidarr_key():
    with open("/opt/appdata/lidarr/config.xml") as f:
        m = re.search(r"<ApiKey>([^<]+)</ApiKey>", f.read())
        return m.group(1) if m else None

def lidarr_get(path):
    global LIDARR_KEY
    if not LIDARR_KEY:
        LIDARR_KEY = _lidarr_key()
    req = urllib.request.Request(f"{LIDARR_URL}/api/v1/{path}", headers={"X-Api-Key": LIDARR_KEY})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (503, 502) and attempt < 2:
                time.sleep(5)
                continue
            raise
    return []

ARTIST_BLOCKLIST = {
    "r. kelly", "r kelly",
    "marilyn manson",
    "sean combs", "p. diddy", "diddy", "puff daddy",
}

def lidarr_ensure_artist(artist_name):
    global LIDARR_KEY
    if artist_name.lower() in ARTIST_BLOCKLIST:
        return False
    if not LIDARR_KEY:
        LIDARR_KEY = _lidarr_key()
    all_artists = lidarr_get("artist")
    name_l = artist_name.lower()
    for a in all_artists:
        if a.get("artistName", "").lower() == name_l:
            return False
    q = urllib.parse.quote(artist_name)
    results = lidarr_get(f"artist/lookup?term={q}")
    if not results:
        return False
    hit = results[0]
    root = lidarr_get("rootfolder")[0]["path"]
    profile_id = lidarr_get("qualityprofile")[0]["id"]
    meta_id = lidarr_get("metadataprofile")[0]["id"]
    payload = json.dumps({
        "foreignArtistId": hit.get("foreignArtistId"),
        "artistName": hit.get("artistName", artist_name),
        "qualityProfileId": profile_id,
        "metadataProfileId": meta_id,
        "monitored": True,
        "rootFolderPath": root,
        "addOptions": {"monitor": "all", "searchForMissingAlbums": True}
    }).encode()
    req = urllib.request.Request(
        f"{LIDARR_URL}/api/v1/artist", data=payload,
        headers={"X-Api-Key": LIDARR_KEY, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True
    except Exception:
        return False

# ── Resolve tracks → ND ids ───────────────────────────────────────────────────

def resolve_tracks(tracks, label):
    ids = []
    queued = []
    seen_queue = set()
    for i, t in enumerate(tracks):
        artist, title = t["artist"], t["title"]
        sid = nd_search_song(artist, title)
        if sid:
            ids.append(sid)
        elif artist and artist.lower() not in seen_queue:
            seen_queue.add(artist.lower())
            if lidarr_ensure_artist(artist):
                queued.append(artist)
        if i % 20 == 0:
            print(f"\r    {label}: {i+1}/{len(tracks)} checked, {len(ids)} matched...", end="", flush=True)
        time.sleep(0.05)
    print(f"\r    {label}: {len(ids)}/{len(tracks)} matched, {len(queued)} new artists queued" + " " * 10)
    return ids

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Spotify Sync ===\n")
    spotify_access_token()

    print("Fetching Spotify liked songs...")
    liked = spotify_liked_tracks()
    print(f"  Got {len(liked)} liked tracks from Spotify")
    liked_ids = resolve_tracks(liked, "Liked")
    nd_upsert_playlist("❤️ Spotify Liked", liked_ids)

    print("\nFetching Spotify recently played...")
    recent = spotify_recent_tracks()
    print(f"  Got {len(recent)} recent tracks from Spotify")
    recent_ids = resolve_tracks(recent, "Recent")
    nd_upsert_playlist("🕐 Spotify Recent", recent_ids)

    print("\nFetching Spotify playlists...")
    playlists = spotify_user_playlists()
    print(f"  Found {len(playlists)} playlists")
    for pl in playlists:
        tracks = spotify_playlist_tracks(pl["id"])
        if tracks is None:
            print(f"  {pl['name']}: skipped (no access)")
            continue
        print(f"  {pl['name']}: {len(tracks)} tracks")
        if not tracks:
            continue
        ids = resolve_tracks(tracks, pl["name"][:30])
        nd_upsert_playlist(f"🎵 {pl['name']}", ids)

    print("\n=== Done ===")

if __name__ == "__main__":
    main()
