import json
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from ytmusicapi import YTMusic

_yt = None
_ts_cache = {"value": None, "at": 0}

def get_yt():
    """Cria/carrega uma única conexão com o YouTube Music."""
    global _yt
    if _yt is None:
        raw = os.environ.get("YTM_HEADERS", "").strip()
        try:
            _yt = YTMusic(json.loads(raw)) if raw else YTMusic()
        except Exception:
            _yt = YTMusic()
    return _yt

def get_signature_timestamp(yt):
    """Pega o 'carimbo de tempo' atual do YouTube (válido por ~30 min)."""
    now = time.time()
    if _ts_cache["value"] is None or now - _ts_cache["at"] > 1800:
        try:
            _ts_cache["value"] = yt.get_signatureTimestamp()
        except Exception:
            _ts_cache["value"] = None
        _ts_cache["at"] = now
    return _ts_cache["value"]

def search_tracks(term, limit):
    yt = get_yt()
    results = yt.search(term, filter="songs", limit=limit)
    out = []
    for r in results:
        vid = r.get("videoId")
        if not vid:
            continue
        thumbs = r.get("thumbnails") or []
        cover = thumbs[-1].get("url", "") if thumbs else ""
        artists = r.get("artists") or []
        artist = artists[0].get("name", "") if artists else ""
        album_obj = r.get("album") or {}
        album = album_obj.get("name", "") if isinstance(album_obj, dict) else ""
        out.append({
            "id": vid,
            "name": r.get("title", ""),
            "artist": artist,
            "album": album,
            "cover": cover,
            "duration": r.get("duration_seconds") or 0,
        })
    return out

def stream_url(video_id):
    yt = get_yt()
    ts = get_signature_timestamp(yt)
    try:
        song = yt.get_song(video_id, signatureTimestamp=ts)
    except Exception:
        song = yt.get_song(video_id)

    sd = song.get("streamingData") or {}
    formats = sd.get("adaptiveFormats") or [] + (sd.get("formats") or [])

    # 1) Prefere MP4/AAC (toca em qualquer aparelho, inclusive iPhone)
    audio = [f for f in formats if "audio" in (f.get("mimeType") or "") and "mp4" in (f.get("mimeType") or "")]
    # 2) Senão, qualquer formato de áudio
    if not audio:
        audio = [f for f in formats if "audio" in (f.get("mimeType") or "")]
    # 3) Último recurso: qualquer formato
    if not audio:
        audio = formats

    for f in audio:
        url = f.get("url")
        if url:
            return url.replace("\\u0026", "&").replace("\\u003d", "=")
    return None

class handler(BaseHTTPRequestHandler):
    def _headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json; charset=utf-8")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._headers()
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            path = parsed.path.rstrip("/")
            if path == "/api/search":
                term = (params.get("q") or "").strip()
                if not term:
                    return self._json({"error": "Falta o parâmetro 'q'."}, 400)
                try:
                    limit = min(int(params.get("limit") or 20), 50)
                except ValueError:
                    limit = 20
                return self._json({"tracks": search_tracks(term, limit)})
            if path == "/api/stream":
                vid = (params.get("id") or "").strip()
                if not vid:
                    return self._json({"error": "Falta o parâmetro 'id'."}, 400)
                url = stream_url(vid)
                if not url:
                    return self._json({"error": "Não foi possível obter o áudio."}, 404)
                return self._json({"url": url})
            return self._json({"error": "Rota não encontrada."}, 404)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def log_message(self, *args):
        pass
