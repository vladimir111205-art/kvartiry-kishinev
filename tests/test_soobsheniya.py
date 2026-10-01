"""Тексты сообщений.

Читатель - не технический человек. Значит в сообщении не должно быть ни
«None», ни `botanika`, ни сырого HTML, ни числа без единицы измерения.
Каждый из этих случаев здесь проверяется отдельно, потому что каждый уже
случался в других агентах фермы.
"""
from __future__ import annotations

import pytest

import config
import normalizacia
import soobsheniya as s


def karta(**p) -> dict:
    k = normalizacia.pustaya()
    k.update({
        "istochnik": "999md", "vneshniy_id": "1", "url": "https://999.md/ru/1",
        "zagolovok": "2-комнатная квартира, Ботаника", "sdelka": "prodazha",
        "gorod": "kishinev", "sektor": "botanika", "ulica": "ул. Дачия, 34",
        "cena": 52000, "valyuta": "EUR", "cena_eur": 52000, "cena_eur_za_m2": 945,
        "komnat": 2, "ploshad_m2": 61, "etazh": 4, "etazhnost": 9,
        "fond": "novostroy", "sostoyanie": "evroremont", "prodavec": "sobstvennik",
    })
    k.update(p)
    return normalizacia.privesti(k)


GRUPPA = {"mediana": 1210, "obektov": 340}


# --- карточка ---------------------------------------------------------------

def test_kartochka_chitaetsya_chelovekom():
    t = s.kartochka(karta(), GRUPPA)
    assert "2-комнатная, Ботаника" in t
    assert "52 000 €" in t
    assert "945 €/м²" in t
    assert "61 м²" in t
    assert "этаж 4 из 9" in t
    assert "новострой" in t and "евроремонт" in t and "собственник" in t
    assert "ул. Дачия, 34" in t


def test_v_kartochke_net_kodov_dlya_filtrov():
    t = s.kartochka(karta(), GRUPPA)
    for kod in ("botanika", "novostroy", "evroremont", "sobstvennik", "prodazha",
                "kishinev"):
        assert kod not in t, kod


def test_v_kartochke_net_none():
    """None в сообщении - это «None» на экране у папы."""
    t = s.kartochka(karta(ulica="", sostoyanie="", tip_doma="", fond=""), {})
    assert "None" not in t


def test_pustye_polya_ne_dayut_strok_s_odnimi_emodzi():
    t = s.kartochka(karta(ulica="", sostoyanie="", tip_doma="", fond="",
                          prodavec="", ploshad_m2=0, etazh=0, etazhnost=0), {})
    for stroka in t.split("\n"):
        assert stroka.strip() not in ("📐", "🏗", "📍", "🏷"), repr(stroka)


def test_amperand_i_ugolki_ne_lomayut_html():
    """Заголовок с `&` или `<` роняет parse_mode, и сообщение молча не уходит."""
    t = s.kartochka(karta(ulica="ул. <Тест> & Ко"), {})
    assert "&lt;Тест&gt;" in t and "&amp;" in t
    assert "<Тест>" not in t


def test_kishinev_v_kartochke_ne_pishetsya_a_selo_pishetsya():
    """«Ботаника» понятно и без города. А «Центр» Колоницы без города
    читается как центр Кишинёва - ровно та путаница, из-за которой медианы
    считаются с городом в ключе."""
    assert "Кишинёв" not in s.kartochka(karta(), {})
    t = s.kartochka(karta(gorod="kolonica", sektor="centr"), {})
    assert "Колоница" in t


def test_stroka_rynka_molchit_bez_mediany():
    assert s.stroka_rynka(karta(otklonenie_ot_rynka=30), {}) == ""
    assert s.stroka_rynka(karta(otklonenie_ot_rynka=0), GRUPPA) == ""


def test_stroka_rynka_pokazyvaet_razmer_vyborki():
    t = s.stroka_rynka(karta(otklonenie_ot_rynka=22), GRUPPA)
    assert "на 22% дешевле" in t
    assert "1 210 €/м²" in t
    assert "340 объектам" in t


def test_dorozhe_rynka_ne_reklamiruetsya():
    assert s.stroka_rynka(karta(otklonenie_ot_rynka=-15), GRUPPA) == ""


# --- поводы -----------------------------------------------------------------

def test_shapka_snizheniya_ceny():
    t = s.shapka_ceny("cena_upala", 58000, 52000)
    assert "Было 58 000 €" in t and "стало 52 000 €" in t
    assert "-10%" in t


def test_shapka_rosta_ceny():
    assert "+15%" in s.shapka_ceny("cena_vyrosla", 52000, 60000)


def test_u_novogo_obekta_shapki_net():
    assert s.shapka_ceny("novoe", 0, 52000) == ""


def test_snyato_i_vernulos_podpisany_slovami():
    assert "Снято с продажи" in s.shapka_ceny("snyato", 0, 0)
    assert "Снова в продаже" in s.shapka_ceny("vernulos", 0, 0)


# --- избранное --------------------------------------------------------------

def test_dvizhenie_ot_ceny_dobavleniya():
    t = s.stroka_izbrannogo(karta(cena_eur=52000), 60000)
    assert "-8 000 €" in t and "-13%" in t


def test_rost_ot_ceny_dobavleniya():
    t = s.stroka_izbrannogo(karta(cena_eur=60000), 52000)
    assert "+8 000 €" in t and "+15%" in t


def test_bez_dvizheniya_govorim_pryamo():
    assert "не менялась" in s.stroka_izbrannogo(karta(cena_eur=52000), 52000)


def test_bez_ceny_dobavleniya_stroki_net():
    assert s.stroka_izbrannogo(karta(), 0) == ""


# --- кнопки -----------------------------------------------------------------

def test_dve_knopki_u_kartochki():
    k = s.knopki(dict(karta(), id=7))
    ryad = k["inline_keyboard"][0]
    assert ryad[0]["url"] == "https://999.md/ru/1"
    assert ryad[1]["callback_data"] == "izb_dobavit:7"
    assert "Отслеживать" in ryad[1]["text"]


def test_knopka_menyaetsya_u_izbrannogo():
    ryad = s.knopki(dict(karta(), id=7), v_izbrannom=True)["inline_keyboard"][0]
    assert ryad[1]["callback_data"] == "izb_ubrat:7"
    assert "В избранном" in ryad[1]["text"]


def test_bez_ssylki_knopka_otslezhivaniya_ostaetsya():
    ryad = s.knopki(dict(karta(url=""), id=7))["inline_keyboard"][0]
    assert len(ryad) == 1 and "callback_data" in ryad[0]


# --- длина ------------------------------------------------------------------

def test_podpis_ne_dlinnee_limita_telegram():
    dlinnyy = karta(ulica="ул. " + "Очень Длинное Название " * 80)
    t = s.kartochka(dlinnyy, GRUPPA, metki=["метка " * 50])
    assert len(t) <= config.MAX_PODPISI


def test_pri_obrezke_glavnoe_ostaetsya():
    dlinnyy = karta(ulica="ул. " + "Длинное " * 200)
    t = s.kartochka(dlinnyy, GRUPPA)
    assert "2-комнатная" in t and "52 000 €" in t


# --- дайджест и сводки ------------------------------------------------------

def test_daydzhest_odnim_soobshcheniem():
    spisok = [(karta(vneshniy_id=str(i)), GRUPPA) for i in range(12)]
    t = s.daydzhest(spisok)
    assert "12" in t
    assert t.count("•") == 12
    assert len(t) <= 4000


def test_tihiy_progrev_odno_soobshchenie_a_ne_dvesti():
    top = [(karta(vneshniy_id=str(i)), GRUPPA) for i in range(5)]
    t = s.tihiy_progrev(200, top)
    assert "200" in t
    assert "не присылаю" in t
    assert t.count("•") == 5


def test_svodka_soderzhit_cifry_dnya():
    t = s.svodka(
        {"novyh": 3, "podesheveli": 2, "snyato": 1},
        [{"sektor": "botanika", "komnat": 2, "mediana": 1870, "izmenenie_pct": -1.2}],
        [dict(karta(), cena_pri_dobavlenii=60000, aktivno=1)])
    assert "Новых: 3" in t and "подешевело: 2" in t and "ушло с продажи: 1" in t
    assert "Ботаника" in t and "1 870 €/м²" in t
    assert "-1.2% за неделю" in t
    assert "Отслеживаемые" in t


def test_svodka_bez_izbrannogo_ne_lomaetsya():
    t = s.svodka({"novyh": 0, "podesheveli": 0, "snyato": 0}, [], [])
    assert "Итоги дня" in t and "None" not in t


def test_spisok_izbrannogo_pustoy_obyasnyaet_kak_dobavit():
    t = s.spisok_izbrannogo([])
    assert "Отслеживать" in t


def test_ya_na_svyazi_uspokaivaet():
    assert "7" in s.ya_na_svyazi(7)


# --- числа ------------------------------------------------------------------

@pytest.mark.parametrize("n, ed, zhdem", [
    (52000, "€", "52 000 €"),
    (945.6, "€/м²", "946 €/м²"),
    (0, "€", "0 €"),
    (None, "€", ""),
    ("не число", "€", ""),
])
def test_chislo_s_edinicey(n, ed, zhdem):
    assert s.chislo(n, ed) == zhdem


def test_komnatnost():
    assert s.komnatnost(2) == "2-комнатная"
    assert s.komnatnost(0) == "квартира"
    assert s.komnatnost(None) == "квартира"
