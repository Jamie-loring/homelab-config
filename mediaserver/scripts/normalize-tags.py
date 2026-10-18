#!/usr/bin/env python3
"""
Music library tag normalizer + MusicBrainz feature importer.
Runs dry-run by default; pass --apply to write changes.

Phase 1 - Normalization:
  1. feat. standardization  (ft. / Ft. / Feat. / featuring / w/ → feat.)
  2. Strip junk brackets     ([FLAC] [RLG] [320kbps] [PERFECT] etc.)
  3. Self-tag in title       "Song - Artist" → "Song" when artist tag matches
  4. Whitespace              collapse double-spaces, strip leading/trailing

Phase 2 - MusicBrainz feature import:
  For tracks with no feat. in title, look up on MusicBrainz and inject
  featured artists found in artist-credit.
  Rate-limited to 1 req/sec. Resumable via progress file.
"""
import os, re, sys, time, json, urllib.request, urllib.parse, urllib.error

try:
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.mp3  import MP3
    from mutagen.id3  import ID3, TIT2, TALB, TPE1, TXXX, ID3NoHeaderError
    from mutagen.mp4  import MP4
    from mutagen.oggvorbis import OggVorbis
except ImportError:
    print("ERROR: mutagen not installed"); sys.exit(1)

MUSIC_ROOT    = "/data/media/music"
AUDIO_EXTS    = {".flac", ".mp3", ".m4a", ".ogg", ".opus"}
DRY_RUN       = "--apply" not in sys.argv
LOG_FILE      = "/var/log/normalize-tags.log"
MB_PROGRESS   = "/tmp/mb-feat-progress.json"
MB_USER_AGENT = "HomeMediaNormalizer/1.0 (jamie@jamieloring.com)"

# ── Regex patterns ─────────────────────────────────────────────────────────────

FEAT_RE = re.compile(
    r'\b(feat(?:uring)?\.?|ft\.?)\s+',
    re.IGNORECASE
)

JUNK_BRACKET_RE = re.compile(
    r'\s*[\[\(]'
    r'(?:FLAC|MP3|AAC|OGG|WAV|ALAC'
    r'|3\d{2}(?:\s*kbps)?'
    r'|VBR|CBR|HQ|HD'
    r'|RLG|PERFECT|vigoni|H4CKUS|DEFiANT|FiH|YIFY|YTS|ETRG|rartv'
    r'|Scene\s*Release|NFO'
    r')'
    r'[\]\)]',
    re.IGNORECASE
)

# Album clutter — editions, years, remasters, regional variants
ALBUM_CLUTTER_RE = re.compile(
    r'\s*[\[\(]'
    r'(?:'
    # standalone year
    r'(?:19|20)\d{2}'
    # remaster / mix / version with optional year
    r'|(?:(?:19|20)\d{2}\s+)?(?:Re)?[Mm]aster(?:ed)?(?:\s+(?:19|20)\d{2})?'
    r'|(?:(?:19|20)\d{2}\s+)?(?:Re)?[Mm]ix(?:\s+(?:19|20)\d{2})?'
    r'|(?:(?:19|20)\d{2}\s+)?[Vv]ersion(?:\s+(?:19|20)\d{2})?'
    # edition qualifiers
    r'|(?:Super\s+)?[Dd]eluxe(?:\s+Edition|\s+Version)?'
    r'|[Ss]tandard(?:\s+Edition)?'
    r'|[Ss]pecial(?:\s+Edition)?'
    r'|[Ee]xpanded(?:\s+Edition)?'
    r'|(?:\d+\w*\s+)?[Aa]nniversary(?:\s+Edition)?'
    r'|[Cc]ollector.s(?:\s+Edition)?'
    r'|[Ll]imited(?:\s+Edition)?'
    r'|[Bb]onus\s+[Tt]rack(?:s)?(?:\s+[Vv]ersion)?'
    r'|[Cc]omplete(?:\s+Edition)?'
    r'|[Ee]dition'
    # regional variants
    r'|(?:Japan(?:ese)?|UK|US|USA|European?|Australian?|Canadian?|International)'
    r'(?:\s+(?:Edition|Version|Release|Import|Pressing|Bonus))?'
    r')'
    r'[\]\)]',
    re.IGNORECASE
)

def strip_self_tag(title, artist):
    if not artist:
        return title
    pattern = re.compile(
        r'\s+[-–]\s+' + re.escape(artist.strip()) + r'\s*$',
        re.IGNORECASE
    )
    return pattern.sub('', title).strip()

def normalize_feat(s):
    return FEAT_RE.sub('feat. ', s)

def normalize_whitespace(s):
    s = re.sub(r'  +', ' ', s)
    return s.strip()

def strip_junk(s):
    return JUNK_BRACKET_RE.sub('', s).strip()

def normalize_title(title, artist):
    t = normalize_feat(title)
    t = strip_junk(t)
    t = strip_self_tag(t, artist)
    t = normalize_whitespace(t)
    return t

def normalize_album(album):
    a = strip_junk(album)
    # Strip repeatedly until stable (handles stacked suffixes)
    prev = None
    while prev != a:
        prev = a
        a = ALBUM_CLUTTER_RE.sub('', a)
    a = normalize_whitespace(a)
    return a

def has_feat(title):
    return bool(re.search(r'\bfeat\.', title, re.IGNORECASE))

# ── Tag reading/writing ────────────────────────────────────────────────────────

def read_tags_flac(path):
    tags = FLAC(path)
    mbid = str(tags.get('musicbrainz_trackid', tags.get('musicbrainz_recordingid', ['']))[0])
    return {
        'title':  str(tags.get('title',  [''])[0]),
        'album':  str(tags.get('album',  [''])[0]),
        'artist': str(tags.get('artist', [''])[0]),
        'mbid':   mbid,
    }

def write_tags_flac(path, title=None, album=None):
    tags = FLAC(path)
    if title is not None: tags['title'] = [title]
    if album is not None: tags['album'] = [album]
    tags.save()

def read_tags_mp3(path):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return None
    mbid = ''
    for key in tags.keys():
        if 'MUSICBRAINZ' in key.upper() and 'RECORDING' in key.upper():
            mbid = str(tags[key])
            break
    return {
        'title':  str(tags.get('TIT2', '')),
        'album':  str(tags.get('TALB', '')),
        'artist': str(tags.get('TPE1', '')),
        'mbid':   mbid,
    }

def write_tags_mp3(path, title=None, album=None):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    if title is not None: tags['TIT2'] = TIT2(encoding=3, text=title)
    if album is not None: tags['TALB'] = TALB(encoding=3, text=album)
    tags.save(path)

def read_tags_m4a(path):
    tags = MP4(path)
    return {
        'title':  str(tags.get('\xa9nam', [''])[0]),
        'album':  str(tags.get('\xa9alb', [''])[0]),
        'artist': str(tags.get('\xa9ART', [''])[0]),
        'mbid':   '',
    }

def write_tags_m4a(path, title=None, album=None):
    tags = MP4(path)
    if title is not None: tags['\xa9nam'] = [title]
    if album is not None: tags['\xa9alb'] = [album]
    tags.save()

def read_tags_ogg(path):
    tags = OggVorbis(path)
    return {
        'title':  str(tags.get('title',  [''])[0]),
        'album':  str(tags.get('album',  [''])[0]),
        'artist': str(tags.get('artist', [''])[0]),
        'mbid':   str(tags.get('musicbrainz_trackid', [''])[0]),
    }

def write_tags_ogg(path, title=None, album=None):
    tags = OggVorbis(path)
    if title is not None: tags['title'] = [title]
    if album is not None: tags['album'] = [album]
    tags.save()

def get_handlers(ext):
    return {
        '.flac': (read_tags_flac, write_tags_flac),
        '.mp3':  (read_tags_mp3,  write_tags_mp3),
        '.m4a':  (read_tags_m4a,  write_tags_m4a),
        '.ogg':  (read_tags_ogg,  write_tags_ogg),
        '.opus': (read_tags_ogg,  write_tags_ogg),
    }.get(ext)

# ── MusicBrainz ────────────────────────────────────────────────────────────────

_mb_last_req = 0.0

def mb_get(url):
    global _mb_last_req
    elapsed = time.time() - _mb_last_req
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
    req = urllib.request.Request(url, headers={
        'User-Agent': MB_USER_AGENT,
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            _mb_last_req = time.time()
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(5)
            return mb_get(url)
        return None
    except Exception:
        return None

def mb_get_features_by_mbid(mbid):
    data = mb_get(f"https://musicbrainz.org/ws/2/recording/{mbid}?inc=artist-credits&fmt=json")
    return extract_features(data) if data else None

def mb_search_features(artist, title):
    q = urllib.parse.quote(f'recording:"{title}" AND artist:"{artist}"')
    data = mb_get(f"https://musicbrainz.org/ws/2/recording/?query={q}&limit=3&fmt=json")
    if not data:
        return None
    recordings = data.get('recordings', [])
    if not recordings:
        return None
    # Pick best match — same artist, same title
    artist_l = artist.lower()
    title_l  = title.lower()
    for rec in recordings:
        credits = rec.get('artist-credit', [])
        rec_artist = ''.join(
            (c.get('artist', {}).get('name', '') + c.get('joinphrase', ''))
            for c in credits if isinstance(c, dict)
        ).lower()
        rec_title = rec.get('title', '').lower()
        if artist_l in rec_artist and rec_title == title_l:
            return extract_features(rec)
    return None

def extract_features(data):
    """Return list of featured artist names from a MusicBrainz recording dict."""
    credits = data.get('artist-credit', [])
    if len(credits) <= 1:
        return []
    features = []
    take_next = False
    for c in credits:
        if not isinstance(c, dict):
            continue
        joinphrase = c.get('joinphrase', '')
        name = c.get('artist', {}).get('name', '')
        if take_next and name:
            features.append(name)
            take_next = False
        if 'feat' in joinphrase.lower() or 'ft.' in joinphrase.lower():
            take_next = True
    # Fallback: if credits > 1 and first artist matches main, rest are features
    if not features and len(credits) > 1:
        for c in credits[1:]:
            if isinstance(c, dict):
                name = c.get('artist', {}).get('name', '')
                if name:
                    features.append(name)
    return features

# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    mode = "DRY RUN" if DRY_RUN else "APPLYING CHANGES"
    log(f"=== normalize-tags + MB feat import [{mode}] ===")

    files = []
    for dirpath, _, filenames in os.walk(MUSIC_ROOT):
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext in AUDIO_EXTS:
                files.append(os.path.join(dirpath, fn))
    files.sort()
    log(f"Found {len(files)} audio files")

    # Load MB progress cache
    mb_done = {}
    if os.path.exists(MB_PROGRESS):
        with open(MB_PROGRESS) as f:
            mb_done = json.load(f)
        log(f"MB cache: {len(mb_done)} tracks already looked up")

    norm_changed = mb_changed = errors = 0
    mb_candidates = []  # (path, tags) needing MB lookup

    # ── Phase 1: Normalization ─────────────────────────────────────────────────
    log("--- Phase 1: Normalization ---")
    for i, path in enumerate(files):
        ext = os.path.splitext(path)[1].lower()
        handlers = get_handlers(ext)
        if not handlers:
            continue
        read_fn, write_fn = handlers
        try:
            tags = read_fn(path)
        except Exception:
            errors += 1
            continue
        if not tags:
            continue

        orig_title = tags.get('title', '') or ''
        orig_album = tags.get('album', '') or ''
        artist     = tags.get('artist', '') or ''

        new_title = normalize_title(orig_title, artist)
        new_album = normalize_album(orig_album)

        diff = {}
        if new_title != orig_title: diff['title'] = (orig_title, new_title)
        if new_album != orig_album: diff['album'] = (orig_album, new_album)

        if diff:
            norm_changed += 1
            rel = os.path.relpath(path, MUSIC_ROOT)
            for field, (old, new) in diff.items():
                print(f"  NORM [{field}] {repr(old)} → {repr(new)}", flush=True)
            if not DRY_RUN:
                try:
                    write_fn(path,
                        title=new_title if 'title' in diff else None,
                        album=new_album if 'album' in diff else None,
                    )
                    # Update tags for MB phase
                    tags['title'] = new_title
                except Exception as e:
                    log(f"  WRITE ERROR {path}: {e}")
                    errors += 1

        # Queue for MB if no feat. in final title
        final_title = new_title if 'title' in diff else orig_title
        if final_title and not has_feat(final_title) and artist:
            mb_candidates.append((path, tags, final_title, write_fn))

        if (i + 1) % 500 == 0:
            log(f"Phase 1: {i+1}/{len(files)} scanned, {norm_changed} normalized")

    log(f"Phase 1 done: {norm_changed} files normalized, {len(mb_candidates)} queued for MB lookup")

    # ── Phase 2: MusicBrainz feature import ───────────────────────────────────
    log("--- Phase 2: MusicBrainz feature import ---")
    mb_total = len(mb_candidates)
    for i, (path, tags, title, write_fn) in enumerate(mb_candidates):
        artist = tags.get('artist', '') or ''
        mbid   = tags.get('mbid', '') or ''
        cache_key = path

        if cache_key in mb_done:
            continue

        # Look up features
        features = None
        if mbid:
            features = mb_get_features_by_mbid(mbid)
        if features is None:
            features = mb_search_features(artist, title)

        mb_done[cache_key] = features or []

        if features:
            feat_str = ' & '.join(features) if len(features) > 1 else features[0]
            new_title = f"{title} (feat. {feat_str})"
            mb_changed += 1
            rel = os.path.relpath(path, MUSIC_ROOT)
            print(f"  FEAT  {rel}: {repr(title)} → {repr(new_title)}", flush=True)
            if not DRY_RUN:
                try:
                    write_fn(path, title=new_title)
                except Exception as e:
                    log(f"  WRITE ERROR {path}: {e}")
                    errors += 1

        if (i + 1) % 100 == 0:
            pct = (i + 1) / mb_total * 100
            log(f"Phase 2: {i+1}/{mb_total} ({pct:.0f}%)  feat_added={mb_changed}")
            with open(MB_PROGRESS, 'w') as f:
                json.dump(mb_done, f)

    # Save final MB cache
    with open(MB_PROGRESS, 'w') as f:
        json.dump(mb_done, f)

    log(f"=== Done: {norm_changed} normalized, {mb_changed} features added, {errors} errors ===")
    if DRY_RUN:
        log("Re-run with --apply to write all changes.")
    else:
        log("Triggering Navidrome rescan...")
        try:
            import hashlib
            salt = 'abc123'
            token = hashlib.md5(('jamie' + salt).encode()).hexdigest()
            auth = f"u=jamie&t={token}&s={salt}&v=1.16.0&c=normalizer&f=json"
            urllib.request.urlopen(f"http://localhost:4533/rest/startScan.view?{auth}", timeout=10)
            log("Navidrome rescan triggered.")
        except Exception as e:
            log(f"Rescan trigger failed (manual rescan needed): {e}")

if __name__ == "__main__":
    main()
