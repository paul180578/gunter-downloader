import os
import re
import uuid
import time
import shutil
import zipfile
import threading
import requests
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
import yt_dlp
import imageio_ffmpeg

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_downloads")
os.makedirs(TEMP_DIR, exist_ok=True)

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
try:
    os.chmod(FFMPEG_PATH, 0o755)
except Exception:
    pass

progress_tracker = {}

def auto_cleanup_worker():
    while True:
        try:
            ahora = time.time()
            if os.path.exists(TEMP_DIR):
                for folder_name in os.listdir(TEMP_DIR):
                    folder_path = os.path.join(TEMP_DIR, folder_name)
                    if os.path.isdir(folder_path):
                        if ahora - os.path.getctime(folder_path) > 600:
                            shutil.rmtree(folder_path, ignore_errors=True)
                            progress_tracker.pop(folder_name, None)
        except Exception:
            pass
        time.sleep(120)

threading.Thread(target=auto_cleanup_worker, daemon=True).start()

def clean_youtube_url(url):
    url = url.strip()
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})(?:[&?]|$)', url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    return url

def my_progress_hook(d, task_id):
    if d.get('status') == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        if total > 0:
            porcentaje = int((downloaded / total) * 85)
            progress_tracker[task_id] = {
                "percent": porcentaje,
                "status": f"Descargando datos: {porcentaje}%"
            }
        else:
            progress_tracker[task_id] = {"percent": 45, "status": "Descargando flujo..."}
    elif d.get('status') == 'finished':
        progress_tracker[task_id] = {
            "percent": 90,
            "status": "Ensamblando y procesando archivo..."
        }

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

def run_download(task_id, tipo, target, cantidad, calidad_video="best"):
    task_dir = os.path.join(TEMP_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    clean_target = clean_youtube_url(target) if tipo != "batch" else target

    ydl_opts = {
        'ffmpeg_location': FFMPEG_PATH,
        'outtmpl': os.path.join(task_dir, '%(title)s.%(ext)s'),
        'noplaylist': True,
        'socket_timeout': 20,
        'nocheckcertificate': True,
        'quiet': True,
        'progress_hooks': [lambda d: my_progress_hook(d, task_id)],
        'extractor_args': {
            'youtube': {
                'player_client': ['android_creator', 'android', 'web_safari'],
                'player_skip': ['configs', 'webpage']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }
    }

    if tipo == "video":
        ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        ydl_opts['merge_output_format'] = 'mp4'
        download_target = clean_target

    elif tipo == "link":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }]
        download_target = clean_target

    else:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['noplaylist'] = False
        ydl_opts['ignoreerrors'] = True
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }]
        download_target = f"ytsearch{cantidad}:{clean_target}"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([download_target])

        extensiones = (".mp3", ".mp4", ".mkv", ".webm")
        archivos = [f for f in os.listdir(task_dir) if f.endswith(extensiones)]
        if not archivos:
            progress_tracker[task_id] = {"percent": 0, "status": "Error: No se pudo generar el archivo multimedia."}
            shutil.rmtree(task_dir, ignore_errors=True)
            return

        zip_name = f"Gunter_Pack_{len(archivos)}_archivos.zip"
        if len(archivos) > 1:
            zip_path = os.path.join(task_dir, zip_name)
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for a in archivos:
                    zf.write(os.path.join(task_dir, a), arcname=a)

        progress_tracker[task_id] = {
            "percent": 100,
            "status": "¡Completado con éxito!",
            "archivos": archivos,
            "zip_file": zip_name if len(archivos) > 1 else None
        }

    except Exception as e:
        print(f"[ERROR DESCARGA] {str(e)}", flush=True)
        progress_tracker[task_id] = {"percent": 0, "status": f"Error: {e}"}
        shutil.rmtree(task_dir, ignore_errors=True)

@app.route("/start-download", methods=["POST"])
def start_download():
    data = request.json or {}
    tipo = data.get("tipo")
    target = data.get("target", "").strip()
    cantidad = int(data.get("cantidad", 5))
    calidad_video = data.get("calidad_video", "best")

    if not target:
        return jsonify({"status": "error", "message": "Enlace o búsqueda vacía"}), 400

    task_id = str(uuid.uuid4())
    progress_tracker[task_id] = {"percent": 5, "status": "Iniciando descarga..."}

    thread = threading.Thread(
        target=run_download, 
        args=(task_id, tipo, target, cantidad, calidad_video), 
        daemon=True
    )
    thread.start()

    return jsonify({"status": "ok", "task_id": task_id})

@app.route("/check-progress/<task_id>")
def check_progress(task_id):
    info = progress_tracker.get(task_id, {"percent": 0, "status": "Procesando..."})
    return jsonify(info)

@app.route("/get-single-song/<task_id>/<path:filename>")
def get_single_song(task_id, filename):
    task_dir = os.path.join(TEMP_DIR, task_id)
    file_path = os.path.join(task_dir, filename)

    if not os.path.exists(file_path):
        return "Archivo no encontrado o ya descargado", 404

    @after_this_request
    def cleanup(response):
        def remove_data():
            time.sleep(2)
            shutil.rmtree(task_dir, ignore_errors=True)
            progress_tracker.pop(task_id, None)

        threading.Thread(target=remove_data, daemon=True).start()
        return response

    return send_file(file_path, as_attachment=True, download_name=filename)

@app.route("/get-zip/<task_id>")
def get_zip(task_id):
    task_dir = os.path.join(TEMP_DIR, task_id)
    info = progress_tracker.get(task_id)
    if not info or not info.get("zip_file"):
        return "Archivo no encontrado o ya descargado", 404

    zip_path = os.path.join(task_dir, info["zip_file"])
    if not os.path.exists(zip_path):
        return "Archivo no encontrado", 404

    @after_this_request
    def cleanup(response):
        def remove_data():
            time.sleep(2)
            shutil.rmtree(task_dir, ignore_errors=True)
            progress_tracker.pop(task_id, None)

        threading.Thread(target=remove_data, daemon=True).start()
        return response

    return send_file(zip_path, as_attachment=True, download_name=info["zip_file"])

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
