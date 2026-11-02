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


def test_non_followers_rejects_incomplete_list():
    from types import SimpleNamespace as NS

    import pytest

    import ig

    def user(pk):
        return NS(pk=pk, username=f"u{pk}", full_name="", profile_pic_url=None, is_private=False, is_verified=False)

    class Fake:
        user_id = 1
        followers = {}

        def user_info(self, _, use_cache=True):
            return NS(follower_count=1000)

        def user_following(self, _, use_cache=True):
            return {pk: user(pk) for pk in (2, 3)}

        def user_followers(self, _, use_cache=True):
            return self.followers

    ig.cl = Fake()
    try:
        Fake.followers = {pk: user(pk) for pk in range(2, 500)}  # faltan ~500: lista cortada
        with pytest.raises(ig.IncompleteList):
            ig.non_followers()
        Fake.followers = {pk: user(pk) for pk in range(3, 995)}  # faltan 8: margen normal
        assert [u["username"] for u in ig.non_followers()] == ["u2"]
    finally:
        ig.cl = None
