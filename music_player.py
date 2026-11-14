import base64
import json
import os
import re
import sys
import time
from flask import Flask, render_template_string, request, jsonify
import requests

app = Flask(__name__)


def resource_path(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def logo_data_uri():
    try:
        with open(resource_path('logo.png'), 'rb') as f:
            return 'data:image/png;base64,' + base64.b64encode(f.read()).decode('ascii')
    except Exception:
        return ''


LYRICS_STORE_PATH = os.path.join(
    os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
    else os.path.dirname(os.path.abspath(__file__)),
    'lyrics_store.json')


def _load_store():
    try:
        with open(LYRICS_STORE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_store(store):
    try:
        with open(LYRICS_STORE_PATH, 'w', encoding='utf-8') as f:
            json.dump(store, f, ensure_ascii=False, indent=1)
    except Exception:
        pass

ITUNES_SEARCH = "https://itunes.apple.com/search"

TRENDING_TERMS = [
    "Taylor Swift",
    "The Weeknd",
    "Ed Sheeran",
    "Dua Lipa",
    "Bruno Mars",
    "Billie Eilish",
    "Drake",
    "Ariana Grande",
    "Coldplay",
    "Post Malone",
]

ID_TRENDING_TERMS = [
    "Tulus",
    "Raisa",
    "Pamungkas",
    "Nadin Amizah",
    "Mahalini",
    "dangdut koplo",
    "lagu indonesia hits",
    "Andmesh",
    "Judika",
    "Agnez Mo",
    "Bernadya",
    "Tiara Andini",
    "Juicy Luicy",
    "Sal Priadi",
]

AUDIUS_ID_TERMS = [
    "dangdut",
    "koplo",
    "lagu indonesia",
    "lagu daerah",
    "indonesian",
    "tembang kenangan",
    "ndarboy genk",
    "indonesia indie",
]

AI_TERMS = [
    "AI cover",
    "ai generated",
    "suno ai",
    "voice clone cover",
]

YOUTUBE_AI_ID_SEARCH = "https://www.youtube.com/results?search_query=ai+cover+lagu+indonesia"

_cache = {}


def _cache_get(key, ttl=600):
    entry = _cache.get(key)
    if not entry:
        return None
    stored_ttl = entry[2] if len(entry) > 2 else None
    if (time.time() - entry[0]) < (stored_ttl if stored_ttl is not None else ttl):
        return entry[1]
    return None


def _cache_set(key, value, ttl=None):
    _cache[key] = (time.time(), value, ttl)


def _cache_delete(key):
    _cache.pop(key, None)


def fetch_itunes(term, limit=25):
    params = {"term": term, "media": "music", "entity": "song", "limit": limit}
    r = requests.get(ITUNES_SEARCH, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("results", [])


def normalize(results):
    tracks = []
    for t in results:
        preview = t.get("previewUrl")
        if not preview:
            continue
        art = t.get("artworkUrl100") or t.get("artworkUrl60") or ""
        art = art.replace("100x100", "400x400").replace("60x60", "400x400")
        tracks.append({
            "id": t.get("trackId"),
            "title": t.get("trackName", "Unknown"),
            "artist": t.get("artistName", "Unknown"),
            "album": t.get("collectionName", ""),
            "artwork": art,
            "preview": preview,
            "duration": t.get("trackTimeMillis", 0),
            "genre": t.get("primaryGenreName", ""),
            "source": "itunes",
        })
    return tracks


AUDIUS_ROOT = "https://api.audius.co"


def audius_host():
    cached = _cache_get("audius_host", ttl=1800)
    if cached:
        return cached
    r = requests.get(AUDIUS_ROOT, timeout=10)
    r.raise_for_status()
    hosts = r.json().get("data", [])
    if not hosts:
        raise RuntimeError("No Audius host available")
    host = hosts[0] if isinstance(hosts[0], str) else hosts[0].get("endpoint")
    _cache_set("audius_host", host)
    return host


def normalize_audius(results, host):
    tracks = []
    for t in results:
        art = t.get("artwork") or {}
        img = art.get("480x480") or art.get("150x150") or art.get("1000x1000") or ""
        tracks.append({
            "id": "audius-" + str(t.get("id")),
            "title": t.get("title", "Unknown"),
            "artist": (t.get("user") or {}).get("name", "Unknown"),
            "album": t.get("album_name") or t.get("genre") or "",
            "artwork": img,
            "preview": host + "/v1/tracks/" + str(t.get("id")) + "/stream",
            "duration": int(t.get("duration") or 0) * 1000,
            "genre": t.get("genre", ""),
            "source": "audius",
        })
    return tracks


def build_itunes_list(terms, per_term=3, limit=24):
    merged = []
    seen = set()
    for term in terms:
        try:
            for t in normalize(fetch_itunes(term, limit=per_term)):
                if t["id"] not in seen:
                    seen.add(t["id"])
                    merged.append(t)
        except Exception:
            continue
        if len(merged) >= limit:
            break
    return merged[:limit]


def build_audius_list(terms, per_term=3, limit=18):
    host = audius_host()
    merged = []
    seen = set()
    for term in terms:
        try:
            r = requests.get(host + "/v1/tracks/search",
                             params={"query": term, "limit": per_term}, timeout=15)
            r.raise_for_status()
            for t in normalize_audius(r.json().get("data", []), host):
                if t["id"] not in seen:
                    seen.add(t["id"])
                    merged.append(t)
        except Exception:
            continue
        if len(merged) >= limit:
            break
    return merged[:limit]


YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'format': 'bestaudio/best',
    'socket_timeout': 10,
    'http_headers': {'User-Agent': 'Mozilla/5.0'},
}


def search_youtube(query, limit=10):
    import yt_dlp
    opts = {**YDL_OPTS, 'default_search': 'ytsearch' + str(limit)}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            results = ydl.extract_info(query, download=False)
            if not results:
                return []
            entries = results.get('entries') or []
            tracks = []
            for e in entries:
                if not e:
                    continue
                vid = e.get('id', '')
                tracks.append({
                    'id': 'yt-' + vid,
                    'title': e.get('title', 'Unknown'),
                    'artist': e.get('uploader') or e.get('channel', 'Unknown'),
                    'album': '',
                    'artwork': e.get('thumbnail') or '',
                    'duration': int(e.get('duration') or 0) * 1000,
                    'genre': '',
                    'source': 'youtube',
                })
            return tracks
    except Exception:
        return []


def get_youtube_audio_url(video_id):
    import yt_dlp
    ydl_opts = {
        **YDL_OPTS,
        'format': 'bestaudio/best',
        'skip_unavailable_fragment': False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info('https://www.youtube.com/watch?v=' + video_id, download=False)
            if not info:
                return None
            return info.get('url')
    except Exception:
        return None


def get_youtube_audio_info(video_id):
    import yt_dlp
    ydl_opts = {
        **YDL_OPTS,
        'format': 'bestaudio/best',
        'skip_unavailable_fragment': False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info('https://www.youtube.com/watch?v=' + video_id, download=False)
            if not info:
                return None
            url = info.get('url')
            ext = info.get('ext', 'webm')
            return {'url': url, 'ext': ext}
    except Exception:
        return None


LRCLIB = "https://lrclib.net"


def _lrclib_get(path, params):
    headers = {"User-Agent": "KiloMusicPlayer/1.0"}
    try:
        r = requests.get(LRCLIB + path, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def clean_title(title):
    t = re.sub(r'[\U0001F000-\U0001FAFF\u2190-\u32BF\uFE0F]+', ' ', title)
    t = re.sub(r'\s*[\(\[【].*?[\)\]】]', '', t)
    t = re.sub(r'\s*[-–|]\s*(official|lyric|audio|video|m\/v|mv|hd|4k).*$',
               '', t, flags=re.I)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


def clean_artist(artist):
    a = re.sub(r'\s*-\s*Topic$', '', artist)
    a = re.sub(r'VEVO$', '', a)
    a = re.sub(r'[\U0001F000-\U0001FAFF\u2190-\u32BF\uFE0F]+', ' ', a)
    return re.sub(r'\s+', ' ', a).strip()


def fetch_lyrics(title, artist, duration_s=None):
    title_c = clean_title(title)
    artist_c = clean_artist(artist)
    parts = re.split(r'\s+[-\u2013\u2014]\s+', title_c)

    pairs = []
    if artist_c:
        pairs.append((artist_c, title_c))
    if len(parts) >= 2:
        pairs.append((parts[0], ' - '.join(parts[1:])))
        pairs.append((' - '.join(parts[:-1]), parts[-1]))
    pairs.append(('', title_c))

    for a, t in pairs:
        if not t:
            continue
        params = {"track_name": t}
        if a:
            params["artist_name"] = a
        if duration_s and a == artist_c and t == title_c:
            params["duration"] = duration_s
        d = _lrclib_get("/api/get", params)
        if d and (d.get("syncedLyrics") or d.get("plainLyrics")):
            return d

    queries = []
    if artist_c:
        queries.append(artist_c + " " + title_c)
    queries.append(title_c)
    if len(parts) >= 2:
        queries.append(parts[-1])
    seen_q = set()
    for q in queries:
        if q.lower() in seen_q:
            continue
        seen_q.add(q.lower())
        res = _lrclib_get("/api/search", {"q": q})
        if isinstance(res, list):
            for item in res:
                if item.get("syncedLyrics") or item.get("plainLyrics"):
                    return item
    return None


def parse_lrc(lrc):
    lines = []
    for raw in lrc.splitlines():
        stamps = re.findall(r'\[(\d+):(\d+(?:[.:]\d+)?)\]', raw)
        if not stamps:
            continue
        text = re.sub(r'\[(\d+):(\d+(?:[.:]\d+)?)\]', '', raw)
        text = re.sub(r'<\d+:\d+(?:[.:]\d+)?>', '', text).strip()
        for mm, ss in stamps:
            parts = re.split(r'[.:]', ss)
            sec = int(parts[0])
            if len(parts) > 1:
                sec += int(parts[1].ljust(3, '0')[:3]) / 1000.0
            lines.append({'time': int(mm) * 60 + sec, 'text': text})
    lines.sort(key=lambda x: x['time'])
    return lines


def distribute_plain_lrc(text, duration_s):
    lines = [l for l in (raw.rstrip() for raw in text.split('\n')) if l.strip()]
    if not lines:
        return ''
    if duration_s <= 0:
        return '\n'.join(lines)
    if duration_s > 30:
        start = min(max(2.0, duration_s * 0.07), 25.0)
        end = duration_s - min(12.0, duration_s * 0.04)
    else:
        start = max(0.5, duration_s * 0.05)
        end = duration_s * 0.95
    if end <= start:
        start, end = 0.0, duration_s
    span = end - start
    weights = [max(len(l.strip()), 1) for l in lines]
    total = sum(weights)
    out = []
    acc = 0.0
    for l, w in zip(lines, weights):
        t = start + (acc / total) * span
        mm = int(t // 60)
        ss = min(t - mm * 60, 59.99)
        out.append('[%02d:%05.2f]%s' % (mm, ss, l))
        acc += w
    return '\n'.join(out)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#121212">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black">
    <meta name="apple-mobile-web-app-title" content="Music">
    <link rel="manifest" href="/manifest.json">
    <link rel="apple-touch-icon" href="/icons/pwa_icon_192.png">
    <link rel="icon" href="__LOGO_URI__">
    <title>Music</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            --bg: #121212;
            --sidebar: #000000;
            --card: #181818;
            --card-hover: #282828;
            --text: #ffffff;
            --muted: #b3b3b3;
            --accent: #1db954;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: var(--bg);
            color: var(--text);
            height: 100vh;
            overflow: hidden;
        }

        .app {
            display: grid;
            grid-template-columns: 240px 1fr;
            height: calc(100vh - 90px);
        }

        /* Sidebar */
        .sidebar {
            background: var(--sidebar);
            padding: 24px 16px;
            display: flex;
            flex-direction: column;
            gap: 28px;
        }

        .brand {
            font-size: 22px;
            font-weight: 800;
            color: var(--text);
            padding-left: 8px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .brand-logo {
            width: 30px;
            height: 30px;
            border-radius: 7px;
            object-fit: cover;
            flex-shrink: 0;
        }

        .nav { display: flex; flex-direction: column; gap: 4px; }

        .nav-item {
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 12px 12px;
            border-radius: 8px;
            color: var(--muted);
            font-weight: 600;
            cursor: pointer;
            transition: color 0.2s, background 0.2s;
            user-select: none;
        }

        .nav-item:hover { color: var(--text); }
        .nav-item.active { color: var(--text); background: #1a1a1a; }

        /* Main */
        .main { overflow-y: auto; }

        .topbar {
            position: sticky;
            top: 0;
            z-index: 10;
            background: linear-gradient(#1a1a1aee, #121212ee);
            backdrop-filter: blur(8px);
            padding: 18px 28px;
            display: flex;
            align-items: center;
            gap: 18px;
        }

        .searchbox {
            display: flex;
            align-items: center;
            background: #242424;
            border-radius: 999px;
            padding: 4px 6px 4px 18px;
            width: 100%;
            max-width: 480px;
        }

        .searchbox input {
            flex: 1;
            background: transparent;
            border: none;
            outline: none;
            color: var(--text);
            font-size: 15px;
            padding: 10px 0;
        }

        .searchbox input::placeholder { color: #8a8a8a; }

        .searchbox button {
            background: var(--accent);
            color: #000;
            border: none;
            border-radius: 999px;
            padding: 9px 20px;
            font-weight: 700;
            cursor: pointer;
        }

        .searchbox button:hover { transform: scale(1.04); }

        .source-toggle {
            display: flex;
            background: #242424;
            border-radius: 999px;
            padding: 4px;
            gap: 2px;
            flex-shrink: 0;
        }

        .source-toggle button {
            background: transparent;
            border: none;
            color: var(--muted);
            padding: 8px 16px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 13px;
            cursor: pointer;
        }

        .source-toggle button.active { background: var(--accent); color: #000; }

        .content { padding: 12px 28px 40px; }

        .section-title {
            font-size: 24px;
            font-weight: 800;
            margin: 22px 0 16px;
        }

        .chips { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }

        .chip {
            background: #2a2a2a;
            color: var(--text);
            padding: 8px 16px;
            border-radius: 999px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }

        .chip:hover { background: #3a3a3a; }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
            gap: 18px;
        }

        .card {
            background: var(--card);
            border-radius: 10px;
            padding: 14px;
            cursor: pointer;
            transition: background 0.2s;
            position: relative;
        }

        .card:hover { background: var(--card-hover); }

        .card .art {
            position: relative;
            width: 100%;
            aspect-ratio: 1 / 1;
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 12px;
            background: #333;
        }

        .card .art img { width: 100%; height: 100%; object-fit: cover; }

        .card .play-btn {
            position: absolute;
            right: 10px;
            bottom: 10px;
            width: 48px;
            height: 48px;
            border-radius: 50%;
            border: none;
            background: var(--accent);
            color: #000;
            font-size: 20px;
            cursor: pointer;
            opacity: 0;
            transform: translateY(8px);
            transition: opacity 0.2s, transform 0.2s;
            box-shadow: 0 8px 20px rgba(0,0,0,0.4);
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .card:hover .play-btn { opacity: 1; transform: translateY(0); }

        .card .t {
            font-weight: 700;
            font-size: 15px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .card .a {
            color: var(--muted);
            font-size: 13px;
            margin-top: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .card.playing { background: #202a20; outline: 1px solid var(--accent); }

        .fav-toggle {
            position: absolute;
            top: 10px;
            right: 10px;
            border: none;
            background: rgba(0,0,0,0.6);
            color: #fff;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 15px;
            opacity: 0;
            transition: opacity 0.2s;
        }

        .card:hover .fav-toggle { opacity: 1; }
        .fav-toggle.on { color: #ff4d6d; opacity: 1; }

        .src-badge {
            position: absolute;
            left: 8px;
            top: 8px;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.3px;
            color: #000;
            background: var(--accent);
        }

        .src-badge.src-itunes { background: #f5c518; }
        .src-badge.src-audius { background: var(--accent); }
        .src-badge.src-local { background: #7db9ff; }
        .src-badge.src-youtube { background: #ff0000; }

        .pl-toggle {
            position: absolute;
            top: 10px;
            right: 48px;
            border: none;
            background: rgba(0,0,0,0.6);
            color: #fff;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 15px;
            opacity: 0;
            transition: opacity 0.2s;
        }

        .card:hover .pl-toggle { opacity: 1; }
        .pl-toggle:hover { background: var(--accent); color: #000; }
        .dl-toggle { right: 86px; }

        .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.7);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 100;
        }

        .modal-overlay.open { display: flex; }

        .modal {
            background: var(--card);
            border-radius: 12px;
            padding: 24px;
            width: 340px;
            max-width: 90vw;
        }

        .modal h3 { margin-bottom: 14px; }

        .modal .pl-choices { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; max-height: 260px; overflow-y: auto; }

        .modal .pl-choice {
            background: #2a2a2a;
            border-radius: 8px;
            padding: 10px 14px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
        }

        .modal .pl-choice:hover { background: #3a3a3a; }
        .modal .pl-choice .cnt { float: right; color: var(--muted); font-weight: 400; font-size: 12px; }

        .modal .pl-new { display: flex; gap: 8px; margin-bottom: 14px; }

        .modal .pl-new input {
            flex: 1;
            background: #242424;
            border: none;
            outline: none;
            color: var(--text);
            border-radius: 8px;
            padding: 10px 12px;
            font-size: 14px;
        }

        .modal-foot { display: flex; justify-content: flex-end; }

        .pl-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }

        .pl-del {
            background: transparent;
            border: none;
            color: var(--muted);
            font-size: 13px;
            cursor: pointer;
        }

        .pl-del:hover { color: #ff4d6d; }

        /* Now Playing overlay */
        .np-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.82);
            backdrop-filter: blur(24px);
            display: none;
            z-index: 60;
            padding: 30px;
        }

        .np-overlay.open { display: flex; }

        .np-inner {
            margin: auto;
            display: flex;
            gap: 46px;
            max-width: 980px;
            width: 100%;
            align-items: center;
            max-height: 100%;
        }

        .np-left {
            display: flex;
            flex-direction: column;
            gap: 18px;
            flex-shrink: 0;
        }

        .np-left img {
            width: 300px;
            height: 300px;
            border-radius: 14px;
            object-fit: cover;
            background: #222;
            box-shadow: 0 24px 60px rgba(0,0,0,0.6);
        }

        .np-left > div {
            width: 300px;
            max-width: 100%;
        }

        .np-t {
            font-size: 24px;
            font-weight: 800;
            line-height: 1.25;
            word-break: break-word;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .np-a {
            font-size: 15px;
            color: var(--muted);
            margin-top: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .np-progress-row {
            display: flex;
            align-items: center;
            gap: 10px;
            width: 300px;
        }

        .np-controls {
            display: flex;
            align-items: center;
            gap: 26px;
            justify-content: center;
        }

        .np-controls .ctrl { font-size: 22px; }

        .np-controls .ctrl.play {
            width: 52px;
            height: 52px;
            font-size: 20px;
        }

        .np-volume-row {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .np-volume-row span { font-size: 16px; }

        .np-volume-row input[type=range] {
            width: 170px;
            accent-color: var(--accent);
            cursor: pointer;
        }

        .np-right {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
            max-height: 76vh;
        }

        .np-lyrics {
            flex: 1;
            overflow-y: auto;
            padding: 10px 6px;
            mask-image: linear-gradient(transparent, #000 8%, #000 92%, transparent);
            -webkit-mask-image: linear-gradient(transparent, #000 8%, #000 92%, transparent);
        }

        #np-viz {
            width: 100%;
            height: 70px;
            display: block;
            margin-top: 10px;
            flex-shrink: 0;
        }

        .np-eq {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
            flex-shrink: 0;
        }

        .np-eq button {
            background: rgba(255,255,255,0.08);
            color: var(--text);
            border: none;
            padding: 7px 14px;
            border-radius: 999px;
            font-weight: 600;
            font-size: 12px;
            cursor: pointer;
            transition: background 0.15s;
        }

        .np-eq button:hover { background: rgba(255,255,255,0.18); }
        .np-eq button.active { background: var(--accent); color: #000; }

        .lyr-editor {
            display: flex;
            flex-direction: column;
            gap: 12px;
            padding: 10px 6px;
            height: 100%;
        }

        .lyr-editor textarea {
            flex: 1;
            min-height: 220px;
            background: #242424;
            border: 1px solid #333;
            border-radius: 8px;
            color: var(--text);
            padding: 12px;
            font-size: 14px;
            line-height: 1.5;
            resize: vertical;
            outline: none;
            font-family: inherit;
        }

        .lyr-editor textarea:focus { border-color: var(--accent); }

        .lyr-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

        .btn-ghost {
            background: #2a2a2a;
            color: var(--text);
            border: none;
            padding: 10px 16px;
            border-radius: 999px;
            font-weight: 600;
            cursor: pointer;
        }

        .btn-ghost:hover { background: #3a3a3a; }

        .tap-line {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            font-size: 24px;
            font-weight: 800;
            line-height: 1.4;
            color: #fff;
            word-break: break-word;
            overflow-y: auto;
            padding: 10px 0;
        }

        .tap-progress {
            text-align: center;
            color: var(--muted);
            font-size: 13px;
            font-weight: 700;
        }

        .lyrics-line {
            color: #7a7a7a;
            font-size: 18px;
            font-weight: 700;
            line-height: 1.45;
            margin: 16px 0;
            cursor: pointer;
            transition: color 0.25s, font-size 0.25s;
        }

        .lyrics-line:hover { color: #b3b3b3; }
        .lyrics-line.active { color: #fff; font-size: 23px; }

        .np-close {
            position: absolute;
            top: 20px;
            right: 24px;
            background: rgba(255,255,255,0.08);
            border: none;
            color: #fff;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            font-size: 16px;
            cursor: pointer;
        }

        .np-close:hover { background: rgba(255,255,255,0.2); }

        .pb-left img { cursor: pointer; }

        @media (max-width: 800px) {
            .np-inner { flex-direction: column; gap: 20px; overflow-y: auto; }
            .np-left { align-items: center; text-align: center; }
            .np-left img { width: 180px; height: 180px; }
            .np-lyrics { max-height: none; width: 100%; }
            .np-progress-row { width: 100%; }
            .np-left > div { width: 100%; }
        }

        .empty {
            color: var(--muted);
            text-align: center;
            padding: 60px 0;
            font-size: 15px;
        }

        .ai-note {
            margin-top: 26px;
            padding: 14px 18px;
            background: var(--card);
            border-left: 3px solid var(--accent);
            border-radius: 8px;
            color: var(--muted);
            font-size: 13px;
            line-height: 1.5;
        }

        .ai-note a { color: var(--accent); font-weight: 700; text-decoration: none; }
        .ai-note a:hover { text-decoration: underline; }

        /* Settings */
        .panel {
            background: var(--card);
            border-radius: 12px;
            padding: 22px 24px;
            margin-bottom: 22px;
            max-width: 760px;
        }

        .panel h3 {
            font-size: 18px;
            margin-bottom: 6px;
        }

        .panel .hint { color: var(--muted); font-size: 13px; margin-bottom: 16px; }

        .eq-presets { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }

        .eq-presets button {
            background: #2a2a2a;
            color: var(--text);
            border: none;
            padding: 8px 16px;
            border-radius: 999px;
            font-weight: 600;
            font-size: 13px;
            cursor: pointer;
        }

        .eq-presets button:hover { background: #3a3a3a; }
        .eq-presets button.active { background: var(--accent); color: #000; }

        .eq-bands {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-bottom: 18px;
        }

        .eq-band {
            display: grid;
            grid-template-columns: 64px 1fr 48px;
            align-items: center;
            gap: 14px;
        }

        .eq-band input[type=range] {
            width: 100%;
            height: 22px;
            accent-color: var(--accent);
            cursor: pointer;
        }

        .eq-band .val { font-size: 12px; color: var(--muted); }
        .eq-band .lbl { font-size: 11px; color: var(--muted); }

        .row-between {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
            gap: 12px;
        }

        .switch { display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 600; }
        .switch input { width: 18px; height: 18px; accent-color: var(--accent); cursor: pointer; }

        .btn-accent {
            background: var(--accent);
            color: #000;
            border: none;
            padding: 10px 20px;
            border-radius: 999px;
            font-weight: 700;
            cursor: pointer;
        }

        .btn-accent:hover { transform: scale(1.04); }

        .local-list { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; }

        .local-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            background: #222;
            border-radius: 8px;
            padding: 10px 14px;
            cursor: pointer;
        }

        .local-item:hover { background: #2f2f2f; }
        .local-item .nm { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .local-item.playing { outline: 1px solid var(--accent); }

        input[type=file] { color: var(--muted); font-size: 13px; }

        .spinner {
            width: 34px; height: 34px;
            border: 3px solid #333;
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.9s linear infinite;
            margin: 60px auto;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        /* Player bar */
        .playerbar {
            position: fixed;
            bottom: 0; left: 0; right: 0;
            height: 90px;
            background: #181818;
            border-top: 1px solid #282828;
            display: grid;
            grid-template-columns: 1fr 2fr 1fr;
            align-items: center;
            padding: 0 18px;
            gap: 16px;
        }

        .pb-left { display: flex; align-items: center; gap: 14px; min-width: 0; }

        .pb-left img {
            width: 56px; height: 56px;
            border-radius: 6px;
            object-fit: cover;
            background: #333;
        }

        .pb-info { min-width: 0; }
        .pb-info .pt { font-size: 14px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .pb-info .pa { font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

        .pb-center { display: flex; flex-direction: column; align-items: center; gap: 8px; }

        .controls { display: flex; align-items: center; gap: 20px; }

        .ctrl {
            background: transparent;
            border: none;
            color: var(--text);
            cursor: pointer;
            font-size: 18px;
            opacity: 0.85;
        }

        .ctrl:hover { opacity: 1; }

        .ctrl.play {
            background: #fff;
            color: #000;
            width: 38px;
            height: 38px;
            border-radius: 50%;
            font-size: 15px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .progress-row { display: flex; align-items: center; gap: 10px; width: 100%; max-width: 520px; }

        .time { font-size: 11px; color: var(--muted); min-width: 34px; text-align: center; }

        .bar {
            flex: 1;
            height: 5px;
            background: #4d4d4d;
            border-radius: 3px;
            cursor: pointer;
            position: relative;
        }

        .bar .fill {
            height: 100%;
            width: 0%;
            background: var(--accent);
            border-radius: 3px;
        }

        .pb-right { display: flex; align-items: center; justify-content: flex-end; gap: 12px; }

        .pb-right input[type=range] { width: 110px; accent-color: var(--accent); cursor: pointer; }

        @media (max-width: 800px) {
            .app { grid-template-columns: 1fr; }
            .sidebar { flex-direction: row; align-items: center; padding: 12px; overflow-x: auto; gap: 10px; }
            .nav { flex-direction: row; }
            .brand { display: none; }
            .playerbar { grid-template-columns: 1fr auto; }
            .pb-right { display: none; }
        }
    </style>
</head>
<body>
    <div class="app">
        <aside class="sidebar">
            <div class="brand"><img class="brand-logo" src="__LOGO_URI__" alt=""> Music</div>
            <nav class="nav">
                <div class="nav-item active" data-view="home">🏠 Home</div>
                <div class="nav-item" data-view="search">🔍 Search</div>
                <div class="nav-item" data-view="trending">🔥 Trending</div>
                <div class="nav-item" data-view="favorites">❤️ Favorites</div>
                <div class="nav-item" data-view="playlists">📃 Playlists</div>
                <div class="nav-item" data-view="settings">⚙️ Settings</div>
            </nav>
        </aside>

        <main class="main">
            <header class="topbar">
                <div class="searchbox">
                    <input id="search-input" type="text" placeholder="Cari lagu, artis, atau album..." autocomplete="off">
                    <button id="search-btn">Cari</button>
                </div>
                <div class="source-toggle" id="source-toggle">
                    <button data-src="youtube" class="active" title="YouTube">YouTube</button>
                    <button data-src="itunes" title="Katalog mainstream, preview 30 detik">Preview 30s</button>
                    <button data-src="audius" title="Lagu penuh (katalog Audius)">Full</button>
                </div>
            </header>
            <div class="content" id="content"></div>
        </main>
    </div>

    <div class="playerbar">
        <div class="pb-left">
            <img id="pb-art" src="" alt="">
            <div class="pb-info">
                <div class="pt" id="pb-title">Belum ada lagu</div>
                <div class="pa" id="pb-artist">Pilih lagu untuk diputar</div>
            </div>
        </div>
        <div class="pb-center">
            <div class="controls">
                <button class="ctrl" id="btn-prev">⏮</button>
                <button class="ctrl play" id="btn-play">▶</button>
                <button class="ctrl" id="btn-next">⏭</button>
            </div>
            <div class="progress-row">
                <span class="time" id="cur-time">0:00</span>
                <div class="bar" id="progress"><div class="fill" id="progress-fill"></div></div>
                <span class="time" id="dur-time">0:00</span>
            </div>
        </div>
        <div class="pb-right">
            <span>🔊</span>
            <input type="range" id="volume" min="0" max="1" step="0.01" value="1">
        </div>
    </div>

    <div class="modal-overlay" id="pl-modal">
        <div class="modal">
            <h3>➕ Tambah ke Playlist</h3>
            <div class="pl-choices" id="pl-choices"></div>
            <div class="pl-new">
                <input id="pl-new-name" type="text" placeholder="Nama playlist baru..." autocomplete="off">
                <button class="btn-accent" id="pl-create">Buat</button>
            </div>
            <div class="modal-foot"><button class="pl-del" id="pl-close">Tutup</button></div>
        </div>
    </div>

    <div class="np-overlay" id="np-overlay">
        <button class="np-close" id="np-close" title="Tutup">✕</button>
        <div class="np-inner">
            <div class="np-left">
                <img id="np-art" src="" alt="">
                <div>
                    <div class="np-t" id="np-title"></div>
                    <div class="np-a" id="np-artist"></div>
                </div>
                <div class="np-progress-row">
                    <span class="time" id="np-cur">0:00</span>
                    <div class="bar" id="np-progress"><div class="fill" id="np-progress-fill"></div></div>
                    <span class="time" id="np-dur">0:00</span>
                </div>
                <div class="np-controls">
                    <button class="ctrl" id="np-prev" title="Sebelumnya">⏮</button>
                    <button class="ctrl play" id="np-play" title="Putar/Jeda">▶</button>
                    <button class="ctrl" id="np-next" title="Berikutnya">⏭</button>
                </div>
                <div class="np-volume-row">
                    <span>🔊</span>
                    <input type="range" id="np-volume" min="0" max="1" step="0.01" value="1">
                </div>
            </div>
            <div class="np-right">
                <div class="np-lyrics" id="np-lyrics"></div>
                <canvas id="np-viz" height="70"></canvas>
                <div class="np-eq" id="np-eq"></div>
            </div>
        </div>
    </div>

    <audio id="audio"></audio>

    <script>
        const audio = document.getElementById('audio');
        audio.crossOrigin = 'anonymous';
        const content = document.getElementById('content');
        const searchInput = document.getElementById('search-input');

        const state = { queue: [], index: -1, view: 'home', lastQuery: '', source: 'youtube', locals: [] };
        const FAV_KEY = 'music_favorites';
        const PL_KEY = 'music_playlists';
        let plModalTrack = null;

        function getPlaylists() {
            try { return JSON.parse(localStorage.getItem(PL_KEY)) || {}; }
            catch (e) { return {}; }
        }
        function setPlaylists(p) { localStorage.setItem(PL_KEY, JSON.stringify(p)); }

        function addToPlaylist(name, track) {
            const p = getPlaylists();
            if (!p[name]) p[name] = [];
            if (!p[name].some(t => t.id === track.id)) p[name].push(track);
            setPlaylists(p);
        }

        function openPlaylistModal(track) {
            plModalTrack = track;
            const wrap = document.getElementById('pl-choices');
            wrap.innerHTML = '';
            const pls = getPlaylists();
            const names = Object.keys(pls);
            if (!names.length) {
                wrap.innerHTML = '<div class="hint" style="color:var(--muted);font-size:13px">Belum ada playlist. Buat di bawah.</div>';
            }
            names.forEach(name => {
                const el = document.createElement('div');
                el.className = 'pl-choice';
                el.innerHTML = '📃 ' + name + ' <span class="cnt">' + pls[name].length + ' lagu</span>';
                el.addEventListener('click', () => {
                    addToPlaylist(name, plModalTrack);
                    closePlaylistModal();
                });
                wrap.appendChild(el);
            });
            document.getElementById('pl-new-name').value = '';
            document.getElementById('pl-modal').classList.add('open');
            document.getElementById('pl-new-name').focus();
        }

        function closePlaylistModal() {
            document.getElementById('pl-modal').classList.remove('open');
            plModalTrack = null;
        }

        function renderPlaylists() {
            content.innerHTML = '';
            const pls = getPlaylists();
            const names = Object.keys(pls);
            if (!names.length) {
                showEmpty('Belum ada playlist. Klik tombol ➕ pada lagu untuk menambahkan.');
                return;
            }
            names.forEach(name => {
                const head = document.createElement('div');
                head.className = 'section-title pl-head';
                const title = document.createElement('span');
                title.textContent = '📃 ' + name + ' (' + pls[name].length + ')';
                const del = document.createElement('button');
                del.className = 'pl-del';
                del.textContent = '🗑 Hapus playlist';
                del.addEventListener('click', () => {
                    const p = getPlaylists();
                    delete p[name];
                    setPlaylists(p);
                    renderPlaylists();
                });
                head.appendChild(title);
                head.appendChild(del);
                content.appendChild(head);
                if (pls[name].length) renderGrid(pls[name], '');
                else {
                    const e = document.createElement('div');
                    e.className = 'empty';
                    e.textContent = 'Playlist kosong.';
                    content.appendChild(e);
                }
            });
        }

        function getFavorites() {
            try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; }
            catch (e) { return []; }
        }
        function setFavorites(list) { localStorage.setItem(FAV_KEY, JSON.stringify(list)); }
        function isFavorite(id) { return getFavorites().some(t => t.id === id); }

        function toggleFavorite(track, btn) {
            let favs = getFavorites();
            if (favs.some(t => t.id === track.id)) {
                favs = favs.filter(t => t.id !== track.id);
                if (btn) btn.classList.remove('on');
            } else {
                favs.push(track);
                if (btn) btn.classList.add('on');
            }
            setFavorites(favs);
            if (state.view === 'favorites') renderFavorites();
        }

        function fmt(sec) {
            if (!isFinite(sec) || sec < 0) return '0:00';
            const m = Math.floor(sec / 60);
            const s = Math.floor(sec % 60).toString().padStart(2, '0');
            return m + ':' + s;
        }

        function showLoading() { content.innerHTML = '<div class="spinner"></div>'; }
        function showEmpty(msg) { content.innerHTML = '<div class="empty">' + msg + '</div>'; }

        function renderGrid(tracks, title) {
            const wrap = document.createElement('div');
            if (title) {
                const h = document.createElement('div');
                h.className = 'section-title';
                h.textContent = title;
                wrap.appendChild(h);
            }
            const grid = document.createElement('div');
            grid.className = 'grid';

            tracks.forEach(track => {
                const card = document.createElement('div');
                card.className = 'card';
                card.dataset.id = track.id;
                const badge = track.source === 'itunes' ? '30s' : (track.source === 'local' ? 'FILE' : (track.source === 'youtube' ? 'YT' : 'FULL'));
                card.innerHTML = `
                    <div class="art">
                        <img src="${track.artwork || ''}" alt="" loading="lazy">
                        <span class="src-badge src-${track.source}">${badge}</span>
                        <button class="play-btn" title="Putar">▶</button>
                        <button class="pl-toggle" title="Tambah ke playlist">➕</button>
                        <button class="pl-toggle dl-toggle" title="Download">⬇</button>
                        <button class="fav-toggle ${isFavorite(track.id) ? 'on' : ''}" title="Favorit">❤</button>
                    </div>
                    <div class="t">${track.title}</div>
                    <div class="a">${track.artist}</div>
                `;
                card.addEventListener('click', () => playIndex(tracks, tracks.indexOf(track)));
                card.querySelector('.play-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    playIndex(tracks, tracks.indexOf(track));
                });
                card.querySelector('.fav-toggle').addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggleFavorite(track, e.currentTarget);
                });
                card.querySelector('.pl-toggle').addEventListener('click', (e) => {
                    e.stopPropagation();
                    openPlaylistModal(track);
                });
                card.querySelector('.dl-toggle').addEventListener('click', (e) => {
                    e.stopPropagation();
                    downloadTrack(track);
                });
                grid.appendChild(card);
            });

            wrap.appendChild(grid);
            content.appendChild(wrap);
        }

        function renderFavorites() {
            const favs = getFavorites();
            content.innerHTML = '';
            if (!favs.length) { showEmpty('Belum ada lagu favorit. Klik ikon ❤ pada lagu.'); return; }
            renderGrid(favs, '❤️ Favorites');
            markPlaying();
        }

        function markPlaying() {
            document.querySelectorAll('.card').forEach(c => c.classList.remove('playing'));
            if (state.index >= 0 && state.queue[state.index]) {
                const id = state.queue[state.index].id;
                const el = document.querySelector('.card[data-id="' + id + '"]');
                if (el) el.classList.add('playing');
            }
        }

        function playIndex(tracks, index, openNp = true) {
            if (index < 0 || index >= tracks.length) return;
            state.queue = tracks;
            state.index = index;
            const t = tracks[index];
            if (t.source === 'youtube') {
                const vid = t.id.replace('yt-', '');
                audio.src = '/api/yt-stream?v=' + encodeURIComponent(vid);
                audio.play().catch(() => {});
            } else {
                audio.src = t.preview;
                audio.play().catch(() => {});
            }
            document.getElementById('pb-art').src = t.artwork || '';
            document.getElementById('pb-title').textContent = t.title;
            document.getElementById('pb-artist').textContent = t.artist;
            markPlaying();
            if (openNp || document.getElementById('np-overlay').classList.contains('open')) {
                showNowPlaying(t);
            }
        }

        function showNowPlaying(t) {
            document.getElementById('np-art').src = t.artwork || '';
            document.getElementById('np-title').textContent = t.title;
            document.getElementById('np-artist').textContent = t.artist;
            const box = document.getElementById('np-lyrics');
            box.innerHTML = '<div class="spinner"></div>';
            document.getElementById('np-progress-fill').style.width = '0%';
            document.getElementById('np-cur').textContent = '0:00';
            document.getElementById('np-dur').textContent = '0:00';
            document.getElementById('np-volume').value = audio.volume;
            syncNpUI();
            document.getElementById('np-overlay').classList.add('open');
            startViz();
            renderNpEqPresets();
            fetch('/api/lyrics?title=' + encodeURIComponent(t.title) +
                  '&artist=' + encodeURIComponent(t.artist) +
                  '&duration=' + (t.duration || 0))
                .then(r => r.json())
                .then(data => {
                    const b = document.getElementById('np-lyrics');
                    if (!b) return;
                    b.innerHTML = '';
                    if (data.lines && data.lines.length) {
                        data.lines.forEach(l => {
                            const el = document.createElement('p');
                            el.className = 'lyrics-line';
                            el.textContent = l.text || '♪';
                            el.dataset.time = l.time;
                            el.addEventListener('click', () => {
                                audio.currentTime = l.time;
                                if (audio.paused) audio.play();
                            });
                            b.appendChild(el);
                        });
                    } else if (data.plain) {
                        data.plain.split('\\n').forEach(line => {
                            const el = document.createElement('p');
                            el.className = 'lyrics-line';
                            el.textContent = line || ' ';
                            b.appendChild(el);
                        });
                    } else {
                        const empty = document.createElement('div');
                        empty.className = 'empty';
                        empty.textContent = 'Lirik tidak ditemukan untuk lagu ini.';
                        const btn = document.createElement('button');
                        btn.className = 'btn-accent';
                        btn.textContent = '➕ Tambah Lirik Manual';
                        btn.addEventListener('click', () => openLyricsEditor(t));
                        b.appendChild(empty);
                        b.appendChild(btn);
                    }
                    highlightLyrics(true);
                })
                .catch(() => {
                    const b = document.getElementById('np-lyrics');
                    if (b) b.innerHTML = '<div class="empty">Gagal memuat lirik.</div>';
                });
        }

        function closeNowPlaying() {
            document.getElementById('np-overlay').classList.remove('open');
        }

        function openLyricsEditor(t, initialText) {
            const box = document.getElementById('np-lyrics');
            box.innerHTML = `
                <div class="lyr-editor">
                    <div class="hint" style="color:var(--muted);font-size:13px;line-height:1.5">
                        Tempel lirik dengan format <b>LRC</b> [mm:ss.xx] agar presisi sinkron. Lirik polos hasil copy
                        akan <b>disinkronkan otomatis</b> secara perkiraan mengikuti durasi lagu.
                        Untuk hasil presisi, gunakan <b>🎯 Sinkron Manual</b>: putar lagu lalu tap per baris.
                    </div>
                    <textarea id="lyr-text" placeholder="Contoh LRC:\n[00:12.00] Baris pertama lagu\n[00:18.50] Baris kedua lagu\n\nAtau tempel lirik polos tanpa timestamp."></textarea>
                    <div class="lyr-actions">
                        <input type="file" id="lyr-file" accept=".lrc,.txt,text/plain" style="display:none">
                        <button class="btn-ghost" id="lyr-import">📂 Impor .lrc / .txt</button>
                        <button class="btn-ghost" id="lyr-tapsync">🎯 Sinkron Manual (Tap)</button>
                        <button class="btn-accent" id="lyr-save">💾 Simpan Lirik</button>
                        <button class="pl-del" id="lyr-cancel">Batal</button>
                    </div>
                </div>
            `;
            const ta = document.getElementById('lyr-text');
            ta.value = initialText || '';
            document.getElementById('lyr-import').addEventListener('click', () => document.getElementById('lyr-file').click());
            document.getElementById('lyr-file').addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = () => { ta.value = reader.result; };
                reader.readAsText(file);
            });
            document.getElementById('lyr-save').addEventListener('click', () => {
                const text = ta.value.trim();
                if (!text) return;
                saveLyricsText(t, text);
            });
            document.getElementById('lyr-tapsync').addEventListener('click', () => startTapSync(t, ta.value));
            document.getElementById('lyr-cancel').addEventListener('click', () => showNowPlaying(t));
            ta.focus();
        }

        function saveLyricsText(t, text) {
            const durMs = t.duration || (isFinite(audio.duration) ? audio.duration * 1000 : 0) || 0;
            fetch('/api/lyrics-custom', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: t.title, artist: t.artist, text: text, duration: durMs }),
            }).then(r => r.json()).then(d => {
                if (d.ok) showNowPlaying(t);
            });
        }

        function fmtLrcStamp(sec) {
            if (!isFinite(sec) || sec < 0) sec = 0;
            const mm = Math.floor(sec / 60);
            const ss = sec - mm * 60;
            return '[' + String(mm).padStart(2, '0') + ':' + ss.toFixed(2).padStart(5, '0') + ']';
        }

        let tapSyncActive = false;

        function startTapSync(t, text) {
            const lines = (text || '').split('\\n').map(l => l.trim()).filter(l => l);
            if (!lines.length) return;
            const box = document.getElementById('np-lyrics');
            tapSyncActive = true;
            const stamps = [];
            let idx = 0;
            audio.currentTime = 0;
            audio.play().catch(() => {});

            function finish() {
                tapSyncActive = false;
                const lrc = lines.map((l, i) => fmtLrcStamp(stamps[i] || 0) + l).join('\\n');
                saveLyricsText(t, lrc);
            }

            function render() {
                const editing = idx < lines.length;
                box.innerHTML = '';
                const wrap = document.createElement('div');
                wrap.className = 'lyr-editor';
                const hint = document.createElement('div');
                hint.className = 'hint';
                hint.style.cssText = 'color:var(--muted);font-size:13px;line-height:1.5';
                hint.textContent = editing
                    ? 'Putar lagu dan tekan TAP / Space tepat saat baris ini dinyanyikan. Backspace = undo, Esc = batal.'
                    : 'Selesai! Lirik tersinkron — menyimpan...';
                wrap.appendChild(hint);

                const line = document.createElement('div');
                line.className = 'tap-line';
                line.textContent = editing ? lines[idx] : '✓ Selesai';
                wrap.appendChild(line);

                const prog = document.createElement('div');
                prog.className = 'tap-progress';
                prog.textContent = Math.min(idx, lines.length) + ' / ' + lines.length;
                wrap.appendChild(prog);

                const actions = document.createElement('div');
                actions.className = 'lyr-actions';
                if (editing) {
                    const tapBtn = document.createElement('button');
                    tapBtn.className = 'btn-accent';
                    tapBtn.id = 'tap-btn';
                    tapBtn.textContent = 'TAP (Space)';
                    tapBtn.addEventListener('click', tap);
                    actions.appendChild(tapBtn);
                    const undoBtn = document.createElement('button');
                    undoBtn.className = 'btn-ghost';
                    undoBtn.id = 'tap-undo';
                    undoBtn.textContent = '↩ Undo';
                    undoBtn.addEventListener('click', undo);
                    actions.appendChild(undoBtn);
                }
                const cancelBtn = document.createElement('button');
                cancelBtn.className = 'pl-del';
                cancelBtn.id = 'tap-cancel';
                cancelBtn.textContent = 'Batal';
                cancelBtn.addEventListener('click', cancel);
                actions.appendChild(cancelBtn);
                wrap.appendChild(actions);
                box.appendChild(wrap);
            }

            function tap() {
                if (idx >= lines.length) return;
                stamps[idx] = audio.currentTime || 0;
                idx++;
                if (idx >= lines.length) finish();
                else render();
            }

            function undo() {
                if (idx > 0) { idx--; stamps.length = idx; render(); }
            }

            function cancel() {
                tapSyncActive = false;
                openLyricsEditor(t, lines.join('\\n'));
            }

            render();
        }

        function syncNpUI() {
            const overlay = document.getElementById('np-overlay');
            if (!overlay.classList.contains('open')) return;
            const cur = audio.currentTime || 0;
            const dur = audio.duration || 0;
            document.getElementById('np-cur').textContent = fmt(cur);
            document.getElementById('np-dur').textContent = fmt(dur);
            document.getElementById('np-progress-fill').style.width = dur ? (cur / dur * 100) + '%' : '0%';
            document.getElementById('np-play').textContent = audio.paused ? '▶' : '⏸';
        }

        function highlightLyrics(force) {
            const overlay = document.getElementById('np-overlay');
            if (!overlay.classList.contains('open')) return;
            const box = document.getElementById('np-lyrics');
            if (!box) return;
            const lines = box.querySelectorAll('.lyrics-line[data-time]');
            if (!lines.length) return;
            const cur = audio.currentTime || 0;
            let active = null;
            lines.forEach(el => {
                if (parseFloat(el.dataset.time) <= cur + 0.3) active = el;
            });
            lines.forEach(el => el.classList.toggle('active', el === active));
            if (active) {
                const target = active.offsetTop - box.clientHeight / 2 + active.clientHeight / 2;
                if (force || Math.abs(target - box.scrollTop) > 60) box.scrollTop = target;
            }
        }

        function drawViz() {
            const cv = document.getElementById('np-viz');
            if (!cv || !document.getElementById('np-overlay').classList.contains('open')) {
                vizRaf = null;
                return;
            }
            const w = cv.clientWidth, h = cv.clientHeight;
            if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
            const ctx = cv.getContext('2d');
            ctx.clearRect(0, 0, w, h);
            if (analyser) {
                const data = new Uint8Array(analyser.frequencyBinCount);
                analyser.getByteFrequencyData(data);
                const bars = Math.min(48, data.length);
                const bw = w / bars;
                for (let i = 0; i < bars; i++) {
                    const v = data[i] / 255;
                    const bh = Math.max(2, v * h);
                    ctx.fillStyle = 'rgba(29,185,84,' + (0.30 + v * 0.70).toFixed(2) + ')';
                    ctx.fillRect(i * bw + 1, h - bh, Math.max(2, bw - 2), bh);
                }
            }
            vizRaf = requestAnimationFrame(drawViz);
        }

        function startViz() {
            ensureAudioGraph();
            if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
            if (!vizRaf) vizRaf = requestAnimationFrame(drawViz);
        }

        function makeSeekable(barId, onSeek) {
            const bar = document.getElementById(barId);
            if (!bar) return;
            let dragging = false;
            const seek = (e) => {
                const rect = bar.getBoundingClientRect();
                const pct = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
                onSeek(pct);
            };
            bar.addEventListener('pointerdown', (e) => {
                dragging = true;
                try { bar.setPointerCapture(e.pointerId); } catch (err) {}
                seek(e);
            });
            bar.addEventListener('pointermove', (e) => { if (dragging) seek(e); });
            bar.addEventListener('pointerup', () => { dragging = false; });
            bar.addEventListener('pointercancel', () => { dragging = false; });
        }

        async function downloadTrack(t) {
            if (t.source === 'youtube') {
                const vid = t.id.replace('yt-', '');
                window.location.href = '/api/yt-stream?v=' + encodeURIComponent(vid) +
                    '&dl=1&name=' + encodeURIComponent(t.title);
                return;
            }
            try {
                const res = await fetch(t.preview);
                const blob = await res.blob();
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                const ext = ((t.preview || '').split('.').pop() || 'mp3').split('?')[0];
                a.download = (t.title || 'lagu') + '.' + ext;
                a.click();
                URL.revokeObjectURL(a.href);
            } catch (e) {
                window.open(t.preview, '_blank');
            }
        }

        function togglePlay() {
            if (!audio.src) return;
            if (audio.paused) audio.play(); else audio.pause();
        }

        function nextTrack() {
            if (state.index < state.queue.length - 1) playIndex(state.queue, state.index + 1, false);
        }

        function prevTrack() {
            if (state.index > 0) playIndex(state.queue, state.index - 1, false);
            else audio.currentTime = 0;
        }

        async function loadTrending() {
            showLoading();
            try {
                const url = state.source === 'youtube' ? '/api/yt-trending' : (state.source === 'audius' ? '/api/audius/trending' : '/api/trending');
                const res = await fetch(url);
                const data = await res.json();
                content.innerHTML = '';
                const suffix = state.source === 'audius' ? ' (lagu penuh)' : (state.source === 'youtube' ? ' (YouTube)' : '');
                const hasGlobal = data.results && data.results.length;
                const hasId = data.indonesia && data.indonesia.length;
                const hasAi = data.ai && data.ai.length;
                if (!hasGlobal && !hasId && !hasAi) { showEmpty('Tidak ada data trending.'); return; }
                if (hasGlobal) renderGrid(data.results, '🔥 Trending Global' + suffix);
                if (hasId) renderGrid(data.indonesia, '🇮🇩 Trending Indonesia' + suffix);
                if (hasAi) renderGrid(data.ai, '🤖 AI Covers' + suffix);
                if (data.ai_id_search) renderAiIdLink(data.ai_id_search);
                renderChips();
                markPlaying();
            } catch (e) {
                showEmpty('Gagal memuat trending: ' + e.message);
            }
        }

        function renderAiIdLink(url) {
            const box = document.createElement('div');
            box.className = 'ai-note';
            box.innerHTML = '🤖 <b>AI Cover Indonesia</b> belum tersedia di sumber gratis yang bisa diputar di sini. ' +
                'Cari di YouTube: <a href="' + url + '" target="_blank" rel="noopener">buka pencarian AI Cover lagu Indonesia ↗</a>';
            content.appendChild(box);
        }

        function renderChips() {
            const genres = ['Pop', 'Rock', 'Jazz', 'Hip-Hop', 'EDM', 'Klasik', 'Dangdut', 'Koplo', 'Indonesia', 'AI Cover', 'Lo-fi'];
            const wrap = document.createElement('div');
            wrap.className = 'chips';
            wrap.style.marginTop = '24px';
            genres.forEach(g => {
                const chip = document.createElement('div');
                chip.className = 'chip';
                chip.textContent = g;
                chip.addEventListener('click', () => doSearch(g));
                wrap.appendChild(chip);
            });
            const h = document.createElement('div');
            h.className = 'section-title';
            h.textContent = 'Jelajahi Genre';
            content.appendChild(h);
            content.appendChild(wrap);
        }

        async function doSearch(q) {
            q = (q || '').trim();
            if (!q) return;
            state.lastQuery = q;
            searchInput.value = q;
            setViewActive('search');
            showLoading();
            try {
                const base = state.source === 'youtube' ? '/api/yt-search?q=' : (state.source === 'audius' ? '/api/audius/search?q=' : '/api/search?q=');
                const res = await fetch(base + encodeURIComponent(q));
                const data = await res.json();
                content.innerHTML = '';
                if (!data.results || !data.results.length) {
                    showEmpty('Tidak ditemukan hasil untuk "' + q + '".');
                    return;
                }
                const label = 'Hasil untuk "' + q + '"' + (state.source === 'audius' ? ' (lagu penuh)' : (state.source === 'youtube' ? ' (YouTube)' : ''));
                renderGrid(data.results, label);
                markPlaying();
            } catch (e) {
                showEmpty('Gagal mencari: ' + e.message);
            }
        }

        function setViewActive(view) {
            state.view = view;
            document.querySelectorAll('.nav-item').forEach(n => {
                n.classList.toggle('active', n.dataset.view === view);
            });
        }

        function setView(view) {
            setViewActive(view);
            if (view === 'home' || view === 'trending') loadTrending();
            else if (view === 'favorites') renderFavorites();
            else if (view === 'playlists') renderPlaylists();
            else if (view === 'settings') renderSettings();
            else if (view === 'search') {
                if (state.lastQuery) doSearch(state.lastQuery);
                else {
                    content.innerHTML = '<div class="section-title">Cari musik</div><div class="empty">Ketik nama artis, lagu, atau album di kolom pencarian di atas.</div>';
                    searchInput.focus();
                }
            }
        }

        function setSource(src) {
            state.source = src;
            document.querySelectorAll('#source-toggle button').forEach(b => {
                b.classList.toggle('active', b.dataset.src === src);
            });
            audio.pause();
            if (state.view === 'search') {
                if (state.lastQuery) doSearch(state.lastQuery);
                else showEmpty('Ketik nama lagu/artis untuk mencari.');
            } else if (state.view === 'home' || state.view === 'trending') {
                loadTrending();
            }
        }

        // ---- Equalizer (Web Audio) ----
        const EQ_BANDS = [60, 170, 350, 1000, 3500, 10000];
        const EQ_PRESETS = {
            Flat:   [0, 0, 0, 0, 0, 0],
            Bass:   [7, 5, 3, 0, -1, -2],
            Treble: [-2, -1, 0, 2, 4, 6],
            Vocal:  [-2, 0, 3, 4, 3, 1],
            Rock:   [4, 3, -1, -2, 2, 4],
            Pop:    [-1, 2, 3, 2, 0, -1],
            Jazz:   [3, 2, 1, 1, 2, 3],
        };
        const eqState = { enabled: false, gains: [0, 0, 0, 0, 0, 0], preset: 'Flat' };
        let audioCtx = null, eqFilters = [], mediaSource = null, analyser = null;
        let vizRaf = null;

        function ensureAudioGraph() {
            if (audioCtx) return;
            const AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) return;
            audioCtx = new AC();
            try {
                mediaSource = audioCtx.createMediaElementSource(audio);
            } catch (e) { return; }
            let prev = mediaSource;
            eqFilters = EQ_BANDS.map(freq => {
                const f = audioCtx.createBiquadFilter();
                f.type = 'peaking';
                f.frequency.value = freq;
                f.Q.value = 1;
                f.gain.value = 0;
                prev.connect(f);
                prev = f;
                return f;
            });
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 128;
            analyser.smoothingTimeConstant = 0.82;
            prev.connect(analyser);
            analyser.connect(audioCtx.destination);
        }

        function applyEq() {
            eqFilters.forEach((f, i) => { f.gain.value = eqState.enabled ? eqState.gains[i] : 0; });
        }

        function setEqBand(i, v) {
            eqState.gains[i] = v;
            eqState.preset = 'Custom';
            ensureAudioGraph();
            applyEq();
            renderNpEqPresets();
        }

        function setEqPreset(name) {
            if (!EQ_PRESETS[name]) return;
            eqState.preset = name;
            eqState.gains = EQ_PRESETS[name].slice();
            eqState.enabled = true;
            ensureAudioGraph();
            if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
            applyEq();
            if (state.view === 'settings') renderSettings();
            renderNpEqPresets();
        }

        function renderNpEqPresets() {
            const wrap = document.getElementById('np-eq');
            if (!wrap) return;
            wrap.innerHTML = '';
            Object.keys(EQ_PRESETS).forEach(name => {
                const b = document.createElement('button');
                b.textContent = name;
                if (eqState.enabled && eqState.preset === name) b.classList.add('active');
                b.addEventListener('click', () => setEqPreset(name));
                wrap.appendChild(b);
            });
        }

        function renderSettings() {
            content.innerHTML = `
                <div class="section-title">⚙️ Pengaturan</div>
                <div class="panel">
                    <div class="row-between">
                        <div>
                            <h3>🎚️ Equalizer</h3>
                            <div class="hint" style="margin:0">Sesuaikan nada lagu. Berlaku untuk semua sumber (iTunes, Audius, file lokal).</div>
                        </div>
                        <label class="switch"><input type="checkbox" id="eq-enable" ${eqState.enabled ? 'checked' : ''}> Aktifkan</label>
                    </div>
                    <div class="eq-presets" id="eq-presets"></div>
                    <div class="eq-bands" id="eq-bands"></div>
                    <button class="btn-accent" id="eq-reset">Reset (Flat)</button>
                </div>
                <div class="panel">
                    <h3>📁 Musik Lokal</h3>
                    <div class="hint">Pilih file audio dari komputer (MP3, WAV, OGG, M4A, FLAC). File diputar langsung di browser.</div>
                    <input type="file" id="local-input" accept="audio/*" multiple>
                    <div class="local-list" id="local-list"></div>
                </div>
            `;

            const pWrap = document.getElementById('eq-presets');
            Object.keys(EQ_PRESETS).forEach(name => {
                const b = document.createElement('button');
                b.textContent = name;
                if (eqState.preset === name) b.classList.add('active');
                b.addEventListener('click', () => setEqPreset(name));
                pWrap.appendChild(b);
            });

            const bWrap = document.getElementById('eq-bands');
            EQ_BANDS.forEach((freq, i) => {
                const band = document.createElement('div');
                band.className = 'eq-band';
                const label = freq >= 1000 ? (freq / 1000) + 'k' : freq;
                band.innerHTML = `
                    <span class="lbl">${label}Hz</span>
                    <input type="range" min="-12" max="12" step="1" value="${eqState.gains[i]}" id="eq-slider-${i}">
                    <span class="val" id="eq-val-${i}">${eqState.gains[i] > 0 ? '+' : ''}${eqState.gains[i]}</span>
                `;
                bWrap.appendChild(band);
                band.querySelector('input').addEventListener('input', (e) => {
                    const v = parseInt(e.target.value, 10);
                    document.getElementById('eq-val-' + i).textContent = (v > 0 ? '+' : '') + v;
                    setEqBand(i, v);
                });
            });

            document.getElementById('eq-enable').addEventListener('change', (e) => {
                eqState.enabled = e.target.checked;
                ensureAudioGraph();
                if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
                applyEq();
            });
            document.getElementById('eq-reset').addEventListener('click', () => setEqPreset('Flat'));

            renderLocalList();
            document.getElementById('local-input').addEventListener('change', (e) => addLocalFiles(e.target.files));
        }

        function renderLocalList() {
            const wrap = document.getElementById('local-list');
            if (!wrap) return;
            const locals = state.locals || [];
            wrap.innerHTML = '';
            if (!locals.length) {
                wrap.innerHTML = '<div class="hint">Belum ada file lokal.</div>';
                return;
            }
            const cur = state.queue[state.index];
            locals.forEach((t, i) => {
                const el = document.createElement('div');
                el.className = 'local-item' + (cur && cur.id === t.id ? ' playing' : '');
                el.innerHTML = '<span class="nm">🎵 ' + t.title + '</span><span class="val">▶</span>';
                el.addEventListener('click', () => playIndex(locals, i));
                wrap.appendChild(el);
            });
        }

        function addLocalFiles(files) {
            state.locals = state.locals || [];
            Array.from(files).forEach(file => {
                state.locals.push({
                    id: 'local-' + file.name + '-' + file.size,
                    title: file.name.replace(/[.][^.]+$/, ''),
                    artist: 'Musik Lokal',
                    album: '',
                    artwork: '',
                    preview: URL.createObjectURL(file),
                    duration: 0,
                    genre: 'Local',
                    source: 'local',
                });
            });
            renderLocalList();
        }

        // Event wiring
        document.querySelectorAll('#source-toggle button').forEach(b => {
            b.addEventListener('click', () => setSource(b.dataset.src));
        });
        document.querySelectorAll('.nav-item').forEach(n => {
            n.addEventListener('click', () => setView(n.dataset.view));
        });
        document.getElementById('search-btn').addEventListener('click', () => doSearch(searchInput.value));
        searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(searchInput.value); });

        document.getElementById('pl-create').addEventListener('click', () => {
            const name = document.getElementById('pl-new-name').value.trim();
            if (!name || !plModalTrack) return;
            addToPlaylist(name, plModalTrack);
            closePlaylistModal();
        });
        document.getElementById('pl-new-name').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') document.getElementById('pl-create').click();
        });
        document.getElementById('pl-close').addEventListener('click', closePlaylistModal);
        document.getElementById('pl-modal').addEventListener('click', (e) => {
            if (e.target.id === 'pl-modal') closePlaylistModal();
        });

        document.getElementById('btn-play').addEventListener('click', togglePlay);
        document.getElementById('btn-next').addEventListener('click', nextTrack);
        document.getElementById('btn-prev').addEventListener('click', prevTrack);

        document.getElementById('np-close').addEventListener('click', closeNowPlaying);
        document.getElementById('np-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'np-overlay') closeNowPlaying();
        });
        document.getElementById('pb-art').addEventListener('click', () => {
            const t = state.queue[state.index];
            if (t) showNowPlaying(t);
        });

        document.getElementById('np-play').addEventListener('click', togglePlay);
        document.getElementById('np-next').addEventListener('click', nextTrack);
        document.getElementById('np-prev').addEventListener('click', prevTrack);
        makeSeekable('np-progress', (pct) => {
            if (audio.duration) audio.currentTime = pct * audio.duration;
        });
        document.getElementById('np-volume').addEventListener('input', (e) => {
            audio.volume = parseFloat(e.target.value);
            document.getElementById('volume').value = audio.volume;
        });

        audio.addEventListener('play', () => {
            document.getElementById('btn-play').textContent = '⏸';
            markPlaying();
            syncNpUI();
            startViz();
            if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
        });
        audio.addEventListener('pause', () => {
            document.getElementById('btn-play').textContent = '▶';
            syncNpUI();
        });
        audio.addEventListener('ended', nextTrack);

        audio.addEventListener('timeupdate', () => {
            const cur = audio.currentTime || 0;
            const dur = audio.duration || 0;
            document.getElementById('cur-time').textContent = fmt(cur);
            document.getElementById('progress-fill').style.width = dur ? (cur / dur * 100) + '%' : '0%';
            highlightLyrics();
            syncNpUI();
        });
        audio.addEventListener('loadedmetadata', () => {
            document.getElementById('dur-time').textContent = fmt(audio.duration);
            syncNpUI();
        });

        makeSeekable('progress', (pct) => {
            if (audio.duration) audio.currentTime = pct * audio.duration;
        });

        document.getElementById('volume').addEventListener('input', (e) => {
            audio.volume = parseFloat(e.target.value);
            document.getElementById('np-volume').value = audio.volume;
        });

        document.addEventListener('keydown', (e) => {
            if (tapSyncActive) {
                if (e.code === 'Space') { e.preventDefault(); const b = document.getElementById('tap-btn'); if (b) b.click(); }
                else if (e.code === 'Backspace') { e.preventDefault(); const b = document.getElementById('tap-undo'); if (b) b.click(); }
                else if (e.key === 'Escape') { e.preventDefault(); const b = document.getElementById('tap-cancel'); if (b) b.click(); }
                return;
            }
            if (e.code === 'Space' && e.target.tagName !== 'INPUT') { e.preventDefault(); togglePlay(); }
            if (e.key === 'Escape') { closeNowPlaying(); closePlaylistModal(); }
        });

        // Initial load
        setView('home');

        if ('serviceWorker' in navigator && location.protocol === 'https:') {
            window.addEventListener('load', () => {
                navigator.serviceWorker.register('/sw.js').catch(() => {});
            });
        }
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE.replace('__LOGO_URI__', logo_data_uri()))


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route('/api/search')
def api_search():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'results': []})
    key = 'search:' + q.lower()
    cached = _cache_get(key)
    if cached is not None:
        return jsonify({'results': cached})
    try:
        results = normalize(fetch_itunes(q, limit=30))
    except Exception as e:
        return jsonify({'results': [], 'error': str(e)}), 200
    _cache_set(key, results)
    return jsonify({'results': results})


@app.route('/api/trending')
def api_trending():
    cached = _cache_get('trending')
    if cached is not None:
        return jsonify(cached)

    data = {
        'results': build_itunes_list(TRENDING_TERMS, limit=24),
        'indonesia': build_itunes_list(ID_TRENDING_TERMS, per_term=3, limit=18),
        'ai': build_itunes_list(AI_TERMS, per_term=3, limit=18),
        'ai_id_search': YOUTUBE_AI_ID_SEARCH,
    }
    _cache_set('trending', data)
    return jsonify(data)


@app.route('/api/audius/trending')
def api_audius_trending():
    cached = _cache_get('audius_trending', ttl=900)
    if cached is not None:
        return jsonify(cached)
    try:
        host = audius_host()
        r = requests.get(host + "/v1/tracks/trending", params={"limit": 24}, timeout=15)
        r.raise_for_status()
        global_list = normalize_audius(r.json().get("data", []), host)
        id_list = build_audius_list(AUDIUS_ID_TERMS, per_term=3, limit=18)
        ai_list = build_audius_list(AI_TERMS, per_term=4, limit=18)
    except Exception as e:
        return jsonify({'results': [], 'indonesia': [], 'ai': [], 'error': str(e)}), 200
    data = {'results': global_list, 'indonesia': id_list, 'ai': ai_list,
            'ai_id_search': YOUTUBE_AI_ID_SEARCH}
    _cache_set('audius_trending', data)
    return jsonify(data)


@app.route('/api/audius/search')
def api_audius_search():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'results': []})
    key = 'audius_search:' + q.lower()
    cached = _cache_get(key)
    if cached is not None:
        return jsonify({'results': cached})
    try:
        host = audius_host()
        r = requests.get(host + "/v1/tracks/search", params={"query": q, "limit": 30}, timeout=15)
        r.raise_for_status()
        results = normalize_audius(r.json().get("data", []), host)
    except Exception as e:
        return jsonify({'results': [], 'error': str(e)}), 200
    _cache_set(key, results)
    return jsonify({'results': results})


@app.route('/api/yt-search')
def api_yt_search():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'results': []})
    key = 'yt_search:' + q.lower()
    cached = _cache_get(key)
    if cached is not None:
        return jsonify({'results': cached})
    results = search_youtube(q, limit=25)
    _cache_set(key, results)
    return jsonify({'results': results})


YOUTUBE_ID_CHART_TERMS = [
    "lagu indonesia terpopuler",
    "top lagu indonesia 2026",
    "lagu indonesia viral",
    "playlist lagu indonesia",
]


@app.route('/api/yt-trending')
def api_yt_trending():
    cached = _cache_get('yt_trending', ttl=900)
    if cached is not None:
        return jsonify(cached)
    terms = ID_TRENDING_TERMS + YOUTUBE_ID_CHART_TERMS
    merged = []
    seen = set()
    for term in terms:
        for t in search_youtube(term, limit=3):
            if t['id'] not in seen:
                seen.add(t['id'])
                merged.append(t)
        if len(merged) >= 30:
            break
    result = {'results': [], 'indonesia': merged[:30], 'ai': []}
    _cache_set('yt_trending', result, ttl=900)
    return jsonify(result)


@app.route('/api/yt-stream')
def api_yt_stream():
    vid = (request.args.get('v') or '').strip()
    if not vid:
        return jsonify({'error': 'No video ID'}), 400
    vid = vid.replace('yt-', '')
    dl = (request.args.get('dl') or '').strip() == '1'
    name = (request.args.get('name') or '').strip()

    info = _cache_get('ytaudio:' + vid, ttl=1800)
    if not info or not info.get('url'):
        info = get_youtube_audio_info(vid)
    if not info or not info.get('url'):
        return jsonify({'error': 'Could not extract audio URL'}), 400
    _cache_set('ytaudio:' + vid, info, ttl=1800)

    upstream_headers = {'User-Agent': 'Mozilla/5.0'}
    rng = request.headers.get('Range')
    if rng:
        upstream_headers['Range'] = rng
    try:
        r = requests.get(info['url'], headers=upstream_headers, timeout=15, stream=True)
        if r.status_code >= 400:
            _cache_delete('ytaudio:' + vid)
            return jsonify({'error': 'Upstream failed'}), 502
    except Exception:
        return jsonify({'error': 'Upstream failed'}), 502

    def generate():
        try:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            r.close()

    from flask import Response
    out_headers = {'Accept-Ranges': 'bytes'}
    for h in ('Content-Range', 'Content-Length', 'Content-Type'):
        if h in r.headers:
            out_headers[h] = r.headers[h]
    if dl:
        safe = re.sub(r'[^\w\- ]', '', name).strip() or 'lagu'
        out_headers['Content-Disposition'] = 'attachment; filename="' + safe + '.webm"'
    else:
        out_headers['Content-Disposition'] = 'inline'
    resp = Response(generate(), status=r.status_code,
                    mimetype=out_headers.get('Content-Type', 'audio/webm'))
    for k, v in out_headers.items():
        if k != 'Content-Type':
            resp.headers[k] = v
    return resp


@app.route('/api/lyrics')
def api_lyrics():
    title = (request.args.get('title') or '').strip()
    artist = (request.args.get('artist') or '').strip()
    dur_ms = (request.args.get('duration') or '').strip()
    if not title:
        return jsonify({'lines': [], 'plain': ''})
    duration_s = int(dur_ms) // 1000 if dur_ms.isdigit() and int(dur_ms) > 0 else None
    key = 'lyrics:' + (title + '|' + artist).lower()
    custom = _load_store().get(key)
    if custom is not None:
        result = {
            'lines': parse_lrc(custom['text']) if custom.get('lrc') else [],
            'plain': '' if custom.get('lrc') else custom['text'],
            'custom': True,
        }
        return jsonify(result)
    cached = _cache_get(key, ttl=86400)
    if cached is not None:
        return jsonify(cached)
    data = fetch_lyrics(title, artist, duration_s)
    lines = parse_lrc(data['syncedLyrics']) if data and data.get('syncedLyrics') else []
    plain = (data.get('plainLyrics') or '') if data else ''
    if not lines and plain and duration_s:
        lines = parse_lrc(distribute_plain_lrc(plain, duration_s))
    result = {
        'lines': lines,
        'plain': plain,
    }
    if result['lines'] or result['plain']:
        _cache_set(key, result, ttl=86400)
    else:
        _cache_set(key, result, ttl=300)
    return jsonify(result)


@app.route('/api/lyrics-custom', methods=['POST'])
def api_lyrics_custom():
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    artist = (data.get('artist') or '').strip()
    text = (data.get('text') or '').replace('\r\n', '\n').strip()
    if not title or not text:
        return jsonify({'ok': False, 'error': 'Judul dan lirik wajib diisi'}), 400
    try:
        duration_ms = int(data.get('duration') or 0)
    except Exception:
        duration_ms = 0
    key = 'lyrics:' + (title + '|' + artist).lower()
    is_lrc = bool(re.search(r'\[\d+:\d+', text))
    auto_synced = False
    if not is_lrc and duration_ms > 3000:
        text = distribute_plain_lrc(text, duration_ms / 1000.0)
        is_lrc = True
        auto_synced = True
    store = _load_store()
    store[key] = {
        'title': title,
        'artist': artist,
        'text': text,
        'lrc': is_lrc,
        'auto': auto_synced,
    }
    _save_store(store)
    _cache_delete(key)
    return jsonify({'ok': True})


if __name__ == '__main__':
    import sys
    import threading

    if getattr(sys, 'frozen', False):
        import time
        import urllib.request

        def run_server():
            app.run(debug=False, host='127.0.0.1', port=5001, use_reloader=False)

        threading.Thread(target=run_server, daemon=True).start()
        url = 'http://127.0.0.1:5001'
        for _ in range(60):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        try:
            import webview
            webview.create_window('Music Player', url, width=1280, height=820)
            ico = resource_path('icon.ico')
            webview.start(icon=ico if os.path.isfile(ico) else None)
        except Exception:
            import webbrowser
            webbrowser.open(url)
            while True:
                time.sleep(3600)
    else:
        app.run(debug=True, host='0.0.0.0', port=5001)
