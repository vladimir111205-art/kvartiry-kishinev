"""Каркас жив: конфиг читается, пути на месте, секретов в репозитории нет."""
import re
from pathlib import Path

import config


def test_puti_vnutri_agenta():
    # Имя папки не проверяем: в weview копия лежит как 19_kvartiry_kishinev,
    # а в чекауте Actions - как kvartiry-kishinev. Проверяем структуру.
    assert (config.BASE_DIR / "config.py").exists()
    assert config.DB_PATH.parent == config.DATA_DIR
    assert config.STATE_DIR.parent == config.BASE_DIR


def test_potolki_polozhitelnye():
    assert config.MAX_OTPRAVOK_ZA_PROGON > 0
    assert config.MAX_OTPRAVOK_V_DEN >= config.MAX_OTPRAVOK_ZA_PROGON
    assert config.MAX_PODPISI == 1024


def test_bez_tokena_ne_padaem_kogda_ne_obyazatelno(monkeypatch):
    # Тесты не должны требовать боевых секретов.
    monkeypatch.setenv("KVARTIRY_SECRETY", str(config.BASE_DIR / "net-takogo-fayla.json"))
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    import importlib
    importlib.reload(config)
    assert config.bot_token(obyazatelno=False) == ""
    importlib.reload(config)


def test_v_repozitorii_net_tokena():
    """Токен бота не должен лежать в коде ни одним файлом."""
    for f in Path(config.BASE_DIR).rglob("*.py"):
        if ".venv" in f.parts:
            continue
        t = f.read_text(encoding="utf-8")
        # Токен @BotFather: цифры, двоеточие, ~35 символов base64.
        assert not re.search(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}", t), f
