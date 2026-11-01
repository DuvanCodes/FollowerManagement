import hmac
import os
import random
import threading
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from instagrapi.exceptions import (BadPassword, ChallengeRequired, FeedbackRequired, LoginRequired,
                                   PleaseWaitFewMinutes, RateLimitError, TwoFactorRequired)
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

import ig
import limits

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if len(APP_PASSWORD) < 10 or len(SECRET_KEY) < 32:
    raise RuntimeError("Define APP_PASSWORD (>=10 caracteres) y SECRET_KEY (>=32 caracteres aleatorios).")

BASE = Path(__file__).parent
SECURE = "RAILWAY_ENVIRONMENT" in os.environ or os.environ.get("COOKIE_SECURE") == "1"

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=SECURE, same_site="strict",
                   max_age=7 * 86400)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
ig.restore()


@app.middleware("http")
async def guard(request: Request, call_next):
    # CSRF: toda petición que cambia estado debe venir de nuestro propio origen
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        if not origin or urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Origen no permitido"}, 403)
    resp = await call_next(request)
    resp.headers.update({
        "Content-Security-Policy": "default-src 'self'; img-src https: data:; frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    })
    return resp


def authed(request: Request):
    if not request.session.get("ok"):
        raise HTTPException(401, "No autenticado")


def ig_ready(_=Depends(authed)):
    if not ig.cl:
        raise HTTPException(409, "Conecta primero tu cuenta de Instagram")


# ---------- acceso a la app ----------
fails = {}  # ip -> (intentos, bloqueado_hasta)  # ponytail: en memoria; Redis si hay varias instancias


class Password(BaseModel):
    password: str = Field(max_length=200)


@app.post("/api/auth/login")
def auth_login(body: Password, request: Request):
    ip = request.client.host
    n, until = fails.get(ip, (0, 0))
    if until > time.time():
        raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")
    if hmac.compare_digest(body.password.encode(), APP_PASSWORD.encode()):
        fails.pop(ip, None)
        request.session["ok"] = True
        return {"ok": True}
    fails[ip] = (0, time.time() + 900) if n + 1 >= 5 else (n + 1, 0)
    raise HTTPException(401, "Contraseña incorrecta")


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}


# ---------- Instagram ----------
class IGLogin(BaseModel):
    username: str = Field("", max_length=64)
    password: str = Field("", max_length=200)
    code: str = Field("", max_length=12)
    sessionid: str = Field("", max_length=500)


def ig_error(e):
    """Traduce una excepción de Instagram a (mensaje, ¿detener todo?) y activa el enfriamiento."""
    if isinstance(e, (PleaseWaitFewMinutes, RateLimitError)):
        limits.set_cooldown(3600)
        return "Instagram pidió esperar. Acciones pausadas 1 hora.", True
    if isinstance(e, (FeedbackRequired, ChallengeRequired)):
        limits.set_cooldown(86400)
        return "Instagram detectó actividad inusual. Pausado 24 h; revisa la app de Instagram.", True
    if isinstance(e, LoginRequired):
        ig.logout()
        return "La sesión de Instagram expiró. Vuelve a conectar la cuenta.", True
    return f"{type(e).__name__}: {e}"[:200], False


@app.post("/api/ig/login", dependencies=[Depends(authed)])
def ig_login(b: IGLogin):
    try:
        if b.sessionid:
            ig.login_sessionid(b.sessionid.strip())
        elif b.username and b.password:
            ig.login(b.username.strip().lstrip("@"), b.password, b.code.strip())
        else:
            raise HTTPException(422, "Indica usuario y contraseña, o un sessionid")
    except TwoFactorRequired:
        return JSONResponse({"detail": "Ingresa el código de verificación en dos pasos", "need_code": True}, 401)
    except BadPassword:
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    except ChallengeRequired:
        raise HTTPException(401, "Instagram pidió verificar este acceso. Usa la opción «Cookie de sesión».")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, ig_error(e)[0])
    return {"ok": True}


@app.post("/api/ig/logout", dependencies=[Depends(authed)])
def ig_logout():
    ig.logout()
    return {"ok": True}


class Analyze(BaseModel):
    username: str = Field("", pattern=r"^[A-Za-z0-9._]{0,30}$")
    amount: int = Field(100, ge=1, le=300)


@app.post("/api/analyze/unfollow", dependencies=[Depends(ig_ready)])
def analyze_unfollow():
    try:
        return ig.non_followers()
    except Exception as e:
        raise HTTPException(502, ig_error(e)[0])


@app.post("/api/analyze/follow", dependencies=[Depends(ig_ready)])
def analyze_follow(b: Analyze):
    if not b.username:
        raise HTTPException(422, "Indica la cuenta de la que quieres seguir a los seguidores")
    try:
        return ig.follower_candidates(b.username, b.amount)
    except Exception as e:
        raise HTTPException(502, ig_error(e)[0])


# ---------- trabajos en segundo plano ----------
job = {"kind": None, "status": "idle", "total": 0, "done": 0, "failed": 0, "resume_at": None, "log": []}
stop = threading.Event()
thread = None


def log(msg):
    job["log"].append({"t": time.time(), "m": msg})
    del job["log"][:-60]


def run(kind, targets):
    call = {"follow": "user_follow", "unfollow": "user_unfollow"}[kind]
    final, errors = "done", 0
    for t in targets:
        while not stop.is_set() and (w := limits.wait_seconds(kind)) > 0:
            job.update(status="waiting", resume_at=time.time() + w)
            stop.wait(min(w, 5))
        if stop.is_set():
            final = "stopped"
            break
        job.update(status="running", resume_at=None)
        try:
            with ig.lock:
                getattr(ig.cl, call)(int(t.pk))
        except Exception as e:
            msg, fatal = ig_error(e)
            log(f"@{t.username}: {msg}")
            job["failed"] += 1
            errors += 1
            if fatal or errors >= 3:
                final = "error"
                break
        else:
            limits.record(kind, t.pk)
            job["done"] += 1
            errors = 0
            log(("Seguido" if kind == "follow" else "Dejado de seguir") + f" @{t.username}")
        # ritmo parejo (no ráfagas): ~ una acción cada 3600/cupo_hora segundos, con variación aleatoria
        stop.wait(random.uniform(0.7, 1.3) * 3600 / limits.LIMITS[kind][0])
    job.update(status=final, resume_at=None)


class Target(BaseModel):
    pk: str = Field(pattern=r"^\d{1,20}$")
    username: str = Field(max_length=64)


class Start(BaseModel):
    kind: Literal["follow", "unfollow"]
    targets: list[Target] = Field(min_length=1, max_length=500)


@app.post("/api/job/start", dependencies=[Depends(ig_ready)])
def job_start(b: Start):
    global thread
    if thread and thread.is_alive():
        raise HTTPException(409, "Ya hay un trabajo en curso")
    if (cd := limits.cooldown_until() - time.time()) > 0:
        raise HTTPException(409, f"Instagram pidió una pausa; vuelve en {int(cd // 60) + 1} min")
    targets = list({t.pk: t for t in b.targets}.values())
    if b.kind == "follow":
        targets = [t for t in targets if not limits.already_followed(t.pk)]
    stop.clear()
    job.update(kind=b.kind, status="running", total=len(targets), done=0, failed=0, resume_at=None, log=[])
    thread = threading.Thread(target=run, args=(b.kind, targets), daemon=True)
    thread.start()
    return {"ok": True}


@app.post("/api/job/stop", dependencies=[Depends(authed)])
def job_stop():
    stop.set()
    return {"ok": True}


@app.get("/api/state")
def state(request: Request):
    if not request.session.get("ok"):
        return {"auth": False}
    return {
        "auth": True,
        "ig": ig.username,
        "usage": {k: limits.usage(k) for k in limits.LIMITS},
        "cooldown": max(0, limits.cooldown_until() - time.time()),
        "job": job,
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
