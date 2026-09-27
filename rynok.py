"""Медианы €/м² по связке сектор+комнатность и отклонение объекта от рынка.

Ради этого модуля вся база и собирается целиком. Без базы сравнения агент
превращается в ленту объявлений: «появилась двушка в Ботанике» - это новость,
а «двушка в Ботанике вышла по 1 040 €/м² при медиане сектора 1 380» - повод
звонить сегодня.

Три решения:

- **медиана, а не среднее**: одна квартира за 500 000 € не должна сдвигать
  оценку сектора;
- **минимум объектов в выборке** (по умолчанию 15): меньше - оценка не
  выводится и метка не ставится. Лучше промолчать, чем соврать цифрой, на
  которую человек будет принимать решение о деньгах;
- **окно в 90 дней**: рынок за квартал успевает сдвинуться, а более старые
  объявления тянут оценку назад.

Первые недели база будет мелкой, и метка просто не появится - это нормально,
агент в это время работает как обычный уведомитель и включит оценку сам,
когда выборки дорастут.
"""
from __future__ import annotations

import statistics


def _mediana(znacheniya: list) -> float:
    return round(statistics.median(znacheniya), 2)


def gruppa(karta: dict) -> tuple:
    """Ключ сравнения: город + сектор + комнатность.

    Город в ключе не для красоты: у села Колоница тоже есть сектор «Центр», и
    без города его квартиры по 300 €/м² смешаются с центром Кишинёва по
    2000 €/м². Медиана станет средним по больнице, а объекты Кишинёва начнут
    выглядеть «дороже рынка».
    """
    return (karta.get("gorod"), karta.get("sektor"), karta.get("komnat"))


def sobrat_mediany(con, okno_dney: int = 90, minimum: int = 15,
                   sdelka: str = "prodazha") -> dict:
    """{(gorod, sektor, komnat): {'mediana': €/м², 'obektov': N}}.

    Аренда в расчёт продажи не идёт: 500 €/мес и 50 000 € - величины из разных
    миров, и смешать их значит получить бессмысленное число.
    """
    stroki = con.execute(
        "SELECT gorod, sektor, komnat, cena_eur_za_m2 FROM obyavleniya "
        "WHERE sdelka = ? AND aktivno = 1 AND gorod != '' AND sektor != '' AND komnat > 0 "
        "AND cena_eur_za_m2 > 0 AND dannye_nadezhny = 1 "
        "AND podnyato_at >= date('now', ?)",
        (sdelka, f"-{int(okno_dney)} day")).fetchall()

    po_gruppam = {}
    for r in stroki:
        po_gruppam.setdefault((r["gorod"], r["sektor"], r["komnat"]), []).append(
            r["cena_eur_za_m2"])

    out = {}
    for gruppa, ceny in po_gruppam.items():
        if len(ceny) < minimum:
            # Выборка мала - группы просто нет. Вызывающий код увидит отсутствие
            # и не поставит метку, вместо того чтобы посчитать «примерно».
            continue
        out[gruppa] = {"mediana": _mediana(ceny), "obektov": len(ceny)}
    return out


def otklonenie(karta: dict, mediany: dict) -> float:
    """На сколько процентов €/м² карточки ниже медианы её группы.

    Положительное число - дешевле рынка, отрицательное - дороже. Ноль означает
    «сказать нечего»: либо нет цены за метр, либо выборка группы мала.
    """
    za_m2 = karta.get("cena_eur_za_m2") or 0
    if za_m2 <= 0:
        return 0.0
    # Объявление с опечаткой в площади не сравниваем с рынком: именно такие
    # дают «дешевле на 99%» и встают первыми в списке.
    if not karta.get("dannye_nadezhny", 1):
        return 0.0
    g = mediany.get(gruppa(karta))
    if not g or not g["mediana"]:
        return 0.0
    return round((g["mediana"] - za_m2) / g["mediana"] * 100, 1)


def mediana_gruppy(karta: dict, mediany: dict) -> dict:
    """Медиана и размер выборки для карточки - чтобы показать их в сообщении.

    В карточку попадает и число объектов: «медиана сектора 1 210 €/м²» без
    указания, по скольки объектам она посчитана, - это цифра без веса.
    """
    return mediany.get(gruppa(karta)) or {}


def prostavit_otkloneniya(kartochki: list, mediany: dict) -> list:
    for k in kartochki:
        k["otklonenie_ot_rynka"] = otklonenie(k, mediany)
    return kartochki


def dvizhenie_mediany(con, sektor: str, komnat: int, dney_nazad: int = 7,
                      gorod: str = "kishinev",
                      okno_dney: int = 90, minimum: int = 15) -> dict:
    """Насколько сдвинулась медиана группы за неделю - строка дневной сводки.

    Считается по истории цен: берём последнюю известную цену каждого объявления
    на ту дату, а не текущую. Иначе «движение за неделю» всегда будет нулём.
    """
    def na_datu(sdvig_dney: int):
        stroki = con.execute(
            "SELECT o.ploshad_m2, ("
            "  SELECT i.cena_eur FROM istoriya_cen i "
            "  WHERE i.obyavlenie_id = o.id AND i.zamecheno_at <= datetime('now', ?) "
            "  ORDER BY i.zamecheno_at DESC LIMIT 1"
            ") AS cena "
            "FROM obyavleniya o "
            "WHERE o.gorod = ? AND o.sektor = ? AND o.komnat = ? AND o.sdelka = 'prodazha' "
            "AND o.ploshad_m2 > 0 AND o.dannye_nadezhny = 1 "
            "AND o.podnyato_at >= date('now', ?)",
            (f"-{int(sdvig_dney)} day", gorod, sektor, komnat,
             f"-{int(okno_dney)} day")).fetchall()
        za_m2 = [r["cena"] / r["ploshad_m2"] for r in stroki
                 if r["cena"] and r["ploshad_m2"]]
        return _mediana(za_m2) if len(za_m2) >= minimum else None

    seychas, bylo = na_datu(0), na_datu(dney_nazad)
    if seychas is None or bylo is None or not bylo:
        return {}
    return {"seychas": seychas, "bylo": bylo,
            "izmenenie_pct": round((seychas - bylo) / bylo * 100, 1)}
