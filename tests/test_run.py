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
