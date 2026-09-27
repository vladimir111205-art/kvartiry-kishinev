"""Протокол источника. Ядро знает только его и ни одной площадки по имени.

Правило корректности: серверные фильтры площадки - только экономия трафика.
Источником истины остаются локальные предикаты, прогоняемые по каждой
карточке. Иначе площадки будут по-своему понимать «состояние» и «сектор», и
результат перестанет быть воспроизводимым.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Istochnik(Protocol):
    imya: str            # "999md"
    vozmozhnosti: dict   # какие фильтры площадка умеет отдать серверу

    def sobrat(self, nastroyki: dict, limit: int) -> list:
        """Сырые записи площадки. Сеть только здесь."""

    def normalizovat(self, syroe: dict) -> dict:
        """Сырая запись -> канонический словарь карточки. Без сети."""


ISTOCHNIKI = {}


def zaregistrirovat(ist) -> None:
    ISTOCHNIKI[ist.imya] = ist


def poluchit(imya: str):
    if imya not in ISTOCHNIKI:
        raise KeyError(
            f"Нет источника «{imya}». Известные: {', '.join(sorted(ISTOCHNIKI)) or 'ни одного'}")
    return ISTOCHNIKI[imya]
