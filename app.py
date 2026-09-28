import os
import uuid
import time
import shutil
import zipfile
import threading
import requests
from flask import Flask, render_template, request, jsonify, send_file, after_this_request

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_downloads")
os.makedirs(TEMP_DIR, exist_ok=True)

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

def get_cobalt_stream(url, is_audio=False, video_quality="1080"):
    cobalt_instances = [
        "https://api.cobalt.tools",
        "https://cobalt-api.kwiatekm.pl",
        "https://api.wuk.sh"
    ]
    
    payload = {
        "url": url,
        "downloadMode": "audio" if is_audio else "auto",
        "audioFormat": "mp3" if is_audio else "best",
        "videoQuality": video_quality if not is_audio else "720"
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    for instance in cobalt_instances:
        try:
            res = requests.post(f"{instance}/", json=payload, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") in ("tunnel", "redirect", "success"):
                    return data.get("url")
        except Exception:
            continue
    return None

def download_file_stream(download_url, dest_path, task_id):
    r = requests.get(download_url, stream=True, timeout=30)
    total_length = r.headers.get('content-length')

    if total_length is None:
        with open(dest_path, 'wb') as f:
            f.write(r.content)
    else:
        dl = 0
        total_length = int(total_length)
        with open(dest_path, 'wb') as f:
            for data in r.iter_content(chunk_size=4096*8):
                dl += len(data)
                f.write(data)
                percent = int((dl / total_length) * 85)
                progress_tracker[task_id] = {
                    "percent": percent,
                    "status": f"Descargando datos: {percent}%"
                }

def run_download(task_id, tipo, target, cantidad, calidad_video="best"):
    task_dir = os.path.join(TEMP_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    try:
        urls_to_download = []
        is_audio = (tipo in ("link", "batch"))

        if tipo == "batch":
            search_api = f"https://pipedapi.kavin.rocks/search?q={requests.utils.quote(target)}&filter=videos"
            try:
                s_res = requests.get(search_api, timeout=6).json()
                items = s_res.get("items", [])[:cantidad]
                for it in items:
                    v_url = it.get("url")
                    if v_url:
                        urls_to_download.append(("https://www.youtube.com" + v_url, it.get("title", "audio")))
            except Exception:
                urls_to_download.append((target, "audio"))
        else:
            urls_to_download.append((target, "archivo"))

        archivos = []
        for idx, (media_url, base_name) in enumerate(urls_to_download):
            progress_tracker[task_id] = {
                "percent": int((idx / len(urls_to_download)) * 30) + 10,
                "status": f"Procesando enlace {idx + 1} de {len(urls_to_download)}..."
            }
            
            stream_url = get_cobalt_stream(media_url, is_audio=is_audio, video_quality=calidad_video)
            if not stream_url:
                continue

            clean_name = "".join(c for c in base_name if c.isalnum() or c in (' ', '_', '-')).rstrip()
            if not clean_name:
                clean_name = f"gunter_media_{idx+1}"

            ext = ".mp3" if is_audio else ".mp4"
            filename = f"{clean_name}{ext}"
            dest_file = os.path.join(task_dir, filename)

            download_file_stream(stream_url, dest_file, task_id)
            if os.path.exists(dest_file):
                archivos.append(filename)

        if not archivos:
            progress_tracker[task_id] = {"percent": 0, "status": "Error: El enlace no pudo ser procesado."}
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
        print(f"[ERROR MOTOR] {str(e)}", flush=True)
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
    progress_tracker[task_id] = {"percent": 5, "status": "Iniciando motor Gunter..."}

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
