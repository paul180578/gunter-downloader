import os
import re
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

def resolve_download_url(video_id, is_audio=True):
    """Obtiene el enlace directo de descarga sin requerir autenticación ni cookies locales."""
    clean_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Intento 1: API de conversión pública y2mate
    try:
        init_res = requests.post(
            "https://www-y2mate.com/mates/analyzeV2/ajax",
            data={"k_query": clean_url, "k_page": "home", "hl": "es", "q_auto": 0},
            headers={"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"},
            timeout=10
        ).json()
        
        vid = init_res.get("vid")
        title = init_res.get("title", f"media_{video_id}")
        
        if is_audio:
            links = init_res.get("links", {}).get("mp3", {})
            k = next(iter(links.values()))["k"]
        else:
            links = init_res.get("links", {}).get("mp4", {})
            k = next(iter(links.values()))["k"]

        conv_res = requests.post(
            "https://www-y2mate.com/mates/convertV2/index",
            data={"vid": vid, "k": k},
            headers={"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"},
            timeout=15
        ).json()

        dlink = conv_res.get("dlink")
        if dlink:
            return dlink, title
    except Exception:
        pass

    # Intento 2: Invidious Stream Resolver
    invidious_hosts = [
        "https://inv.nadeko.net",
        "https://invidious.nerdvpn.de",
        "https://yt.artemislena.eu"
    ]
    for host in invidious_hosts:
        try:
            r = requests.get(f"{host}/api/v1/videos/{video_id}", timeout=6).json()
            title = r.get("title", f"media_{video_id}")
            if is_audio:
                formats = [f for f in r.get("adaptiveFormats", []) if "audio" in f.get("type", "")]
                if formats:
                    return formats[0].get("url"), title
            else:
                formats = r.get("formatStreams", [])
                if formats:
                    return formats[-1].get("url"), title
        except Exception:
            continue

    return None, None

def download_file_stream(download_url, dest_path, task_id):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(download_url, headers=headers, stream=True, timeout=40)
    total_length = r.headers.get('content-length')

    if not total_length:
        with open(dest_path, 'wb') as f:
            f.write(r.content)
    else:
        dl = 0
        total_length = int(total_length)
        with open(dest_path, 'wb') as f:
            for data in r.iter_content(chunk_size=32768):
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

    is_audio = (tipo in ("link", "batch"))
    targets_to_process = []

    try:
        if tipo == "batch":
            # Búsqueda de canciones
            try:
                search_url = f"https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q={requests.utils.quote(target)}"
                queries = requests.get(search_url, timeout=3).json()[1][:cantidad]
                for q in queries:
                    # resolver ID buscando en API pública
                    inv_res = requests.get(f"https://inv.nadeko.net/api/v1/search?q={requests.utils.quote(q)}&type=video", timeout=5).json()
                    if inv_res and isinstance(inv_res, list):
                        targets_to_process.append(inv_res[0].get("videoId"))
            except Exception:
                pass
        else:
            vid = extract_video_id(target)
            if vid:
                targets_to_process.append(vid)

        if not targets_to_process:
            progress_tracker[task_id] = {"percent": 0, "status": "Error: Enlace de YouTube no válido."}
            shutil.rmtree(task_dir, ignore_errors=True)
            return

        archivos = []
        for idx, vid in enumerate(targets_to_process):
            progress_tracker[task_id] = {
                "percent": 15,
                "status": f"Resolviendo archivo ({idx + 1}/{len(targets_to_process)})..."
            }

            durl, raw_title = resolve_download_url(vid, is_audio=is_audio)
            if not durl:
                continue

            clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title or f"audio_{vid}")
            ext = ".mp3" if is_audio else ".mp4"
            filename = f"{clean_title}{ext}"
            dest_path = os.path.join(task_dir, filename)

            download_file_stream(durl, dest_path, task_id)
            if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
                archivos.append(filename)

        if not archivos:
            progress_tracker[task_id] = {"percent": 0, "status": "Error: La plataforma no permitió extraer este video."}
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
