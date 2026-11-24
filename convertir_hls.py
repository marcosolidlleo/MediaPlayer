import os
import shutil
import subprocess #Ejecutar ffmpeg
import re #Expresiones regulares
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import boto3 #Puente que nos permite subir archivos y leer carpetas en S3
import static_ffmpeg

#Descarga el ejecutable compilado de FFmpeg y lo añade al PATH del sistema al arrancar
static_ffmpeg.add_paths()

app = FastAPI(title="Servicio Streaming HLS - PaaS & AWS S3")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def servir_frontend():
    return FileResponse("index.html")

#Permitir peticiones desde tu página HTML
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], #Permite la consulta a todos los dominios
    allow_methods=["*"], #Operaciones HTTP permitidas
    allow_headers=["*"],     
)

#Las lee del panel de Render, donde estan configuradas
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "eu-north-1")
BUCKET_NAME = os.getenv("BUCKET_NAME")

#Inicializa la conexión
s3_client = boto3.client(
    service_name='s3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

PUBLIC_DOMAIN = f"https://{BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com"

def procesar_y_subir_s3(ruta_mp4_temporal: str, id_video: str):
    carpeta_hls = f"temp_hls_{id_video}"
    
    try:
        print(f"--> Iniciando procesado de '{id_video}'...")
        if not os.path.exists(carpeta_hls):
            os.makedirs(carpeta_hls)

        output_playlist = os.path.join(carpeta_hls, "index.m3u8")
        output_segment_pattern = os.path.join(carpeta_hls, "segmento_%03d.ts")

        # 1. Transcodificación HLS forzando cortes exactos cada 2 segundos
        comando = [
            "ffmpeg", "-y", "-i", ruta_mp4_temporal,
            "-vf", "scale=-2:720",
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-c:a", "aac",
            "-hls_time", "2",
            "-hls_list_size", "0",
            "-hls_segment_filename", output_segment_pattern,
            "-f", "hls", output_playlist
        ]
        
        resultado = subprocess.run(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if resultado.returncode != 0:
            print(f"--> ERROR EN FFMPEG: {resultado.stderr}")
            return

        print(f"--> FFmpeg completado. Subiendo archivos a S3 ({BUCKET_NAME})...")

        archivos = os.listdir(carpeta_hls)
        for archivo in archivos:
            ruta_local = os.path.join(carpeta_hls, archivo)
            ruta_remota = f"videos/{id_video}/{archivo}"
            content_type = "application/x-mpegURL" if archivo.endswith(".m3u8") else "video/MP2T"
            
            s3_client.upload_file(
                ruta_local,
                BUCKET_NAME,
                ruta_remota,
                ExtraArgs={'ContentType': content_type}
            )

        print(f"--> SUCCESS: ¡Vídeo '{id_video}' subido con éxito a AWS S3!")

    except Exception as e:
        print(f"--> ERROR CRÍTICO EN TAREA DE FONDO: {str(e)}")

    finally:
        #Limpia los archivos basuras
        if os.path.exists(ruta_mp4_temporal):
            #Borra .mp4 original
            os.remove(ruta_mp4_temporal)
        if os.path.exists(carpeta_hls):
            #Borra los .ts temporales de Render
            shutil.rmtree(carpeta_hls)


@app.post("/subir-video/")
async def subir_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    nombre_limpio = os.path.splitext(file.filename)[0]
    #Evita errores cambiando todo lo que no sean letras, numeros o guiones bajos, por un guion bajo
    id_video = re.sub(r'[^a-zA-Z0-9_]', '_', nombre_limpio)
    ruta_temporal = f"temp_{id_video}.mp4"

    with open(ruta_temporal, "wb") as buffer: #Crea archivo vacio en escritura binaria
        shutil.copyfileobj(file.file, buffer) #Vuelca el video (file), a ese archivo creado

    background_tasks.add_task(procesar_y_subir_s3, ruta_temporal, id_video)
    url_stream_final = f"{PUBLIC_DOMAIN}/videos/{id_video}/index.m3u8"

    return JSONResponse(
        content={
            "mensaje": "Vídeo recibido.",
            "id_video": id_video,
            "url_playlist_hls": url_stream_final
        }
    )


# 2. Nuevo endpoint para listar todos los vídeos guardados en S3
@app.get("/videos/")
async def listar_videos():
    try:
        respuesta = s3_client.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix="videos/",
            Delimiter="/"
        )
        videos = []
        for prefijo in respuesta.get("CommonPrefixes", []):
            # Extraer el nombre de la carpeta (ej: "videos/Fortnite_123/" -> "Fortnite_123")
            carpeta = prefijo.get("Prefix").rstrip("/").split("/")[-1]
            videos.append({
                "id": carpeta,
                "url": f"{PUBLIC_DOMAIN}/videos/{carpeta}/index.m3u8"
            })
        return JSONResponse(content={"videos": videos})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})