"""База, события, очередь, избранное.

Критерии «сделано» фазы 3 из плана проверяются здесь по пунктам:
двойной прогон не даёт событий, смена цены даёт ровно одно событие и одну
строку истории, ручная пометка переживает ingest, три промаха дают «снято»,
а два - нет, потолок отправок соблюдается и остаток ждёт в очереди.
"""
from __future__ import annotations

import pytest

import db
import normalizacia


@pytest.fixture
def con(tmp_path):
    s = db.connect(tmp_path / "t.db")
    yield s
    s.close()


def karta(**pereopredeleniya) -> dict:
    k = normalizacia.pustaya()
    k.update({
        "istochnik": "999md", "vneshniy_id": "1", "url": "https://999.md/ru/1",
        "zagolovok": "2-комнатная, Ботаника", "sdelka": "prodazha", "gorod": "kishinev",
        "sektor": "botanika", "cena": 52000, "valyuta": "EUR", "cena_eur": 52000,
        "cena_eur_za_m2": 945, "komnat": 2, "ploshad_m2": 55, "etazh": 4, "etazhnost": 9,
    })
    k.update(pereopredeleniya)
    # Тот же путь, что и в бою: источник -> privesti -> база.
    return normalizacia.privesti(k)


# --- ingest и события -------------------------------------------------------

def test_pervaya_zapis_daet_novoe(con):
    r = db.zapisat(con, karta())
    assert r["povod"] == db.POVOD_NOVOE
    assert r["obyavlenie_id"]


def test_povtornyy_progon_ne_daet_sobytiy(con):
    db.zapisat(con, karta())
    r = db.zapisat(con, karta())
    assert r["povod"] is None
    assert con.execute("SELECT COUNT(*) AS n FROM obyavleniya").fetchone()["n"] == 1


def test_snizhenie_ceny_daet_odno_sobytie_i_odnu_stroku_istorii(con):
    db.zapisat(con, karta())
    r = db.zapisat(con, karta(cena_eur=47000, cena=47000))
    assert r["povod"] == db.POVOD_CENA_UPALA
    assert r["bylo_eur"] == 52000 and r["stalo_eur"] == 47000
    # Одна строка при заведении и одна при снижении - ровно две.
    assert con.execute("SELECT COUNT(*) AS n FROM istoriya_cen").fetchone()["n"] == 2
    # Третий прогон с той же ценой событием уже не считается.
    assert db.zapisat(con, karta(cena_eur=47000, cena=47000))["povod"] is None
    assert con.execute("SELECT COUNT(*) AS n FROM istoriya_cen").fetchone()["n"] == 2


def test_rost_ceny_otlichaetsya_ot_snizheniya(con):
    db.zapisat(con, karta())
    assert db.zapisat(con, karta(cena_eur=60000))["povod"] == db.POVOD_CENA_VYROSLA


def test_pravka_zagolovka_eto_pravka_a_ne_cena(con):
    db.zapisat(con, karta())
    assert db.zapisat(con, karta(zagolovok="Другой заголовок"))["povod"] == db.POVOD_PRAVKA


def test_pravka_opisaniya_voobshche_ne_sobytie(con):
    db.zapisat(con, karta(opisanie="старое"))
    assert db.zapisat(con, karta(opisanie="новое, продавец переписал"))["povod"] is None


def test_ruchnaya_pometka_perezhivaet_ingest(con):
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    con.execute("UPDATE obyavleniya SET status = 'смотрели', zametka = 'звонил' WHERE id = ?",
                (oid,))
    db.zapisat(con, karta(cena_eur=47000))
    r = con.execute("SELECT status, zametka FROM obyavleniya WHERE id = ?", (oid,)).fetchone()
    assert r["status"] == "смотрели" and r["zametka"] == "звонил"


def test_toshchiy_obhod_ne_zatiraet_dotyanutoe_opisanie(con):
    """Дообогащение приходит отдельным запросом, и следующий тощий обход
    не должен стирать описание и фото обратно в пустоту."""
    db.zapisat(con, karta())
    db.zapisat(con, karta(opisanie="полное описание", foto=["a.jpg", "b.jpg"]))
    db.zapisat(con, karta())          # тощая карточка без описания
    k = db.kartochka(con, 1)
    assert k["opisanie"] == "полное описание"
    assert k["foto"] == ["a.jpg", "b.jpg"]


# --- снятие с продажи -------------------------------------------------------

def test_dva_promaha_ne_snimayut_a_tri_snimayut(con):
    db.zapisat(con, karta())
    assert db.otmetit_propavshie(con, "999md", set()) == []      # промах 1
    assert db.otmetit_propavshie(con, "999md", set()) == []      # промах 2
    snyatye = db.otmetit_propavshie(con, "999md", set())         # промах 3
    assert len(snyatye) == 1 and snyatye[0]["vneshniy_id"] == "1"
    assert con.execute("SELECT aktivno FROM obyavleniya").fetchone()["aktivno"] == 0


def test_vstrecha_sbrasyvaet_schetchik_promahov(con):
    db.zapisat(con, karta())
    db.otmetit_propavshie(con, "999md", set())
    db.otmetit_propavshie(con, "999md", set())
    db.zapisat(con, karta())          # объявление снова встретилось
    assert con.execute("SELECT propuskov FROM obyavleniya").fetchone()["propuskov"] == 0
    assert db.otmetit_propavshie(con, "999md", set()) == []


def test_vozvrat_v_prodazhu_eto_sobytie(con):
    db.zapisat(con, karta())
    for _ in range(3):
        db.otmetit_propavshie(con, "999md", set())
    assert db.zapisat(con, karta())["povod"] == db.POVOD_VERNULOS


def test_uvidennye_ne_poluchayut_promah(con):
    db.zapisat(con, karta())
    db.zapisat(con, karta(vneshniy_id="2"))
    db.otmetit_propavshie(con, "999md", {"1"})
    r = {x["vneshniy_id"]: x["propuskov"] for x in
         con.execute("SELECT vneshniy_id, propuskov FROM obyavleniya")}
    assert r == {"1": 0, "2": 1}


def test_izbrannomu_hvataet_odnogo_promaha(con):
    db.zapisat(con, karta())
    snyatye = db.otmetit_propavshie(con, "999md", set(),
                                    porog=1)
    assert len(snyatye) == 1


# --- очередь ----------------------------------------------------------------

def test_odno_i_to_zhe_sobytie_v_ochered_dvazhdy_ne_popadet(con):
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    assert db.v_ochered(con, oid, "п", db.POVOD_NOVOE) is True
    assert db.v_ochered(con, oid, "п", db.POVOD_NOVOE) is False


def test_vtoroe_snizhenie_ceny_popadaet_v_ochered(con):
    """UNIQUE по поводу проглотил бы второе снижение. Ключ события это чинит."""
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    assert db.v_ochered(con, oid, "п", db.POVOD_CENA_UPALA,
                        db.klyuch_sobytiya(db.POVOD_CENA_UPALA, 47000)) is True
    assert db.v_ochered(con, oid, "п", db.POVOD_CENA_UPALA,
                        db.klyuch_sobytiya(db.POVOD_CENA_UPALA, 47000)) is False
    assert db.v_ochered(con, oid, "п", db.POVOD_CENA_UPALA,
                        db.klyuch_sobytiya(db.POVOD_CENA_UPALA, 44000)) is True


def test_potolok_progona_soblyudaetsya_ostatok_zhdet(con):
    for i in range(15):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "п", db.POVOD_NOVOE)
    k_otpravke = db.ochered_k_otpravke(con, potolok_progona=10, potolok_dnya=25)
    assert len(k_otpravke) == 10
    assert con.execute(
        "SELECT COUNT(*) AS n FROM ochered WHERE sostoyanie = 'zhdet'").fetchone()["n"] == 15


def test_sutochnyy_potolok_ogranichivaet_progon(con):
    for i in range(30):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "п", db.POVOD_NOVOE)
    for z in db.ochered_k_otpravke(con, potolok_progona=10, potolok_dnya=25):
        db.otmetit_otpravlennym(con, z["id"], 1)
    for z in db.ochered_k_otpravke(con, potolok_progona=10, potolok_dnya=25):
        db.otmetit_otpravlennym(con, z["id"], 1)
    # Двадцать ушло, на сутки осталось пять.
    assert len(db.ochered_k_otpravke(con, potolok_progona=10, potolok_dnya=25)) == 5


def test_izbrannoe_idet_pervym_i_mimo_potolkov(con):
    for i in range(20):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "п", db.POVOD_NOVOE)
    lyubimyy = db.zapisat(con, karta(vneshniy_id="izb"))["obyavlenie_id"]
    db.v_ochered(con, lyubimyy, "izbrannoe", db.POVOD_CENA_UPALA,
                 klyuch="cena_upala:1", prioritet=10)

    k_otpravke = db.ochered_k_otpravke(con, potolok_progona=10, potolok_dnya=25)
    assert k_otpravke[0]["obyavlenie_id"] == lyubimyy
    # Потолок прогона - 10 обычных, плюс избранное сверх него.
    assert len(k_otpravke) == 11


def test_izbrannoe_prohodit_kogda_potolok_uzhe_vybran(con):
    for i in range(30):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "п", db.POVOD_NOVOE)
    for _ in range(3):
        for z in db.ochered_k_otpravke(con, potolok_progona=10, potolok_dnya=25):
            db.otmetit_otpravlennym(con, z["id"], 1)
    assert db.ochered_k_otpravke(con, potolok_progona=10, potolok_dnya=25) == []

    lyubimyy = db.zapisat(con, karta(vneshniy_id="izb"))["obyavlenie_id"]
    db.v_ochered(con, lyubimyy, "izbrannoe", db.POVOD_CENA_UPALA,
                 klyuch="cena_upala:1", prioritet=10)
    k_otpravke = db.ochered_k_otpravke(con, potolok_progona=10, potolok_dnya=25)
    assert len(k_otpravke) == 1 and k_otpravke[0]["obyavlenie_id"] == lyubimyy


def test_neudachnaya_otpravka_ostavlyaet_zapis_v_ocheredi(con):
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    db.v_ochered(con, oid, "п", db.POVOD_NOVOE)
    z = db.ochered_k_otpravke(con)[0]
    db.otmetit_popytku(con, z["id"])
    snova = db.ochered_k_otpravke(con)
    assert len(snova) == 1 and snova[0]["popytok"] == 1


def test_tihiy_progrev_gasit_vsyu_ochered(con):
    for i in range(200):
        oid = db.zapisat(con, karta(vneshniy_id=str(i)))["obyavlenie_id"]
        db.v_ochered(con, oid, "п", db.POVOD_NOVOE)
    assert db.pometit_vsyo_otpravlennym(con) == 200
    assert db.ochered_k_otpravke(con) == []


# --- избранное --------------------------------------------------------------

def test_izbrannoe_dobavlyaetsya_i_snimaetsya(con):
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    assert db.dobavit_v_izbrannoe(con, oid, "papa", 52000) is True
    assert db.dobavit_v_izbrannoe(con, oid, "papa", 52000) is False   # повтор
    assert db.v_izbrannom(con, oid, "papa") is True
    assert db.ubrat_iz_izbrannogo(con, oid, "papa") is True
    assert db.v_izbrannom(con, oid, "papa") is False


def test_izbrannoe_pomnit_cenu_na_moment_dobavleniya(con):
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    db.dobavit_v_izbrannoe(con, oid, "papa", 52000)
    db.zapisat(con, karta(cena_eur=44000))
    i = db.izbrannye(con, "papa")[0]
    assert i["cena_pri_dobavlenii"] == 52000
    assert i["cena_eur"] == 44000        # движение видно: -8 000 €


def test_izbrannoe_ostaetsya_kogda_obekt_vypal_iz_filtrov(con):
    """Цена выросла выше папиной границы - но отслеживать не перестаём."""
    oid = db.zapisat(con, karta())["obyavlenie_id"]
    db.dobavit_v_izbrannoe(con, oid, "papa", 52000)
    db.zapisat(con, karta(cena_eur=200000))
    assert len(db.izbrannye(con, "papa")) == 1


# --- прочее -----------------------------------------------------------------

def test_dva_istochnika_ne_putayutsya(con):
    db.zapisat(con, karta(istochnik="999md", vneshniy_id="1"))
    db.zapisat(con, karta(istochnik="maklermd", vneshniy_id="1"))
    assert con.execute("SELECT COUNT(*) AS n FROM obyavleniya").fetchone()["n"] == 2
    db.otmetit_propavshie(con, "999md", set())
    r = {x["istochnik"]: x["propuskov"] for x in
         con.execute("SELECT istochnik, propuskov FROM obyavleniya")}
    assert r == {"999md": 1, "maklermd": 0}


def test_baza_pustaya_znaet_pro_holodnyy_start(con):
    assert db.baza_pustaya(con) is True
    db.zapisat(con, karta())
    assert db.baza_pustaya(con) is False


def test_offset_getupdates_perezhivaet_perezapusk(con):
    db.meta_set(con, "tg_offset", 12345)
    con.commit()
    assert db.meta_get(con, "tg_offset") == "12345"
    assert db.meta_get(con, "net_takogo", "по умолчанию") == "по умолчанию"


def test_kursy_sohranyayutsya_i_chitayutsya(con):
    db.sohranit_kursy(con, {"MDL": 0.0497, "USD": 0.8669, "EUR": 1.0})
    assert db.posledniye_kursy(con)["MDL"] == 0.0497


def test_mnogo_uvidennyh_ne_ronyaet_zapros(con):
    """Двадцать тысяч id за прогон: через параметры запроса SQLite бы упал."""
    db.zapisat(con, karta(vneshniy_id="ostalos"))
    mnogo = {str(i) for i in range(20000)}
    db.otmetit_propavshie(con, "999md", mnogo)
    assert con.execute("SELECT propuskov FROM obyavleniya").fetchone()["propuskov"] == 1
