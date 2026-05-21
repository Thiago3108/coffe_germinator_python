# Germinador IoT — Backend FastAPI

API REST para el germinador de semillas de café con ESP32-S3.

## Características

- Recibe telemetría del ESP32 (temperatura, humedad ambiente, 4 sensores de
  suelo, luz, pH, nivel de agua, estado de actuadores).
- Sirve estado actual e histórico para la app Android.
- Gestiona setpoints de control (umbrales) configurables remotamente.
- Modo manual (overrides) para forzar bomba / ventilador / luz.
- Genera alertas automáticas (tanque vacío, temperatura alta, sensor caído,
  bomba prolongada) con cooldown anti-spam.
- Autenticación con token compartido (`X-Device-Token`).

Documentación interactiva: `/docs`

## Estructura del repositorio

```
.
├── main.py             # toda la API
├── requirements.txt    # dependencias
├── runtime.txt         # versión de Python
├── render.yaml         # configuración Render
├── configuracion.txt   # guía de uso local
├── .env.example        # plantilla de variables de entorno
└── .gitignore
```

## Despliegue en Render.com

### 1. Subir el código a GitHub

Desde la carpeta del proyecto:

```bash
git init
git add .
git commit -m "Backend germinador IoT"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/germinador-backend.git
git push -u origin main
```

> Verifica antes que tu `.gitignore` excluya `.env`, `.venv/` y `*.db`.

### 2. Crear el servicio en Render

1. Entra a https://render.com (login con GitHub).
2. **New +** → **Web Service**.
3. Conecta el repositorio recién creado.
4. Render detecta `render.yaml` y rellena casi todo. Si no:
   - **Runtime**: Python
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free
5. En **Environment variables**, agrega manualmente:
   - `API_TOKEN` = el mismo token que tienes en `secrets.h` del ESP32 y
     `local.properties` del Android (`116d…17d9` en nuestro caso).
6. **Create Web Service** → espera ~3 minutos.

### 3. Obtener la URL pública

Render te asigna una URL del tipo:

```
https://germinador-iot.onrender.com
```

Verifica que funciona:

```bash
curl https://germinador-iot.onrender.com/health
# {"status": "ok", "timestamp": "..."}
```

### 4. Apuntar el ESP32 y la app a esa URL

- **ESP32** (`secrets.h`):
  ```cpp
  #define SERVER_BASE "https://germinador-iot.onrender.com"
  ```
  Re-flashear.

- **Android** (`local.properties`):
  ```
  BASE_URL=https://germinador-iot.onrender.com/
  ```
  Rebuild + reinstalar APK.

## Limitaciones del Free Tier

- El servicio se duerme tras 15 min sin tráfico — el primer request al
  despertar tarda ~30 s. Con el ESP32 enviando cada 10 s, nunca se duerme.
- SQLite es efímero: el archivo `germinador.db` vive en el disco efímero
  del contenedor. Si Render reinicia el servicio (cada cierto tiempo o por
  deploy), los datos históricos se pierden. Los setpoints se reinicializan
  con sus defaults gracias a `_bootstrap_setpoints()`.
- Para histórico persistente: migrar a PostgreSQL gratis en
  https://neon.tech y cambiar `DATABASE_URL` en las env vars de Render.

## Desarrollo local

Ver `configuracion.txt`.
