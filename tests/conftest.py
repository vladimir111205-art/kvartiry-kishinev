"""Общие фикстуры и запрет сети.

Ни один тест не должен ходить в интернет: тесты обязаны быть воспроизводимыми
и зелёными без сети. Поэтому сокеты здесь глушатся на уровне модуля, и
случайно оставленный сетевой вызов упадёт с внятным текстом, а не молча
замедлит прогон и начнёт зависеть от погоды на 999.md.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

KOREN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOREN))


@pytest.fixture(autouse=True)
def bez_seti(monkeypatch):
    def zapret(*a, **kw):
        raise RuntimeError(
            "Тест попытался выйти в сеть. Тесты идут только на фикстурах.")
    monkeypatch.setattr(socket, "socket", zapret)
    monkeypatch.setattr(socket, "create_connection", zapret)


@pytest.fixture
def syroy_spisok() -> list:
    d = json.loads((KOREN / "fixtures" / "999md_spisok.json").read_text(encoding="utf-8"))
    return d["data"]["searchAds"]["ads"]


@pytest.fixture
def syrye_kursy() -> dict:
    return json.loads((KOREN / "fixtures" / "999md_kursy.json").read_text(encoding="utf-8"))


@pytest.fixture
def k_eur(syrye_kursy) -> dict:
    import kursy
    return kursy.razobrat(syrye_kursy)


@pytest.fixture
def istochnik():
    from istochniki.devyat999 import Devyat999
    return Devyat999()


@pytest.fixture
def kartochki(istochnik, syroy_spisok, k_eur) -> list:
    import normalizacia
    return [normalizacia.privesti(istochnik.normalizovat(s, k_eur)) for s in syroy_spisok]
