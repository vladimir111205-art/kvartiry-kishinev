"""База: схема, upsert, история цен, очередь отправки, избранное.

Три решения, которые стоит держать в голове при чтении:

1. **Ручные пометки не перезаписываются.** `status` и `zametka` ставит человек,
   а ingest их не трогает - иначе очередной прогон затрёт то, что владелец
   пометил руками. Механика взята из agents/9_base_miner/database.py.

2. **Очередь вместо прямой отправки.** Раннер эфемерный, и падение на середине
   отправки не должно давать ни дублей, ни потерь: событие сначала ложится в
   очередь, потом отправляется, потом помечается отправленным.

3. **Событие определяется хешем карточки**, а не сравнением всех полей: правка
   описания или добавление фотографии событием не считается, иначе бот будет
   дёргать папу по каждой косметической правке продавца.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import config
import normalizacia

SHEMA = """
CREATE TABLE IF NOT EXISTS obyavleniya (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    istochnik       TEXT NOT NULL,
    vneshniy_id     TEXT NOT NULL,
    url             TEXT,
    zagolovok       TEXT,
    sdelka          TEXT,
    gorod           TEXT,
    sektor          TEXT,
    ulica           TEXT,
    cena            REAL,
    valyuta         TEXT,
    cena_eur        REAL,
    cena_eur_za_m2  REAL,
    prezhnyaya_cena_eur REAL,
    komnat          INTEGER,
    ploshad_m2      REAL,
    etazh           INTEGER,
    etazhnost       INTEGER,
    tip_doma        TEXT,
    sostoyanie      TEXT,
    fond            TEXT,
    prodavec        TEXT,
    avtor_login     TEXT,
    opisanie        TEXT,
    foto_json       TEXT,
    podnyato_at     TEXT,
    dannye_nadezhny INTEGER DEFAULT 1,
    hash_kartochki  TEXT,
    pervyy_raz      TEXT DEFAULT (datetime('now')),
    posledniy_raz   TEXT DEFAULT (datetime('now')),
    aktivno         INTEGER DEFAULT 1,
    propuskov       INTEGER DEFAULT 0,
    -- Ручные пометки владельца. ingest их НИКОГДА не перезаписывает.
    status          TEXT,
    zametka         TEXT,
    UNIQUE(istochnik, vneshniy_id)
);

-- Строка появляется только при смене цены, а не при каждом прогоне.
CREATE TABLE IF NOT EXISTS istoriya_cen (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    obyavlenie_id  INTEGER NOT NULL,
    cena_eur       REAL,
    zamecheno_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ochered (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    obyavlenie_id  INTEGER NOT NULL,
    profil         TEXT NOT NULL,
    povod          TEXT NOT NULL,
    -- Ключ события: повод плюс то, что отличает одно срабатывание от другого
    -- (например новая цена). Без него второе снижение цены по тому же объекту
    -- не попало бы в очередь - UNIQUE бы его проглотил.
    klyuch         TEXT NOT NULL,
    prioritet      INTEGER DEFAULT 0,
    -- Цена до события: без неё шапку «Было 58 000 €, стало 52 000 €» не
    -- собрать, а к моменту отправки прежняя цена в карточке уже затёрта.
    bylo_eur       REAL DEFAULT 0,
    metki_json     TEXT,
    sostoyanie     TEXT DEFAULT 'zhdet',   -- zhdet | otpravleno | otkazano
    popytok        INTEGER DEFAULT 0,
    message_id     TEXT,
    sozdano_at     TEXT DEFAULT (datetime('now')),
    otpravleno_at  TEXT,
    UNIQUE(obyavlenie_id, profil, klyuch)
);

CREATE TABLE IF NOT EXISTS izbrannoe (
    obyavlenie_id       INTEGER NOT NULL,
    kto                 TEXT NOT NULL,
    dobavleno_at        TEXT DEFAULT (datetime('now')),
    cena_pri_dobavlenii REAL,
    primechanie         TEXT,
    UNIQUE(obyavlenie_id, kto)
);

CREATE TABLE IF NOT EXISTS progony (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nachalo    TEXT DEFAULT (datetime('now')),
    konec      TEXT,
    istochnik  TEXT,
    naydeno    INTEGER DEFAULT 0,
    novyh      INTEGER DEFAULT 0,
    izmenenij  INTEGER DEFAULT 0,
    otpravleno INTEGER DEFAULT 0,
    status     TEXT DEFAULT 'idet',
    oshibka    TEXT
);

CREATE TABLE IF NOT EXISTS kursy (
    valyuta  TEXT PRIMARY KEY,
    k_eur    REAL,
    na_datu  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_ob_aktivno   ON obyavleniya(aktivno);
CREATE INDEX IF NOT EXISTS idx_ob_rynok     ON obyavleniya(sektor, komnat, sdelka, dannye_nadezhny, podnyato_at);
CREATE INDEX IF NOT EXISTS idx_ochered_zhdet ON ochered(sostoyanie, prioritet DESC, id);
CREATE INDEX IF NOT EXISTS idx_istoriya     ON istoriya_cen(obyavlenie_id, zamecheno_at);
"""

# Поля карточки, которые кладутся в таблицу как есть.
POLYA_V_BAZU = [p for p in normalizacia.POLYA if p not in ("foto", "otklonenie_ot_rynka")]


def connect(put: Path = None) -> sqlite3.Connection:
    put = Path(put or config.DB_PATH)
    put.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(put, timeout=60)
    con.row_factory = sqlite3.Row
    # WAL и busy_timeout - по образцу agents/13_uae_leadgen/db.py.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=60000")
    con.executescript(SHEMA)
    return con


# --- meta -------------------------------------------------------------------

def meta_get(con, klyuch: str, po_umolchaniyu=None):
    r = con.execute("SELECT value FROM meta WHERE key = ?", (klyuch,)).fetchone()
    return r["value"] if r else po_umolchaniyu


def meta_set(con, klyuch: str, znachenie) -> None:
    con.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (klyuch, str(znachenie)))


def baza_pustaya(con) -> bool:
    return not con.execute("SELECT 1 FROM obyavleniya LIMIT 1").fetchone()


# --- курсы ------------------------------------------------------------------

def sohranit_kursy(con, k_eur: dict) -> None:
    for val, kurs in k_eur.items():
        con.execute(
            "INSERT INTO kursy (valyuta, k_eur, na_datu) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(valyuta) DO UPDATE SET k_eur = excluded.k_eur, "
            "na_datu = excluded.na_datu", (val, kurs))
    con.commit()


def posledniye_kursy(con) -> dict:
    return {r["valyuta"]: r["k_eur"] for r in con.execute("SELECT valyuta, k_eur FROM kursy")}


# --- ingest -----------------------------------------------------------------

POVOD_NOVOE = "novoe"
POVOD_CENA_UPALA = "cena_upala"
POVOD_CENA_VYROSLA = "cena_vyrosla"
POVOD_PRAVKA = "pravka"
POVOD_SNYATO = "snyato"
POVOD_VERNULOS = "vernulos"


def zapisat(con, karta: dict) -> dict:
    """Записать карточку и вернуть, что с ней произошло.

    Возвращает {'obyavlenie_id', 'povod', 'bylo_eur', 'stalo_eur'}.
    Повод `None` означает «ничего не изменилось» - такое не шлём.
    """
    hesh = normalizacia.hash_kartochki(karta)
    staraya = con.execute(
        "SELECT id, cena_eur, hash_kartochki, aktivno, opisanie, foto_json "
        "FROM obyavleniya WHERE istochnik = ? AND vneshniy_id = ?",
        (karta["istochnik"], karta["vneshniy_id"])).fetchone()

    # Дообогащение приходит позже, отдельным запросом. Пустое описание из
    # тощего обхода не должно затирать уже дотянутое.
    opisanie = karta["opisanie"] or (staraya["opisanie"] if staraya else "")
    foto_json = (json.dumps(karta["foto"], ensure_ascii=False) if karta["foto"]
                 else (staraya["foto_json"] if staraya else "[]"))

    znacheniya = {p: karta[p] for p in POLYA_V_BAZU}
    znacheniya["opisanie"] = opisanie

    if staraya is None:
        stolbcy = list(znacheniya) + ["foto_json", "hash_kartochki"]
        con.execute(
            f"INSERT INTO obyavleniya ({', '.join(stolbcy)}) "
            f"VALUES ({', '.join('?' * len(stolbcy))})",
            [znacheniya[p] for p in znacheniya] + [foto_json, hesh])
        oid = con.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
        if karta["cena_eur"]:
            con.execute("INSERT INTO istoriya_cen (obyavlenie_id, cena_eur) VALUES (?, ?)",
                        (oid, karta["cena_eur"]))
        return {"obyavlenie_id": oid, "povod": POVOD_NOVOE,
                "bylo_eur": 0.0, "stalo_eur": karta["cena_eur"]}

    oid = staraya["id"]
    bylo = staraya["cena_eur"] or 0.0
    stalo = karta["cena_eur"] or 0.0

    nabor = ", ".join(f"{p} = ?" for p in znacheniya)
    con.execute(
        f"UPDATE obyavleniya SET {nabor}, foto_json = ?, hash_kartochki = ?, "
        f"posledniy_raz = datetime('now'), propuskov = 0, aktivno = 1 "
        f"WHERE id = ?",
        [znacheniya[p] for p in znacheniya] + [foto_json, hesh, oid])
    # status и zametka в UPDATE не входят - ручные пометки переживают ingest.

    if stalo and bylo and abs(stalo - bylo) > 0.5:
        con.execute("INSERT INTO istoriya_cen (obyavlenie_id, cena_eur) VALUES (?, ?)",
                    (oid, stalo))
        povod = POVOD_CENA_UPALA if stalo < bylo else POVOD_CENA_VYROSLA
    elif not staraya["aktivno"]:
        povod = POVOD_VERNULOS
    elif staraya["hash_kartochki"] != hesh:
        povod = POVOD_PRAVKA
    else:
        povod = None

    return {"obyavlenie_id": oid, "povod": povod, "bylo_eur": bylo, "stalo_eur": stalo}


def otmetit_propavshie(con, istochnik: str, vidennye: set, porog: int = None) -> list:
    """Поднять счётчик промахов у тех, кого не встретили, и снять дошедших до порога.

    Три промаха, а не один: пагинация или частичный сбой не должны порождать
    ложное «продано». По избранным порог свой, ниже - там важнее скорость, а
    ложную тревогу гасит точечная перепроверка страницы объекта.

    Увиденных за прогон - двадцать с лишним тысяч, поэтому список идёт через
    временную таблицу, а не через `NOT IN (?, ?, ...)`: SQLite ограничивает
    число параметров в запросе, и на таком объёме он бы просто упал.
    """
    porog = porog if porog is not None else config.PROPUSKOV_DO_SNYATIYA

    con.execute("CREATE TEMP TABLE IF NOT EXISTS vidennye (vneshniy_id TEXT PRIMARY KEY)")
    con.execute("DELETE FROM vidennye")
    con.executemany("INSERT OR IGNORE INTO vidennye (vneshniy_id) VALUES (?)",
                    [(str(v),) for v in vidennye])
    con.execute(
        "UPDATE obyavleniya SET propuskov = propuskov + 1 "
        "WHERE istochnik = ? AND aktivno = 1 "
        "AND vneshniy_id NOT IN (SELECT vneshniy_id FROM vidennye)", (istochnik,))

    snyatye = [dict(r) for r in con.execute(
        "SELECT id, vneshniy_id, zagolovok, cena_eur, sektor, komnat, url "
        "FROM obyavleniya WHERE istochnik = ? AND aktivno = 1 AND propuskov >= ?",
        (istochnik, porog))]
    if snyatye:
        con.execute(
            "UPDATE obyavleniya SET aktivno = 0 WHERE istochnik = ? AND aktivno = 1 "
            "AND propuskov >= ?", (istochnik, porog))
    return snyatye


# --- очередь ----------------------------------------------------------------

def v_ochered(con, obyavlenie_id: int, profil: str, povod: str,
              klyuch: str = None, prioritet: int = 0, metki: list = None,
              bylo_eur: float = 0) -> bool:
    """Поставить событие в очередь. Возвращает False, если оно там уже есть."""
    klyuch = klyuch or povod
    try:
        con.execute(
            "INSERT INTO ochered (obyavlenie_id, profil, povod, klyuch, prioritet, "
            "metki_json, bylo_eur) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (obyavlenie_id, profil, povod, klyuch, prioritet,
             json.dumps(metki or [], ensure_ascii=False), bylo_eur or 0))
        return True
    except sqlite3.IntegrityError:
        return False


def klyuch_sobytiya(povod: str, cena_eur: float) -> str:
    """Одно и то же снижение цены - одно событие; следующее снижение - новое."""
    if povod in (POVOD_CENA_UPALA, POVOD_CENA_VYROSLA):
        return f"{povod}:{int(cena_eur or 0)}"
    return povod


def ochered_zhdet(con) -> int:
    """Сколько записей ждут отправки (ночью копятся до 08:00)."""
    return con.execute(
        "SELECT COUNT(*) AS n FROM ochered WHERE sostoyanie = 'zhdet'").fetchone()["n"]


def ochered_k_otpravke(con, potolok_progona: int = None, potolok_dnya: int = None) -> list:
    """Что отправлять в этом прогоне.

    Избранное (prioritet > 0) идёт первым и **не считается** в потолках: по
    отслеживаемым объектам владелец ждёт каждое движение сам, спама там не
    бывает. Всё остальное подчиняется потолкам и ждёт в очереди - ровный
    ручеёк вместо лавины.
    """
    potolok_progona = (config.MAX_OTPRAVOK_ZA_PROGON if potolok_progona is None
                       else potolok_progona)
    potolok_dnya = config.MAX_OTPRAVOK_V_DEN if potolok_dnya is None else potolok_dnya

    vse = [dict(r) for r in con.execute(
        "SELECT * FROM ochered WHERE sostoyanie = 'zhdet' "
        "ORDER BY prioritet DESC, id ASC")]

    izbrannye = [z for z in vse if z["prioritet"] > 0]
    obychnye = [z for z in vse if z["prioritet"] <= 0]

    za_sutki = con.execute(
        "SELECT COUNT(*) AS n FROM ochered WHERE sostoyanie = 'otpravleno' "
        "AND prioritet <= 0 AND otpravleno_at >= datetime('now', '-1 day')").fetchone()["n"]
    ostalos_na_den = max(0, potolok_dnya - za_sutki)
    return izbrannye + obychnye[:min(potolok_progona, ostalos_na_den)]


def otmetit_otpravlennym(con, zapis_id: int, message_id=None) -> None:
    con.execute(
        "UPDATE ochered SET sostoyanie = 'otpravleno', otpravleno_at = datetime('now'), "
        "message_id = ?, popytok = popytok + 1 WHERE id = ?", (str(message_id or ""), zapis_id))


def otmetit_popytku(con, zapis_id: int) -> None:
    """Не ушло - остаётся в очереди, счётчик попыток растёт."""
    con.execute("UPDATE ochered SET popytok = popytok + 1 WHERE id = ?", (zapis_id,))


def pometit_vsyo_otpravlennym(con, prichina: str = "tihiy_progrev") -> int:
    """Тихий прогрев: первый прогон помечает всё уведомлённым и не шлёт ничего."""
    n = con.execute("SELECT COUNT(*) AS n FROM ochered WHERE sostoyanie = 'zhdet'").fetchone()["n"]
    con.execute(
        "UPDATE ochered SET sostoyanie = 'otpravleno', otpravleno_at = datetime('now'), "
        "message_id = ? WHERE sostoyanie = 'zhdet'", (prichina,))
    return n


# --- карточки ---------------------------------------------------------------

def kartochka(con, obyavlenie_id: int) -> dict:
    r = con.execute("SELECT * FROM obyavleniya WHERE id = ?", (obyavlenie_id,)).fetchone()
    if not r:
        return {}
    k = dict(r)
    k["foto"] = json.loads(k.pop("foto_json") or "[]")
    return k


def bez_opisaniya(con, obyavlenie_ids: list) -> list:
    """Кому нужно дообогащение перед отправкой: описание или фото ещё не тянули."""
    if not obyavlenie_ids:
        return []
    znaki = ",".join("?" * len(obyavlenie_ids))
    return [r["vneshniy_id"] for r in con.execute(
        f"SELECT vneshniy_id FROM obyavleniya WHERE id IN ({znaki}) "
        f"AND (foto_json IS NULL OR foto_json IN ('', '[]'))", obyavlenie_ids)]


# --- избранное --------------------------------------------------------------

def dobavit_v_izbrannoe(con, obyavlenie_id: int, kto: str, cena_eur: float) -> bool:
    try:
        con.execute(
            "INSERT INTO izbrannoe (obyavlenie_id, kto, cena_pri_dobavlenii) VALUES (?, ?, ?)",
            (obyavlenie_id, kto, cena_eur))
        return True
    except sqlite3.IntegrityError:
        return False


def ubrat_iz_izbrannogo(con, obyavlenie_id: int, kto: str) -> bool:
    kur = con.execute("DELETE FROM izbrannoe WHERE obyavlenie_id = ? AND kto = ?",
                      (obyavlenie_id, kto))
    return kur.rowcount > 0


def v_izbrannom(con, obyavlenie_id: int, kto: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM izbrannoe WHERE obyavlenie_id = ? AND kto = ?",
        (obyavlenie_id, kto)).fetchone())


def izbrannye(con, kto: str = None) -> list:
    """Отслеживаемые объекты вместе с ценой на момент добавления.

    Избранное никогда не выпадает из опроса, даже если объект перестал
    проходить фильтры профиля: иначе агент замолчит ровно по тому объекту,
    который папа попросил отслеживать.
    """
    gde, args = "", []
    if kto:
        gde, args = "WHERE i.kto = ?", [kto]
    return [dict(r) for r in con.execute(
        f"SELECT o.*, i.kto, i.dobavleno_at, i.cena_pri_dobavlenii, i.primechanie "
        f"FROM izbrannoe i JOIN obyavleniya o ON o.id = i.obyavlenie_id {gde} "
        f"ORDER BY i.dobavleno_at DESC", args)]


def po_vneshnemu_id(con, istochnik: str, vneshniy_id: str) -> dict:
    r = con.execute(
        "SELECT * FROM obyavleniya WHERE istochnik = ? AND vneshniy_id = ?",
        (istochnik, str(vneshniy_id))).fetchone()
    return dict(r) if r else {}


# --- прогоны ----------------------------------------------------------------

def nachat_progon(con, istochnik: str) -> int:
    con.execute("INSERT INTO progony (istochnik) VALUES (?)", (istochnik,))
    con.commit()
    return con.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def zakonchit_progon(con, progon_id: int, **polya) -> None:
    polya.setdefault("status", "ok")
    nabor = ", ".join(f"{p} = ?" for p in polya)
    con.execute(f"UPDATE progony SET {nabor}, konec = datetime('now') WHERE id = ?",
                list(polya.values()) + [progon_id])
    con.commit()


def poslednie_progony(con, skolko: int = 5) -> list:
    return [dict(r) for r in con.execute(
        "SELECT * FROM progony ORDER BY id DESC LIMIT ?", (skolko,))]
