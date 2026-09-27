"""Локальный помощник: снять chat_id после того, как человек нажал Start.

Запускается руками один раз, в Actions не участвует. Нужен потому, что
числовой chat_id в Telegram нигде не показывают, а искать его руками через
сторонних ботов - лишний риск и лишний шаг.

    python nastroit_bota.py              показать, кто нажал Start
    python nastroit_bota.py --papa <chat_id>
    python nastroit_bota.py --proverit   отправить проверочное сообщение

Токен и чаты живут в ~/.config/weview/kvartiry_bot.json (правило 8 CLAUDE.md),
в репозиторий не попадают. В GitHub Actions те же значения приходят из
repository secrets и перекрывают файл.
"""
from __future__ import annotations

import json
import os
import sys

import config
import notify


def pokazat() -> None:
    bot = notify.Bot(token=config.bot_token(obyazatelno=True))
    obnovleniya = bot.obnovleniya()
    if not obnovleniya:
        print("Никто пока не написал боту. Попроси нажать Start и запусти снова.")
        print("Учти: getUpdates отдаёт события только за последние сутки.")
        return
    print(f"Нашёл {len(obnovleniya)} событий:\n")
    vidennye = {}
    for u in obnovleniya:
        soobshenie = u.get("message") or u.get("edited_message") or {}
        chat = soobshenie.get("chat") or (u.get("callback_query") or {}).get(
            "message", {}).get("chat", {})
        if not chat.get("id") or chat["id"] in vidennye:
            continue
        vidennye[chat["id"]] = chat
        imya = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
        login = f"@{chat['username']}" if chat.get("username") else "без username"
        print(f"  chat_id={chat['id']}  {imya or '(без имени)'}  {login}")
    print("\nЗапиши нужный:")
    print("  python nastroit_bota.py --papa <chat_id>")
    print("  python nastroit_bota.py --vladimir <chat_id>")


def zapisat(klyuch: str, chat_id: str) -> None:
    config.SECRETY_FILE.parent.mkdir(parents=True, exist_ok=True)
    dannye = {}
    if config.SECRETY_FILE.exists():
        dannye = json.loads(config.SECRETY_FILE.read_text(encoding="utf-8"))
    dannye[klyuch] = str(chat_id).strip()
    config.SECRETY_FILE.write_text(
        json.dumps(dannye, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(config.SECRETY_FILE, 0o600)
    print(f"Записал {klyuch}={chat_id} в {config.SECRETY_FILE}")
    print("\nТеперь тот же chat_id - в secrets репозитория:")
    print(f"  gh secret set {klyuch.upper()} --repo <owner>/kvartiry-kishinev")


def proverit() -> None:
    bot = notify.Bot(token=config.bot_token(obyazatelno=True))
    for imya, chat in (("папа", config.chat_papy()),
                       ("владимир", config.chat_vladimira())):
        if not chat:
            print(f"  {imya}: chat_id не задан")
            continue
        try:
            bot.tekst(chat, "Проверка связи. Бот настроен и на связи.")
            print(f"  {imya}: ушло в чат {chat}")
        except Exception as e:
            print(f"  {imya}: НЕ ушло в {chat} - {str(e)[:120]}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv:
        pokazat()
    elif argv[0] == "--proverit":
        proverit()
    elif argv[0] in ("--papa", "--vladimir") and len(argv) > 1:
        zapisat("papa_chat_id" if argv[0] == "--papa" else "vladimir_chat_id", argv[1])
    else:
        print(__doc__)
