function switchTab(tabId) {
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));

  document.getElementById(tabId).classList.add("active");
  document.getElementById(`${tabId}-btn`).classList.add("active");
}

const keywordInput = document.getElementById("keyword-input");
const suggestionsList = document.getElementById("suggestions-list");
let debounceTimer;

keywordInput.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  const q = keywordInput.value.trim();

  if (q.length < 2) {
    suggestionsList.classList.add("hidden");
    return;
  }

  debounceTimer = setTimeout(async () => {
    try {
      const res = await fetch(`/suggest?q=${encodeURIComponent(q)}`);
      const suggestions = await res.json();

      if (suggestions.length === 0) {
        suggestionsList.classList.add("hidden");
        return;
      }

      suggestionsList.innerHTML = "";
      suggestions.forEach(item => {
        const li = document.createElement("li");
        li.textContent = item;
        li.onclick = () => {
          keywordInput.value = item;
          suggestionsList.classList.add("hidden");
        };
        suggestionsList.appendChild(li);
      });

      suggestionsList.classList.remove("hidden");
    } catch (err) {
      console.error(err);
    }
  }, 220);
});

document.addEventListener("click", (e) => {
  if (!keywordInput.contains(e.target) && !suggestionsList.contains(e.target)) {
    suggestionsList.classList.add("hidden");
  }
});

async function iniciarProceso(tipo) {
  const statusPanel = document.getElementById("status-panel");
  const statusText = document.getElementById("status-text");
  const percentText = document.getElementById("percent-text");
  const progressBar = document.getElementById("progress-bar");
  const downloadHint = document.getElementById("download-hint");

  let payload = { tipo: tipo };

  if (tipo === "video") {
    const val = document.getElementById("video-url-input").value.trim();
    if (!val) return alert("Pega el enlace del video (TikTok, IG, FB o YouTube).");
    payload.target = val;
    payload.calidad_video = document.getElementById("video-quality").value;
  } else if (tipo === "link") {
    const val = document.getElementById("url-input").value.trim();
    if (!val) return alert("Pega un enlace de YouTube.");
    payload.target = val;
  } else {
    const val = keywordInput.value.trim();
    if (!val) return alert("Escribe qué quieres buscar.");
    payload.target = val;
    payload.cantidad = document.getElementById("batch-count").value;
  }

  statusPanel.classList.remove("hidden");
  downloadHint.classList.add("hidden");
  downloadHint.innerHTML = "";
  progressBar.style.width = "5%";
  percentText.textContent = "5%";
  statusText.textContent = "Iniciando descarga en el servidor...";

  const botones = document.querySelectorAll(".action-btn");
  botones.forEach(b => b.disabled = true);

  try {
    const res = await fetch("/start-download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (!res.ok) {
      statusText.textContent = "Error: " + data.message;
      botones.forEach(b => b.disabled = false);
      return;
    }

    const taskId = data.task_id;


    const pollInterval = setInterval(async () => {
      try {
        const progRes = await fetch(`/check-progress/${taskId}`);
        const progData = await progRes.json();

        progressBar.style.width = `${progData.percent}%`;
        percentText.textContent = `${progData.percent}%`;
        statusText.textContent = progData.status;

        if (progData.percent >= 100) {
          clearInterval(pollInterval);
          botones.forEach(b => b.disabled = false);

          if (progData.archivos && progData.archivos.length === 1) {
            const singleName = progData.archivos[0];
            const esVideo = singleName.endsWith(".mp4") || singleName.endsWith(".mkv");
            statusText.textContent = esVideo ? "¡Video 4K / HD listo!" : "¡Canción MP3 lista!";

            window.location.href = `/get-single-song/${taskId}/${encodeURIComponent(singleName)}`;

            downloadHint.innerHTML = `
              <div style="margin-top: 10px; text-align: center;">
                <p style="color:#4ade80; margin-bottom:8px;">
                  ✅ Descargando archivo <b>${singleName}</b> en tu dispositivo.
                </p>
                <a href="/get-single-song/${taskId}/${encodeURIComponent(singleName)}" 
                   style="color:#f26a1b; text-decoration:underline; font-size:0.88rem;">
                   ¿No inició la descarga? Toca aquí para reintentar
                </a>
              </div>
            `;
            downloadHint.classList.remove("hidden");

          } else if (progData.archivos && progData.archivos.length > 1) {

            statusText.textContent = `¡Se descargaron ${progData.archivos.length} archivos!`;

            let htmlLista = `
              <div style="margin-top: 14px; display: flex; flex-direction: column; gap: 8px;">
                <p style="font-size:0.85rem; color:#dfd5cb; margin-bottom:4px;">
                  📱 Toca <b>"BAJAR MP3"</b> para guardar cada tema en tu celular:
                </p>
            `;

            progData.archivos.forEach((nombre, index) => {
              const nombreLimpio = nombre.replace(".mp3", "").replace(".mp4", "");
              htmlLista += `
                <div style="display:flex; justify-content:space-between; align-items:center; background:#1b1511; border:1px solid #33261d; padding:10px 12px; border-radius:8px;">
                  <div style="display:flex; align-items:center; gap:8px; max-width:68%; overflow:hidden;">
                    <span style="color:#f26a1b; font-size:0.8rem; font-weight:bold;">#${index + 1}</span>
                    <span style="color:#f9f6f0; font-size:0.86rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                      ${nombreLimpio}
                    </span>
                  </div>
                  <a href="/get-single-song/${taskId}/${encodeURIComponent(nombre)}" 
                     style="background:rgba(242, 106, 27, 0.15); color:#f26a1b; border:1px solid #f26a1b; padding:6px 10px; border-radius:6px; text-decoration:none; font-weight:700; font-size:0.75rem;"
                     download="${nombre}">
                    BAJAR MP3
                  </a>
                </div>
              `;
            });

            if (progData.zip_file) {
              htmlLista += `
                <a href="/get-zip/${taskId}" 
                   style="margin-top:10px; text-align:center; background:linear-gradient(135deg, #d4510c, #8c2e04); color:#fff; padding:12px; border-radius:8px; text-decoration:none; font-weight:bold; font-size:0.88rem; box-shadow:0 4px 15px rgba(212,81,12,0.4);"
                   download="${progData.zip_file}">
                  📦 DESCARGAR TODO EN ZIP
                </a>
              `;
            }
            htmlLista += `</div>`;

            downloadHint.innerHTML = htmlLista;
            downloadHint.classList.remove("hidden");
          }
        }
      } catch (e) {
        clearInterval(pollInterval);
        botones.forEach(b => b.disabled = false);
      }
    }, 1000);

  } catch (error) {
    statusText.textContent = "Error de conexión con el servidor.";
    botones.forEach(b => b.disabled = false);
  }
}
