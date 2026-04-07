# TikTok Multi-Account Automator

Guia completa para dejar el sistema listo y empezar a subir videos a multiples cuentas de TikTok.

## 1. Que hace este proyecto

Esta aplicacion permite:

1. Configurar varias cuentas de TikTok.
2. Procesar velocidad de videos por cuenta con FFmpeg.
3. Subir videos de forma automatizada con Playwright usando perfiles reales de Chrome.
4. Ver progreso en tiempo real, log en vivo y resumen final.
5. Registrar historial en MySQL y evitar duplicados.

## 2. Estructura del proyecto

- backend: API FastAPI, conexion MySQL, job manager, uploader y procesamiento de video.
- frontend: interfaz web en un unico archivo HTML + CSS + JS.
- videos: carpeta de entrada de videos .mp4 y .mov.
- temp: carpeta temporal para videos procesados.

## 3. Requisitos previos

Antes de iniciar, verifica:

1. Windows con PowerShell.
2. Python 3.10 o superior.
3. Docker Desktop funcionando.
4. Contenedor MySQL activo.
5. Google Chrome instalado.
6. FFmpeg instalado y disponible en PATH.

## 4. Datos actuales de base de datos

Con la configuracion actual de este workspace:

- Contenedor MySQL: mysql_local
- Motor: mysql:8.0
- Host desde tu maquina: 127.0.0.1
- Puerto: 3306
- Usuario: root
- Password: password
- Base: tiktok_automator

## 5. Paso a paso de instalacion completa

## Paso 1. Entrar al proyecto

```powershell
cd C:\Users\dev\Desktop\TikTokAutomator
```

## Paso 2. Verificar que MySQL Docker este arriba

```powershell
docker ps
docker port mysql_local
```

Debes ver el puerto 3306 publicado al host.

Si el contenedor esta detenido:

```powershell
docker start mysql_local
```

## Paso 3. Crear y activar entorno virtual (si no existe)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si ya tienes .venv, solo activalo.

## Paso 4. Instalar dependencias Python

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

## Paso 5. Instalar navegador para Playwright

```powershell
.\.venv\Scripts\python.exe -m playwright install chrome
```

## Paso 6. Instalar FFmpeg

Opcion recomendada con winget:

```powershell
winget install --id Gyan.FFmpeg -e
```

Opcion con Chocolatey:

```powershell
choco install ffmpeg -y
```

Verifica instalacion:

```powershell
ffmpeg -version
```

Si no se reconoce el comando, cierra y abre terminal, o agrega FFmpeg al PATH manualmente.

## Paso 7. Configurar variables de entorno

Archivo: backend/.env

```env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=password
DB_NAME=tiktok_automator
APP_HOST=0.0.0.0
APP_PORT=8000
PLAYWRIGHT_HEADLESS=false
```

Notas:

1. PLAYWRIGHT_HEADLESS=false ayuda en pruebas porque ves el navegador.
2. Si ejecutas backend dentro de Docker y quieres resolver por nombre de contenedor, usa backend/.env.docker como referencia.

## Paso 8. Inicializar esquema de base de datos

Desde la raiz del proyecto:

```powershell
Get-Content -Raw backend\schema.sql | docker exec -i mysql_local mysql -uroot -ppassword
```

Esto crea:

1. Base tiktok_automator.
2. Tabla accounts.
3. Tabla upload_history.
4. Tabla settings con valores iniciales.

## Paso 9. Levantar backend

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Backend listo en:

- http://127.0.0.1:8000

## Paso 10. Abrir la interfaz web

En navegador:

- http://127.0.0.1:8000/static/index.html

## 6. Como conectar cuentas de TikTok correctamente

Cada cuenta debe usar un perfil distinto de Chrome con sesion ya iniciada en TikTok.

## Paso 1. Preparar cada perfil

1. Abre Chrome con un perfil.
2. Inicia sesion en TikTok con esa cuenta.
3. En esa misma ventana, abre chrome://version.
4. Copia el valor de Profile Path.

Ejemplo de Profile Path:

- C:\Users\dev\AppData\Local\Google\Chrome\User Data\Profile 1

Con eso obtienes:

1. chrome_user_data_dir: C:\Users\dev\AppData\Local\Google\Chrome\User Data
2. chrome_profile: Profile 1

## Paso 2. Registrar la cuenta en la UI

En la pestaña Cuentas:

1. Nombre: etiqueta descriptiva, por ejemplo Cuenta Principal.
2. Ruta User Data Chrome: pega chrome_user_data_dir.
3. Perfil de Chrome: pega chrome_profile exacto.
4. Velocidad: usa 1.0, 1.1 o 1.2.
5. Estado inicial: Activa.
6. Clic en Agregar Cuenta.

Repite para cada cuenta.

## Paso 3. Regla importante

Durante la subida automatica, cierra Chrome en esos perfiles. Si un perfil esta en uso, Playwright puede fallar por bloqueo.

## 7. Como configurar el proyecto desde la UI

Abre pestaña Configuracion y define:

1. Hashtags globales.
2. Plantilla descripcion, por ejemplo: {title} {hashtags}.
3. Carpeta videos.
4. Delay entre subidas, recomendado 20 a 40 segundos.
5. Max diarios por cuenta, recomendado 15.
6. Selectores TikTok si la plataforma cambia.

Campos de selectores importantes:

1. tiktok_file_input_selector
2. tiktok_description_selector
3. tiktok_upload_button_selector
4. tiktok_success_selector
5. tiktok_captcha_selector

Despues clic en Guardar Configuracion.

## 8. Como preparar videos para subir

## Opcion A. Carpeta por defecto

Copia videos .mp4 o .mov a:

- C:\Users\dev\Desktop\TikTokAutomator\videos

## Opcion B. Carpeta personalizada

1. Cambia videos_folder en la seccion Configuracion.
2. Guarda cambios.
3. Verifica en Panel Principal que aparezca el contador de videos.

## 9. Primera subida real paso a paso

1. Verifica API conectada en la parte superior de la interfaz.
2. Revisa que haya cuentas activas.
3. Revisa que haya videos detectados.
4. En Panel Principal, clic en INICIAR SUBIDA.
5. Observa progreso, tiempo, tarjetas por cuenta y log en vivo.
6. Espera resumen final al terminar.

## 10. Estados del proceso

El sistema puede marcar cada operacion como:

1. success: subida exitosa.
2. failed: fallo definitivo.
3. skipped: omitido por duplicado o limite diario.

El boton principal cambia automaticamente:

1. INICIAR SUBIDA.
2. SUBIDA EN PROGRESO...
3. REINTENTAR FALLIDAS cuando hubo errores.

## 11. Duplicados y reintentos

1. Antes de subir, se valida si ese video ya fue subido con exito en esa cuenta.
2. Si ya existe, se omite automaticamente.
3. Si hay error de red o timeout, se reintenta hasta 3 intentos.
4. Si aparece captcha, el proceso solicita detener y resolver manualmente.

## 12. Historial y auditoria

En la pestaña Historial puedes filtrar por:

1. Cuenta.
2. Fecha inicio.
3. Fecha fin.
4. Limite de resultados.

## 13. Comandos utiles de verificacion

## Ver salud de API

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method GET
```

## Ver cuentas

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/accounts" -Method GET
```

## Ver configuracion

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/settings" -Method GET
```

## Ver videos detectados

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/videos" -Method GET
```

## Ver progreso

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/progress?since=0" -Method GET
```

## 14. Solucion de problemas comunes

## Error: no se puede abrir perfil Chrome

Solucion:

1. Cierra todas las ventanas de Chrome de ese perfil.
2. Reintenta.

## Error: ffmpeg no esta disponible

Solucion:

1. Instala FFmpeg.
2. Confirma ffmpeg -version.
3. Reinicia terminal.

## Error: no hay videos

Solucion:

1. Verifica extension .mp4 o .mov.
2. Verifica carpeta en videos_folder.
3. Recarga en UI.

## Error: MySQL no conecta

Solucion:

1. Verifica docker ps.
2. Verifica DB_HOST, DB_PORT, DB_USER, DB_PASSWORD en backend/.env.
3. Verifica puerto publicado con docker port mysql_local.

## Error: cambios de TikTok en botones o campos

Solucion:

1. Actualiza selectores en la seccion Configuracion.
2. Guarda y prueba de nuevo.

## 15. Flujo recomendado diario

1. Arrancar MySQL Docker.
2. Arrancar backend.
3. Abrir UI.
4. Revisar cuentas activas.
5. Cargar videos.
6. Iniciar subida.
7. Revisar resumen final e historial.

## 16. Endpoints disponibles

1. GET /accounts
2. POST /accounts
3. PUT /accounts/{id}
4. DELETE /accounts/{id}
5. GET /settings
6. POST /settings
7. GET /videos
8. POST /upload
9. GET /progress
10. POST /stop
11. GET /history
12. GET /health

## 17. Checklist rapido de inicio

Antes de tu primera corrida real, confirma todo esto:

1. MySQL docker activo.
2. backend/.env correcto.
3. Schema cargado.
4. FFmpeg instalado y visible por terminal.
5. Playwright Chrome instalado.
6. Cuentas de TikTok con sesion iniciada en perfiles separados.
7. Chrome cerrado al momento de automatizar.
8. Videos .mp4 o .mov en la carpeta correcta.
9. API en estado ok.
10. UI detecta videos y cuentas.

Con esto ya puedes iniciar subidas multi-cuenta de forma estable.

