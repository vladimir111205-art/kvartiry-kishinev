"""SPIKE фазы 1: пустит ли 999.md обычный HTTP-клиент с IP раннера GitHub.

Гейт всего проекта. Пока не доказано, что POST /graphql с датацентрового IP
возвращает настоящие объявления с ценами, ядро писать нельзя (риск R1 плана).

Печатает отчёт в лог Actions и выходит с ненулевым кодом, если гейт не прошёл.
Ничего никуда не шлёт и ничего не пишет в базу.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
ZAPROS = BASE / "istochniki" / "devyat999_zapros.graphql"

URL = "https://999.md/graphql"
PODKATEGORIYA_KVARTIRY = 1404
REGION_KISHINEV_MUN = 12900        # feature 7
GOROD_KISHINEV = 13859             # feature 8
FILTR_REGION = 32
NADO_OBYAVLENIY = 20               # порог гейта из плана

ZAGOLOVKI = {
    "content-type": "application/json",
    "accept": "*/*",
    "lang": "ru",
    "source": "mobile_redesign",
    "origin": "https://999.md",
    "referer": "https://999.md/ru/list/real-estate/apartments-and-rooms",
    "accept-language": "ru-RU,ru;q=0.9",
    "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
}


def zapros_spiska(limit: int = 30, skip: int = 0) -> dict:
    return {
        "operationName": "SearchAds",
        "query": ZAPROS.read_text(encoding="utf-8"),
        "variables": {
            "locale": "ru_RU",
            "input": {
                "subCategoryId": PODKATEGORIYA_KVARTIRY,
                "source": "AD_SOURCE_DESKTOP_REDESIGN",
                "sort": "SORT_ADS_DATE_DESC",
                "pagination": {"limit": limit, "skip": skip},
                "filters": [{
                    "filterId": FILTR_REGION,
                    "features": [
                        {"featureId": 7, "optionIds": [REGION_KISHINEV_MUN]},
                        {"featureId": 8, "optionIds": [GOROD_KISHINEV]},
                    ],
                }],
            },
        },
    }


ZAPROS_KURSY = {
    "operationName": "Kursy",
    "query": ("query Kursy { getMainCurrenciesRates { mainCurrenciesRates "
              "{ key ratios { key value } } } }"),
    "variables": {},
}


def post(telo: dict, taymaut: int = 30) -> dict:
    req = urllib.request.Request(
        URL, data=json.dumps(telo).encode("utf-8"), headers=ZAGOLOVKI, method="POST")
    with urllib.request.urlopen(req, timeout=taymaut) as r:
        return json.loads(r.read().decode("utf-8"))


def znachenie(feat) -> str:
    """Поле feature приходит как {id,type,value} либо как список таких словарей."""
    if not feat:
        return ""
    if isinstance(feat, list):
        return "; ".join(str(f.get("value", "")) for f in feat if f)
    return str(feat.get("value", ""))


def main() -> int:
    print("=== SPIKE 999.md: гейт фазы 1 ===")

    try:
        kursy = post(ZAPROS_KURSY)
    except Exception as e:
        print(f"ПРОВАЛ: курсы валют не получены: {type(e).__name__}: {e}")
        return 2
    rates = (kursy.get("data") or {}).get("getMainCurrenciesRates") or {}
    print(f"Курсы: получено {len(rates.get('mainCurrenciesRates') or [])} валют")

    try:
        otvet = post(zapros_spiska())
    except urllib.error.HTTPError as e:
        print(f"ПРОВАЛ: HTTP {e.code} {e.reason}")
        print((e.read()[:800]).decode("utf-8", "replace"))
        return 2
    except Exception as e:
        print(f"ПРОВАЛ: {type(e).__name__}: {e}")
        return 2

    if otvet.get("errors"):
        print("ПРОВАЛ: GraphQL вернул ошибки:")
        print(json.dumps(otvet["errors"], ensure_ascii=False, indent=2)[:1500])
        return 2

    blok = (otvet.get("data") or {}).get("searchAds") or {}
    ads = blok.get("ads") or []
    print(f"Всего по фильтру на площадке: {blok.get('count')}")
    print(f"Отдано в этом ответе: {len(ads)}")

    s_cenoy = [a for a in ads if znachenie(a.get("price")).strip()]
    print(f"Из них с непустой ценой: {len(s_cenoy)}")

    print("\n--- первые 3 карточки ---")
    for a in ads[:3]:
        print(json.dumps({
            "id": a.get("id"),
            "zagolovok": (a.get("title") or "")[:70],
            "sdelka": znachenie(a.get("offerType")),
            "cena": znachenie(a.get("price")),
            "za_m2": znachenie(a.get("pricePerM2")),
            "komnat": znachenie(a.get("rooms")),
            "ploshad": znachenie(a.get("area")),
            "etazh": znachenie(a.get("floor")),
            "etazhnost": znachenie(a.get("floors")),
            "sektor": znachenie(a.get("district")),
            "ulica": znachenie(a.get("street")),
            "sostoyanie": znachenie(a.get("condition")),
            "tip_doma": znachenie(a.get("buildType")),
            "prodavec": znachenie(a.get("author")),
            "login": (a.get("owner") or {}).get("login"),
            "podnyato": a.get("reseted"),
            "foto": len(a.get("images") or []),
        }, ensure_ascii=False))

    if len(s_cenoy) < NADO_OBYAVLENIY:
        print(f"\nПРОВАЛ ГЕЙТА: карточек с ценой {len(s_cenoy)}, нужно >= {NADO_OBYAVLENIY}")
        return 1

    print(f"\nГЕЙТ ПРОЙДЕН: {len(s_cenoy)} карточек с ценой (порог {NADO_OBYAVLENIY})")

    if "--fikstura" in sys.argv:
        (BASE / "fixtures").mkdir(exist_ok=True)
        (BASE / "fixtures" / "999md_spisok.json").write_text(
            json.dumps(otvet, ensure_ascii=False, indent=1), encoding="utf-8")
        (BASE / "fixtures" / "999md_kursy.json").write_text(
            json.dumps(kursy, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Фикстуры сохранены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
