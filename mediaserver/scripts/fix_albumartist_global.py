#!/usr/bin/env python3
"""
Global ALBUMARTIST normalizer.
Walks /data/media/music/Artist/Album/ structure.
For any album where tracks have inconsistent ALBUMARTIST tags,
sets all tracks to the parent artist folder name.
"""
import os
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.id3 import TPE2
from mutagen.mp4 import MP4

MUSIC_ROOT = '/data/media/music'

def get_albumartist(path):
    if path.endswith('.flac'):
        t = FLAC(path)
        return t.get('albumartist', [None])[0]
    elif path.endswith('.mp3'):
        t = MP3(path)
        if t.tags:
            v = t.tags.get('TPE2')
            return str(v) if v else None
    elif path.endswith(('.m4a', '.aac')):
        t = MP4(path)
        v = t.tags.get('aART') if t.tags else None
        return v[0] if v else None
    return None

def set_albumartist(path, value):
    if path.endswith('.flac'):
        t = FLAC(path)
        t['albumartist'] = [value]
        t.save()
    elif path.endswith('.mp3'):
        t = MP3(path)
        if t.tags is None:
            t.add_tags()
        t.tags['TPE2'] = TPE2(encoding=3, text=value)
        t.save()
    elif path.endswith(('.m4a', '.aac')):
        t = MP4(path)
        if t.tags is None:
            t.add_tags()
        t.tags['aART'] = [value]
        t.save()

AUDIO_EXTS = ('.flac', '.mp3', '.m4a', '.aac')

albums_fixed = 0
tracks_fixed = 0

for artist_name in sorted(os.listdir(MUSIC_ROOT)):
    artist_dir = os.path.join(MUSIC_ROOT, artist_name)
    if not os.path.isdir(artist_dir):
        continue
    for album_name in sorted(os.listdir(artist_dir)):
        album_dir = os.path.join(artist_dir, album_name)
        if not os.path.isdir(album_dir):
            continue
        tracks = [f for f in os.listdir(album_dir) if f.lower().endswith(AUDIO_EXTS)]
        if not tracks:
            continue

        albumartists = set()
        track_paths = []
        for f in tracks:
            p = os.path.join(album_dir, f)
            aa = get_albumartist(p)
            if aa:
                albumartists.add(aa)
            track_paths.append(p)

        # Fix if: multiple different albumartists, or albumartist != artist folder name
        needs_fix = len(albumartists) > 1 or (
            len(albumartists) == 1 and list(albumartists)[0] != artist_name
            and ',' in list(albumartists)[0]  # only fix if it contains featuring credits
        )

        if needs_fix:
            print('Fixing: ' + artist_name + ' / ' + album_name)
            print('  Was: ' + str(albumartists))
            for p in track_paths:
                try:
                    set_albumartist(p, artist_name)
                    tracks_fixed += 1
                except Exception as e:
                    print('  ERROR ' + os.path.basename(p) + ': ' + str(e))
            albums_fixed += 1

print('\nDone. Albums fixed: ' + str(albums_fixed) + ', tracks fixed: ' + str(tracks_fixed))
