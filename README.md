# TikTok Multi-Account Automator

- Gestion de cuentas TikTok.
- Procesamiento de velocidad por cuenta antes de publicar.
- Cola de subidas.
- Historial en MySQL para evitar duplicados.

## Estructura del proyecto

- `backend/`: API, base de datos, motor de subidas y procesamiento.
- `frontend/`: UI web (HTML + CSS + JS).
- `videos/`: carpeta de entrada de archivos `.mp4` y `.mov`.
- `temp/`: archivos temporales generados durante la automatizacion.

## Requisitos

- Python 3.10+
- MySQL 8+
- Google Chrome
- FFmpeg disponible en PATH

## Instalacion

1. Crear y activar entorno virtual.

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/macOS (bash/zsh):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Instalar dependencias del backend.

```bash
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
```

3. Instalar navegador para Playwright.

```bash
python -m playwright install chrome
```

## Configuracion

Crea `backend/.env` con valores segun tu entorno:

```env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=tu_password
DB_NAME=tiktok_automator
APP_HOST=0.0.0.0
APP_PORT=8000
PLAYWRIGHT_HEADLESS=false
```

Notas:

- El backend aplica `backend/schema.sql` al iniciar.
- Asegura que tu usuario de MySQL tenga permisos para crear/usar la base.
- Si ejecutas en servidor, puedes poner `PLAYWRIGHT_HEADLESS=true`.

## Ejecutar

Desde la raiz del proyecto:

```bash
python backend/main.py
```

Accesos:

- App/UI: `http://127.0.0.1:8000/`
- Healthcheck: `http://127.0.0.1:8000/health`

## Flujo minimo de uso

1. Agrega cuentas en la pestaña de cuentas usando `chrome_user_data_dir` y `chrome_profile`.
2. Configura `videos_folder`, delays y limites diarios desde la UI.
3. Coloca videos `.mp4` o `.mov` en la carpeta configurada.
4. Inicia la subida y monitorea progreso/logs en tiempo real.

## Endpoints principales

- `GET /accounts`
- `POST /accounts`
- `PUT /accounts/{account_id}`
- `DELETE /accounts/{account_id}`
- `GET /settings`
- `POST /settings`
- `GET /videos`
- `POST /upload`
- `GET /progress`
- `POST /stop`
- `GET /history`
- `GET /health`

## Solucion de problemas rapida

- Error de Chrome perfil en uso: cierra todas las ventanas del perfil antes de automatizar.
- FFmpeg no detectado: valida con `ffmpeg -version` y revisa PATH.
- No aparecen videos: confirma extension `.mp4`/`.mov` y ruta en `videos_folder`.
- Fallos por cambios de TikTok: actualiza selectores en configuracion.

