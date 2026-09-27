"""Тощий обход + точечное дообогащение - то, как агент работает в бою.

Отец просил узнавать первым и о новом объекте, и о смене цены. Сортировки «по
изменению» у площадки нет, поэтому каждый прогон обходится весь рынок, и весь
смысл этих тестов - что тощая карточка не хуже полной во всём, кроме описания
и фотографий, которые дотягиваются отдельно.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import normalizacia
import filtry
import config

KOREN = Path(__file__).resolve().parent.parent


@pytest.fixture
def toshchiy_spisok() -> list:
    d = json.loads((KOREN / "fixtures" / "999md_spisok_toshchiy.json").read_text(encoding="utf-8"))
    return d["data"]["searchAds"]["ads"]


@pytest.fixture
def obogashchenie() -> dict:
    return json.loads((KOREN / "fixtures" / "999md_obogashchenie.json").read_text(encoding="utf-8"))


@pytest.fixture
def toshchie_kartochki(istochnik, toshchiy_spisok, k_eur) -> list:
    return [normalizacia.privesti(istochnik.normalizovat(s, k_eur)) for s in toshchiy_spisok]


def test_toshchaya_kartochka_polnocenna_krome_opisaniya(toshchie_kartochki):
    for k in toshchie_kartochki:
        assert k["vneshniy_id"] and k["url"]
        assert k["cena_eur"] > 0
        assert k["sdelka"]
        # Серверный фильтр теперь только по городу: с регионом площадка
        # город игнорировала и подмешивала сёла муниципия.
        assert k["gorod"] == "kishinev", k["zagolovok"]
        # Описание и фото тощий обход не тянет - их дотягивает obogatit().
        assert k["opisanie"] == ""
        assert k["foto"] == []


def test_sektor_est_pochti_vsegda(toshchie_kartochki):
    """Часть продавцов не заполняет сектор - это данные, а не поломка.
    Такая карточка не пройдёт фильтр по сектору и не попадёт в медиану
    сектора, и это правильно: выдумывать ей район мы не будем."""
    bez = [k for k in toshchie_kartochki if not k["sektor"]]
    assert len(bez) <= len(toshchie_kartochki) * 0.1


def test_slovar_znaet_vse_sektory_kotorye_shlyot_ploshchadka(toshchiy_spisok):
    """Если площадка заведёт новый сектор, он молча станет пустым и выпадет
    из медиан. Тест ловит это на фикстуре при каждом её обновлении."""
    from istochniki.devyat999 import _perevod
    from istochniki import devyat999_slovar as slovar
    neizvestnye = {_perevod(a.get("district")) for a in toshchiy_spisok
                   if _perevod(a.get("district")) and not slovar.sektor(_perevod(a.get("district")))}
    assert not neizvestnye, f"сектор не в словаре: {neizvestnye}"


def test_polya_dlya_mediany_est_v_toshchey(toshchie_kartochki):
    """Медиана считается по сектор+комнатность за 90 дней. Всё это в тощей есть."""
    godnyh = [k for k in toshchie_kartochki
              if k["sektor"] and k["komnat"] and k["cena_eur_za_m2"] and k["podnyato_at"]]
    assert len(godnyh) >= len(toshchie_kartochki) * 0.9


def test_polya_dlya_filtrov_est_v_toshchey(toshchie_kartochki):
    """Боевой профиль фильтрует по сделке, комнатам, цене, сектору, площади,
    этажу и этажности. Если тощий обход их не отдаёт, фильтр отсечёт всё."""
    k = filtry.zagruzit(config.FILTRY_PATH)
    profil = filtry.aktivnye_profili(k)[0]
    for pravilo in profil["pravila"]:
        est = sum(1 for x in toshchie_kartochki if x[pravilo["pole"]] not in ("", 0, []))
        assert est > 0, f"поле {pravilo['pole']} пусто во всех тощих карточках"


def test_prodavec_est_v_toshchey(toshchie_kartochki):
    """Метка «собственник» - мягкое правило боевого профиля, и это главная
    причина, по которой поле автора осталось в тощем запросе."""
    assert any(k["prodavec"] for k in toshchie_kartochki)


def test_obogashchenie_dobavlyaet_opisanie_i_foto(istochnik, obogashchenie, k_eur):
    for vid, syroe in obogashchenie.items():
        k = normalizacia.privesti(istochnik.normalizovat(syroe, k_eur))
        assert k["vneshniy_id"] == vid
        assert k["foto"], "дообогащение обязано принести фото"
        assert k["opisanie"], "дообогащение обязано принести описание"
        for u in k["foto"]:
            assert u.startswith("https://i.simpalsmedia.com/999.md/BoardImages/")


def test_obogashchenie_ne_menyaet_cenu_i_sektor(istochnik, toshchiy_spisok, obogashchenie, k_eur):
    """Списочный и точечный запросы должны видеть одну и ту же карточку.

    Разъедутся - «цена упала» будет срабатывать на разнице между двумя
    запросами, а не на реальном движении цены.
    """
    toshchie = {s["id"]: istochnik.normalizovat(s, k_eur) for s in toshchiy_spisok}
    for vid, syroe in obogashchenie.items():
        if vid not in toshchie:
            continue
        polnaya = istochnik.normalizovat(syroe, k_eur)
        for pole in ("cena_eur", "sektor", "komnat", "ploshad_m2", "etazh", "sdelka"):
            assert polnaya[pole] == toshchie[vid][pole], (vid, pole)


def test_hash_ne_zavisit_ot_obogashcheniya(istochnik, toshchiy_spisok, obogashchenie, k_eur):
    """Хеш карточки не должен меняться от того, дотянули мы описание или нет.

    Иначе каждое дообогащение выглядело бы как правка карточки и порождало
    событие на пустом месте.
    """
    toshchie = {s["id"]: normalizacia.privesti(istochnik.normalizovat(s, k_eur))
                for s in toshchiy_spisok}
    for vid, syroe in obogashchenie.items():
        if vid not in toshchie:
            continue
        polnaya = normalizacia.privesti(istochnik.normalizovat(syroe, k_eur))
        assert normalizacia.hash_kartochki(polnaya) == \
            normalizacia.hash_kartochki(toshchie[vid]), vid


def test_v_obogashchenii_net_telefonov(istochnik, obogashchenie, k_eur):
    for syroe in obogashchenie.values():
        k = normalizacia.privesti(istochnik.normalizovat(syroe, k_eur))
        assert "+373" not in k["opisanie"]


def test_toshchiy_zapros_ne_prosit_opisanie_i_foto():
    """Контракт тощего запроса: если в него вернут body/images, обход снова
    станет полутораминутным и 150-мегабайтным, а расписание не влезет в лимит."""
    tekst = (KOREN / "istochniki" / "devyat999_spisok.graphql").read_text(encoding="utf-8")
    zapros = tekst[tekst.index("query SearchAds"):]
    assert "feature(id: 13)" not in zapros, "описание вернулось в тощий запрос"
    assert "feature(id: 14)" not in zapros, "фото вернулись в тощий запрос"
    assert "feature(id: 16)" not in zapros, "телефоны запрашивать нельзя"


def test_polnyy_zapros_telefony_ne_prosit():
    for imya in ("devyat999_zapros.graphql", "devyat999_odin.graphql"):
        tekst = (KOREN / "istochniki" / imya).read_text(encoding="utf-8")
        assert "feature(id: 16)" not in tekst, imya


def test_razmer_foto_iz_izvestnyh():
    """CDN 999.md отдаёт только 320x240 и 640x480, на остальное - 404.
    Telegram на 404 молча роняет sendPhoto, и карточка вырождается в текст
    без фотографии - без единой ошибки в логах."""
    from istochniki.devyat999 import FOTO_SHABLON, RAZMERY_FOTO
    assert any(f"/{r}/" in FOTO_SHABLON for r in RAZMERY_FOTO)
    assert FOTO_SHABLON.endswith("/{}")
