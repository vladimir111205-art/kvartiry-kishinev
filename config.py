"""Настройки агента 19 «квартиры Кишинёв».

Здесь только то, что не меняется от прогона к прогону: пути, таймауты,
потолки отправки и чтение секретов из окружения. Всё, что владелец правит
руками (сектора, цены, площади, пороги рынка) - в `filtry.yaml`, не здесь.

Секреты берутся из переменных окружения (в GitHub Actions - repository secrets),
а локально - из файла `~/.config/weview/kvartiry_bot.json`. Паттерн «env
перекрывает локальный файл» повторяет agents/18_oskar_bot/config.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- пути -------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
STATE_DIR = BASE_DIR / "state"
FIXTURES_DIR = BASE_DIR / "fixtures"
DB_PATH = Path(os.getenv("KVARTIRY_DB", DATA_DIR / "kvartiry.db"))
DUMP_PATH = STATE_DIR / "dump.sql"
FILTRY_PATH = Path(os.getenv("KVARTIRY_FILTRY", BASE_DIR / "filtry.yaml"))

# Локальный файл с токеном и чатами - вне репозитория (правило 8 CLAUDE.md).
SECRETY_FILE = Path(os.getenv(
    "KVARTIRY_SECRETY", os.path.expanduser("~/.config/weview/kvartiry_bot.json")))

# --- сеть -------------------------------------------------------------------
TAYMAUT_SEK = int(os.getenv("KVARTIRY_TAYMAUT", "25"))
POPYTOK_SETI = 3
PAUZA_MEZHDU_POPYTKAMI_SEK = 5
# Вежливый темп: пауза между страницами списка, чтобы не долбить площадку.
PAUZA_MEZHDU_STRANICAMI_SEK = float(os.getenv("KVARTIRY_PAUZA_STRANIC", "1.5"))
# Честный User-Agent: не прячемся, даём способ с нами связаться (R7 плана).
USER_AGENT = os.getenv(
    "KVARTIRY_UA",
    "kvartiry-kishinev/1.0 (lichnyy monitoring kvartir)")

# Сколько страниц списка тянуть за прогон максимум - предохранитель на случай,
# если площадка начнёт отдавать бесконечную пагинацию. Рынок Кишинёва это
# 47 страниц по 500, запас двукратный.
MAX_STRANIC_ZA_PROGON = int(os.getenv("KVARTIRY_MAX_STRANIC", "100"))
# Страницы тянутся параллельно: последовательный обход идёт две минуты, за это
# время список сдвигается и карточки теряются. Четыре потока - 12 секунд на весь
# рынок и ни одной потери; шесть быстрее, но начинают проскакивать дубли.
POTOKOV_SBORA = int(os.getenv("KVARTIRY_POTOKOV", "4"))

# --- отправка ---------------------------------------------------------------
MAX_OTPRAVOK_ZA_PROGON = int(os.getenv("KVARTIRY_MAX_ZA_PROGON", "10"))
MAX_OTPRAVOK_V_DEN = int(os.getenv("KVARTIRY_MAX_V_DEN", "25"))
# Больше этого числа карточек за прогон - шлём одним дайджестом списком.
# Цикл внутри одного запуска GitHub Actions. Расписание GitHub пропускает
# запуски (замер 17-27.09: 3-5 прогонов в день вместо 45), поэтому бот сам
# держит цикл: свежая верхушка ленты раз в минуту, весь рынок раз в 20 минут.
# 01.10.2026 ускорено ради «первым»: верхушка раз в 30 с (~2 с на запрос),
# весь рынок раз в 5 минут (~20 с) - снижение цены без подъёма объявления
# видно только при полном обходе. Ночью полный обход раз в 20 минут.
CIKL_PAUZA_SEK = int(os.getenv("KVARTIRY_CIKL_PAUZA", "30"))
CIKL_POLNYY_SEK = int(os.getenv("KVARTIRY_CIKL_POLNYY", "300"))
CIKL_POLNYY_NOCH_SEK = int(os.getenv("KVARTIRY_CIKL_POLNYY_NOCH", "1200"))
BYSTRO_OBYAVLENIY = int(os.getenv("KVARTIRY_BYSTRO_OBYAVLENIY", "500"))
CHAS_S, CHAS_DO = 9, 22   # по Кишинёву; ночью смотрим, но не шлём - копим до 09:00

POROG_DAYDZHESTA = int(os.getenv("KVARTIRY_POROG_DAYDZHESTA", "6"))
# Telegram режет подпись к фото на 1024 символах.
MAX_PODPISI = 1024
# Сколько промахов подряд до «снято с продажи». Для избранных - 1 (плюс
# точечная перепроверка страницы объекта, она же гасит ложную тревогу).
PROPUSKOV_DO_SNYATIYA = 3
PROPUSKOV_DO_SNYATIYA_IZBRANNOE = 1
# Молчим неделю при зелёных прогонах - шлём «я на связи».
DNEY_TISHINY_DO_PULSA = 7

# --- правдоподобие данных ---------------------------------------------------
# Продавцы ошибаются при вводе: площадь 42,46 м² уезжает в поле как 4246, и
# площадка честно делит цену на эту площадь, получая 10 €/м². Таких объявлений
# 0,2%, но именно они возглавляют список «дешевле рынка» - то есть портят ровно
# то, ради чего агент делается. Всё, что вне границ, в медианы не идёт и метку
# «дешевле рынка» не получает.
PLOSHAD_OT_DO = (10.0, 400.0)            # м², квартира Кишинёва
# Замер по живому рынку Кишинёва (20 537 объявлений, 17.09.2026):
# 1-й процентиль 1067 €/м², медиана 1965, 99-й 4277. Нижняя граница стоит
# заведомо ниже реального рынка - она ловит не дешёвые квартиры, а мусор:
# объявления «в рассрочку», где в поле цены стоит первый взнос.
ZA_M2_OT_DO_PRODAZHA = (600.0, 9000.0)   # €/м²
CENA_OT_DO_PRODAZHA = (5000.0, 3000000.0)   # €
CENA_OT_DO_ARENDA = (50.0, 20000.0)         # € в месяц

# --- часовой пояс и расписание ---------------------------------------------
# Кишинёв: UTC+2 зимой, UTC+3 летом. Cron в Actions всегда в UTC, поэтому
# сводка привязана к локальному часу, вычисленному через zoneinfo.
TZ_KISHINEV = "Europe/Chisinau"
CHAS_SVODKI = int(os.getenv("KVARTIRY_CHAS_SVODKI", "20"))

# --- здоровье ---------------------------------------------------------------
# «Тихий ноль»: naydeno == 0 при непустой базе - это сбой, а не «новых нет» (R3).
PUSTYH_PROGONOV_DO_ALERTA = 3


def _secrety() -> dict:
    if not SECRETY_FILE.exists():
        return {}
    try:
        return json.loads(SECRETY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _secret(env_klyuch: str, fayl_klyuch: str, obyazatelno: bool = False) -> str:
    znachenie = (os.getenv(env_klyuch) or "").strip()
    if not znachenie:
        znachenie = str(_secrety().get(fayl_klyuch) or "").strip()
    if not znachenie and obyazatelno:
        raise SystemExit(
            f"Нет секрета {env_klyuch}.\n"
            f"В GitHub Actions - repository secret {env_klyuch}.\n"
            f"Локально - положи в {SECRETY_FILE} поле \"{fayl_klyuch}\".")
    return znachenie


def bot_token(obyazatelno: bool = True) -> str:
    return _secret("BOT_TOKEN", "token", obyazatelno)


def chat_papy(obyazatelno: bool = False) -> str:
    return _secret("PAPA_CHAT_ID", "papa_chat_id", obyazatelno)


def chat_vladimira(obyazatelno: bool = False) -> str:
    return _secret("VLADIMIR_CHAT_ID", "vladimir_chat_id", obyazatelno)


def chat_poluchatelya(imya: str) -> str:
    """Имя получателя из filtry.yaml -> chat_id.

    Получатель один - папа. Решение Владимира 01.10.2026: «он должен только
    папе отправлять». Любое другое имя даёт пустой chat, и отправка не идёт."""
    return chat_papy() if imya == "papa" else ""
