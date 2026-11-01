import os
import tempfile

os.environ.update(APP_PASSWORD="clave-de-prueba-1", SECRET_KEY="x" * 40, DATA_DIR=tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402

import app as appmod  # noqa: E402

c = TestClient(appmod.app, base_url="http://testserver")
H = {"Origin": "http://testserver"}


def test_auth_flow():
    assert c.get("/api/state").json() == {"auth": False}
    assert c.post("/api/ig/login", json={}, headers=H).status_code == 401  # sin acceso a la app
    assert c.post("/api/auth/login", json={"password": "x"}).status_code == 403  # sin Origin (CSRF)
    assert c.post("/api/auth/login", json={"password": "x"}, headers={"Origin": "http://evil.com"}).status_code == 403
    assert c.post("/api/auth/login", json={"password": "mala"}, headers=H).status_code == 401
    assert c.post("/api/auth/login", json={"password": "clave-de-prueba-1"}, headers=H).status_code == 200
    s = c.get("/api/state").json()
    assert s["auth"] and s["ig"] is None and len(s["usage"]["follow"]) == 2
    assert c.post("/api/analyze/unfollow", headers=H).status_code == 409  # falta conectar Instagram
    assert "Content-Security-Policy" in c.get("/").headers


def test_lockout():
    for _ in range(5):
        c2 = TestClient(appmod.app, base_url="http://testserver")
        r = c2.post("/api/auth/login", json={"password": "mala"}, headers=H)
    assert c2.post("/api/auth/login", json={"password": "clave-de-prueba-1"}, headers=H).status_code == 429
