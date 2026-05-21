# 🚀 Guía de despliegue — Germinador IoT

Documento paso a paso para llevar el proyecto a producción **gratis**:

- **Backend** → Render.com
- **ESP32** → físico en tu casa, apuntando al backend remoto (HTTPS)
- **App Android** → APK que puedes compartir con tu docente

Tiempo total estimado: **45 minutos**.

---

## 📋 Pre-requisitos

- [ ] Cuenta de GitHub (https://github.com/signup)
- [ ] Cuenta de Render — entra con tu GitHub (https://render.com)
- [ ] Git instalado en Windows — descarga: https://git-scm.com/download/win
- [ ] Arduino IDE con soporte ESP32-S3 instalado
- [ ] Android Studio abierto con el proyecto

---

## A) Backend → Render.com

### A.1. Preparar el código

Abre PowerShell en la carpeta del backend:

```powershell
cd "C:\Users\Santiago Martinez\OneDrive\Escritorio\coffe_germinator_python"
```

Verifica que estos archivos existan (todos deberían estar listos):

```powershell
ls
# Deberías ver:
# main.py, requirements.txt, runtime.txt, render.yaml
# README.md, configuracion.txt, .env.example, .gitignore
```

**Importante**: confirma que `.gitignore` esté excluyendo `.env`, `.venv` y `*.db`:

```powershell
cat .gitignore
```

### A.2. Inicializar Git y subir a GitHub

1. En tu navegador, ve a https://github.com/new
2. Nombre del repo: `germinador-backend` (o el que quieras)
3. **Visibility**: Public (más simple) o Private (con Render free también funciona)
4. **NO marques** "Initialize with README" — ya tenemos uno
5. Click **Create repository**

GitHub te muestra una URL del tipo `https://github.com/TU_USUARIO/germinador-backend.git`.
Copia esa URL.

Volviendo a PowerShell:

```powershell
git init
git add .
git commit -m "Backend germinador IoT - versión inicial"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/germinador-backend.git
git push -u origin main
```

Si te pide credenciales, ingresa usuario GitHub + token personal (no contraseña).
Para crear un token: https://github.com/settings/tokens → Generate new token (classic) → marca `repo`.

### A.3. Crear el servicio en Render

1. Ve a https://dashboard.render.com
2. Click **New +** (arriba a la derecha) → **Web Service**
3. **Connect a repository** → autoriza Render para ver tus repos de GitHub
4. Selecciona `germinador-backend`
5. Render detecta `render.yaml` y rellena la configuración automáticamente:
   - **Name**: germinador-iot
   - **Runtime**: Python
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free
6. Si Render NO detecta el `render.yaml`, completa esos campos manualmente.

### A.4. Configurar variables de entorno

Antes de crear el servicio, baja hasta la sección **Environment Variables** y añade:

| Key | Value |
|---|---|
| `API_TOKEN` | `116d0dd2562a8edc9a4e922a062c2b025d25241c9c560ac92a937475b4fb17d9` |
| `CORS_ORIGINS` | (déjalo vacío) |
| `DATABASE_URL` | `sqlite:///./germinador.db` |

Click **Create Web Service**.

### A.5. Esperar el primer deploy

Render compila y arranca el servicio. Verás logs en vivo:

```
==> Installing dependencies
==> Build successful
==> Starting service with 'uvicorn main:app --host 0.0.0.0 --port $PORT'
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:10000
INFO:     germinador: Setpoints inicializados con valores por defecto.
```

Cuando veas el último log, anota la URL pública que aparece arriba del panel,
del tipo:

```
https://germinador-iot.onrender.com
```

### A.6. Verificar que el backend responde

Desde tu PowerShell local:

```powershell
curl https://germinador-iot.onrender.com/health
```

Esperado:
```json
{"status":"ok","timestamp":"2026-05-20T..."}
```

Probar con token:
```powershell
curl https://germinador-iot.onrender.com/api/setpoints `
     -H "X-Device-Token: 116d0dd2562a8edc9a4e922a062c2b025d25241c9c560ac92a937475b4fb17d9"
```

Esperado: JSON con los setpoints por defecto.

✅ **Backend desplegado.**

---

## B) ESP32 → apuntar al backend remoto

### B.1. Editar `secrets.h`

Abre `coffe_germinator_esp32/secrets.h` y cambia `SERVER_BASE`:

```cpp
// Antes:
// #define SERVER_BASE  "http://192.168.1.53:8001"

// Después (usa TU URL real de Render):
#define SERVER_BASE  "https://germinador-iot.onrender.com"
```

El firmware detecta automáticamente que es HTTPS y usa `WiFiClientSecure`.
No hay que cambiar nada más.

### B.2. Re-flashear

En Arduino IDE: **Sketch → Upload**.

En el Serial Monitor (115200 baud) debes ver:

```
[WiFi] OK
[WiFi] IP local: 192.168.1.XXX
[Sistema] Modo conexión: HTTPS
[HTTP POST] 201
[Setpoints] T_min=20.0 Vent[25.0/23.5] ...
```

> ⚠️ **El primer POST puede tardar hasta 30 segundos** si el servicio Render
> estaba dormido. A partir de ahí responde en <1s.

✅ **ESP32 enviando telemetría al backend remoto.**

---

## C) App Android → APK para el docente

### C.1. Editar `local.properties`

Abre `coffee_germinator/local.properties` y cambia `BASE_URL`:

```properties
# Antes:
# BASE_URL=http://192.168.1.53:8001/

# Después:
BASE_URL=https://germinador-iot.onrender.com/

# (API_TOKEN se queda igual)
API_TOKEN=116d0dd2562a8edc9a4e922a062c2b025d25241c9c560ac92a937475b4fb17d9
```

### C.2. Generar el APK firmado (debug es suficiente para la demo)

```powershell
cd "C:\Users\Santiago Martinez\OneDrive\Escritorio\coffee_germinator"
.\gradlew clean
.\gradlew assembleDebug
```

El APK queda en:

```
coffee_germinator\app\build\outputs\apk\debug\app-debug.apk
```

### C.3. Compartir el APK con el docente

Tres opciones según prefieras:

**Opción 1 — Por mensaje directo (recomendado)**: súbelo a Google Drive,
WhatsApp Web, Telegram, etc., y le pasas el link.

**Opción 2 — Súbelo al repo de GitHub** como release:
```powershell
git tag v1.0
git push origin v1.0
```
Luego en GitHub → Releases → Draft a new release → adjunta el APK.

**Opción 3 — Servirlo desde Render**: NO recomendado en free tier
(consume bandwidth innecesario).

### C.4. Instrucciones para el docente

Cuando le pases el APK, agrega esta nota:

> 1. En el celular Android, abre el archivo `app-debug.apk` recibido.
> 2. Si Android avisa "Instalar apps desconocidas" → Permitir desde
>    la app desde la que descargó el archivo (WhatsApp, navegador, etc.).
> 3. Abre la app "coffee_germinator" instalada.
> 4. Cuando aparezca el diálogo "Permitir notificaciones" → Aceptar.
> 5. El dashboard muestra los datos en tiempo real del germinador remoto.
> 6. Los íconos del TopBar son: Refresh, Alertas, Histórico, Modo Manual,
>    Setpoints.

✅ **Sistema completo desplegado.**

---

## 🧪 Verificación final

Con el ESP32 enchufado y enviando, el docente debería poder:

| Cosa que probar | Cómo verificarlo |
|---|---|
| Ver telemetría en tiempo real | Dashboard muestra T, humedad, etc. y se actualiza cada 5s |
| Ver histórico | Tap en 📈 → selecciona 1h/6h/24h |
| Cambiar setpoints | Tap en ⚙ → mueve sliders → Guardar. El ESP32 los aplica en ≤30s |
| Modo manual | Tap en ✋ → fuerza ventilador ON → el ESP32 lo enciende en ≤10s |
| Ver alertas | Tap en 🔔 — si alguna sensor falla o tanque está bajo, aparece aquí |
| Notificación push | Drop nivel agua bajo umbral → en ≤15 min llega push al celular |

---

## 🐛 Problemas comunes

### "Sin conexión con el servidor" en la app

1. Verifica que el backend respondió `200` a `/health` con `curl`.
2. Si el servicio estaba dormido, espera 30s y vuelve a abrir la app.
3. Confirma que `BASE_URL` en `local.properties` tenga **https** y la URL exacta.
4. Si modificaste `local.properties`, hay que **rebuild** del APK (`gradlew clean assembleDebug`).

### El ESP32 muestra `[HTTP POST] -1`

1. Confirma que el SSID/contraseña en `secrets.h` son correctos.
2. Confirma que `SERVER_BASE` usa **https://** (con HTTP plano contra Render no funciona).
3. Si Render estaba dormido, el primer request tarda hasta 30s. Comprueba unos
   3 ciclos antes de asumir que hay un problema.

### El histórico aparece vacío después de un día

Eso es esperable en free tier — Render reinicia el servicio cada cierto tiempo
y la DB SQLite vive en disco efímero. Para histórico persistente, ver la sección
sobre Neon.tech en `README.md`.

### Render dice "Build failed: ModuleNotFoundError"

Verifica que `requirements.txt` esté en UTF-8 (no UTF-16) y todas las dependencias
listadas. Si abres el archivo y ves espacios extraños entre letras, es UTF-16.
Recréalo con: `Set-Content requirements.txt -Encoding UTF8 -Value (cat requirements.txt)`.

---

## 🔐 Notas de seguridad

- El `API_TOKEN` actual ya pasó por chats; es **suficiente** para esta demo pero
  no es seguro para producción real. Después de la entrega, rótalo:
  ```powershell
  -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
  ```
  Y actualiza los 3 lados (`secrets.h`, env var en Render, `local.properties`).

- El firmware ESP32 usa `setInsecure()` en `WiFiClientSecure` — acepta cualquier
  cert TLS sin validar. Suficiente para demo pero no para producción. Para
  endurecer, incluir el cert root de Let's Encrypt e usar `setCACert()`.

- En Render, el `API_TOKEN` se configura como variable de entorno (no en el
  repo). El repo se mantiene público sin filtrar secretos.
