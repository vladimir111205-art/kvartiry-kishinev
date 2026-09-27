"""Сборка и отправка: дообогащение, перепроверка, очередь, потолки.

Главный тест здесь - `test_rassrochka_otsevaetsya_posle_doobogashcheniya`.
Это не выдуманный случай: при первой боевой отправке из трёх карточек одна
оказалась объявлением «в рассрочку» (в поле цены первый взнос, а не цена
квартиры) и ушла бы папе как «на 41% дешевле рынка». Тощий обход описания не
тянет, поэтому увидеть это можно только после дообогащения - то есть фильтр
обязан отрабатывать дважды.
"""
from __future__ import annotations

import datetime

import pytest

import db
import filtry
import normalizacia
import otpravka
import rynok
from tests.test_notify import Podstavnoy
import notify


@pytest.fixture
def con(tmp_path):
    s = db.connect(tmp_path / "t.db")
    yield s
    s.close()


PROFIL = {
    "imya": "тест", "poluchatel": "vladimir",
    "pravila": [
        {"pole": "sdelka", "op": "ravno", "znachenie": "prodazha"},
        {"pole": "dannye_nadezhny", "op": "ravno", "znachenie": 1},
    ],
    "myagkie": [],
}


def karta(**p) -> dict:
    k = normalizacia.pustaya()
    k.update({
        "istochnik": "999md", "vneshniy_id": "1", "url": "https://999.md/ru/1",
        "zagolovok": "2к, Ботаника", "sdelka": "prodazha", "gorod": "kishinev",
        "sektor": "botanika", "cena": 52000, "valyuta": "EUR", "cena_eur": 52000,
        "cena_eur_za_m2": 945, "komnat": 2, "ploshad_m2": 55, "etazh": 4,
        "etazhnost": 9,
        # Без даты подъёма карточка выпадает из окна 90 дней и не попадает
        # в медианы - у боевых карточек эта дата есть всегда.
        "podnyato_at": datetime.date.today().isoformat() + " 12:00",
    })
    k.update(p)
    return normalizacia.privesti(k)


class Istochnik:
    """Подставной источник: отдаёт заранее заданное дообогащение."""

    imya = "999md"

    def __init__(self, obogashchenie: dict):
        self.obogashchenie = obogashchenie
        self.sprosili = []

    def po_id(self, ids):
        self.sprosili.extend(ids)
        return [(v, self.obogashchenie.get(v)) for v in ids]

    def normalizovat(self, syroe, k_eur=None):
        return syroe


def bot(otvety=None):
    t = Podstavnoy(otvety)
    return notify.Bot(token="тест", transport=t), t


# --- дообогащение и перепроверка --------------------------------------------

def test_rassrochka_otsevaetsya_posle_doobogashcheniya(con, monkeypatch):
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    con.commit()
    kandidat = db.kartochka(con, oid)
    assert filtry.prohodit(kandidat, PROFIL)      # до дообогащения проходит

    # Дообогащение приносит описание, и оно всё меняет.
    ist = Istochnik({"1": karta(
        opisanie="Vand apartamentul in rate. Prima rată 30% (19000)€",
        foto=["https://i/a.jpg"])})
    gotovye = otpravka.podgotovit(con, ist, [kandidat], PROFIL, {}, {})
    assert gotovye == []


def test_chestnaya_kartochka_prohodit_i_poluchaet_foto(con):
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    con.commit()
    ist = Istochnik({"1": karta(opisanie="Светлая квартира, рядом парк",
                                foto=["https://i/a.jpg", "https://i/b.jpg"])})
    gotovye = otpravka.podgotovit(con, ist, [db.kartochka(con, oid)], PROFIL, {}, {})
    assert len(gotovye) == 1
    assert gotovye[0]["foto"] == ["https://i/a.jpg", "https://i/b.jpg"]
    assert "Светлая квартира" in gotovye[0]["opisanie"]


def test_doobogashchaem_tolko_tex_u_kogo_net_foto(con):
    """Дообогащение - отдельный запрос на каждый объект. Дёргать его по
    карточкам, которые уже дотянуты, значит жечь время прогона зря."""
    a = db.zapisat(con, karta(vneshniy_id="a"))["obyavlenie_id"]
    db.zapisat(con, karta(vneshniy_id="b", foto=["https://i/uzhe.jpg"]))
    con.commit()
    ist = Istochnik({"a": karta(vneshniy_id="a", foto=["https://i/a.jpg"])})
    otpravka.podgotovit(con, ist, [db.kartochka(con, a), db.kartochka(con, 2)],
                        PROFIL, {}, {})
    assert ist.sprosili == ["a"]


def test_ischeznuvshiy_pri_doobogashchenii_ne_ronyaet(con):
    """Объект сняли между обходом и дообогащением - это не повод падать."""
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    con.commit()
    ist = Istochnik({})       # площадка вернула None
    gotovye = otpravka.podgotovit(con, ist, [db.kartochka(con, oid)], PROFIL, {}, {})
    assert len(gotovye) == 1  # карточка осталась той, что была в базе


# --- очередь ----------------------------------------------------------------

def test_ochered_razgruzhaetsya_i_pomechaetsya(con, monkeypatch):
    monkeypatch.setattr("config.chat_poluchatelya", lambda imya: "42")
    for i in range(3):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "тест", db.POVOD_NOVOE)
    con.commit()
    b, t = bot()
    itog = otpravka.razgruzit_ochered(con, b, {}, {"тест": PROFIL})
    assert itog["otpravleno"] == 3
    assert t.metody == ["sendPhoto"] * 0 + ["sendMessage"] * 3 or len(t.vyzovy) == 3
    assert db.ochered_k_otpravke(con) == []


def test_403_ostanavlivaet_i_ne_vyzhigaet_ochered(con, monkeypatch):
    monkeypatch.setattr("config.chat_poluchatelya", lambda imya: "42")
    for i in range(5):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "тест", db.POVOD_NOVOE)
    con.commit()
    b, t = bot([{"ok": False, "error_code": 403, "description": "blocked"}])
    itog = otpravka.razgruzit_ochered(con, b, {}, {"тест": PROFIL})
    assert itog["ostanovleno"] is True
    assert itog["otpravleno"] == 0
    # Все пять по-прежнему ждут: очередь не выжжена.
    assert len(db.ochered_k_otpravke(con)) == 5


def test_ne_ushlo_ostaetsya_v_ocheredi(con, monkeypatch):
    monkeypatch.setattr("config.chat_poluchatelya", lambda imya: "42")
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    db.v_ochered(con, oid, "тест", db.POVOD_NOVOE)
    con.commit()
    b, _ = bot([{"ok": False, "error_code": 400, "description": "chat not found"}] * 4)
    itog = otpravka.razgruzit_ochered(con, b, {}, {"тест": PROFIL})
    assert itog["ne_ushlo"] == 1
    ostalos = db.ochered_k_otpravke(con)
    assert len(ostalos) == 1 and ostalos[0]["popytok"] == 1


def test_mnogo_novyh_uhodyat_odnim_daydzhestom(con, monkeypatch):
    """Лавина из двадцати сообщений подряд отучает читать бота быстрее,
    чем полное молчание."""
    monkeypatch.setattr("config.chat_poluchatelya", lambda imya: "42")
    monkeypatch.setattr("config.MAX_OTPRAVOK_ZA_PROGON", 30)
    for i in range(20):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "тест", db.POVOD_NOVOE)
    con.commit()
    b, t = bot()
    itog = otpravka.razgruzit_ochered(con, b, {}, {"тест": PROFIL})
    assert itog["otpravleno"] == 1          # одно сообщение вместо двадцати
    assert t.metody == ["sendMessage"]
    assert db.ochered_k_otpravke(con) == []


def test_snizhenie_ceny_ne_svorachivaetsya_v_daydzhest(con, monkeypatch):
    """Дайджестом идут только новинки. Снижение цены - повод посмотреть
    сегодня, ему место отдельным сообщением."""
    monkeypatch.setattr("config.chat_poluchatelya", lambda imya: "42")
    monkeypatch.setattr("config.MAX_OTPRAVOK_ZA_PROGON", 30)
    for i in range(20):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "тест", db.POVOD_NOVOE)
    upala = db.zapisat(con, karta(vneshniy_id="upala"))["obyavlenie_id"]
    db.v_ochered(con, upala, "тест", db.POVOD_CENA_UPALA,
                 klyuch="cena_upala:47000", bylo_eur=58000)
    con.commit()
    b, t = bot()
    itog = otpravka.razgruzit_ochered(con, b, {}, {"тест": PROFIL})
    assert itog["otpravleno"] == 2          # дайджест + отдельная карточка
    otdelnoe = [d for _, d in t.vyzovy if "Было" in str(d)]
    assert otdelnoe, "шапка «Было ... стало ...» должна уйти отдельным сообщением"


def test_izbrannoe_ne_svorachivaetsya_v_daydzhest(con, monkeypatch):
    monkeypatch.setattr("config.chat_poluchatelya", lambda imya: "42")
    monkeypatch.setattr("config.MAX_OTPRAVOK_ZA_PROGON", 30)
    for i in range(20):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "тест", db.POVOD_NOVOE)
    lyub = db.zapisat(con, karta(vneshniy_id="izb"))["obyavlenie_id"]
    db.v_ochered(con, lyub, "тест", db.POVOD_NOVOE, prioritet=10)
    con.commit()
    b, t = bot()
    itog = otpravka.razgruzit_ochered(con, b, {}, {"тест": PROFIL})
    assert itog["otpravleno"] == 2


def test_bez_poluchatelya_zapis_ne_visnet_vechno(con, monkeypatch):
    monkeypatch.setattr("config.chat_poluchatelya", lambda imya: "")
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    db.v_ochered(con, oid, "тест", db.POVOD_NOVOE)
    con.commit()
    b, t = bot()
    otpravka.razgruzit_ochered(con, b, {}, {"тест": PROFIL})
    assert db.ochered_k_otpravke(con) == []
    assert t.vyzovy == []


# --- содержимое карточки ----------------------------------------------------

def test_otpravlennaya_kartochka_neset_metku_rynka(con, monkeypatch):
    monkeypatch.setattr("config.chat_poluchatelya", lambda imya: "42")
    profil = dict(PROFIL, myagkie=[
        {"pole": "otklonenie_ot_rynka", "op": "ne_menshe", "znachenie": 25,
         "metka": "дешевле рынка"}])
    for i in range(20):
        k = karta(vneshniy_id=f"r{i}", cena_eur_za_m2=1900,
                  cena_eur=1900 * 55)
        db.zapisat(con, k)
    oid = db.zapisat(con, karta(vneshniy_id="deshevaya", cena_eur_za_m2=1200,
                                cena_eur=1200 * 55))["obyavlenie_id"]
    con.commit()
    m = rynok.sobrat_mediany(con, minimum=15)
    b, t = bot()
    kart = db.kartochka(con, oid)
    kart["otklonenie_ot_rynka"] = rynok.otklonenie(kart, m)
    otpravka.otpravit_kartochku(b, "42", kart, m, profil)
    tekst = str(t.vyzovy[0][1])
    assert "дешевле рынка" in tekst
    assert "объектам" in tekst
