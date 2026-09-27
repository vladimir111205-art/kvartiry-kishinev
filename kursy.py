"""Курсы MDL/USD/EUR.

Часть объявлений в леях и долларах, а вся оценка рынка - в евро за м².
Хардкодить курс нельзя (правило 1 репо), поэтому берём его у той же площадки
и кэшируем в базе с датой. Площадка не ответила - работаем на последнем
известном курсе, а не падаем: устаревший на день курс исказит оценку на
доли процента, а остановка прогона стоит целого окна наблюдения.
"""
from __future__ import annotations

VALYUTY = {
    "RATES_MAIN_CURRENCY_EUR": "EUR",
    "RATES_MAIN_CURRENCY_USD": "USD",
    "RATES_MAIN_CURRENCY_MDL": "MDL",
    "UNIT_EUR": "EUR",
    "UNIT_USD": "USD",
    "UNIT_MDL": "MDL",
    "UNIT_LEI": "MDL",
}

ZAPROS = {
    "operationName": "Kursy",
    "query": ("query Kursy { getMainCurrenciesRates { mainCurrenciesRates "
              "{ key ratios { key value } } } }"),
    "variables": {},
}


def valyuta(kod: str) -> str:
    """'UNIT_EUR' -> 'EUR'. Незнакомое оставляем как есть, чтобы было видно."""
    return VALYUTY.get(str(kod or "").strip().upper(), str(kod or "").strip().upper())


def razobrat(otvet: dict) -> dict:
    """Ответ площадки -> {'MDL': 0.0497, 'USD': 0.8669, 'EUR': 1.0} - сколько евро в единице."""
    blok = ((otvet or {}).get("data") or {}).get("getMainCurrenciesRates") or {}
    k_eur = {}
    for stroka in blok.get("mainCurrenciesRates") or []:
        iz = valyuta(stroka.get("key"))
        for r in stroka.get("ratios") or []:
            if valyuta(r.get("key")) == "EUR":
                try:
                    znach = float(r.get("value"))
                except (TypeError, ValueError):
                    continue
                if znach > 0:
                    k_eur[iz] = znach
    k_eur["EUR"] = 1.0
    return k_eur


def v_evro(summa: float, val: str, k_eur: dict) -> float:
    """Перевести сумму в евро. Курса нет - возвращаем 0, а не выдумываем число."""
    try:
        summa = float(summa)
    except (TypeError, ValueError):
        return 0.0
    if summa <= 0:
        return 0.0
    kurs = k_eur.get(valyuta(val))
    if not kurs:
        return 0.0
    return round(summa * kurs, 2)


def svezhie(post, sohranit=None, posledniy=None) -> dict:
    """Взять курсы у площадки; не вышло - отдать последние известные.

    `post` - функция запроса к площадке, `sohranit`/`posledniy` - работа с
    базой. Всё через аргументы, чтобы модуль тестировался без сети и без БД.
    """
    try:
        k_eur = razobrat(post(ZAPROS))
    except Exception as e:
        print(f"[kursy] площадка не ответила ({type(e).__name__}), берём последние известные")
        k_eur = {}
    if len(k_eur) < 2:       # только EUR - значит настоящих курсов не пришло
        k_eur = (posledniy() if posledniy else {}) or {}
        k_eur.setdefault("EUR", 1.0)
    elif sohranit:
        sohranit(k_eur)
    return k_eur
