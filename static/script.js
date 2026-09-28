document.addEventListener("DOMContentLoaded", () => {
    const inputTarget = document.getElementById("target");
    const btnDownload = document.getElementById("btn-download");
    const progressBox = document.getElementById("progress-box");
    const progressBar = document.getElementById("progress-bar");
    const progressStatus = document.getElementById("progress-status");
    const selectType = document.getElementById("tipo");

    if (!btnDownload) return;

    btnDownload.addEventListener("click", async () => {
        const target = inputTarget.value.trim();
        const tipo = selectType ? selectType.value : "link";

        if (!target) {
            alert("Por favor, ingresa un enlace de YouTube.");
            return;
        }

        progressBox.style.display = "block";
        progressBar.style.width = "30%";
        progressStatus.textContent = "Obteniendo archivo multimedia...";

        try {
            const res = await fetch("/start-download", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ tipo: tipo, target: target })
            });

            const data = await res.json();

            if (data.status === "ok" && data.direct_url) {
                progressBar.style.width = "100%";
                progressStatus.textContent = "¡Descarga lista! Iniciando transferencia...";

                // Descarga directa en el navegador
                const a = document.createElement("a");
                a.href = data.direct_url;
                a.download = data.filename || "audio.mp3";
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);

                setTimeout(() => {
                    progressStatus.textContent = "¡Descarga completada con éxito!";
                }, 1500);
            } else {
                progressBar.style.width = "0%";
                progressStatus.textContent = "Error: " + (data.message || "No se pudo procesar.");
            }
        } catch (err) {
            progressBar.style.width = "0%";
            progressStatus.textContent = "Error de red al conectar con el servidor.";
        }
    });
});
