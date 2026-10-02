import json
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from ytmusicapi import YTMusic

_yt = None
_yt_auth = "missing"  # missing | ok | invalid
_ts_cache = {"value": None, "at": 0}


def get_yt():
    global _yt, _yt_auth
    if _yt is None:
        raw = os.environ.get("YTM_HEADERS", "").strip()
        if not raw:
            _yt_auth = "missing"
            _yt = YTMusic()  # anônimo
        else:
            try:
                _yt = YTMusic(json.loads(raw))
                _yt_auth = "ok"
            except Exception:
                _yt_auth = "invalid"
                _yt = YTMusic()  # cai para anônimo mas marca inválido
    return _yt


def get_signature_timestamp(yt):
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
    """Retorna (url, detalhe). Se url for None, detalhe explica o motivo."""
    yt = get_yt()
    ts = get_signature_timestamp(yt)
    song = None
    try:
        song = yt.get_song(video_id, signatureTimestamp=ts)
    except Exception as e1:
        try:
            song = yt.get_song(video_id)
        except Exception as e2:
            return None, f"get_song falhou: {e1} / {e2}"

    sd = song.get("streamingData") or {}
    if not sd:
        ps = song.get("playabilityStatus") or {}
        return None, f"sem streamingData - playability: {ps.get('status')} / {ps.get('reason')}"

    formats = list(sd.get("adaptiveFormats") or []) + list(sd.get("formats") or [])

    # 1) áudio MP4/AAC (toca em qualquer aparelho, inclusive iPhone)
    audio = [f for f in formats if "audio" in (f.get("mimeType") or "") and "mp4" in (f.get("mimeType") or "")]
    # 2) qualquer formato de áudio
    if not audio:
        audio = [f for f in formats if "audio" in (f.get("mimeType") or "")]
    # 3) qualquer formato (último recurso)
    if not audio:
        audio = formats

    for f in audio:
        url = f.get("url")
        if url:
            return url.replace("\\u0026", "&").replace("\\u003d", "="), "ok"
    return None, "formatos sem URL de áudio"


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

            if path == "/api/status":
                return self._json({
                    "auth": _yt_auth,
                    "mensagem": {
                        "missing": "YTM_HEADERS ainda nao foi configurada no Vercel.",
                        "invalid": "YTM_HEADERS foi configurada, mas o JSON e invalido (confira aspas/chaves/colchetes).",
                        "ok": "YTM_HEADERS configurada corretamente.",
                    }[_yt_auth],
                })

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
                url, detail = stream_url(vid)
                if not url:
                    return self._json({"error": "Não foi possível obter o áudio.", "detail": detail}, 404)
                return self._json({"url": url, "auth": _yt_auth})

            return self._json({"error": "Rota nao encontrada."}, 404)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def log_message(self, *args):
        pass
