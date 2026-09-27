"""Тексты сообщений. Ни сети, ни базы - чистые функции от карточки к строке.

Почему текст живёт отдельно от логики: его правят чаще всего и правят на глаз,
а ломаться от этого ничего не должно. Здесь же лежит вся защита от того, что
читатель увидит «None», «0 м²» или сырой HTML.

Получатель - не технический человек. Значит: никаких кодов вроде `botanika`,
никаких пустых строк с эмодзи, никаких цифр без единиц.
"""
from __future__ import annotations

import html

import config

# Обратный перевод в человеческий вид. Канонические коды нужны фильтрам,
# а папе нужен русский текст.
SEKTORY = {
    "centr": "Центр", "botanika": "Ботаника", "chekany": "Чокана",
    "ryshkanovka": "Рышкановка", "buyukany": "Буюканы", "telecentr": "Телецентр",
    "staraya_pochta": "Старая Почта", "skulyanka": "Скулянка", "aeroport": "Аэропорт",
}
GORODA = {
    "kishinev": "Кишинёв", "durleshty": "Дурлешты", "kodru": "Кодру",
    "stavcheny": "Ставчены", "gidigich": "Гидигич", "gratieshty": "Гратиешты",
    "choresku": "Чореску", "bachoy": "Бачой", "synzhera": "Сынжера",
    "vatra": "Ватра", "krikovo": "Криково", "trusheny": "Трушены",
    "bubuech": "Бубуечь", "revaka": "Ревака", "togatin": "Тогатин",
    "kolonica": "Колоница", "budeshty": "Будешты", "vadul": "Вадул-луй-Водэ",
    "dobruzha": "Добружа", "gyoyan": "Гоян",
}
SOSTOYANIYA = {
    "evroremont": "евроремонт", "horoshee": "хорошее состояние",
    "srednee": "среднее состояние", "bez_remonta": "без ремонта",
    "chernovaya": "черновой вариант", "pod_klyuch": "под ключ",
    "chastichnyy": "частичный ремонт", "svezhiy": "свежий ремонт",
    "dizaynerskiy": "дизайнерский ремонт",
}
FONDY = {"novostroy": "новострой", "vtorichka": "вторичка"}
TIPY_DOMA = {
    "monolit": "монолит", "kirpich": "кирпич", "panel": "панель",
    "kotelec": "котелец", "blok": "блок", "derevo": "дерево",
}
PRODAVCY = {
    "sobstvennik": "собственник", "agentstvo": "агентство",
    "zastroyshchik": "застройщик", "posrednik": "посредник",
}
SDELKI = {"prodazha": "продажа", "arenda": "аренда", "arenda_sutki": "посуточно"}

ZAGOLOVKI_POVODOV = {
    "novoe": "",
    "cena_upala": "📉",
    "cena_vyrosla": "📈",
    "vernulos": "↩️ Снова в продаже",
    "snyato": "🚫 Снято с продажи",
    "pravka": "✏️ Объявление поправили",
}


def ekran(s) -> str:
    """HTML-экранирование. Заголовок с `&` или `<` иначе роняет parse_mode,
    и сообщение просто не уходит - молча, что хуже всего."""
    return html.escape(str(s or ""), quote=False)


def chislo(n, edinica: str = "") -> str:
    """52000 -> «52 000 €». Неразрывный пробел, чтобы число не рвалось."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    celoe = f"{int(round(n)):,}".replace(",", " ")
    return f"{celoe} {edinica}".strip() if edinica else celoe


def komnatnost(k) -> str:
    try:
        k = int(k)
    except (TypeError, ValueError):
        return "квартира"
    return f"{k}-комнатная" if k else "квартира"


def _sektor_gorod(karta: dict) -> str:
    sektor = SEKTORY.get(karta.get("sektor"), "")
    gorod = GORODA.get(karta.get("gorod"), "")
    # Сектор Кишинёва говорит сам за себя, а вот «Центр» Колоницы без города
    # читается как центр города - и это ровно та путаница, из-за которой
    # медианы считаются с городом в ключе.
    if gorod and gorod != "Кишинёв":
        return f"{sektor}, {gorod}" if sektor else gorod
    return sektor


def stroka_ceny(karta: dict) -> str:
    ceny = chislo(karta.get("cena_eur"), "€")
    za_m2 = karta.get("cena_eur_za_m2")
    if not ceny:
        return "💶 цена не указана"
    if za_m2:
        return f"💶 {ceny} · {chislo(za_m2, '€/м²')}"
    return f"💶 {ceny}"


def stroka_rynka(karta: dict, gruppa: dict) -> str:
    """«на 22% дешевле рынка (медиана 1 210 €/м² по 340 объектам)».

    Число объектов показываем всегда: медиана без указания, по скольки
    объектам она посчитана, - это цифра без веса, а решение по ней о деньгах.
    """
    otkl = karta.get("otklonenie_ot_rynka") or 0
    if not gruppa or not gruppa.get("mediana") or otkl < 1:
        return ""
    znak = "🔥" if otkl >= 20 else "👀"
    return (f"{znak} на {otkl:.0f}% дешевле рынка "
            f"(медиана {chislo(gruppa['mediana'], '€/м²')} "
            f"по {gruppa['obektov']} объектам)")


def stroka_ploshadi(karta: dict) -> str:
    chasti = []
    if karta.get("ploshad_m2"):
        chasti.append(chislo(karta["ploshad_m2"], "м²"))
    etazh, etazhnost = karta.get("etazh"), karta.get("etazhnost")
    if etazh and etazhnost:
        chasti.append(f"этаж {etazh} из {etazhnost}")
    elif etazh:
        chasti.append(f"этаж {etazh}")
    return "📐 " + " · ".join(chasti) if chasti else ""


def stroka_doma(karta: dict) -> str:
    chasti = [x for x in (
        FONDY.get(karta.get("fond"), ""),
        TIPY_DOMA.get(karta.get("tip_doma"), ""),
        SOSTOYANIYA.get(karta.get("sostoyanie"), ""),
    ) if x]
    prodavec = PRODAVCY.get(karta.get("prodavec"), "")
    levo = ", ".join(chasti)
    if levo and prodavec:
        return f"🏗 {levo} · {prodavec}"
    if levo:
        return f"🏗 {levo}"
    if prodavec:
        return f"🏗 {prodavec}"
    return ""


def stroka_adresa(karta: dict) -> str:
    ulica = (karta.get("ulica") or "").strip()
    return f"📍 {ekran(ulica)}" if ulica else ""


def shapka_ceny(povod: str, bylo: float, stalo: float) -> str:
    """«📉 Было 58 000 €, стало 52 000 € (-10%)»."""
    if povod not in ("cena_upala", "cena_vyrosla") or not bylo or not stalo:
        return ZAGOLOVKI_POVODOV.get(povod, "")
    pct = (stalo - bylo) / bylo * 100
    znak = ZAGOLOVKI_POVODOV[povod]
    return (f"{znak} Было {chislo(bylo, '€')}, стало {chislo(stalo, '€')} "
            f"({pct:+.0f}%)")


def stroka_izbrannogo(karta: dict, cena_pri_dobavlenii: float) -> str:
    """«⭐ с момента добавления -8 000 € (-13%)» - движение от точки интереса."""
    seychas = karta.get("cena_eur") or 0
    if not cena_pri_dobavlenii or not seychas:
        return ""
    raznica = seychas - cena_pri_dobavlenii
    if abs(raznica) < 1:
        return "⭐ цена не менялась с момента добавления"
    pct = raznica / cena_pri_dobavlenii * 100
    znak = "-" if raznica < 0 else "+"
    return (f"⭐ с момента добавления {znak}{chislo(abs(raznica), '€')} "
            f"({pct:+.0f}%)")


def kartochka(karta: dict, gruppa: dict = None, povod: str = "novoe",
              bylo: float = 0, stalo: float = 0, metki: list = None,
              cena_pri_dobavlenii: float = 0) -> str:
    """Подпись к фото. Гарантированно не длиннее лимита Telegram."""
    strok = []

    shapka = shapka_ceny(povod, bylo, stalo)
    if shapka:
        strok.append(f"<b>{ekran(shapka)}</b>")

    gde = _sektor_gorod(karta)
    zagolovok = komnatnost(karta.get("komnat"))
    if gde:
        zagolovok += f", {gde}"
    sdelka = karta.get("sdelka")
    if sdelka and sdelka != "prodazha":
        zagolovok += f" · {SDELKI.get(sdelka, sdelka)}"
    strok.append(f"🏠 <b>{ekran(zagolovok)}</b>")

    strok.append(stroka_ceny(karta))
    for stroka in (stroka_rynka(karta, gruppa or {}),
                   stroka_izbrannogo(karta, cena_pri_dobavlenii),
                   stroka_ploshadi(karta),
                   stroka_doma(karta),
                   stroka_adresa(karta)):
        if stroka:
            strok.append(stroka)

    prochie = [m for m in (metki or []) if m and m != "дешевле рынка"]
    if prochie:
        strok.append("🏷 " + ", ".join(ekran(m) for m in prochie))

    tekst = "\n".join(strok)
    if len(tekst) > config.MAX_PODPISI:
        # Режем по строкам, а не по символам: обрезанная строка выглядит
        # поломкой, а недостающая строка - просто короче.
        while len(tekst) > config.MAX_PODPISI and len(strok) > 3:
            strok.pop()
            tekst = "\n".join(strok)
        tekst = tekst[:config.MAX_PODPISI]
    return tekst


def knopki(karta: dict, v_izbrannom: bool = False) -> dict:
    """Две кнопки: открыть объявление и поставить на отслеживание."""
    oid = karta.get("id") or karta.get("obyavlenie_id") or 0
    metka = "⭐ В избранном" if v_izbrannom else "⭐ Отслеживать"
    dejstvie = "izb_ubrat" if v_izbrannom else "izb_dobavit"
    ryad = []
    if karta.get("url"):
        ryad.append({"text": "Открыть на 999.md", "url": karta["url"]})
    ryad.append({"text": metka, "callback_data": f"{dejstvie}:{oid}"})
    return {"inline_keyboard": [ryad]}


def daydzhest(kartochki_s_gruppami: list, povod: str = "novoe") -> str:
    """Больше нескольких карточек за прогон - одно сообщение списком.

    Лавина из двадцати сообщений подряд отучает читать бота быстрее, чем
    полное молчание.
    """
    shapka = {"novoe": "🆕 Новые объекты",
              "cena_upala": "📉 Подешевели",
              "snyato": "🚫 Ушли с продажи"}.get(povod, "Изменения")
    strok = [f"<b>{shapka}: {len(kartochki_s_gruppami)}</b>", ""]
    for karta, gruppa in kartochki_s_gruppami:
        gde = _sektor_gorod(karta) or "—"
        otkl = karta.get("otklonenie_ot_rynka") or 0
        hvost = f" · на {otkl:.0f}% дешевле рынка" if otkl >= 1 and gruppa else ""
        url = karta.get("url") or ""
        nazvanie = f"{komnatnost(karta.get('komnat'))}, {ekran(gde)}"
        strok.append(
            f"• <a href=\"{ekran(url)}\">{nazvanie}</a> — "
            f"{chislo(karta.get('cena_eur'), '€')}"
            f"{', ' + chislo(karta.get('ploshad_m2'), 'м²') if karta.get('ploshad_m2') else ''}"
            f"{hvost}")
    return "\n".join(strok)[:4000]


def tihiy_progrev(vsego: int, top: list) -> str:
    """Первое сообщение: бот подключён, лавины не будет."""
    strok = [
        "<b>Бот подключён.</b>",
        f"Сейчас по вашим условиям в продаже {vsego} подходящих квартир.",
        "",
        "Чтобы не заваливать вас сразу, я их не присылаю - буду писать только "
        "о новых и о тех, где изменилась цена.",
    ]
    if top:
        strok += ["", "<b>Самые дешёвые по цене за метр из них:</b>"]
        for karta, _ in top:
            gde = _sektor_gorod(karta) or "—"
            strok.append(
                f"• <a href=\"{ekran(karta.get('url') or '')}\">"
                f"{komnatnost(karta.get('komnat'))}, {ekran(gde)}</a> — "
                f"{chislo(karta.get('cena_eur'), '€')} · "
                f"{chislo(karta.get('cena_eur_za_m2'), '€/м²')}")
    return "\n".join(strok)[:4000]


def svodka(za_den: dict, mediany: list, izbrannye: list) -> str:
    """Вечерняя сводка: что за день изменилось и как стоит рынок."""
    strok = ["<b>📊 Итоги дня</b>", ""]
    strok.append(f"Новых: {za_den.get('novyh', 0)} · "
                 f"подешевело: {za_den.get('podesheveli', 0)} · "
                 f"ушло с продажи: {za_den.get('snyato', 0)}")

    if mediany:
        strok += ["", "<b>Цена за метр по интересующим секторам:</b>"]
        for m in mediany:
            hvost = ""
            if m.get("izmenenie_pct"):
                hvost = f" ({m['izmenenie_pct']:+.1f}% за неделю)"
            strok.append(
                f"• {SEKTORY.get(m['sektor'], m['sektor'])}, "
                f"{komnatnost(m['komnat'])} — {chislo(m['mediana'], '€/м²')}"
                f"{hvost}")

    if izbrannye:
        strok += ["", "<b>⭐ Отслеживаемые:</b>"]
        for karta in izbrannye:
            dvizhenie = stroka_izbrannogo(karta, karta.get("cena_pri_dobavlenii"))
            hvost = f" — {dvizhenie[2:]}" if dvizhenie else ""
            status = "" if karta.get("aktivno", 1) else " · снято с продажи"
            strok.append(
                f"• <a href=\"{ekran(karta.get('url') or '')}\">"
                f"{komnatnost(karta.get('komnat'))}, "
                f"{ekran(_sektor_gorod(karta) or '—')}</a> — "
                f"{chislo(karta.get('cena_eur'), '€')}{hvost}{status}")
    return "\n".join(strok)[:4000]


def ya_na_svyazi(dney: int) -> str:
    """Обратный предохранитель: молчание не должно выглядеть как поломка."""
    return (f"Я на связи. За последние {dney} дн. ничего нового по вашим "
            f"условиям не появилось - как только появится, напишу сразу.")


def spisok_izbrannogo(izbrannye: list) -> str:
    if not izbrannye:
        return ("Пока вы ничего не отслеживаете.\n\n"
                "Нажмите «⭐ Отслеживать» под любой карточкой - и я буду "
                "сообщать по этому объекту обо всём и сразу.")
    strok = [f"<b>⭐ Отслеживаемые объекты: {len(izbrannye)}</b>", ""]
    for karta in izbrannye:
        dvizhenie = stroka_izbrannogo(karta, karta.get("cena_pri_dobavlenii"))
        strok.append(
            f"• <a href=\"{ekran(karta.get('url') or '')}\">"
            f"{komnatnost(karta.get('komnat'))}, "
            f"{ekran(_sektor_gorod(karta) or '—')}</a> — "
            f"{chislo(karta.get('cena_eur'), '€')}")
        if dvizhenie:
            strok.append(f"   {dvizhenie}")
    return "\n".join(strok)[:4000]
