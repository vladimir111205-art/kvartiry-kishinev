"""Медианы и отклонение от рынка.

Главное, что здесь проверяется, - что агент **молчит, когда сказать нечего**.
Метка «дешевле рынка» это приглашение посмотреть объект, и поставить её по
выборке из трёх квартир значит соврать цифрой, на которую человек будет
принимать решение о деньгах.
"""
from __future__ import annotations

import pytest

import db
import normalizacia
import rynok


@pytest.fixture
def con(tmp_path):
    s = db.connect(tmp_path / "t.db")
    yield s
    s.close()


def zalit(con, sektor, komnat, za_m2_spisok, sdelka="prodazha", dney_nazad=0,
          gorod="kishinev"):
    for i, za_m2 in enumerate(za_m2_spisok):
        k = normalizacia.pustaya()
        k.update({
            "istochnik": "999md", "vneshniy_id": f"{gorod}-{sektor}-{komnat}-{i}-{sdelka}",
            "sdelka": sdelka, "gorod": gorod, "sektor": sektor, "komnat": komnat,
            "ploshad_m2": 60, "cena_eur": za_m2 * 60, "cena_eur_za_m2": za_m2,
            "valyuta": "EUR",
        })
        # Через privesti, как в бою: иначе карточка не получит dannye_nadezhny
        # и тест будет проверять не тот путь, которым идут настоящие данные.
        db.zapisat(con, normalizacia.privesti(k))
    con.execute(
        "UPDATE obyavleniya SET podnyato_at = date('now', ?) WHERE podnyato_at = ''",
        (f"-{dney_nazad} day",))
    con.commit()


def test_mediana_schitaetsya_kogda_vyborki_hvataet(con):
    zalit(con, "botanika", 2, list(range(1000, 1020)))    # 20 объектов
    m = rynok.sobrat_mediany(con, minimum=15)
    assert ("kishinev", "botanika", 2) in m
    assert m[("kishinev", "botanika", 2)]["obektov"] == 20
    assert 1009 <= m[("kishinev", "botanika", 2)]["mediana"] <= 1010


def test_malaya_vyborka_ne_daet_mediany(con):
    zalit(con, "chekany", 3, [1000] * 14)                 # 14 < 15
    assert ("kishinev", "chekany", 3) not in rynok.sobrat_mediany(con, minimum=15)


def test_metka_ne_stavitsya_poka_baza_melkaya(con):
    """Первые недели агент работает как уведомитель - и это нормально."""
    zalit(con, "chekany", 3, [1000] * 5)
    m = rynok.sobrat_mediany(con, minimum=15)
    deshevaya = {"gorod": "kishinev", "sektor": "chekany", "komnat": 3, "cena_eur_za_m2": 400}
    assert rynok.otklonenie(deshevaya, m) == 0.0


def test_odna_dorogaya_kvartira_ne_sdvigaet_ocenku_sektora(con):
    """Медиана, а не среднее: пентхаус за 500 000 € не должен портить сектор."""
    zalit(con, "centr", 2, [1000] * 19 + [20000])
    m = rynok.sobrat_mediany(con, minimum=15)
    assert m[("kishinev", "centr", 2)]["mediana"] == 1000


def test_otklonenie_schitaetsya_v_procentah(con):
    zalit(con, "botanika", 2, [1000] * 20)
    m = rynok.sobrat_mediany(con, minimum=15)
    assert rynok.otklonenie({"gorod": "kishinev", "sektor": "botanika", "komnat": 2,
                             "cena_eur_za_m2": 800}, m) == 20.0
    assert rynok.otklonenie({"gorod": "kishinev", "sektor": "botanika", "komnat": 2,
                             "cena_eur_za_m2": 1200}, m) == -20.0
    assert rynok.otklonenie({"gorod": "kishinev", "sektor": "botanika", "komnat": 2,
                             "cena_eur_za_m2": 1000}, m) == 0.0


def test_bez_ceny_za_metr_otklonenie_ne_vydumyvaetsya(con):
    zalit(con, "botanika", 2, [1000] * 20)
    m = rynok.sobrat_mediany(con, minimum=15)
    assert rynok.otklonenie({"gorod": "kishinev", "sektor": "botanika", "komnat": 2, "cena_eur_za_m2": 0}, m) == 0.0


def test_gruppy_ne_smeshivayutsya_po_komnatnosti(con):
    zalit(con, "botanika", 1, [2000] * 20)
    zalit(con, "botanika", 2, [1000] * 20)
    m = rynok.sobrat_mediany(con, minimum=15)
    assert m[("kishinev", "botanika", 1)]["mediana"] == 2000
    assert m[("kishinev", "botanika", 2)]["mediana"] == 1000


def test_arenda_ne_meshaetsya_v_medianu_prodazhi(con):
    """500 €/мес и 50 000 € - величины из разных миров."""
    zalit(con, "botanika", 2, [1000] * 20, sdelka="prodazha")
    zalit(con, "botanika", 2, [8] * 20, sdelka="arenda")
    m = rynok.sobrat_mediany(con, minimum=15, sdelka="prodazha")
    assert m[("kishinev", "botanika", 2)]["mediana"] == 1000
    assert m[("kishinev", "botanika", 2)]["obektov"] == 20


def test_staroe_ne_uchastvuet_v_okne(con):
    zalit(con, "botanika", 2, [1000] * 20, dney_nazad=200)
    assert rynok.sobrat_mediany(con, okno_dney=90, minimum=15) == {}


def test_snyatye_s_prodazhi_ne_uchastvuyut(con):
    zalit(con, "botanika", 2, [1000] * 20)
    con.execute("UPDATE obyavleniya SET aktivno = 0")
    con.commit()
    assert rynok.sobrat_mediany(con, minimum=15) == {}


def test_selo_municipiya_ne_smeshivaetsya_s_gorodom(con):
    """У села Колоница тоже есть сектор «Центр». Без города в ключе его
    квартиры по 800 €/м² утянули бы центр Кишинёва вниз, и объекты города
    начали бы выглядеть «дороже рынка»."""
    zalit(con, "centr", 2, [2000] * 20, gorod="kishinev")
    zalit(con, "centr", 2, [800] * 20, gorod="kolonica")
    m = rynok.sobrat_mediany(con, minimum=15)
    assert m[("kishinev", "centr", 2)]["mediana"] == 2000
    assert m[("kolonica", "centr", 2)]["mediana"] == 800
    # Квартира Кишинёва сравнивается с Кишинёвом, а не со средним по муниципию.
    kishinevskaya = {"gorod": "kishinev", "sektor": "centr", "komnat": 2,
                     "cena_eur_za_m2": 2000, "dannye_nadezhny": 1}
    assert rynok.otklonenie(kishinevskaya, m) == 0.0


def test_bez_goroda_ne_uchastvuet(con):
    zalit(con, "centr", 2, [1000] * 20, gorod="")
    assert rynok.sobrat_mediany(con, minimum=15) == {}


def test_bez_sektora_ne_uchastvuet(con):
    zalit(con, "", 2, [1000] * 20)
    assert rynok.sobrat_mediany(con, minimum=15) == {}


def test_prostavit_otkloneniya_zapolnyaet_pole(con):
    zalit(con, "botanika", 2, [1000] * 20)
    m = rynok.sobrat_mediany(con, minimum=15)
    kartochki = [{"gorod": "kishinev", "sektor": "botanika", "komnat": 2, "cena_eur_za_m2": 850,
                  "otklonenie_ot_rynka": 0}]
    rynok.prostavit_otkloneniya(kartochki, m)
    assert kartochki[0]["otklonenie_ot_rynka"] == 15.0


def test_v_soobshchenie_idet_i_razmer_vyborki(con):
    """«Медиана сектора 1 210 €/м²» без числа объектов - цифра без веса."""
    zalit(con, "botanika", 2, [1000] * 20)
    m = rynok.sobrat_mediany(con, minimum=15)
    g = rynok.mediana_gruppy({"gorod": "kishinev", "sektor": "botanika", "komnat": 2}, m)
    assert g["mediana"] == 1000 and g["obektov"] == 20
    assert rynok.mediana_gruppy({"gorod": "kishinev", "sektor": "mars", "komnat": 2}, m) == {}


def test_dvizhenie_mediany_za_nedelyu(con):
    zalit(con, "botanika", 2, [1000] * 20)
    # Неделю назад те же объекты стоили дороже.
    for r in con.execute("SELECT id FROM obyavleniya").fetchall():
        con.execute(
            "INSERT INTO istoriya_cen (obyavlenie_id, cena_eur, zamecheno_at) "
            "VALUES (?, ?, datetime('now', '-8 day'))", (r["id"], 1100 * 60))
    con.commit()
    d = rynok.dvizhenie_mediany(con, "botanika", 2, dney_nazad=7, minimum=15)
    assert d["bylo"] == 1100 and d["seychas"] == 1000
    assert d["izmenenie_pct"] == pytest.approx(-9.1, abs=0.1)


def test_dvizhenie_molchit_na_maloy_vyborke(con):
    zalit(con, "botanika", 2, [1000] * 5)
    assert rynok.dvizhenie_mediany(con, "botanika", 2, minimum=15) == {}
