import os
import shutil
import subprocess
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse
import boto3

app = FastAPI(title="Servicio Streaming HLS - PaaS & AWS S3")

# Leer las credenciales cargadas desde las variables de entorno de Render
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "eu-north-1")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# Cliente de AWS S3
s3_client = boto3.client(
    service_name='s3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

# Dominio público para acceder a los archivos alojados en S3
PUBLIC_DOMAIN = f"https://{BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com"

def procesar_y_subir_s3(ruta_mp4_temporal: str, id_video: str):
    """
    Trocea el vídeo a formato HLS (.m3u8 y .ts) en el servidor de Render,
    sube los archivos a AWS S3 y limpia los temporales.
    """
    carpeta_hls = f"temp_hls_{id_video}"
    
    try:
        if not os.path.exists(carpeta_hls):
            os.makedirs(carpeta_hls)

        output_playlist = os.path.join(carpeta_hls, "index.m3u8")
        output_segment_pattern = os.path.join(carpeta_hls, "segmento_%03d.ts")

        # 1. Transcodificación HLS con FFmpeg
        comando = [
            "ffmpeg", "-i", ruta_mp4_temporal,
            "-c:v", "libx264", "-c:a", "aac",
            "-hls_time", "4",
            "-hls_list_size", "0",
            "-hls_segment_filename", output_segment_pattern,
            "-f", "hls", output_playlist
        ]
        subprocess.run(comando, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 2. Subida de la lista de reproducción y fragmentos a Amazon S3
        for archivo in os.listdir(carpeta_hls):
            ruta_local = os.path.join(carpeta_hls, archivo)
            ruta_remota = f"videos/{id_video}/{archivo}"
            
            # Content-Type necesario para la reproducción HTTP correcta
            content_type = "application/x-mpegURL" if archivo.endswith(".m3u8") else "video/MP2T"
            
            s3_client.upload_file(
                ruta_local,
                BUCKET_NAME,
                ruta_remota,
                ExtraArgs={'ContentType': content_type}
            )

        print(f"¡Vídeo '{id_video}' procesado y subido con éxito a AWS S3!")

    except Exception as e:
        print(f"Error durante el procesado o subida: {str(e)}")

    finally:
        # 3. Limpieza de archivos temporales del disco del servidor
        if os.path.exists(ruta_mp4_temporal):
            os.remove(ruta_mp4_temporal)
        if os.path.exists(carpeta_hls):
            shutil.rmtree(carpeta_hls)


@app.post("/subir-video/")
async def subir_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Endpoint HTTP POST: Recibe el MP4 y dispara el proceso en segundo plano.
    """
    id_video = os.path.splitext(file.filename)[0].replace(" ", "_")
    ruta_temporal = f"temp_{file.filename}"

    with open(ruta_temporal, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Añadir la tarea asíncrona
    background_tasks.add_task(procesar_y_subir_s3, ruta_temporal, id_video)
    
    url_stream_final = f"{PUBLIC_DOMAIN}/videos/{id_video}/index.m3u8"

    return JSONResponse(
        content={
            "mensaje": "Vídeo recibido correctamente. Procesando HLS y subiendo a AWS S3...",
            "id_video": id_video,
            "url_playlist_hls": url_stream_final
        }
    )