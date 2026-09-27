"""Курсы валют. Хардкод курса запрещён правилом 1 репо, значит надо проверить,
что отказ площадки не превращается ни в падение, ни в выдуманное число."""
from __future__ import annotations

import kursy


def test_razobrat_daet_kurs_k_evro(syrye_kursy):
    k = kursy.razobrat(syrye_kursy)
    assert k["EUR"] == 1.0
    assert 0.03 < k["MDL"] < 0.08     # ~20 лей за евро
    assert 0.7 < k["USD"] < 1.1


def test_perevod_v_evro(k_eur):
    assert kursy.v_evro(1000, "UNIT_EUR", k_eur) == 1000
    assert 40 < kursy.v_evro(1000, "UNIT_MDL", k_eur) < 60
    assert 700 < kursy.v_evro(1000, "USD", k_eur) < 1000


def test_neizvestnaya_valyuta_ne_vydumyvaet_chislo(k_eur):
    # Ноль виден и в базе, и в карточке. Молча посчитать по курсу «примерно»
    # значит соврать цифрой, на которую человек будет принимать решение.
    assert kursy.v_evro(1000, "UNIT_GBP", k_eur) == 0.0


def test_musor_vmesto_summy_ne_ronyaet(k_eur):
    assert kursy.v_evro(None, "EUR", k_eur) == 0.0
    assert kursy.v_evro("договорная", "EUR", k_eur) == 0.0
    assert kursy.v_evro(-5, "EUR", k_eur) == 0.0


def test_ploshchadka_ne_otvetila_beryom_posledniy_izvestnyy():
    def upal(_):
        raise RuntimeError("сеть отвалилась")
    k = kursy.svezhie(upal, posledniy=lambda: {"MDL": 0.05, "USD": 0.87})
    assert k["MDL"] == 0.05
    assert k["EUR"] == 1.0


def test_ploshchadka_otvetila_pustotoy_tozhe_beryom_posledniy():
    k = kursy.svezhie(lambda _: {"data": {"getMainCurrenciesRates": {}}},
                      posledniy=lambda: {"MDL": 0.05})
    assert k["MDL"] == 0.05


def test_svezhie_kursy_sohranyayutsya(syrye_kursy):
    sohraneno = {}
    kursy.svezhie(lambda _: syrye_kursy, sohranit=sohraneno.update)
    assert "MDL" in sohraneno


def test_ni_odnogo_kursa_ne_zahardkozheno():
    """В коде не должно быть числа вроде 19.5 или 0.05 как курса."""
    import inspect
    tekst = inspect.getsource(kursy)
    # Единственная константа - EUR к самому себе.
    chisla = [s for s in tekst.split() if s.replace(".", "").isdigit() and "." in s]
    assert set(chisla) <= {"1.0", "0.0"}, chisla
