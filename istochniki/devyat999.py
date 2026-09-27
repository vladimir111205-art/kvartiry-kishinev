"""Источник 999.md: GraphQL-клиент и нормализация.

Сеть живёт только в `sobrat`. `normalizovat` - чистая функция, поэтому все
тесты разбора идут на фикстуре и без интернета.

Схема может смениться при следующем деплое сайта (риск R2 плана), поэтому
текст запроса лежит отдельным файлом `devyat999_zapros.graphql`, а не в коде,
и контрактный тест проверяет обязательные поля в ответе.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent))

import config                     # noqa: E402
import kursy as kursy_mod         # noqa: E402
from istochniki import devyat999_slovar as slovar   # noqa: E402

URL = "https://999.md/graphql"
# Тощий - для полного обхода рынка каждый прогон. Полный - для точечного
# дообогащения тех карточек, что реально уходят в Telegram.
ZAPROS_FAYL = BASE / "devyat999_spisok.graphql"
ZAPROS_ODIN_FAYL = BASE / "devyat999_odin.graphql"

PODKATEGORIYA_KVARTIRY = 1404
FILTR_REGION = 32
FICHA_REGION = 7
FICHA_GOROD = 8
REGION_KISHINEV_MUN = 12900
GOROD_KISHINEV = 13859

NA_STRANICE = 500   # больше площадка игнорирует, проверено

# CDN 999.md отдаёт ровно два размера: 640x480 и 320x240. На всё остальное -
# 404, а Telegram на 404 молча роняет sendPhoto, и карточка вырождается в
# текст без фотографии, без единой ошибки в логах. Проверено 17.09.2026.
RAZMERY_FOTO = ("640x480", "320x240")
FOTO_SHABLON = "https://i.simpalsmedia.com/999.md/BoardImages/%s/{}" % RAZMERY_FOTO[0]


def _zagolovki() -> dict:
    return {
        "content-type": "application/json",
        "accept": "*/*",
        "lang": "ru",
        "source": "mobile_redesign",
        "origin": "https://999.md",
        "referer": "https://999.md/ru/list/real-estate/apartments-and-rooms",
        "accept-language": "ru-RU,ru;q=0.9",
        "user-agent": config.USER_AGENT,
    }


class OshibkaPloshchadki(Exception):
    """Площадка не отдала данные. Наверх уходит алертом, а не тихим нулём."""


def post(telo: dict) -> dict:
    """POST с повторами. Последняя ошибка поднимается наружу, а не глотается."""
    posledniaya = None
    for popytka in range(1, config.POPYTOK_SETI + 1):
        try:
            req = urllib.request.Request(
                URL, data=json.dumps(telo).encode("utf-8"),
                headers=_zagolovki(), method="POST")
            with urllib.request.urlopen(req, timeout=config.TAYMAUT_SEK) as r:
                otvet = json.loads(r.read().decode("utf-8"))
            if otvet.get("errors"):
                raise OshibkaPloshchadki(
                    "GraphQL вернул ошибки: "
                    + json.dumps(otvet["errors"], ensure_ascii=False)[:500])
            return otvet
        except urllib.error.HTTPError as e:
            posledniaya = OshibkaPloshchadki(f"HTTP {e.code} {e.reason}")
        except OshibkaPloshchadki as e:
            # Ошибка схемы повторами не лечится - сразу наверх.
            raise
        except Exception as e:
            posledniaya = OshibkaPloshchadki(f"{type(e).__name__}: {e}")
        if popytka < config.POPYTOK_SETI:
            time.sleep(config.PAUZA_MEZHDU_POPYTKAMI_SEK * popytka)
    raise posledniaya or OshibkaPloshchadki("неизвестная ошибка сети")


def _znach(feat):
    """Развернуть feature: {'value': X} -> X, где X бывает словарём или списком."""
    if not feat:
        return None
    return feat.get("value")


def _perevod(feat) -> str:
    """Опция площадки -> её русский текст."""
    v = _znach(feat)
    if isinstance(v, dict):
        return str(v.get("translated") or "")
    return str(v or "")


def _chislo_opcii(feat):
    """Этаж и этажность приходят опцией, где translated - это само число."""
    v = _znach(feat)
    if isinstance(v, dict):
        return v.get("translated")
    return v


def _tekst_opisaniya(feat) -> str:
    """Описание приходит словарём языков {'ru': ..., 'ro': ...}."""
    v = _znach(feat)
    if isinstance(v, dict):
        return str(v.get("ru") or v.get("ro") or "")
    return str(v or "")


class Devyat999:
    imya = "999md"
    # Что площадка умеет отфильтровать на своей стороне. Это только экономия
    # трафика: всё равно всё перепроверяется локальными предикатами.
    vozmozhnosti = {"gorod": True, "sdelka": True, "komnat": True, "cena": True}

    def __init__(self, zapros_fayl: Path = ZAPROS_FAYL,
                 zapros_odin_fayl: Path = ZAPROS_ODIN_FAYL):
        self.zapros = Path(zapros_fayl).read_text(encoding="utf-8")
        self.zapros_odin = Path(zapros_odin_fayl).read_text(encoding="utf-8")

    # --- сеть ---------------------------------------------------------------
    def _telo(self, limit: int, skip: int) -> dict:
        return {
            "operationName": "SearchAds",
            "query": self.zapros,
            "variables": {
                "locale": "ru_RU",
                "input": {
                    "subCategoryId": PODKATEGORIYA_KVARTIRY,
                    "source": "AD_SOURCE_DESKTOP_REDESIGN",
                    "sort": "SORT_ADS_DATE_DESC",
                    "pagination": {"limit": limit, "skip": skip},
                    # Только город, без региона. Если задать оба, площадка
                    # применяет регион и игнорирует город, подмешивая сёла
                    # муниципия - 11% выдачи. Проверено 17.09.2026.
                    "filters": [{
                        "filterId": FILTR_REGION,
                        "features": [
                            {"featureId": FICHA_GOROD, "optionIds": [GOROD_KISHINEV]},
                        ],
                    }],
                },
            },
        }

    def skolko_vsego(self) -> int:
        """Сколько объявлений по нашему фильтру. Одна дешёвая страница в ноль строк."""
        otvet = post(self._telo(1, 0))
        return int((((otvet.get("data") or {}).get("searchAds")) or {}).get("count") or 0)

    def sobrat(self, nastroyki: dict = None, limit: int = 0) -> list:
        """Полный обход рынка тощим запросом, страницы параллельно.

        Почему весь рынок каждый прогон, а не «что изменилось». У площадки нет
        ни фильтра по дате изменения, ни сортировки по ней - только по дате
        подъёма. Продавец может снизить цену не поднимая объявление, и такая
        карточка останется глубоко в списке. Отец просил узнавать о смене цены
        первым, значит смотреть надо весь список.

        Почему параллельно. Последовательный обход идёт под две минуты, и за это
        время список успевает сдвинуться: новые объявления поднимаются наверх,
        страницы съезжают, и часть карточек приходит дважды, а часть теряется
        (замер: 22 965 уникальных из 23 020). В четыре потока обход занимает 12
        секунд, сдвига практически нет (23 019 из 23 019).
        """
        vsego = self.skolko_vsego()
        if not vsego:
            return []
        if limit:
            vsego = min(vsego, limit)
        stranic = min((vsego + NA_STRANICE - 1) // NA_STRANICE,
                      config.MAX_STRANIC_ZA_PROGON)

        def stranica(nomer: int) -> list:
            otvet = post(self._telo(NA_STRANICE, nomer * NA_STRANICE))
            return (((otvet.get("data") or {}).get("searchAds")) or {}).get("ads") or []

        with ThreadPoolExecutor(max_workers=config.POTOKOV_SBORA) as pul:
            kuski = list(pul.map(stranica, range(stranic)))

        # Дедуп по id: даже за 12 секунд список может чуть сдвинуться.
        po_id, porydok = {}, []
        for kusok in kuski:
            for a in kusok:
                vid = a.get("id")
                if vid and vid not in po_id:
                    po_id[vid] = a
                    porydok.append(vid)
        return [po_id[v] for v in porydok]

    def obogatit(self, vneshnie_id: list) -> dict:
        """Дотянуть описание и фото по конкретным объявлениям.

        Тощий обход их не тянет - это 90% веса ответа. Дотягиваем только те
        карточки, что действительно уходят в Telegram: их единицы за прогон.
        Заодно чужие описания (а в них продавцы пишут свои телефоны) попадают
        к нам по единицам, а не по 23 000 за раз.
        """
        return {vid: syroe for vid, syroe in self.po_id(vneshnie_id) if syroe}

    def po_id(self, vneshnie_id: list) -> list:
        """Точечная проверка конкретных объявлений - нужна избранному.

        Возвращает список пар (id, сырая_карточка_или_None). None означает, что
        площадка объявление больше не отдаёт: снято, продано или скрыто.
        Именно этот случай по избранному уходит немедленным сообщением, а не
        строкой в вечерней сводке.
        """
        out = []
        for vid in vneshnie_id:
            telo = {
                "operationName": "Advert",
                "query": self.zapros_odin,
                "variables": {"id": str(vid), "locale": "ru_RU"},
            }
            try:
                otvet = post(telo)
                out.append((str(vid), (otvet.get("data") or {}).get("advert")))
            except OshibkaPloshchadki as e:
                # Сеть моргнула - это не «снято». Молчим до следующего прогона:
                # ложная тревога по избранному хуже опоздания на полчаса.
                print(f"[999md] объявление {vid} не проверено: {e}")
            time.sleep(config.PAUZA_MEZHDU_STRANICAMI_SEK)
        return out

    def kursy(self) -> dict:
        return kursy_mod.razobrat(post(kursy_mod.ZAPROS))

    # --- разбор (без сети) --------------------------------------------------
    def normalizovat(self, syroe: dict, k_eur: dict = None) -> dict:
        k_eur = k_eur or {"EUR": 1.0}

        cena_blok = _znach(syroe.get("price")) or {}
        if isinstance(cena_blok, dict):
            cena = cena_blok.get("value")
            val = kursy_mod.valyuta(cena_blok.get("unit") or cena_blok.get("measurement"))
        else:
            cena, val = cena_blok, "EUR"
        cena_eur = kursy_mod.v_evro(cena, val, k_eur)

        ploshad = _znach(syroe.get("area"))
        if isinstance(ploshad, dict):
            ploshad = ploshad.get("value")

        # €/м² площадка считает сама, но в валюте объявления - пересчитываем.
        za_m2 = kursy_mod.v_evro(_znach(syroe.get("pricePerM2")), val, k_eur)
        if not za_m2 and cena_eur and ploshad:
            try:
                za_m2 = round(cena_eur / float(ploshad), 2)
            except (TypeError, ValueError, ZeroDivisionError):
                za_m2 = 0

        # Комнатность приходит текстом «2-комнатная квартира».
        komnat_text = _perevod(syroe.get("rooms"))
        komnat = "".join(c for c in komnat_text[:2] if c.isdigit())

        foto = [FOTO_SHABLON.format(f) for f in (_znach(syroe.get("images")) or [])
                if isinstance(f, str)]

        vid = str(syroe.get("id") or "")
        return {
            "istochnik": self.imya,
            "vneshniy_id": vid,
            "url": f"https://999.md/ru/{vid}" if vid else "",
            "zagolovok": syroe.get("title") or "",
            "sdelka": slovar.sdelka(_perevod(syroe.get("offerType"))),
            "gorod": slovar.gorod(_perevod(syroe.get("city"))),
            "sektor": slovar.sektor(_perevod(syroe.get("district"))),
            "ulica": _znach(syroe.get("street")) or "",
            "cena": cena,
            "valyuta": val,
            "cena_eur": cena_eur,
            "cena_eur_za_m2": za_m2,
            "prezhnyaya_cena_eur": kursy_mod.v_evro(_znach(syroe.get("oldPrice")), val, k_eur),
            "komnat": komnat,
            "ploshad_m2": ploshad,
            "etazh": _chislo_opcii(syroe.get("floor")),
            "etazhnost": _chislo_opcii(syroe.get("floors")),
            "tip_doma": slovar.tip_doma(_perevod(syroe.get("buildType"))),
            "sostoyanie": slovar.sostoyanie(_perevod(syroe.get("condition"))),
            "fond": slovar.fond(_perevod(syroe.get("housingFund"))),
            "prodavec": slovar.prodavec(_perevod(syroe.get("author"))),
            "avtor_login": (syroe.get("owner") or {}).get("login") or "",
            "opisanie": _tekst_opisaniya(syroe.get("body")),
            "foto": foto,
            "podnyato_at": syroe.get("reseted") or "",
            "otklonenie_ot_rynka": 0,
            # Проставит normalizacia.privesti(), ей нужны уже приведённые числа.
            "dannye_nadezhny": 1,
        }


# Обязательные поля ответа: их пропажа означает смену схемы (R2).
OBYAZATELNYE_POLYA = ("id", "title", "price", "rooms", "area", "district", "offerType")


def proverit_kontrakt(ads: list) -> list:
    """Вернуть список претензий к ответу площадки. Пустой список - всё в порядке."""
    if not ads:
        return ["площадка вернула ноль объявлений"]
    pretenzii = []
    for pole in OBYAZATELNYE_POLYA:
        est = sum(1 for a in ads if a.get(pole) is not None)
        # Часть полей объявления заполняют не всегда, но не у всех же разом.
        if est == 0:
            pretenzii.append(f"поле «{pole}» пусто во всех {len(ads)} карточках")
    return pretenzii
