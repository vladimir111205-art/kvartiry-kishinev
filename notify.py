"""Отправка в Telegram на голом urllib.

Два правила, из которых следует всё остальное:

1. **Очередь важнее отправки.** Раннер эфемерный, его могут убить на середине.
   Поэтому не ушло - запись остаётся в очереди и уйдёт следующим прогоном; уже
   ушло - помечается сразу, чтобы не продублировать.

2. **403 останавливает всё.** Если получатель заблокировал бота, дальнейшие
   попытки бессмысленны и только выжгут очередь: каждая запись получит свою
   ошибку и свой счётчик попыток. Останавливаемся и зовём владельца.

Транспорт вынесен в аргумент, чтобы тесты шли офлайн и проверяли настоящий
код отправки, а не его имитацию.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import config

API = "https://api.telegram.org/bot{token}/{metod}"


class ZablokirovalBota(Exception):
    """403: получатель заблокировал бота. Отправку останавливаем целиком."""


class SlishkomChasto(Exception):
    """429: Telegram просит подождать. Запись остаётся в очереди."""

    def __init__(self, sekund: int):
        super().__init__(f"429, ждать {sekund} с")
        self.sekund = sekund


def transport_urllib(token: str, metod: str, dannye: dict) -> dict:
    """Боевой транспорт. Единственное место в модуле, которое ходит в сеть."""
    url = API.format(token=token, metod=metod)
    telo = json.dumps(dannye).encode("utf-8")
    req = urllib.request.Request(
        url, data=telo, headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=config.TAYMAUT_SEK) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        syroe = e.read().decode("utf-8", "replace")
        try:
            otvet = json.loads(syroe)
        except ValueError:
            otvet = {"ok": False, "error_code": e.code, "description": syroe[:300]}
        return otvet


class Bot:
    def __init__(self, token: str = None, transport=transport_urllib):
        self.token = token or config.bot_token(obyazatelno=False)
        self.transport = transport
        # Взводится на 403 и гасит отправку до конца прогона.
        self.ostanovlen = False

    def _vyzov(self, metod: str, dannye: dict) -> dict:
        if self.ostanovlen:
            raise ZablokirovalBota("отправка остановлена в этом прогоне")
        otvet = self.transport(self.token, metod, dannye) or {}
        if otvet.get("ok"):
            return otvet.get("result") or {}

        kod = otvet.get("error_code")
        opisanie = str(otvet.get("description") or "")
        if kod == 429:
            sekund = int((otvet.get("parameters") or {}).get("retry_after") or 5)
            raise SlishkomChasto(sekund)
        if kod == 403:
            self.ostanovlen = True
            raise ZablokirovalBota(opisanie or "бот заблокирован получателем")
        raise RuntimeError(f"Telegram {kod}: {opisanie[:200]}")

    # --- отправка -----------------------------------------------------------

    def tekst(self, chat_id, tekst: str, knopki: dict = None,
              bez_preview: bool = True) -> dict:
        dannye = {"chat_id": str(chat_id), "text": tekst[:4096],
                  "parse_mode": "HTML",
                  "link_preview_options": {"is_disabled": bez_preview}}
        if knopki:
            dannye["reply_markup"] = knopki
        return self._vyzov("sendMessage", dannye)

    def foto(self, chat_id, foto_url: str, podpis: str, knopki: dict = None) -> dict:
        """Карточка объекта. Фото не отдалось - шлём текстом, а не молчим.

        Ссылки на картинки 999.md иногда отваливаются, и терять из-за этого
        сообщение о подешевевшей квартире нельзя.
        """
        if not foto_url:
            return self.tekst(chat_id, podpis, knopki, bez_preview=False)
        dannye = {"chat_id": str(chat_id), "photo": foto_url,
                  "caption": podpis[:config.MAX_PODPISI], "parse_mode": "HTML"}
        if knopki:
            dannye["reply_markup"] = knopki
        try:
            return self._vyzov("sendPhoto", dannye)
        except (SlishkomChasto, ZablokirovalBota):
            raise
        except RuntimeError as e:
            print(f"[notify] фото не ушло ({str(e)[:90]}), шлём текстом")
            return self.tekst(chat_id, podpis, knopki, bez_preview=False)

    # --- приём --------------------------------------------------------------

    def obnovleniya(self, offset: int = 0, taymaut: int = 0) -> list:
        """getUpdates с сохранённым offset - так нажатия доходят до эфемерного
        раннера без вебхука и без постоянно живущего процесса."""
        dannye = {"timeout": taymaut, "allowed_updates": ["message", "callback_query"]}
        if offset:
            dannye["offset"] = offset
        try:
            return self._vyzov("getUpdates", dannye) or []
        except (SlishkomChasto, ZablokirovalBota):
            raise
        except RuntimeError as e:
            print(f"[notify] getUpdates не удался: {str(e)[:120]}")
            return []

    def otvetit_na_knopku(self, callback_id: str, tekst: str = "",
                          vsplyvashkoy: bool = False) -> None:
        """Всплывающее подтверждение нажатия.

        Между нажатием и обработкой проходит до одного интервала расписания -
        постоянно живущего бота у нас нет. Всплывашка при обработке нужна,
        чтобы человек не решил, что кнопка не сработала.
        """
        try:
            self._vyzov("answerCallbackQuery", {
                "callback_query_id": callback_id, "text": tekst[:200],
                "show_alert": bool(vsplyvashkoy)})
        except Exception as e:
            print(f"[notify] не подтвердили нажатие: {str(e)[:100]}")

    def pererisovat_knopki(self, chat_id, message_id, knopki: dict) -> None:
        try:
            self._vyzov("editMessageReplyMarkup", {
                "chat_id": str(chat_id), "message_id": message_id,
                "reply_markup": knopki})
        except Exception as e:
            print(f"[notify] кнопку не перерисовали: {str(e)[:100]}")


def otpravit_s_povtorom(otpravka, popytok: int = 2, spat=time.sleep):
    """Обёртка над одной отправкой: 429 уважаем, остальное наверх.

    `spat` аргументом - чтобы тест не ждал по-настоящему.
    """
    posledniaya = None
    for nomer in range(popytok):
        try:
            return otpravka()
        except SlishkomChasto as e:
            posledniaya = e
            if nomer + 1 < popytok:
                # Telegram сам говорит, сколько ждать. Спорить с ним себе дороже.
                spat(min(e.sekund, 30))
    raise posledniaya
