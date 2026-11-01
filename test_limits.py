import tempfile

import limits

limits.DATA = tempfile.mkdtemp()
limits.LIMITS["follow"] = (2, 3)


def test_hour_and_day_windows():
    t0 = 1_000_000.0
    assert limits.wait_seconds("follow", t0) == 0
    limits.record("follow", 1, t0)
    limits.record("follow", 2, t0 + 60)
    # hora llena: se libera cuando expira la 1ª acción
    assert limits.wait_seconds("follow", t0 + 100) == t0 + 3600 - (t0 + 100)
    # pasada la hora, vuelve a haber cupo
    assert limits.wait_seconds("follow", t0 + 3601) == 0
    limits.record("follow", 3, t0 + 3700)
    # 3 en el día = tope diario: espera hasta que expire la 1ª (24 h)
    assert limits.wait_seconds("follow", t0 + 3800) == t0 + 86400 - (t0 + 3800)


def test_cooldown_and_dedupe():
    assert not limits.already_followed(99)
    limits.record("follow", 99)
    assert limits.already_followed(99)
    limits.set_cooldown(500)
    assert 490 < limits.wait_seconds("unfollow") <= 500
