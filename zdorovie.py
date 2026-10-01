"""Самодиагностика прогона: тихий ноль, контракт ответа, алерты владельцу.

Всё здесь - про то, чтобы поломка была видна **сразу владельцу**, а не
через неделю, когда батя решит, что бот сломался и перестанет проверять.

R3 плана: `naydeno == 0` при непустой базе - это сбой, а не «новых нет».
Молчаливый ноль опаснее любой другой ошибки, потому что выглядит как
«просто ничего не нашлось».
"""
from __future__ import annotations

import config
import db


def alert(bot, tekst: str) -> None:
    """Алерт только в лог Actions. Бот пишет одному человеку - папе
    (решение Владимира 01.10.2026), а технические сообщения папа не поймёт и
    испугается. Поломку видно по красному прогону: GitHub сам присылает
    владельцу репозитория письмо о падении workflow."""
    print(f"[zdorovie] АЛЕРТ: {tekst}", flush=True)


def proverit_tihiy_nol(con, bot, naydeno: int, holodnyy_start: bool) -> bool:
    """True, если это тихий ноль (сбой). Копит счётчик подряд в meta."""
    if naydeno > 0 or holodnyy_start:
        db.meta_set(con, "pustyh_progonov_podryad", "0")
        return False

    pustyh = int(db.meta_get(con, "pustyh_progonov_podryad", "0") or "0") + 1
    db.meta_set(con, "pustyh_progonov_podryad", str(pustyh))
    if pustyh >= config.PUSTYH_PROGONOV_DO_ALERTA:
        alert(bot, f"Площадка вернула 0 объявлений {pustyh} прогонов подряд.\n"
                   f"Похоже на смену схемы GraphQL или блокировку - проверь "
                   f"probe.py вручную.")
    return True


def proverit_kontrakt(bot, problemy: list) -> None:
    if problemy:
        alert(bot, "Контракт ответа 999.md нарушен (похоже на смену схемы "
                   "сайта):\n" + "\n".join(f"- {p}" for p in problemy))
