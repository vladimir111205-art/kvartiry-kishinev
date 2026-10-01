"""Оркестратор целиком, на фикстурах, офлайн - тот же путь, что `--rezhim proba`.

Проверяет то, что модульные тесты по отдельности не видят: что все части
реально стыкуются друг с другом в run.py и не падают на живом наборе данных.
"""
from __future__ import annotations

import sqlite3

import pytest

import config
import db
import run


@pytest.fixture(autouse=True)
def izolirovannaya_baza(tmp_path, monkeypatch):
    """Каждый тест - со своей базой, чтобы прогоны не смешивались."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")


def poslednyaya_stroka_progona() -> dict:
    con = db.connect()
    r = con.execute("SELECT * FROM progony ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    return dict(r) if r else {}


def test_pervyy_progon_holodnyy_start_tishe_vody(monkeypatch):
    """Пустая база - тихий прогрев: всё пометить, прислать одно сообщение,
    а не лавину из 60 карточек."""
    monkeypatch.setattr("config.chat_papy", lambda obyazatelno=False: "1")
    monkeypatch.setattr("config.chat_vladimira", lambda obyazatelno=False: "2")
    itog = run.odin_progon("proba")
    assert itog["status"] == "holodnyy_start"
    assert itog["naydeno"] == 60

    con = db.connect()
    assert con.execute("SELECT COUNT(*) AS n FROM obyavleniya").fetchone()["n"] == 60
    # Очередь пуста - тихий прогрев не кладёт события, а сразу шлёт своё
    # единственное сообщение и помечает всё уведомлённым.
    assert con.execute("SELECT COUNT(*) AS n FROM ochered").fetchone()["n"] == 0
    con.close()


def test_povtornyy_progon_na_toy_zhe_dannye_ne_daet_sobytiy():
    run.odin_progon("proba")
    itog = run.odin_progon("proba")
    assert itog["status"] == "ok"
    assert itog["sobytiy"] == 0
    assert itog["otpravleno"] == 0


def test_progon_pishet_stroku_v_progony():
    run.odin_progon("proba")
    stroka = poslednyaya_stroka_progona()
    assert stroka["status"] == "ok"
    assert stroka["naydeno"] == 60


def test_izmenenie_ceny_posle_progreva_daet_sobytie_i_ne_ronyaet():
    run.odin_progon("proba")   # холодный старт

    con = db.connect()
    row = con.execute(
        "SELECT id FROM obyavleniya WHERE sdelka='prodazha' AND dannye_nadezhny=1 "
        "LIMIT 1").fetchone()
    con.execute("UPDATE obyavleniya SET cena_eur = cena_eur * 0.5 WHERE id = ?",
                (row["id"],))
    con.commit()
    con.close()

    itog = run.odin_progon("proba")
    assert itog["status"] == "ok"
    assert itog["sobytiy"] >= 1


def test_krivoy_konfig_ne_ronyaet_python_a_zavershaet_progon(monkeypatch, tmp_path):
    bityy = tmp_path / "bityy.yaml"
    bityy.write_text("versiya: 2\n", encoding="utf-8")   # неверная версия
    monkeypatch.setattr(config, "FILTRY_PATH", bityy)
    itog = run.odin_progon("proba")
    assert itog["status"] == "oshibka_konfiga"


def test_fiktivnyy_istochnik_ne_hodit_v_set(monkeypatch):
    """Контроль, что `--rezhim proba` не пытается открыть сокет."""
    import socket

    def zapret(*a, **kw):
        raise RuntimeError("proba полез в сеть")
    monkeypatch.setattr(socket, "socket", zapret)
    monkeypatch.setattr(socket, "create_connection", zapret)
    itog = run.odin_progon("proba")
    assert itog["status"] in ("ok", "holodnyy_start")


# --- какие поводы уходят в общую (не-избранную) ленту -----------------------

def karta_dlya_ocheredi(**p) -> dict:
    import normalizacia
    k = normalizacia.pustaya()
    k.update({
        "istochnik": "999md", "vneshniy_id": "X", "url": "https://999.md/ru/X",
        "zagolovok": "2к", "sdelka": "prodazha", "gorod": "kishinev",
        "sektor": "botanika", "cena": 52000, "valyuta": "EUR", "cena_eur": 52000,
        "cena_eur_za_m2": 945, "komnat": 2, "ploshad_m2": 55, "etazh": 4,
        "etazhnost": 9, "podnyato_at": "2026-09-18 10:00",
    })
    k.update(p)
    import normalizacia as n
    return n.privesti(k)


PROFIL_VSEM = {
    "imya": "все", "poluchatel": "papa",
    "pravila": [{"pole": "sdelka", "op": "ravno", "znachenie": "prodazha"}],
    "myagkie": [],
}


class FiktivnyIstochnikBezObogashcheniya:
    def obogatit(self, ids):
        return {}


def test_rost_ceny_ne_uhodit_v_obshchuyu_lentu():
    """Нашли на живых данных 18.09.2026: рост цены уходил всем подряд, хотя
    по таблице событий в плане это «нет» для общей ленты и «да» только
    для избранного (фаза 5)."""
    con = db.connect()
    oid = db.zapisat(con, karta_dlya_ocheredi())["obyavlenie_id"]
    con.commit()

    for povod in (db.POVOD_CENA_VYROSLA, db.POVOD_VERNULOS, db.POVOD_PRAVKA):
        run.doobogatit_i_ochered(
            con, FiktivnyIstochnikBezObogashcheniya(),
            [{"obyavlenie_id": oid, "povod": povod, "bylo_eur": 1, "stalo_eur": 2}],
            [PROFIL_VSEM], {}, {})
    con.commit()
    assert con.execute("SELECT COUNT(*) AS n FROM ochered").fetchone()["n"] == 0


def test_novoe_i_snizhenie_ceny_uhodyat_v_obshchuyu_lentu():
    con = db.connect()
    oid = db.zapisat(con, karta_dlya_ocheredi())["obyavlenie_id"]
    con.commit()

    for povod in (db.POVOD_NOVOE, db.POVOD_CENA_UPALA):
        run.doobogatit_i_ochered(
            con, FiktivnyIstochnikBezObogashcheniya(),
            [{"obyavlenie_id": oid, "povod": povod, "bylo_eur": 60000, "stalo_eur": 52000}],
            [PROFIL_VSEM], {}, {})
    con.commit()
    assert con.execute("SELECT COUNT(*) AS n FROM ochered").fetchone()["n"] == 2


# --- ночь: цепочка не гаснет, но папу не будит ------------------------------

def test_nochnoy_progon_kopit_ochered_a_dnevnoy_otpravlyaet(monkeypatch):
    """Замер 27.09-01.10: расписание GitHub будило цепочку в 14:00 вместо
    08:00, и 70% карточек приходили папе с опозданием на часы. Теперь ночью
    цепочка собирает рынок и копит очередь, а первый дневной прогон шлёт."""
    monkeypatch.setattr(config, "chat_poluchatelya", lambda kto: "1")
    run.odin_progon("proba")   # холодный старт

    con = db.connect()
    oid = db.zapisat(con, karta_dlya_ocheredi())["obyavlenie_id"]
    db.v_ochered(con, oid, "двушки папе", db.POVOD_NOVOE, db.POVOD_NOVOE)
    con.commit()
    con.close()

    noch = run.odin_progon("proba", otpravlyat=False)
    assert noch["otpravleno"] == 0
    assert noch["zhdet_utra"] >= 1

    utro = run.odin_progon("proba")
    assert utro["otpravleno"] >= 1


class FalshivoeVremya:
    """time.time и time.sleep, которые двигают часы без ожидания."""

    def __init__(self):
        self.t = 1_000_000.0

    def time(self):
        return self.t

    def sleep(self, sek):
        self.t += max(sek, 1)


def test_cikl_nochyu_ne_vyhodit_i_ne_shlet(monkeypatch):
    from datetime import datetime as dt
    import run as r

    class Noch(dt):
        @classmethod
        def now(cls, tz=None):
            return dt(2026, 10, 2, 3, 0, tzinfo=tz)

    vyzovy = []
    vremya = FalshivoeVremya()
    monkeypatch.setattr(r, "datetime", Noch)
    monkeypatch.setattr(r.time, "time", vremya.time)
    monkeypatch.setattr(r.time, "sleep", vremya.sleep)
    monkeypatch.setattr(r, "odin_progon", lambda rezhim, bystro=False, otpravlyat=True:
                        vyzovy.append((bystro, otpravlyat)) or {"status": "ok"})

    r.cikl(60, "boy")
    # 60 минут ночью: весь рынок раз в 20 минут, верхушку не гоняем, не шлём
    assert len(vyzovy) == 3
    assert all(not bystro and not otpravlyat for bystro, otpravlyat in vyzovy)


def test_cikl_dnem_shlet(monkeypatch):
    from datetime import datetime as dt
    import run as r

    class Den(dt):
        @classmethod
        def now(cls, tz=None):
            return dt(2026, 10, 2, 9, 0, tzinfo=tz)

    vyzovy = []
    vremya = FalshivoeVremya()
    monkeypatch.setattr(r, "datetime", Den)
    monkeypatch.setattr(r.time, "time", vremya.time)
    monkeypatch.setattr(r.time, "sleep", vremya.sleep)
    monkeypatch.setattr(r, "odin_progon", lambda rezhim, bystro=False, otpravlyat=True:
                        vyzovy.append((bystro, otpravlyat)) or {"status": "ok"})

    r.cikl(5, "boy")
    assert vyzovy[0] == (False, True)          # первым - весь рынок
    assert all(otpravlyat for _, otpravlyat in vyzovy)
    assert any(bystro for bystro, _ in vyzovy)  # дальше верхушка


def test_holodnyy_start_nochyu_ne_budit_papu(monkeypatch):
    poslano = []
    monkeypatch.setattr(run, "tihiy_progrev", lambda *a, **k: poslano.append(1))
    itog = run.odin_progon("proba", otpravlyat=False)
    assert itog["status"] == "holodnyy_start"
    assert poslano == []


# --- бот пишет только папе (решение Владимира 01.10.2026) -------------------

def test_poluchatel_tolko_papa(monkeypatch):
    monkeypatch.setattr(config, "chat_papy", lambda obyazatelno=False: "PAPA")
    monkeypatch.setattr(config, "chat_vladimira", lambda obyazatelno=False: "VOVA")
    assert config.chat_poluchatelya("papa") == "PAPA"
    assert config.chat_poluchatelya("vladimir") == ""
    assert config.chat_poluchatelya("") == ""


def test_alert_ne_uhodit_v_telegram(monkeypatch):
    import zdorovie

    class Bot:
        def tekst(self, *a, **k):
            raise AssertionError("алерт ушёл в Telegram")

    monkeypatch.setattr(config, "chat_vladimira", lambda obyazatelno=False: "VOVA")
    zdorovie.alert(Bot(), "проверка")


def test_profil_ne_dlya_papy_ne_proydet_validaciyu(tmp_path):
    import filtry
    f = tmp_path / "f.yaml"
    f.write_text(
        "versiya: 1\nsbor: {gorod: kishinev, sdelki: [prodazha], komnat: [2]}\n"
        "rynok: {okno_dney: 90, minimum_obektov: 15, porog_deshevle: 25}\n"
        "profili:\n  - imya: x\n    aktiven: true\n    poluchatel: vladimir\n"
        "    pravila:\n      - {pole: sdelka, op: ravno, znachenie: prodazha}\n",
        encoding="utf-8")
    with pytest.raises(filtry.OshibkaKonfiga):
        filtry.zagruzit(f)
