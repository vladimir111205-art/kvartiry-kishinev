"""Разбор сырых записей 999.md в канонические карточки. Всё на фикстуре."""
from __future__ import annotations

import normalizacia
from istochniki import devyat999_slovar as slovar
from istochniki.devyat999 import proverit_kontrakt


def test_kazhdaya_syraya_zapis_daet_kartochku(syroy_spisok, kartochki):
    # 60 сырых -> 60 карточек: ни одна не теряется по дороге.
    assert len(kartochki) == len(syroy_spisok) == 60


def test_u_kazhdoy_kartochki_polnyy_nabor_poley(kartochki):
    for k in kartochki:
        assert set(k) == set(normalizacia.POLYA)


def test_ni_odnogo_none_ni_v_odnom_pole(kartochki):
    # None в карточке = «None» в сообщении папе. Ловим здесь, а не в Telegram.
    for k in kartochki:
        for pole, znach in k.items():
            assert znach is not None, pole


def test_cena_i_ploshad_razobrany(kartochki):
    s_cenoy = [k for k in kartochki if k["cena_eur"] > 0]
    assert len(s_cenoy) == len(kartochki)
    s_ploshadyu = [k for k in kartochki if k["ploshad_m2"] > 0]
    assert len(s_ploshadyu) >= len(kartochki) * 0.9


def test_cena_v_leyah_perevedena_v_evro(kartochki, k_eur):
    lei = [k for k in kartochki if k["valyuta"] == "MDL"]
    assert lei, "в фикстуре должны быть объявления в леях"
    for k in lei:
        # 20 лей за евро с запасом в обе стороны: проверяем порядок, не курс.
        assert k["cena"] / 30 < k["cena_eur"] < k["cena"] / 10


def test_za_m2_soglasuetsya_s_cenoy(kartochki):
    for k in kartochki:
        if k["cena_eur"] and k["ploshad_m2"] and k["cena_eur_za_m2"]:
            svoe = k["cena_eur"] / k["ploshad_m2"]
            # Площадка округляет площадь до целых, поэтому допуск широкий.
            assert 0.8 < k["cena_eur_za_m2"] / svoe < 1.25, k["url"]


def test_sektory_raspoznany(kartochki):
    bez_sektora = [k for k in kartochki if not k["sektor"]]
    assert not bez_sektora, [k["zagolovok"] for k in bez_sektora[:3]]


def test_sdelki_raspoznany(kartochki):
    assert {k["sdelka"] for k in kartochki} <= {
        "prodazha", "arenda", "arenda_sutki", "pokupka", "snyat", "obmen"}
    assert any(k["sdelka"] == "prodazha" for k in kartochki)


def test_ssylka_i_foto_sobrany(kartochki):
    for k in kartochki:
        assert k["url"].startswith("https://999.md/ru/")
        assert k["vneshniy_id"] in k["url"]
    s_foto = [k for k in kartochki if k["foto"]]
    assert s_foto
    for u in s_foto[0]["foto"]:
        assert u.startswith("https://i.simpalsmedia.com/999.md/BoardImages/")


def test_telefony_vyrezany_iz_opisaniya():
    tekst = ("Продаю квартиру, звоните +373 69 123 456 или 069123456, "
             "телеграм @nedvizhka_md, срочно")
    chisto = normalizacia.bez_telefonov(tekst)
    assert "373" not in chisto
    assert "069123456" not in chisto
    assert "@nedvizhka_md" not in chisto
    assert "Продаю квартиру" in chisto


def test_v_fiksture_ne_ostalos_telefonov(kartochki):
    # Фикстура коммитится в git - чужих номеров в ней быть не должно.
    for k in kartochki:
        assert "+373" not in k["opisanie"]


def test_hash_menyaetsya_ot_ceny_no_ne_ot_opisaniya(kartochki):
    k = dict(kartochki[0])
    ishodnyy = normalizacia.hash_kartochki(k)
    k["opisanie"] = "совсем другой текст"
    assert normalizacia.hash_kartochki(k) == ishodnyy
    k["cena_eur"] = k["cena_eur"] - 1000
    assert normalizacia.hash_kartochki(k) != ishodnyy


def test_chuzhoe_pole_ne_prohodit_molcha():
    import pytest
    with pytest.raises(ValueError, match="нет в каноне"):
        normalizacia.privesti({"vneshniy_id": "1", "vydumannoe_pole": 5})


def test_kontrakt_otveta_ploshchadki(syroy_spisok):
    assert proverit_kontrakt(syroy_spisok) == []
    assert proverit_kontrakt([]) == ["площадка вернула ноль объявлений"]
    # Смена схемы: поле пропало во всех карточках разом.
    bez_ceny = [dict(a, price=None) for a in syroy_spisok]
    assert any("price" in p for p in proverit_kontrakt(bez_ceny))


def test_slovar_terpit_raznopisanie():
    assert slovar.sektor("Рышкановка") == "ryshkanovka"
    assert slovar.sektor("Râșcani") == "ryshkanovka"
    assert slovar.sektor("  ЧОКАНА ") == "chekany"
    assert slovar.sektor("Марс") == ""
    assert slovar.prodavec("Частное лицо") == "sobstvennik"
    assert slovar.prodavec("Агенство") == "agentstvo"   # опечатка площадки


# --- правдоподобие данных ---------------------------------------------------
# Реальный случай с 999.md: продавец ввёл площадь 42,46 м² как 4246, площадка
# честно поделила и получила 10 €/м², а объект стал «дешевле рынка на 99%» и
# встал первым в списке. Таких 0,2% от рынка, и они одни способны похоронить
# доверие к боту.

def horoshaya(**p) -> dict:
    k = normalizacia.pustaya()
    k.update({"sdelka": "prodazha", "cena_eur": 52000, "ploshad_m2": 55,
              "cena_eur_za_m2": 945})
    k.update(p)
    return normalizacia.privesti(k)


def test_normalnaya_kvartira_nadezhna():
    assert horoshaya()["dannye_nadezhny"] == 1


def test_ploshad_s_opechatkoy_nenadezhna():
    # 42,46 м² записанные как 4246 - тот самый боевой случай.
    assert horoshaya(ploshad_m2=4246, cena_eur=46500, cena_eur_za_m2=10)["dannye_nadezhny"] == 0


def test_kladovka_i_dvorec_nenadezhny():
    assert horoshaya(ploshad_m2=3)["dannye_nadezhny"] == 0
    assert horoshaya(ploshad_m2=900)["dannye_nadezhny"] == 0


def test_cena_za_metr_vne_razumnogo_nenadezhna():
    assert horoshaya(cena_eur_za_m2=140, cena_eur=7700)["dannye_nadezhny"] == 0
    assert horoshaya(cena_eur_za_m2=15000, cena_eur=825000)["dannye_nadezhny"] == 0


def test_cena_i_ploshad_dolzhny_shoditsya_s_cenoy_za_metr():
    # Цена и площадь дают 945 €/м², а площадка отдала 200 - кому-то из них
    # верить нельзя, значит с рынком такое не сравниваем.
    assert horoshaya(cena_eur_za_m2=200)["dannye_nadezhny"] == 0


def test_arenda_ne_meryaetsya_merkoy_prodazhi():
    # 500 € в месяц - нормальная аренда, но абсурдная цена продажи.
    assert horoshaya(sdelka="arenda", cena_eur=500, ploshad_m2=55,
                     cena_eur_za_m2=0)["dannye_nadezhny"] == 1
    assert horoshaya(sdelka="prodazha", cena_eur=500, ploshad_m2=55,
                     cena_eur_za_m2=0)["dannye_nadezhny"] == 0


def test_nepolnye_dannye_ne_schitayutsya_nenadezhnymi():
    # Площадка не отдала площадь - это не повод объявлять объявление битым.
    assert horoshaya(ploshad_m2=0, cena_eur_za_m2=0)["dannye_nadezhny"] == 1


def test_granicy_pravdopodobiya_v_konfige_a_ne_v_kode():
    """Правило 1 репо: пороги меняются в конфиге, а не правкой кода."""
    import inspect
    tekst = inspect.getsource(normalizacia.dannye_nadezhny)
    assert "config.PLOSHAD_OT_DO" in tekst
    assert "config.ZA_M2_OT_DO_PRODAZHA" in tekst


def test_rassrochka_lovitsya_po_opisaniyu():
    """В поле цены стоит первый взнос, а не цена квартиры: объект выглядит
    вдвое дешевле рынка и лезет в топ. Боевые примеры с 999.md."""
    for tekst in ("Prima rată 30% (19000)€ Preț: cel mai bun",
                  "Vand apartamentul personal in rate sau achitare integrala",
                  "Продаётся в рассрочку, первый взнос 20 000",
                  "Posibilitatea de achitare în rate fără bancă"):
        assert horoshaya(opisanie=tekst)["dannye_nadezhny"] == 0, tekst


def test_obychnoe_opisanie_ne_schitaetsya_rassrochkoy():
    assert horoshaya(opisanie="Светлая квартира, рядом парк и школа, "
                              "возможен торг")["dannye_nadezhny"] == 1
