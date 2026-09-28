import os
import re
import uuid
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

def extract_video_id(url):
    url = url.strip()
    match = re.search(r'(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})', url)
    if match:
        return match.group(1)
    return None

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/suggest")
def suggest():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
    try:
        url = f"https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q={query}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        if r.status_code == 200:
            return jsonify(r.json()[1][:7])
    except Exception:
        pass
    return jsonify([])

def get_direct_stream(video_id, is_audio=True):
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    # Motores públicos con túneles CDN activos
    endpoints = [
        ("https://cobalt-api.kwiatekm.pl", {
            "url": video_url,
            "downloadMode": "audio" if is_audio else "auto",
            "audioFormat": "mp3" if is_audio else "best",
            "videoQuality": "1080"
        }),
        ("https://api.wuk.sh", {
            "url": video_url,
            "downloadMode": "audio" if is_audio else "auto",
            "audioFormat": "mp3" if is_audio else "best",
            "videoQuality": "1080"
        })
    ]

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    for base_url, payload in endpoints:
        try:
            r = requests.post(f"{base_url}/", json=payload, headers=headers, timeout=8)
            if r.status_code == 200:
                data = r.json()
                stream_url = data.get("url")
                if stream_url:
                    filename = data.get("filename") or f"Gunter_{video_id}.{'mp3' if is_audio else 'mp4'}"
                    return stream_url, filename
        except Exception:
            continue

    return None, None

@app.route("/start-download", methods=["POST"])
def start_download():
    data = request.json or {}
    tipo = data.get("tipo")
    target = data.get("target", "").strip()
    is_audio = (tipo in ("link", "batch"))

    vid = extract_video_id(target)
    if not vid:
        return jsonify({"status": "error", "message": "Enlace de YouTube no válido"}), 400

    task_id = str(uuid.uuid4())
    stream_url, filename = get_direct_stream(vid, is_audio=is_audio)

    if not stream_url:
        return jsonify({
            "status": "error",
            "message": "Servidores de descarga ocupados temporalmente. Inténtalo de nuevo en unos segundos."
        }), 503

    return jsonify({
        "status": "ok",
        "task_id": task_id,
        "direct_url": stream_url,
        "filename": filename
    })

@app.route("/check-progress/<task_id>")
def check_progress(task_id):
    # Respuesta inmediata para finalizar barra en el frontend
    return jsonify({
        "percent": 100,
        "status": "¡Enlace generado con éxito!",
        "archivos": []
    })

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
