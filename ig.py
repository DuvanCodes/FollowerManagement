"""Cliente de Instagram (instagrapi): login, sesión cifrada en disco y consultas."""
import base64
import hashlib
import json
import os
import threading

from cryptography.fernet import Fernet
from instagrapi import Client

import limits

FILE = os.path.join(limits.DATA, "session.bin")
lock = threading.Lock()  # el cliente no es thread-safe: una llamada a la vez
cl = None
username = None


def _fernet():
    key = hashlib.sha256(os.environ["SECRET_KEY"].encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _new():
    c = Client()
    c.delay_range = [2, 5]  # pausa aleatoria entre requests internos
    if os.environ.get("IG_PROXY"):
        c.set_proxy(os.environ["IG_PROXY"])
    return c


def _save():
    os.makedirs(limits.DATA, exist_ok=True)
    blob = json.dumps({"username": username, "settings": cl.get_settings()}).encode()
    with open(FILE, "wb") as f:
        f.write(_fernet().encrypt(blob))


def login(user, password, code=""):
    """Lanza instagrapi.exceptions.TwoFactorRequired si falta el código 2FA."""
    global cl, username
    c = _new()
    c.login(user, password, verification_code=code)
    cl, username = c, user
    _save()


def login_sessionid(sessionid):
    global cl, username
    c = _new()
    c.login_by_sessionid(sessionid)
    cl, username = c, c.account_info().username
    _save()


def restore():
    """Recupera la sesión guardada (sin guardar nunca la contraseña)."""
    global cl, username
    if not os.path.exists(FILE):
        return
    try:
        with open(FILE, "rb") as f:
            data = json.loads(_fernet().decrypt(f.read()))
        c = _new()
        c.set_settings(data["settings"])
        c.account_info()  # valida que la sesión siga viva
        cl, username = c, data["username"]
    except Exception:
        logout()


def logout():
    global cl, username
    cl = username = None
    if os.path.exists(FILE):
        os.remove(FILE)


def _short(u):
    return {"pk": str(u.pk), "username": u.username, "name": u.full_name,
            "pic": str(u.profile_pic_url or ""), "private": u.is_private, "verified": bool(u.is_verified)}


def non_followers():
    """A quién sigo yo que no me sigue de vuelta."""
    with lock:
        following = cl.user_following(str(cl.user_id))
        followers = cl.user_followers(str(cl.user_id))
    fset = {str(k) for k in followers}
    return [_short(u) for pk, u in following.items() if str(pk) not in fset]


def follower_candidates(target, amount):
    """Seguidores de `target` que yo aún no sigo ni he seguido antes con esta app."""
    with lock:
        tpk = cl.user_id_from_username(target)
        theirs = cl.user_followers(str(tpk), amount=amount)
        mine = {str(k) for k in cl.user_following(str(cl.user_id))}
    me = str(cl.user_id)
    return [_short(u) for pk, u in theirs.items()
            if str(pk) not in mine and str(pk) != me and not limits.already_followed(pk)]
