"""Движок фильтров и, главное, его валидация.

Самый важный тест здесь - `test_opechatka_v_imeni_polya_ronyaet_zapusk`.
Опечатка, которая превращает фильтр в «пропускай всё», - худший баг в этом
агенте: папа получает лавину и перестаёт читать бота.
"""
from __future__ import annotations

import pytest
import yaml

import config
import filtry
from filtry import OshibkaKonfiga


def konf(pravila, myagkie=None) -> dict:
    return {
        "versiya": 1,
        "sbor": {"gorod": "kishinev", "sdelki": ["prodazha"], "komnat": [1, 2]},
        "rynok": {"okno_dney": 90, "minimum_obektov": 15, "porog_deshevle": 15},
        "profili": [{"imya": "т", "poluchatel": "papa", "pravila": pravila,
                     "myagkie": myagkie or []}],
    }


# --- боевой конфиг ----------------------------------------------------------

def test_boevoy_filtry_yaml_prohodit_proverku():
    filtry.zagruzit(config.FILTRY_PATH)


def test_boevoy_profil_ostavlyaet_ozhidaemoe(kartochki):
    k = filtry.zagruzit(config.FILTRY_PATH)
    profil = filtry.aktivnye_profili(k)[0]
    proshli = [x for x in kartochki if filtry.prohodit(x, profil)]
    # Профиль узкий: двушки 35-90к в трёх секторах, не последний этаж.
    # Из 60 свежих объявлений города проходят единицы - и это правильно.
    assert 0 <= len(proshli) <= 10
    for x in proshli:
        assert x["sdelka"] == "prodazha"
        assert x["komnat"] == 2
        assert 35000 <= x["cena_eur"] <= 90000
        assert x["sektor"] in ("botanika", "chekany", "ryshkanovka")
        assert x["etazh"] != x["etazhnost"]


# --- валидация --------------------------------------------------------------

def test_opechatka_v_imeni_polya_ronyaet_zapusk():
    with pytest.raises(OshibkaKonfiga) as e:
        filtry.proverit(konf([{"pole": "sektorr", "op": "ravno", "znachenie": "centr"}]))
    assert "sektorr" in str(e.value)
    assert "Доступные поля" in str(e.value)


def test_opechatka_v_operatore_ronyaet_zapusk():
    with pytest.raises(OshibkaKonfiga, match="нет оператора"):
        filtry.proverit(konf([{"pole": "sektor", "op": "равно", "znachenie": "centr"}]))


def test_pustoy_spisok_pravil_ronyaet_zapusk():
    # Профиль без правил пропустил бы весь рынок.
    with pytest.raises(OshibkaKonfiga, match="пропустил бы весь рынок"):
        filtry.proverit(konf([]))


def test_diapazon_zadom_naperyod_ronyaet_zapusk():
    with pytest.raises(OshibkaKonfiga, match="задом наперёд"):
        filtry.proverit(konf([{"pole": "cena_eur", "op": "mezhdu", "znachenie": [90000, 35000]}]))


def test_mezhdu_trebuet_dvuh_chisel():
    with pytest.raises(OshibkaKonfiga, match="список из двух"):
        filtry.proverit(konf([{"pole": "cena_eur", "op": "mezhdu", "znachenie": 35000}]))


def test_chislovoy_operator_ne_beret_stroku():
    with pytest.raises(OshibkaKonfiga, match="ждёт число"):
        filtry.proverit(konf([{"pole": "ploshad_m2", "op": "ne_menshe", "znachenie": "пятьдесят"}]))


def test_sravnenie_s_nesushchestvuyushchim_polem():
    with pytest.raises(OshibkaKonfiga, match="поля «etazhi» нет"):
        filtry.proverit(konf([{"pole": "etazh", "op": "ne_ravno_polyu", "znachenie": "etazhi"}]))


def test_myagkoe_pravilo_bez_metki_ronyaet_zapusk():
    with pytest.raises(OshibkaKonfiga, match="обязана"):
        filtry.proverit(konf(
            [{"pole": "sektor", "op": "ravno", "znachenie": "centr"}],
            [{"pole": "otklonenie_ot_rynka", "op": "ne_menshe", "znachenie": 15}]))


def test_neizvestnyy_poluchatel_ronyaet_zapusk():
    k = konf([{"pole": "sektor", "op": "ravno", "znachenie": "centr"}])
    k["profili"][0]["poluchatel"] = "sosed"
    with pytest.raises(OshibkaKonfiga, match="poluchatel"):
        filtry.proverit(k)


def test_povtor_imeni_profilya_ronyaet_zapusk():
    k = konf([{"pole": "sektor", "op": "ravno", "znachenie": "centr"}])
    k["profili"].append(dict(k["profili"][0]))
    with pytest.raises(OshibkaKonfiga, match="повторяется"):
        filtry.proverit(k)


def test_lishniy_klyuch_v_pravile_ronyaet_zapusk():
    with pytest.raises(OshibkaKonfiga, match="неизвестные ключи"):
        filtry.proverit(konf([{"pole": "sektor", "op": "ravno",
                               "znachenie": "centr", "znachenei": 1}]))


def test_krivoy_porog_rynka_ronyaet_zapusk():
    k = konf([{"pole": "sektor", "op": "ravno", "znachenie": "centr"}])
    k["rynok"]["minimum_obektov"] = 0
    with pytest.raises(OshibkaKonfiga, match="minimum_obektov"):
        filtry.proverit(k)


def test_bitiy_yaml_ronyaet_zapusk(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text("versiya: 1\n  кривой: [отступ\n", encoding="utf-8")
    with pytest.raises(OshibkaKonfiga, match="YAML не читается"):
        filtry.zagruzit(p)


# --- операторы --------------------------------------------------------------

KARTA = {
    "sektor": "botanika", "komnat": 2, "cena_eur": 52000.0, "ploshad_m2": 61.0,
    "etazh": 4, "etazhnost": 9, "opisanie": "Квартира с ремонтом, без мебели",
    "prodavec": "sobstvennik", "foto": ["a.jpg"], "otklonenie_ot_rynka": 22.0,
    "prezhnyaya_cena_eur": 0,
}


@pytest.mark.parametrize("p, zhdem", [
    ({"pole": "sektor", "op": "ravno", "znachenie": "botanika"}, True),
    ({"pole": "sektor", "op": "ravno", "znachenie": "BOTANIKA"}, True),
    ({"pole": "sektor", "op": "ne_ravno", "znachenie": "centr"}, True),
    ({"pole": "sektor", "op": "v_spiske", "znachenie": ["centr", "botanika"]}, True),
    ({"pole": "sektor", "op": "ne_v_spiske", "znachenie": ["centr"]}, True),
    ({"pole": "cena_eur", "op": "ne_menshe", "znachenie": 50000}, True),
    ({"pole": "cena_eur", "op": "ne_bolshe", "znachenie": 50000}, False),
    ({"pole": "cena_eur", "op": "mezhdu", "znachenie": [35000, 90000]}, True),
    ({"pole": "cena_eur", "op": "mezhdu", "znachenie": [90000, 120000]}, False),
    ({"pole": "opisanie", "op": "soderzhit", "znachenie": ["ремонт"]}, True),
    ({"pole": "opisanie", "op": "ne_soderzhit", "znachenie": ["первый этаж"]}, True),
    ({"pole": "foto", "op": "est", "znachenie": None}, True),
    ({"pole": "prezhnyaya_cena_eur", "op": "net", "znachenie": None}, True),
    ({"pole": "etazh", "op": "ne_ravno_polyu", "znachenie": "etazhnost"}, True),
])
def test_operatory(p, zhdem):
    assert filtry.pravilo_prohodit(KARTA, p) is zhdem


def test_posledniy_etazh_otsekaetsya():
    posledniy = dict(KARTA, etazh=9, etazhnost=9)
    p = {"pole": "etazh", "op": "ne_ravno_polyu", "znachenie": "etazhnost"}
    assert filtry.pravilo_prohodit(posledniy, p) is False


def test_pustoe_pole_ne_ronyaet_chislovoy_operator():
    # Площадка иногда не отдаёт площадь. Это «не подходит», а не падение.
    pusto = dict(KARTA, ploshad_m2="")
    assert filtry.pravilo_prohodit(
        pusto, {"pole": "ploshad_m2", "op": "ne_menshe", "znachenie": 50}) is False


def test_nepolnaya_kartochka_ronyaet_a_ne_molchit():
    with pytest.raises(OshibkaKonfiga, match="неполную карточку"):
        filtry.pravilo_prohodit({"sektor": "centr"},
                                {"pole": "cena_eur", "op": "ne_menshe", "znachenie": 1})


def test_myagkie_pravila_veshayut_metki():
    profil = {"imya": "т", "pravila": [], "myagkie": [
        {"pole": "otklonenie_ot_rynka", "op": "ne_menshe", "znachenie": 15,
         "metka": "дешевле рынка"},
        {"pole": "prodavec", "op": "ravno", "znachenie": "sobstvennik",
         "metka": "собственник"},
        {"pole": "komnat", "op": "ravno", "znachenie": 3, "metka": "трёшка"},
    ]}
    assert filtry.metki(KARTA, profil) == ["дешевле рынка", "собственник"]


def test_vyklyuchennyy_profil_ne_beretsya():
    k = konf([{"pole": "sektor", "op": "ravno", "znachenie": "centr"}])
    k["profili"][0]["aktiven"] = False
    assert filtry.aktivnye_profili(k) == []


def test_primer_iz_readme_zhivoy():
    """README обещает, что новый фильтр - одна строка YAML. Проверяем обещание."""
    tekst = """
versiya: 1
sbor: {gorod: kishinev, sdelki: [prodazha], komnat: [2]}
rynok: {okno_dney: 90, minimum_obektov: 15, porog_deshevle: 15}
profili:
  - imya: "двушки папе"
    poluchatel: papa
    pravila:
      - {pole: cena_eur, op: mezhdu, znachenie: [35000, 90000]}
      - {pole: sektor,   op: v_spiske, znachenie: [botanika, chekany]}
"""
    filtry.proverit(yaml.safe_load(tekst))
