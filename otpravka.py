"""Сборка и отправка карточек: дообогащение, перепроверка, очередь.

Ключевая мысль файла - **перепроверка фильтра после дообогащения**.

Тощий обход не тянет описание, а в описании прячется то, что делает объект
непригодным: «в рассрочку», где в поле цены стоит первый взнос, а не цена
квартиры. Проверять фильтр только до дообогащения значит отправлять такие
объекты - проверено на живых данных: из трёх первых карточек одна оказалась
рассрочкой и ушла бы папе как «на 41% дешевле рынка».

Поэтому порядок жёсткий: фильтр -> дообогащение -> **фильтр ещё раз** ->
отправка.
"""
from __future__ import annotations

import config
import db
import filtry
import normalizacia
import rynok
import soobsheniya as s
from notify import SlishkomChasto, ZablokirovalBota, otpravit_s_povtorom


def podgotovit(con, istochnik, kandidaty: list, profil: dict, mediany: dict,
               k_eur: dict) -> list:
    """Дотянуть описание и фото, пересчитать и отсеять тех, кто отпал.

    Возвращает только те карточки, которые прошли фильтр **после** того, как
    мы узнали о них всё.
    """
    nuzhno = db.bez_opisaniya(con, [k["id"] for k in kandidaty])
    if nuzhno:
        for vneshniy_id, syroe in istochnik.po_id(nuzhno):
            if not syroe:
                continue
            db.zapisat(con, normalizacia.privesti(
                istochnik.normalizovat(syroe, k_eur)))
        con.commit()

    gotovye = []
    for kandidat in kandidaty:
        karta = db.kartochka(con, kandidat["id"])
        if not karta:
            continue
        karta["otklonenie_ot_rynka"] = rynok.otklonenie(karta, mediany)
        if not filtry.prohodit(karta, profil):
            # Дообогащение вскрыло то, чего не было видно в тощей карточке.
            print(f"[отправка] отпал после дообогащения: {karta.get('url')}")
            continue
        gotovye.append(karta)
    return gotovye


def otpravit_kartochku(bot, chat_id, karta: dict, mediany: dict, profil: dict,
                       povod: str = "novoe", bylo: float = 0,
                       v_izbrannom: bool = False,
                       cena_pri_dobavlenii: float = 0) -> dict:
    gruppa = rynok.mediana_gruppy(karta, mediany)
    podpis = s.kartochka(
        karta, gruppa, povod=povod, bylo=bylo, stalo=karta.get("cena_eur"),
        metki=filtry.metki(karta, profil) if profil else [],
        cena_pri_dobavlenii=cena_pri_dobavlenii)
    foto = (karta.get("foto") or [""])[0]
    return otpravit_s_povtorom(
        lambda: bot.foto(chat_id, foto, podpis, s.knopki(karta, v_izbrannom)))


def razgruzit_ochered(con, bot, mediany: dict, profili_po_imeni: dict) -> dict:
    """Отправить то, что ждёт в очереди, соблюдая потолки.

    Не ушло - запись остаётся в очереди со счётчиком попыток и уйдёт следующим
    прогоном. Заблокировали бота - останавливаемся целиком, чтобы не выжечь
    очередь по одной записи.
    """
    itog = {"otpravleno": 0, "ne_ushlo": 0, "ostanovleno": False}
    k_otpravke = db.ochered_k_otpravke(con)

    # Дайджестом идут только обычные новинки: по избранному владелец ждёт
    # каждое движение сам, сворачивать их в список нельзя.
    obychnye_novye = [z for z in k_otpravke
                      if z["prioritet"] <= 0 and z["povod"] == db.POVOD_NOVOE]
    daydzhestom = len(obychnye_novye) > config.POROG_DAYDZHESTA

    for zapis in k_otpravke:
        if daydzhestom and zapis in obychnye_novye:
            continue
        karta = db.kartochka(con, zapis["obyavlenie_id"])
        if not karta:
            db.otmetit_otpravlennym(con, zapis["id"], "нет карточки")
            continue
        karta["otklonenie_ot_rynka"] = rynok.otklonenie(karta, mediany)
        profil = profili_po_imeni.get(zapis["profil"])
        chat = config.chat_poluchatelya(
            (profil or {}).get("poluchatel", ""))
        if not chat:
            db.otmetit_otpravlennym(con, zapis["id"], "нет получателя")
            continue
        try:
            r = otpravit_kartochku(
                bot, chat, karta, mediany, profil,
                povod=zapis["povod"], bylo=zapis.get("bylo_eur") or 0,
                v_izbrannom=bool(zapis["prioritet"] > 0))
            db.otmetit_otpravlennym(con, zapis["id"], r.get("message_id"))
            itog["otpravleno"] += 1
            # Для проверки «первым ли»: что ушло и когда объявление подняли.
            print(f"[отправка] папе: {karta.get('url')} {zapis['povod']} "
                  f"(подняли на 999.md {karta.get('podnyato_at') or '?'})", flush=True)
        except ZablokirovalBota as e:
            print(f"[отправка] остановлена: {e}")
            itog["ostanovleno"] = True
            break
        except (SlishkomChasto, RuntimeError) as e:
            print(f"[отправка] не ушло, останется в очереди: {str(e)[:120]}")
            db.otmetit_popytku(con, zapis["id"])
            itog["ne_ushlo"] += 1

    if daydzhestom and not itog["ostanovleno"]:
        itog["otpravleno"] += _daydzhest(con, bot, mediany, profili_po_imeni,
                                         obychnye_novye)
    con.commit()
    return itog


def _daydzhest(con, bot, mediany, profili_po_imeni, zapisi) -> int:
    """Больше порога карточек за прогон - одно сообщение списком.

    Лавина из двадцати сообщений подряд отучает читать бота быстрее, чем
    полное молчание.
    """
    po_chatam = {}
    for zapis in zapisi:
        karta = db.kartochka(con, zapis["obyavlenie_id"])
        if not karta:
            continue
        karta["otklonenie_ot_rynka"] = rynok.otklonenie(karta, mediany)
        profil = profili_po_imeni.get(zapis["profil"]) or {}
        chat = config.chat_poluchatelya(profil.get("poluchatel", ""))
        if chat:
            po_chatam.setdefault(chat, []).append(
                (zapis, karta, rynok.mediana_gruppy(karta, mediany)))

    ushlo = 0
    for chat, punkty in po_chatam.items():
        tekst = s.daydzhest([(k, g) for _, k, g in punkty])
        try:
            r = otpravit_s_povtorom(lambda: bot.tekst(chat, tekst, bez_preview=True))
            for zapis, _, _ in punkty:
                db.otmetit_otpravlennym(con, zapis["id"], r.get("message_id"))
            ushlo += 1
        except Exception as e:
            print(f"[отправка] дайджест не ушёл: {str(e)[:120]}")
            for zapis, _, _ in punkty:
                db.otmetit_popytku(con, zapis["id"])
    return ushlo
