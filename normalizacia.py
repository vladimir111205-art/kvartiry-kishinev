"""Канонический словарь карточки - единственная форма, которую знает ядро.

Всё, что приходит с площадок, приводится сюда. Фильтры, база, рынок и шаблоны
сообщений работают только с этими полями и ни с какими другими. Добавить новое
поле - строка в POLYA плюс строка в словаре источника, больше нигде.

Телефоны из описаний вырезаются на входе. Продавцы пишут их в тексте, нам они
не нужны ни для одного фильтра, а хранить чужие персональные данные, чтобы
потом отправить их в Telegram, - ровно та связка, которую запрещает правило 5
CLAUDE.md. Ссылки на объявление достаточно.
"""
from __future__ import annotations

import hashlib
import json
import re

# Канонический набор полей карточки. Имена в filtry.yaml проверяются по нему:
# опечатка в имени поля роняет запуск, а не превращает фильтр в «пропускай всё».
POLYA = {
    "istochnik":          str,    # "999md"
    "vneshniy_id":        str,    # id объявления на площадке
    "url":                str,
    "zagolovok":          str,
    "sdelka":             str,    # prodazha / arenda / ...
    "gorod":              str,
    "sektor":             str,    # botanika / chekany / ...
    "ulica":              str,
    "cena":               float,  # в исходной валюте, как на площадке
    "valyuta":            str,    # EUR / USD / MDL
    "cena_eur":           float,
    "cena_eur_za_m2":     float,
    "prezhnyaya_cena_eur": float, # площадка сама показывает старую цену
    "komnat":             int,
    "ploshad_m2":         float,
    "etazh":              int,
    "etazhnost":          int,
    "tip_doma":           str,
    "sostoyanie":         str,
    "fond":               str,    # novostroy / vtorichka
    "prodavec":           str,    # sobstvennik / agentstvo / ...
    "avtor_login":        str,
    "opisanie":           str,
    "foto":               list,
    "podnyato_at":        str,
    # Считается позже, в rynok.py: на сколько % ниже медианы сектор+комнатность.
    "otklonenie_ot_rynka": float,
    # 1, если цифрам объявления можно верить. См. `dannye_nadezhny()`.
    "dannye_nadezhny": int,
}

# Телефоны Молдовы в любом виде: +373 xx xxx xxx, 069123456, 0-22-123-456.
# Ловим осознанно жадно: лучше замазать лишнее число, чем сохранить чужой номер.
TELEFON = re.compile(
    r"(?:\+?\s*373[\s\-.()]*\d[\d\s\-.()]{5,})"       # международный
    r"|(?:\b0\s*[236789]\d{1,2}[\s\-.()]*\d[\d\s\-.()]{4,})",  # местный
)
# Телеграм/вайбер-контакты в описании - тот же класс данных.
KONTAKT = re.compile(r"(?:@[A-Za-z0-9_]{4,32})")

# Объявления «в рассрочку»: в поле цены стоит первый взнос, а не цена квартиры.
# Такой объект выглядит вдвое дешевле рынка и лезет в топ. Ловим по описанию -
# оно дотягивается перед самой отправкой, то есть ровно тогда, когда нужно.
RASSROCHKA = re.compile(
    r"в\s+рассрочк|рассрочка|первый\s+взнос|перв(ый|ая)\s+(взнос|рат)"
    r"|[iî]n\s+rate|prima\s+rat|rate\s+f[aă]r[aă]\s+banc|achitare\s+[iî]n\s+rate",
    re.IGNORECASE)


def bez_telefonov(text: str) -> str:
    """Замазать телефоны и мессенджер-ники в чужом тексте."""
    if not text:
        return ""
    text = TELEFON.sub("[телефон]", text)
    return KONTAKT.sub("[контакт]", text)


def dannye_nadezhny(karta: dict) -> int:
    """Можно ли верить цифрам объявления настолько, чтобы сравнивать с рынком.

    Продавцы ошибаются при вводе: площадь 42,46 м² уезжает в поле как 4246.
    Площадка честно делит цену на площадь и получает 10 €/м², а у нас такой
    объект становится «дешевле рынка на 99%» и встаёт первым в списке. Таких
    0,2%, и они одни способны похоронить доверие к боту.

    Мы не пытаемся угадать правильную площадь - додумывать чужие цифры хуже,
    чем промолчать. Объявление просто не участвует в медианах и не получает
    метку «дешевле рынка».
    """
    import config

    ploshad = karta.get("ploshad_m2") or 0
    cena = karta.get("cena_eur") or 0
    za_m2 = karta.get("cena_eur_za_m2") or 0

    ot, do = config.PLOSHAD_OT_DO
    if ploshad and not (ot <= ploshad <= do):
        return 0

    if karta.get("sdelka") == "prodazha":
        ot, do = config.CENA_OT_DO_PRODAZHA
        if cena and not (ot <= cena <= do):
            return 0
        ot, do = config.ZA_M2_OT_DO_PRODAZHA
        if za_m2 and not (ot <= za_m2 <= do):
            return 0
    elif karta.get("sdelka") in ("arenda", "arenda_sutki"):
        ot, do = config.CENA_OT_DO_ARENDA
        if cena and not (ot <= cena <= do):
            return 0

    # «В рассрочку»: в поле цены первый взнос, а не цена квартиры. Описание
    # есть только у дообогащённых карточек - то есть у тех, что вот-вот уйдут
    # папе, и это как раз последний момент, когда такое ещё можно отсечь.
    if karta.get("opisanie") and RASSROCHKA.search(karta["opisanie"]):
        return 0

    # Цена и площадь должны сходиться с ценой за метр, которую отдала площадка.
    if cena and ploshad and za_m2:
        svoe = cena / ploshad
        if not (0.5 < za_m2 / svoe < 2.0):
            return 0
    return 1


def _chislo(x, tip=float):
    """Из '1 232 м²' / 1232 / None получить число или None. Без исключений."""
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        try:
            return tip(x)
        except (TypeError, ValueError):
            return None
    s = re.sub(r"[^\d.,\-]", "", str(x)).replace(",", ".")
    if s in ("", "-", ".", "-."):
        return None
    try:
        return tip(float(s))
    except (TypeError, ValueError):
        return None


def pustaya() -> dict:
    """Карточка со всеми полями, заполненными пустотой нужного типа.

    Источник обязан вернуть словарь именно такой формы: тогда в сообщении
    никогда не появится None, а в фильтре - KeyError на новом поле.
    """
    return {p: ([] if t is list else (0 if t in (int, float) else ""))
            for p, t in POLYA.items()}


def privesti(karta: dict) -> dict:
    """Дочистить карточку источника: типы, пустоты, вычистка телефонов."""
    out = pustaya()
    chuzhie = set(karta) - set(POLYA)
    if chuzhie:
        raise ValueError(
            "Источник вернул поля, которых нет в каноне: %s. "
            "Добавь их в POLYA нормализации или убери из источника."
            % ", ".join(sorted(chuzhie)))
    for pole, tip in POLYA.items():
        z = karta.get(pole)
        if tip is list:
            out[pole] = list(z or [])
        elif tip in (int, float):
            ch = _chislo(z, tip)
            out[pole] = ch if ch is not None else 0
        else:
            out[pole] = str(z or "").strip()
    out["opisanie"] = bez_telefonov(out["opisanie"])
    out["zagolovok"] = bez_telefonov(out["zagolovok"])
    out["dannye_nadezhny"] = dannye_nadezhny(out)
    return out


# Поля, по которым считается «карточка изменилась». Правка описания или
# добавление фото событием не считается - иначе бот будет дёргать по каждой
# косметической правке продавца.
POLYA_HESHA = ("cena_eur", "ploshad_m2", "etazh", "etazhnost", "zagolovok", "sdelka")


def hash_kartochki(karta: dict) -> str:
    slepok = json.dumps([karta.get(p) for p in POLYA_HESHA],
                        ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(slepok.encode("utf-8")).hexdigest()
