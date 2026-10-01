"""Движок предикатов и строгая валидация `filtry.yaml`.

Главная мысль файла: **опечатка должна ронять запуск, а не молча пропускать
всё подряд**. Фильтр, который из-за опечатки в имени поля стал «пропускай
всё», - худший из возможных багов здесь: папа получает лавину нерелевантных
карточек и перестаёт читать бота. Поэтому валидация жёсткая и с внятным
текстом ошибки, а не `.get(pole)`.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from normalizacia import POLYA


class OshibkaKonfiga(Exception):
    """Конфиг непригоден. Ловится в run.py и уходит алертом в Telegram."""


# --- операторы --------------------------------------------------------------
# Каждый - функция (значение_поля, значение_из_конфига, карточка) -> bool.
# Карточка третьим аргументом нужна только оператору сравнения с другим полем.

def _spisok(z):
    return z if isinstance(z, (list, tuple, set)) else [z]


def _kluch(x):
    return str(x).strip().lower()


OPERATORY = {
    "ravno":          lambda v, z, k: _kluch(v) == _kluch(z),
    "ne_ravno":       lambda v, z, k: _kluch(v) != _kluch(z),
    "v_spiske":       lambda v, z, k: _kluch(v) in {_kluch(x) for x in _spisok(z)},
    "ne_v_spiske":    lambda v, z, k: _kluch(v) not in {_kluch(x) for x in _spisok(z)},
    "ne_menshe":      lambda v, z, k: _chislo(v) >= float(z),
    "ne_bolshe":      lambda v, z, k: _chislo(v) <= float(z),
    "mezhdu":         lambda v, z, k: float(z[0]) <= _chislo(v) <= float(z[1]),
    "soderzhit":      lambda v, z, k: any(_kluch(x) in _kluch(v) for x in _spisok(z)),
    "ne_soderzhit":   lambda v, z, k: not any(_kluch(x) in _kluch(v) for x in _spisok(z)),
    "est":            lambda v, z, k: bool(v) and v != 0,
    "net":            lambda v, z, k: not v or v == 0,
    "ne_ravno_polyu": lambda v, z, k: v != k.get(z),
}

# Операторы, которым нужен числовой диапазон списком из двух.
PARNYE = {"mezhdu"}
# Операторам сравнения с полем в znachenie приходит имя другого поля.
SSYLKA_NA_POLE = {"ne_ravno_polyu"}
# Этим операторам значение не нужно вовсе.
BEZ_ZNACHENIYA = {"est", "net"}
CHISLOVYE = {"ne_menshe", "ne_bolshe", "mezhdu"}


def _chislo(v) -> float:
    """Числовое сравнение не должно падать на пустой строке."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("-inf")


# --- валидация --------------------------------------------------------------

def _proverit_pravilo(p, gde: str) -> None:
    if not isinstance(p, dict):
        raise OshibkaKonfiga(f"{gde}: правило должно быть словарём, а не {type(p).__name__}")
    lishnie = set(p) - {"pole", "op", "znachenie", "metka"}
    if lishnie:
        raise OshibkaKonfiga(f"{gde}: неизвестные ключи в правиле: {', '.join(sorted(lishnie))}")

    pole = p.get("pole")
    if pole not in POLYA:
        pohozhie = [x for x in POLYA if x.startswith(str(pole)[:3])]
        podskazka = f" Может быть: {', '.join(pohozhie)}?" if pohozhie else ""
        raise OshibkaKonfiga(
            f"{gde}: нет поля «{pole}». Доступные поля: "
            f"{', '.join(sorted(POLYA))}.{podskazka}")

    op = p.get("op")
    if op not in OPERATORY:
        raise OshibkaKonfiga(
            f"{gde}: нет оператора «{op}». Доступные: {', '.join(sorted(OPERATORY))}")

    z = p.get("znachenie")
    if op in BEZ_ZNACHENIYA:
        return
    if z is None:
        raise OshibkaKonfiga(f"{gde}: оператору «{op}» нужно znachenie")

    if op in PARNYE:
        if not isinstance(z, (list, tuple)) or len(z) != 2:
            raise OshibkaKonfiga(f"{gde}: «{op}» ждёт список из двух чисел, пришло {z!r}")
        try:
            niz, verh = float(z[0]), float(z[1])
        except (TypeError, ValueError):
            raise OshibkaKonfiga(f"{gde}: «{op}» ждёт числа, пришло {z!r}")
        if niz > verh:
            raise OshibkaKonfiga(f"{gde}: диапазон задом наперёд: {niz} > {verh}")
    elif op in CHISLOVYE:
        try:
            float(z)
        except (TypeError, ValueError):
            raise OshibkaKonfiga(f"{gde}: «{op}» ждёт число, пришло {z!r}")
    elif op in SSYLKA_NA_POLE:
        if z not in POLYA:
            raise OshibkaKonfiga(
                f"{gde}: «{op}» сравнивает с другим полем, а поля «{z}» нет")
    elif op in ("v_spiske", "ne_v_spiske"):
        if not isinstance(z, (list, tuple)) or not z:
            raise OshibkaKonfiga(f"{gde}: «{op}» ждёт непустой список, пришло {z!r}")

    if p.get("metka") is not None and not str(p["metka"]).strip():
        raise OshibkaKonfiga(f"{gde}: metka пустая - убери её или впиши текст")


def proverit(konf: dict) -> dict:
    """Полная проверка конфига. Возвращает его же, если всё в порядке."""
    if not isinstance(konf, dict):
        raise OshibkaKonfiga("filtry.yaml: ожидался словарь верхнего уровня")
    if konf.get("versiya") != 1:
        raise OshibkaKonfiga(
            f"filtry.yaml: versiya должна быть 1, а не {konf.get('versiya')!r}")

    sbor = konf.get("sbor")
    if not isinstance(sbor, dict) or not sbor.get("gorod"):
        raise OshibkaKonfiga("filtry.yaml: в блоке sbor нужен gorod")
    if not _spisok(sbor.get("sdelki") or []):
        raise OshibkaKonfiga("filtry.yaml: sbor.sdelki пуст - нечего собирать")

    rynok = konf.get("rynok")
    if not isinstance(rynok, dict):
        raise OshibkaKonfiga("filtry.yaml: нет блока rynok")
    for klyuch in ("okno_dney", "minimum_obektov", "porog_deshevle"):
        if not isinstance(rynok.get(klyuch), (int, float)) or rynok[klyuch] <= 0:
            raise OshibkaKonfiga(
                f"filtry.yaml: rynok.{klyuch} должно быть положительным числом, "
                f"пришло {rynok.get(klyuch)!r}")

    profili = konf.get("profili")
    if not isinstance(profili, list) or not profili:
        raise OshibkaKonfiga("filtry.yaml: нет ни одного профиля")

    imena = set()
    for i, pr in enumerate(profili):
        gde = f"профиль #{i + 1}"
        if not isinstance(pr, dict):
            raise OshibkaKonfiga(f"{gde}: должен быть словарём")
        imya = pr.get("imya")
        if not imya:
            raise OshibkaKonfiga(f"{gde}: нет имени")
        gde = f"профиль «{imya}»"
        if imya in imena:
            raise OshibkaKonfiga(f"{gde}: имя повторяется, имена должны быть уникальны")
        imena.add(imya)
        if pr.get("poluchatel") != "papa":
            raise OshibkaKonfiga(
                f"{gde}: бот пишет только папе, poluchatel должен быть papa, "
                f"пришло {pr.get('poluchatel')!r}")
        pravila = pr.get("pravila")
        if not isinstance(pravila, list) or not pravila:
            # Профиль без правил пропустит весь рынок - именно та авария,
            # ради которой этот файл и написан.
            raise OshibkaKonfiga(
                f"{gde}: пустой список правил пропустил бы весь рынок. "
                "Если это нарочно - впиши правило вроде {pole: gorod, op: ravno, "
                "znachenie: kishinev}")
        for j, p in enumerate(pravila):
            _proverit_pravilo(p, f"{gde}, правило #{j + 1}")
        for j, p in enumerate(pr.get("myagkie") or []):
            _proverit_pravilo(p, f"{gde}, мягкое правило #{j + 1}")
            if not p.get("metka"):
                raise OshibkaKonfiga(
                    f"{gde}, мягкое правило #{j + 1}: у мягкого правила обязана "
                    "быть metka - иначе оно ни на что не влияет")
    return konf


def zagruzit(put: Path) -> dict:
    if not Path(put).exists():
        raise OshibkaKonfiga(f"Нет файла фильтров: {put}")
    try:
        konf = yaml.safe_load(Path(put).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise OshibkaKonfiga(f"{put}: YAML не читается: {e}")
    return proverit(konf)


# --- применение -------------------------------------------------------------

def pravilo_prohodit(karta: dict, p: dict) -> bool:
    if p["pole"] not in karta:
        # Источник вернул карточку без канонического поля - это баг источника,
        # молча считать «не подходит» нельзя, иначе он останется незамеченным.
        raise OshibkaKonfiga(
            f"В карточке нет поля «{p['pole']}» - источник вернул неполную карточку")
    try:
        return bool(OPERATORY[p["op"]](karta[p["pole"]], p.get("znachenie"), karta))
    except (TypeError, ValueError, IndexError, KeyError):
        return False


def prohodit(karta: dict, profil: dict) -> bool:
    """Жёсткие правила: все до одного."""
    return all(pravilo_prohodit(karta, p) for p in profil["pravila"])


def metki(karta: dict, profil: dict) -> list:
    """Мягкие правила: не отсеивают, а вешают метку вроде «дешевле рынка»."""
    return [p["metka"] for p in (profil.get("myagkie") or [])
            if pravilo_prohodit(karta, p)]


def aktivnye_profili(konf: dict) -> list:
    return [p for p in konf["profili"] if p.get("aktiven", True)]
