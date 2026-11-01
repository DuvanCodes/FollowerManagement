"""Registro de acciones en SQLite + cupos por hora/día (ventana móvil) + enfriamiento."""
import os
import sqlite3
import time
from contextlib import closing

DATA = os.environ.get("DATA_DIR", "data")

# (por hora, por día). Conservadores para cuentas normales; ajustables por variable de entorno.
_DEFAULTS = {"follow": (20, 150), "unfollow": (20, 150)}
LIMITS = {
    k: (int(os.environ.get(f"{k.upper()}_PER_HOUR", h)), int(os.environ.get(f"{k.upper()}_PER_DAY", d)))
    for k, (h, d) in _DEFAULTS.items()
}
WINDOWS = (3600, 86400)


def _q(sql, args=()):
    os.makedirs(DATA, exist_ok=True)
    with closing(sqlite3.connect(os.path.join(DATA, "app.db"), timeout=10)) as c:
        c.execute("CREATE TABLE IF NOT EXISTS actions(ts REAL, kind TEXT, pk TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v REAL)")
        rows = c.execute(sql, args).fetchall()
        c.commit()
        return rows


def record(kind, pk, ts=None):
    _q("INSERT INTO actions VALUES (?,?,?)", (ts or time.time(), kind, str(pk)))


def already_followed(pk):
    return bool(_q("SELECT 1 FROM actions WHERE kind='follow' AND pk=? LIMIT 1", (str(pk),)))


def cooldown_until():
    r = _q("SELECT v FROM kv WHERE k='cooldown'")
    return r[0][0] if r else 0.0


def set_cooldown(seconds):
    _q("INSERT OR REPLACE INTO kv VALUES ('cooldown', ?)", (time.time() + seconds,))


def _times(kind, window, now):
    return [r[0] for r in _q("SELECT ts FROM actions WHERE kind=? AND ts>? ORDER BY ts", (kind, now - window))]


def usage(kind, now=None):
    now = now or time.time()
    return [[len(_times(kind, w, now)), lim] for w, lim in zip(WINDOWS, LIMITS[kind])]  # [[hora], [día]]


def wait_seconds(kind, now=None):
    """Segundos hasta que se pueda ejecutar otra acción (0 = ya). Incluye el enfriamiento."""
    now = now or time.time()
    wait = max(0.0, cooldown_until() - now)
    for w, lim in zip(WINDOWS, LIMITS[kind]):
        ts = _times(kind, w, now)
        if len(ts) >= lim:
            # el cupo se libera cuando expira la acción (len-lim)-ésima más antigua
            wait = max(wait, ts[len(ts) - lim] + w - now)
    return wait
