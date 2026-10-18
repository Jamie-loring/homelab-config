#!/usr/bin/env python3
"""
Bulk LRCLib lyrics fetcher.
Walks MUSIC_ROOT directly (avoids Navidrome's stale DB paths).
Reads audio tags via mutagen for artist/title/album/duration.
Saves synced .lrc files alongside audio files.
"""
import json, urllib.request, urllib.parse, os, time, sys

try:
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    from mutagen.oggvorbis import OggVorbis
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

LRCLIB_URL    = "https://lrclib.net/api/get"
PROGRESS_FILE = "/tmp/lrc-sync-progress.json"
MUSIC_ROOT    = "/data/media/music"
AUDIO_EXTS    = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac"}
LOG_FILE      = "/var/log/lrc-sync.log"

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def get_tags(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == ".flac":
            tags = FLAC(filepath)
            artist = str(tags.get("artist", [""])[0])
            title  = str(tags.get("title",  [""])[0])
            album  = str(tags.get("album",  [""])[0])
            dur    = tags.info.length
        elif ext == ".mp3":
            tags = MP3(filepath)
            from mutagen.id3 import ID3NoHeaderError
            artist = str(tags.get("TPE1", [""])[0]) if tags.get("TPE1") else ""
            title  = str(tags.get("TIT2", [""])[0]) if tags.get("TIT2") else ""
            album  = str(tags.get("TALB", [""])[0]) if tags.get("TALB") else ""
            dur    = tags.info.length
        elif ext == ".m4a":
            tags = MP4(filepath)
            artist = str(tags.get("\xa9ART", [""])[0])
            title  = str(tags.get("\xa9nam", [""])[0])
            album  = str(tags.get("\xa9alb", [""])[0])
            dur    = tags.info.length
        elif ext in (".ogg", ".opus"):
            tags = OggVorbis(filepath)
            artist = str(tags.get("artist", [""])[0])
            title  = str(tags.get("title",  [""])[0])
            album  = str(tags.get("album",  [""])[0])
            dur    = tags.info.length
        else:
            return None
        return {"artist": artist, "title": title, "album": album, "duration": dur}
    except Exception:
        return None

def fetch_lrc(artist, title, album, duration_secs):
    params = urllib.parse.urlencode({
        "artist_name": artist,
        "track_name":  title,
        "album_name":  album,
        "duration":    int(duration_secs)
    })
    req = urllib.request.Request(f"{LRCLIB_URL}?{params}",
        headers={"User-Agent": "lrc-sync/1.0 (home-media-server)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read())
                return d.get("syncedLyrics") or d.get("plainLyrics")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return None
        except Exception:
            return None
    return None

def collect_audio_files(root):
    files = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in AUDIO_EXTS:
                files.append(os.path.join(dirpath, fn))
    return sorted(files)

def main():
    if not HAS_MUTAGEN:
        log("ERROR: mutagen not installed. Run: apt-get install python3-mutagen")
        sys.exit(1)

    log(f"Scanning {MUSIC_ROOT} for audio files...")
    files = collect_audio_files(MUSIC_ROOT)
    log(f"Found {len(files)} audio files")

    # Load progress (keyed by filepath)
    done = set()
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            done = set(json.load(f))
        log(f"Resuming — {len(done)} already processed")

    found = not_found = skipped = errors = 0
    total = len(files)

    for i, filepath in enumerate(files):
        if filepath in done:
            skipped += 1
            continue

        lrc_path = os.path.splitext(filepath)[0] + ".lrc"
        if os.path.exists(lrc_path):
            skipped += 1
            done.add(filepath)
            continue

        tags = get_tags(filepath)
        if not tags or not tags["title"]:
            errors += 1
            done.add(filepath)
            continue

        lyrics = fetch_lrc(tags["artist"], tags["title"], tags["album"], tags["duration"])

        if lyrics:
            try:
                with open(lrc_path, "w", encoding="utf-8") as f:
                    f.write(lyrics)
                found += 1
            except Exception as e:
                log(f"  Write error {lrc_path}: {e}")
                errors += 1
        else:
            not_found += 1

        done.add(filepath)

        pct = (i + 1) / total * 100
        print(f"\r  {i+1}/{total} ({pct:.1f}%)  found={found}  not_found={not_found}  skip={skipped}  errors={errors}  ", end="", flush=True)

        if i % 200 == 0:
            with open(PROGRESS_FILE, "w") as f:
                json.dump(list(done), f)

        time.sleep(0.1)

    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    print()
    summary = f"Done! Found: {found}  Not available: {not_found}  Already had .lrc: {skipped}  Errors: {errors}"
    log(summary)

if __name__ == "__main__":
    main()
