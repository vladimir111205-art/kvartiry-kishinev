"""Оркестратор одного прогона. Запускается по расписанию из GitHub Actions,
без постоянно живущего процесса и без зависимости от чьего-либо компьютера.

Порядок жёсткий и это не случайно:

    полный обход (тощий) -> запись всего в базу -> отметить пропавших
    -> медианы по рынку -> кто подходит под профиль (до дообогащения)
    -> дообогащение только тех, кто подходит -> фильтр ЕЩЁ РАЗ
    -> очередь -> отправка

Фильтр отрабатывает дважды, потому что тощий обход не тянет описание, а в
описании прячется то, что делает объект непригодным (см. `otpravka.py`).

    python run.py                запуск на живых данных, реальная отправка
    python run.py --rezhim proba запуск на фикстурах, наружу не шлёт ничего
    python run.py --cikl 55      цикл на 55 минут: верхушка ленты раз в 30 с,
                                 весь рынок раз в 5 минут (так крутится в Actions).
                                 Ночью только весь рынок раз в 20 минут и без
                                 отправки: всё ночное уходит папе в 09:00
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import db
import filtry
import kursy
import normalizacia
import notify
import otpravka
import rynok
import soobsheniya as s
import zdorovie
from istochniki.devyat999 import Devyat999, proverit_kontrakt


class FiktivnyIstochnik:
    """Источник на фикстурах для `--rezhim proba` - ни одного запроса в сеть."""

    imya = "999md"

    def __init__(self):
        real = Devyat999()
        self._normalizovat = real.normalizovat
        self._spisok = json.loads(
            (config.FIXTURES_DIR / "999md_spisok_toshchiy.json").read_text(
                encoding="utf-8"))["data"]["searchAds"]["ads"]
        self._kursy_syrye = json.loads(
            (config.FIXTURES_DIR / "999md_kursy.json").read_text(encoding="utf-8"))
        self._odin = json.loads(
            (config.FIXTURES_DIR / "999md_obogashchenie.json").read_text(encoding="utf-8"))

    def sobrat(self, nastroyki: dict = None, limit: int = 0) -> list:
        return self._spisok

    def normalizovat(self, syroe, k_eur=None):
        return self._normalizovat(syroe, k_eur)

    def obogatit(self, vneshnie_id: list) -> dict:
        return {v: self._odin[v] for v in vneshnie_id if v in self._odin}

    def kursy_zapros(self):
        return self._kursy_syrye


class FiktivnyTransport:
    """Транспорт-пустышка для `--rezhim proba` - фиксирует, что ушло бы,
    но реально в Telegram ничего не отправляет."""

    def __init__(self):
        self.vyzovy = []

    def __call__(self, token, metod, dannye):
        self.vyzovy.append((metod, dannye))
        return {"ok": True, "result": {"message_id": len(self.vyzovy)}}


def sobrat_i_zapisat(con, istochnik, k_eur: dict, limit: int = 0) -> tuple:
    """Обход рынка (весь или верхушка limit), запись в базу. Возвращает (syrye, sobytiya)."""
    syrye = istochnik.sobrat(limit=limit) if limit else istochnik.sobrat()
    sobytiya = []
    vidennye = set()
    for syroe in syrye:
        karta = normalizacia.privesti(istochnik.normalizovat(syroe, k_eur))
        if not karta["vneshniy_id"]:
            continue
        vidennye.add(karta["vneshniy_id"])
        rezultat = db.zapisat(con, karta)
        if rezultat["povod"]:
            sobytiya.append(rezultat)
    con.commit()
    return syrye, sobytiya, vidennye


# По общей (не-избранной) ленте шлём только эти два повода - см. таблицу
# событий в плане. Рост цены, возврат в продажу и правка описания там
# помечены «нет»: это расширенный набор специально для избранного (фаза 5).
POVODY_OBSHCHEY_LENTY = {db.POVOD_NOVOE, db.POVOD_CENA_UPALA}


def doobogatit_i_ochered(con, istochnik, sobytiya: list, active_profiles: list,
                         mediany: dict, k_eur: dict) -> None:
    """Кто прошёл фильтр на тощих данных - дообогатить и проверить фильтр ещё раз.

    Дважды, потому что рассрочка (первый взнос вместо цены квартиры) видна
    только в описании, а тощий обход описание не тянет. Проверено на боевой
    отправке: 2 объекта из 14 отпали именно на этом шаге.
    """
    predvaritelno = {}
    for rezultat in sobytiya:
        karta = db.kartochka(con, rezultat["obyavlenie_id"])
        if not karta:
            continue
        karta["otklonenie_ot_rynka"] = rynok.otklonenie(karta, mediany)
        podhodit = [p["imya"] for p in active_profiles if filtry.prohodit(karta, p)]
        if podhodit:
            predvaritelno[rezultat["obyavlenie_id"]] = (rezultat, podhodit)

    ids = list(predvaritelno)
    nuzhno = db.bez_opisaniya(con, ids)
    if nuzhno:
        for vneshniy_id, syroe in istochnik.obogatit(nuzhno).items():
            if syroe:
                db.zapisat(con, normalizacia.privesti(
                    istochnik.normalizovat(syroe, k_eur)))
        con.commit()

    profili_po_imeni = {p["imya"]: p for p in active_profiles}
    for obyavlenie_id, (rezultat, imena_profiley) in predvaritelno.items():
        karta = db.kartochka(con, obyavlenie_id)
        karta["otklonenie_ot_rynka"] = rynok.otklonenie(karta, mediany)
        for imya in imena_profiley:
            profil = profili_po_imeni[imya]
            if not filtry.prohodit(karta, profil):
                print(f"[run] отпал после дообогащения: {karta.get('url')} "
                     f"(профиль «{imya}»)")
                continue
            izbran = db.v_izbrannom(con, obyavlenie_id, profil["poluchatel"])
            if not izbran and rezultat["povod"] not in POVODY_OBSHCHEY_LENTY:
                # По общей ленте шлём только новое и снижение цены (см. таблицу
                # событий в плане). Рост цены, возврат в продажу и правка -
                # это расширенный набор для избранного (фаза 5), а не для всех.
                continue
            klyuch = db.klyuch_sobytiya(rezultat["povod"], rezultat["stalo_eur"])
            db.v_ochered(con, obyavlenie_id, imya, rezultat["povod"], klyuch,
                        prioritet=10 if izbran else 0,
                        metki=filtry.metki(karta, profil),
                        bylo_eur=rezultat["bylo_eur"])
    con.commit()


def tihiy_progrev(con, bot, istochnik, active_profiles: list, mediany: dict) -> None:
    """Первый прогон (пустая база): собрать всё, пометить уведомлённым,
    прислать одно приветствие, а не лавину. Тот же код срабатывает при
    потере кэша, поэтому проверяем именно пустоту базы, а не флаг."""
    for profil in active_profiles:
        chat = config.chat_poluchatelya(profil["poluchatel"])
        if not chat:
            continue
        kandidaty = []
        for r in con.execute(
                "SELECT id FROM obyavleniya WHERE aktivno = 1 AND istochnik = ?",
                (istochnik.imya,)):
            karta = db.kartochka(con, r["id"])
            karta["otklonenie_ot_rynka"] = rynok.otklonenie(karta, mediany)
            if filtry.prohodit(karta, profil):
                kandidaty.append(karta)
        kandidaty.sort(key=lambda x: -(x.get("otklonenie_ot_rynka") or 0))
        top = [(k, rynok.mediana_gruppy(k, mediany)) for k in kandidaty[:5]]
        tekst = s.tihiy_progrev(len(kandidaty), top)
        try:
            notify.otpravit_s_povtorom(lambda: bot.tekst(chat, tekst))
        except Exception as e:
            print(f"[run] тихий прогрев не ушёл профилю «{profil['imya']}»: "
                 f"{str(e)[:120]}")
    db.pometit_vsyo_otpravlennym(con, "tihiy_progrev")
    # Очередь ещё не заполнена (события не queued в холодном старте), но на
    # всякий случай гасим - вдруг v_ochered уже что-то успел положить.
    con.commit()


def odin_progon(rezhim: str = "boy", bystro: bool = False,
                otpravlyat: bool = True) -> dict:
    """bystro=True - смотрим только свежую верхушку ленты (новые и поднятые
    за последние минуты). Снятых с продажи в этом режиме не отмечаем: кто не
    попал в верхушку, не пропал, а просто ниже в списке.

    otpravlyat=False - ночной прогон: события копятся в очереди и уходят
    первым дневным прогоном в 09:00, папу ночью не будим."""
    con = db.connect()
    proba = rezhim == "proba"
    istochnik = FiktivnyIstochnik() if proba else Devyat999()
    bot = notify.Bot(transport=FiktivnyTransport()) if proba else notify.Bot()

    progon_id = db.nachat_progon(con, istochnik.imya)
    holodnyy_start = db.baza_pustaya(con)

    try:
        konf = filtry.zagruzit(config.FILTRY_PATH)
    except filtry.OshibkaKonfiga as e:
        zdorovie.alert(bot, f"Конфиг фильтров непригоден:\n{e}")
        db.zakonchit_progon(con, progon_id, status="oshibka", oshibka=str(e)[:500])
        con.close()
        return {"status": "oshibka_konfiga"}

    active_profiles = filtry.aktivnye_profili(konf)

    if proba:
        k_eur = kursy.razobrat(istochnik.kursy_zapros())
        db.sohranit_kursy(con, k_eur)
    else:
        from istochniki.devyat999 import post as ist_post
        k_eur = kursy.svezhie(
            ist_post, sohranit=lambda d: db.sohranit_kursy(con, d),
            posledniy=lambda: db.posledniye_kursy(con))
    con.commit()

    try:
        syrye, sobytiya, vidennye = sobrat_i_zapisat(
            con, istochnik, k_eur,
            limit=config.BYSTRO_OBYAVLENIY if (bystro and not holodnyy_start) else 0)
    except Exception as e:
        zdorovie.alert(bot, f"Обход площадки упал: {type(e).__name__}: {str(e)[:300]}")
        db.zakonchit_progon(con, progon_id, status="oshibka", oshibka=str(e)[:500])
        con.close()
        return {"status": "oshibka_sbora"}

    zdorovie.proverit_kontrakt(bot, proverit_kontrakt(syrye))
    tihiy_nol = zdorovie.proverit_tihiy_nol(con, bot, len(syrye), holodnyy_start)

    if tihiy_nol:
        db.zakonchit_progon(con, progon_id, naydeno=0, status="ok")
        con.close()
        return {"status": "tihiy_nol"}

    snyatye = [] if (bystro and not holodnyy_start) else \
        db.otmetit_propavshie(con, istochnik.imya, vidennye)

    mediany = rynok.sobrat_mediany(
        con, konf["rynok"]["okno_dney"], konf["rynok"]["minimum_obektov"])

    if holodnyy_start:
        # Транспорт в --rezhim proba фиктивный (см. FiktivnyTransport), поэтому
        # тихий прогрев безопасно гонять и в пробном режиме - наружу это не шлёт.
        if otpravlyat:
            tihiy_progrev(con, bot, istochnik, active_profiles, mediany)
        else:
            # Кэш потерялся ночью: базу набираем молча, приветствие папе
            # в 3 часа ночи не шлём.
            db.pometit_vsyo_otpravlennym(con, "tihiy_progrev")
            con.commit()
        db.zakonchit_progon(con, progon_id, naydeno=len(syrye), status="ok")
        con.close()
        return {"status": "holodnyy_start", "naydeno": len(syrye)}

    doobogatit_i_ochered(con, istochnik, sobytiya, active_profiles, mediany, k_eur)

    profili_po_imeni = {p["imya"]: p for p in active_profiles}
    if otpravlyat:
        itog_otpravki = otpravka.razgruzit_ochered(con, bot, mediany, profili_po_imeni)
    else:
        itog_otpravki = {"otpravleno": 0, "ne_ushlo": 0, "ostanovleno": False,
                         "zhdet_utra": db.ochered_zhdet(con)}

    db.zakonchit_progon(
        con, progon_id, naydeno=len(syrye),
        novyh=sum(1 for s in sobytiya if s["povod"] == db.POVOD_NOVOE),
        izmenenij=sum(1 for s in sobytiya if s["povod"] != db.POVOD_NOVOE),
        otpravleno=itog_otpravki["otpravleno"], status="ok")

    con.close()
    return {"status": "ok", "naydeno": len(syrye), "sobytiy": len(sobytiya),
            "snyato": len(snyatye), **itog_otpravki}


def cikl(minut: int, rezhim: str = "boy") -> int:
    """Держать цикл minut минут, круглосуточно.

    День (CHAS_S-CHAS_DO по Кишинёву): первый заход и дальше раз в
    CIKL_POLNYY_SEK - весь рынок (медианы, снижения цены без подъёма, снятые),
    между ними раз в CIKL_PAUZA_SEK - только верхушка ленты: новый объект
    уходит папе через 1-2 минуты после публикации.

    Ночь: только весь рынок раз в CIKL_POLNYY_NOCH_SEK и без отправки. Цепочка не
    гаснет, поэтому утром её не надо будить расписанием GitHub - а оно
    опаздывало на 6 часов (замер 27.09-01.10: первый прогон в 14:00 вместо
    08:00 каждый день). Всё, что вышло за ночь, уходит папе в 09:00.
    Возвращает код выхода: 1 только если прогоны падали подряд до конца цикла.
    """
    tz = ZoneInfo("Europe/Chisinau")
    konec = time.time() + minut * 60
    posledniy_polnyy = 0.0
    padeniy_podryad = 0
    while time.time() < konec:
        t0 = time.time()
        chas = datetime.now(tz).hour
        den = config.CHAS_S <= chas < config.CHAS_DO
        polnyy = t0 - posledniy_polnyy >= (
            config.CIKL_POLNYY_SEK if den else config.CIKL_POLNYY_NOCH_SEK)
        if not den and not polnyy:
            time.sleep(config.CIKL_PAUZA_SEK)
            continue
        try:
            itog = odin_progon(rezhim, bystro=not polnyy, otpravlyat=den)
        except Exception as e:
            itog = {"status": f"isklyuchenie {type(e).__name__}: {str(e)[:200]}"}
        ok = itog.get("status") in ("ok", "tihiy_nol", "holodnyy_start")
        padeniy_podryad = 0 if ok else padeniy_podryad + 1
        if polnyy and ok:
            posledniy_polnyy = t0
        rezhim_progona = "весь рынок" if polnyy else "верхушка"
        if not den:
            rezhim_progona += " (ночь, без отправки)"
        print(f"[cikl] {datetime.now(tz):%H:%M:%S} {rezhim_progona}: {itog}",
              flush=True)
        if rezhim == "proba":
            break
        time.sleep(max(0.0, config.CIKL_PAUZA_SEK - (time.time() - t0)))
    return 1 if padeniy_podryad >= 3 else 0



if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rezhim", choices=["boy", "proba"], default="boy")
    ap.add_argument("--cikl", type=int, default=0,
                    help="держать цикл столько минут (0 - один прогон)")
    args = ap.parse_args()
    if args.cikl:
        sys.exit(cikl(args.cikl, args.rezhim))
    itog = odin_progon(args.rezhim)
    print(f"[run] итог: {itog}")
    sys.exit(0 if itog.get("status") in ("ok", "tihiy_nol", "holodnyy_start") else 1)
