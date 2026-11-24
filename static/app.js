const API_URL = "https://mediaplayer-fn8h.onrender.com";
const videoElement = document.getElementById('reproductor');
let hls = null;

// Función para cargar y reproducir un stream HLS (.m3u8)
function reproducirVideo(url, titulo) {
    document.getElementById('titulo-actual').innerText = "Reproduciendo: " + titulo;

    if (Hls.isSupported()) {
        if (hls) hls.destroy();
        hls = new Hls();
        hls.loadSource(url);
        hls.attachMedia(videoElement);
        hls.on(Hls.Events.MANIFEST_PARSED, () => videoElement.play());
    } else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
        videoElement.src = url;
        videoElement.addEventListener('loadedmetadata', () => videoElement.play());
    }
}

// Función para consultar el bucket S3 a través de FastAPI
async function cargarGaleria() {
    const galeria = document.getElementById('galeria');
    galeria.innerHTML = "Consultando AWS S3...";
    try {
        const res = await fetch(`${API_URL}/videos/`);
        const data = await res.json();

        if (!data.videos || data.videos.length === 0) {
            galeria.innerHTML = "<p>Aún no hay vídeos procesados en S3.</p>";
            return;
        }

        galeria.innerHTML = "";
        data.videos.forEach(vid => {
            const card = document.createElement('div');
            card.className = 'video-item';

            const title = document.createElement('div');
            title.className = 'video-title';
            title.textContent = `🎞️ ${vid.id}`;

            const playButton = document.createElement('button');
            playButton.textContent = '▶ Ver vídeo';
            playButton.addEventListener('click', () => reproducirVideo(vid.url, vid.id));

            card.append(title, playButton);
            galeria.appendChild(card);
        });
    } catch (err) {
        galeria.innerHTML = '<p class="error-message">Error al conectar con Render (puede estar despertando, pulsa Actualizar en 30s).</p>';
    }
}

// Función para enviar un MP4 al backend
async function subirVideo() {
    const input = document.getElementById('archivo-video');
    const estado = document.getElementById('estado');
    const btn = document.getElementById('btn-subir');

    if (!input.files.length) {
        alert("Por favor, selecciona un archivo .mp4 primero.");
        return;
    }

    const formData = new FormData();
    formData.append("file", input.files[0]);

    btn.disabled = true;
    estado.innerText = "⏳ Subiendo archivo a Render (si el servidor estaba dormido puede tardar ~40s)...";

    try {
        const res = await fetch(`${API_URL}/subir-video/`, {
            method: "POST",
            body: formData
        });
        const data = await res.json();

        estado.innerHTML = `✅ <strong>${data.mensaje}</strong><br>Espera unos 15-20 segundos a que FFmpeg termine de subirlo a S3 y pulsa <em>"Actualizar lista"</em>.`;
        input.value = "";
    } catch (err) {
        estado.innerHTML = '<span class="error-message">❌ Error al subir el vídeo. Revisa la conexión con Render.</span>';
    } finally {
        btn.disabled = false;
    }
}

document.getElementById('btn-subir').addEventListener('click', subirVideo);
document.getElementById('btn-actualizar').addEventListener('click', cargarGaleria);

// Cargar la lista automáticamente al abrir la página
cargarGaleria();