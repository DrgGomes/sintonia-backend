# api/index.py — Seu servidor de música (catálogo mundial)
import json
import os

from vercel import Request, Response
from ytmusicapi import YTMusic

_yt = None

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

def json_response(data, status=200):
    return Response(
        json.dumps(data, ensure_ascii=False),
        status_code=status,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )

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
        album = (r.get("album") or {}).get("name", "") if r.get("album") else ""
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
    song = yt.get_song(video_id)
    sd = song.get("streamingData") or {}
    fmts = [f for f in (sd.get("adaptiveFormats") or []) if "audio" in (f.get("mimeType") or "")]
    if not fmts:
        fmts = sd.get("formats") or []
    for f in fmts:
        url = f.get("url")
        if url:
            return url.replace("\\u0026", "&")
    return None

def handler(request: Request):
    if request.method == "OPTIONS":
        return json_response({"ok": True})
    path = (request.path or "").rstrip("/")
    params = request.query_params or {}
    try:
        if path.endswith("/api/search"):
            term = (params.get("q") or "").strip()
            if not term:
                return json_response({"error": "Falta o parâmetro 'q'."}, 400)
            try:
                limit = min(int(params.get("limit") or 20), 50)
            except ValueError:
                limit = 20
            return json_response({"tracks": search_tracks(term, limit)})
        if path.endswith("/api/stream"):
            vid = (params.get("id") or "").strip()
            if not vid:
                return json_response({"error": "Falta o parâmetro 'id'."}, 400)
            url = stream_url(vid)
            if not url:
                return json_response({"error": "Não foi possível obter o áudio."}, 404)
            return json_response({"url": url})
        return json_response({"error": "Rota não encontrada."}, 404)
    except Exception as exc:
        return json_response({"error": str(exc)}, 500)
