# Follower Management

Panel web privado para gestionar tu Instagram desde cualquier navegador:

- **Dejar de seguir** a quienes no te siguen de vuelta (con lista para desmarcar a quien quieras conservar).
- **Seguir seguidores** de una cuenta de interés.
- Respeta cupos por hora y por día (ventana móvil), ritmo parejo con variación aleatoria y pausa automática si Instagram pide esperar.

Stack: FastAPI + [instagrapi](https://github.com/subzeroid/instagrapi) (API privada de Instagram) · SQLite · UI en HTML/CSS/JS sin dependencias.

> **Riesgo:** Instagram no ofrece API oficial para seguir/dejar de seguir y automatizarlo va contra sus términos. Los cupos por defecto (20/h, 150/día por acción) son conservadores, pero el riesgo nunca es cero. Empieza con pocas acciones.

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `APP_PASSWORD` | sí | Contraseña de acceso al panel (≥10 caracteres) |
| `SECRET_KEY` | sí | Cadena aleatoria larga (≥32). Firma cookies y cifra la sesión de Instagram guardada |
| `DATA_DIR` | en Railway | Carpeta persistente (ruta del volumen, p. ej. `/data`) |
| `FOLLOW_PER_HOUR`, `FOLLOW_PER_DAY`, `UNFOLLOW_PER_HOUR`, `UNFOLLOW_PER_DAY` | no | Cupos (def. 20/150) |
| `IG_PROXY` | no | Proxy residencial `http://user:pass@host:port` |

Generar un `SECRET_KEY`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

## Local

```powershell
python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt
$env:APP_PASSWORD="tu-clave-larga"; $env:SECRET_KEY="<aleatoria>"
.\.venv\Scripts\python -m uvicorn app:app --port 8000
```

## Railway

1. Nuevo proyecto → *Deploy from GitHub repo* → este repositorio (usa `Procfile` y `.python-version`).
2. **Volumes** → añade un volumen montado en `/data`.
3. **Variables:** `APP_PASSWORD`, `SECRET_KEY`, `DATA_DIR=/data`.
4. **Settings → Networking → Generate Domain** (HTTPS incluido).
5. Mantén **una sola réplica** (el trabajo en curso vive en memoria).

### Conectar Instagram desde la nube

Entrar con usuario/contraseña desde la IP de un datacenter suele disparar verificaciones. Lo más fiable es la pestaña **Cookie de sesión**: inicia sesión en instagram.com desde tu navegador → F12 → *Application* → *Cookies* → copia `sessionid`. Si aun así hay bloqueos, usa `IG_PROXY` con un proxy residencial.

## Seguridad

- Panel protegido por contraseña, cookie `HttpOnly` + `Secure` + `SameSite=Strict`, bloqueo tras 5 intentos fallidos, verificación de `Origin` (anti-CSRF) y CSP estricta.
- La contraseña de Instagram **nunca se guarda**; solo la sesión, cifrada (Fernet) en `DATA_DIR`.

## Tests

```powershell
.\.venv\Scripts\pip install pytest httpx
.\.venv\Scripts\python -m pytest -q
```
