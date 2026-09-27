"""Транспорт Telegram на подставном транспорте - настоящий код, но без сети.

Проверяется в первую очередь поведение при отказах: 429 не должен терять
сообщение, 403 не должен выжигать очередь по одной записи, а отвалившаяся
картинка не должна съедать новость о подешевевшей квартире.
"""
from __future__ import annotations

import pytest

import notify
import soobsheniya as s


class Podstavnoy:
    """Записывает вызовы и отдаёт заранее заданные ответы."""

    def __init__(self, otvety=None):
        self.vyzovy = []
        self.otvety = list(otvety or [])

    def __call__(self, token, metod, dannye):
        self.vyzovy.append((metod, dannye))
        if self.otvety:
            return self.otvety.pop(0)
        return {"ok": True, "result": {"message_id": 100 + len(self.vyzovy)}}

    @property
    def metody(self):
        return [m for m, _ in self.vyzovy]


def bot(otvety=None):
    t = Podstavnoy(otvety)
    return notify.Bot(token="тест", transport=t), t


# --- отправка ---------------------------------------------------------------

def test_tekst_uhodit_s_html():
    b, t = bot()
    b.tekst(42, "<b>привет</b>")
    metod, dannye = t.vyzovy[0]
    assert metod == "sendMessage"
    assert dannye["chat_id"] == "42"
    assert dannye["parse_mode"] == "HTML"


def test_foto_uhodit_kak_sendphoto_s_podpisyu_i_knopkami():
    b, t = bot()
    b.foto(42, "https://i.simpalsmedia.com/a.jpg", "подпись",
           s.knopki({"id": 7, "url": "https://999.md/ru/1"}))
    metod, dannye = t.vyzovy[0]
    assert metod == "sendPhoto"
    assert dannye["photo"].endswith("a.jpg")
    assert dannye["caption"] == "подпись"
    assert dannye["reply_markup"]["inline_keyboard"][0][1]["callback_data"] == "izb_dobavit:7"


def test_bez_foto_shlyom_tekstom_a_ne_molchim():
    b, t = bot()
    b.foto(42, "", "подпись")
    assert t.metody == ["sendMessage"]


def test_bitaya_kartinka_ne_syedaet_soobshchenie():
    """Ссылки на картинки 999.md иногда отваливаются. Терять из-за этого
    новость о подешевевшей квартире нельзя."""
    b, t = bot([{"ok": False, "error_code": 400,
                 "description": "wrong file identifier"}])
    b.foto(42, "https://i.simpalsmedia.com/bitaya.jpg", "подпись")
    assert t.metody == ["sendPhoto", "sendMessage"]


def test_podpis_rezhetsya_do_limita():
    b, t = bot()
    b.foto(42, "https://a/b.jpg", "я" * 2000)
    assert len(t.vyzovy[0][1]["caption"]) == 1024


# --- отказы -----------------------------------------------------------------

def test_429_ne_teryaet_soobshchenie():
    b, t = bot([{"ok": False, "error_code": 429, "parameters": {"retry_after": 7}},
                {"ok": True, "result": {"message_id": 5}}])
    spal = []
    r = notify.otpravit_s_povtorom(lambda: b.tekst(42, "привет"),
                                   spat=spal.append)
    assert r["message_id"] == 5
    assert spal == [7]           # ждали ровно столько, сколько попросили


def test_429_bez_konca_podnimaetsya_naverh():
    b, _ = bot([{"ok": False, "error_code": 429, "parameters": {"retry_after": 3}}] * 4)
    with pytest.raises(notify.SlishkomChasto):
        notify.otpravit_s_povtorom(lambda: b.tekst(42, "привет"), spat=lambda _: None)


def test_403_ostanavlivaet_vsyu_otpravku():
    """Иначе очередь выжжется: каждая запись получит свою ошибку и попытку."""
    b, t = bot([{"ok": False, "error_code": 403,
                 "description": "Forbidden: bot was blocked by the user"}])
    with pytest.raises(notify.ZablokirovalBota):
        b.tekst(42, "первое")
    assert b.ostanovlen
    with pytest.raises(notify.ZablokirovalBota):
        b.tekst(42, "второе")
    # Второй вызов до сети даже не дошёл.
    assert len(t.vyzovy) == 1


def test_403_ne_lechitsya_povtorami():
    b, _ = bot([{"ok": False, "error_code": 403, "description": "blocked"}])
    with pytest.raises(notify.ZablokirovalBota):
        notify.otpravit_s_povtorom(lambda: b.tekst(42, "привет"), spat=lambda _: None)


def test_prochaya_oshibka_vidna_s_tekstom():
    b, _ = bot([{"ok": False, "error_code": 400, "description": "chat not found"}])
    with pytest.raises(RuntimeError, match="chat not found"):
        b.tekst(42, "привет")


# --- приём ------------------------------------------------------------------

def test_getupdates_idet_s_offsetom():
    b, t = bot([{"ok": True, "result": [{"update_id": 5}]}])
    assert b.obnovleniya(offset=12345) == [{"update_id": 5}]
    _, dannye = t.vyzovy[0]
    assert dannye["offset"] == 12345
    assert dannye["allowed_updates"] == ["message", "callback_query"]


def test_getupdates_ne_ronyaet_progon_pri_oshibke():
    """Нажатия - приятная мелочь, сбор рынка - главное. Отвалившийся
    getUpdates не должен ронять весь прогон."""
    b, _ = bot([{"ok": False, "error_code": 400, "description": "что-то не так"}])
    assert b.obnovleniya(offset=1) == []


def test_podtverzhdenie_nazhatiya_vsplyvashkoy():
    b, t = bot()
    b.otvetit_na_knopku("cb1", "Добавлено в отслеживаемые", vsplyvashkoy=True)
    metod, dannye = t.vyzovy[0]
    assert metod == "answerCallbackQuery"
    assert dannye["callback_query_id"] == "cb1"
    assert dannye["show_alert"] is True


def test_neudachnoe_podtverzhdenie_ne_ronyaet_progon():
    b, _ = bot([{"ok": False, "error_code": 400, "description": "query is too old"}])
    b.otvetit_na_knopku("cb1", "ок")     # не должно бросить


def test_pererisovka_knopki():
    b, t = bot()
    b.pererisovat_knopki(42, 99, s.knopki({"id": 7}, v_izbrannom=True))
    metod, dannye = t.vyzovy[0]
    assert metod == "editMessageReplyMarkup"
    assert dannye["message_id"] == 99
    assert "В избранном" in str(dannye["reply_markup"])
