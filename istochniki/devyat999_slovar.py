"""Словарь 999.md: их значения -> наши канонические коды.

Смысл файла: фильтры владельца пишутся латиницей (`botanika`, `chekany`), а
площадка отдаёт «Ботаника» по-русски и «Ciocana» по-румынски. Всё сведение
языков живёт здесь, а не размазано по коду - у второй площадки (makler.md)
будет свой такой же файл, и ядро не заметит разницы.

Ключи сравниваются в нижнем регистре, ё приводится к е: площадка пишет то
«Рышкановка», то «Рышкановка», и одна буква не должна ломать сектор.
"""
from __future__ import annotations


def klyuch(s: str) -> str:
    """Нормализация ключа: регистр, ё/е, пробелы, дефисы."""
    return (str(s or "").strip().lower()
            .replace("ё", "е").replace("-", " ").replace("_", " "))


def _razvernut(pary: dict) -> dict:
    """{'kod': ['вариант', 'varianta']} -> {'вариант': 'kod', 'varianta': 'kod'}"""
    out = {}
    for kod, varianty in pary.items():
        for v in varianty:
            out[klyuch(v)] = kod
    return out


# Секторы Кишинёва. Значения feature 9: Аэропорт 15672, Ботаника 15665,
# Буюканы 15666, Рышкановка 15667, Скулянка 15671, Старая Почта 15670,
# Телецентр 15668, Центр 15664, Чокана 15669.
SEKTORY = _razvernut({
    "centr":       ["Центр", "Centru"],
    "botanika":    ["Ботаника", "Botanica"],
    "chekany":     ["Чокана", "Ciocana"],
    "ryshkanovka": ["Рышкановка", "Рышканы", "Riscani", "Râșcani", "Rîșcani"],
    "buyukany":    ["Буюканы", "Buiucani"],
    "telecentr":   ["Телецентр", "Telecentru"],
    "staraya_pochta": ["Старая Почта", "Posta Veche", "Poșta Veche"],
    "skulyanka":   ["Скулянка", "Sculeni", "Sculeanca"],
    "aeroport":    ["Аэропорт", "Aeroport"],
})

# Населённые пункты муниципия Кишинёв, feature 8. Нужны потому, что у села
# Колоница тоже есть сектор «Центр», и без города его квартиры по 300 €/м²
# смешались бы с центром Кишинёва по 2000 €/м², испортив медиану.
GORODA = _razvernut({
    "kishinev":   ["Кишинёв", "Кишинев", "Chișinău", "Chisinau"],
    "durleshty":  ["Дурлешты", "Durlești", "Durlesti"],
    "kodru":      ["Кодру", "Codru"],
    "stavcheny":  ["Ставчены", "Stăuceni", "Stauceni"],
    "gidigich":   ["Гидигич", "Ghidighici"],
    "gratieshty": ["Гратиешты", "Grătiești", "Gratiesti"],
    "choresku":   ["Чореску", "Ciorescu"],
    "bachoy":     ["Бачой", "Băcioi", "Bacioi"],
    "synzhera":   ["Сынжера", "Sîngera", "Singera"],
    "vatra":      ["Ватра", "Vatra"],
    "krikovo":    ["Криково", "Cricova"],
    "trusheny":   ["Трушены", "Trușeni", "Truseni"],
    "bubuech":    ["Бубуечь", "Bubuieci"],
    "revaka":     ["Ревака", "Revaca"],
    "togatin":   ["Тогатин", "Tohatin"],
    "kolonica":   ["Колоница", "Coloniţa", "Colonita"],
    "budeshty":   ["Будешты", "Budești", "Budesti"],
    "vadul":      ["Вадул-луй-Водэ", "Vadul lui Vodă"],
    "dobruzha":   ["Добружа", "Dobrogea"],
    "gyoyan":     ["Гоян", "Goian"],
})


def gorod(znachenie: str) -> str:
    """Незнакомый населённый пункт остаётся пустым, а не становится Кишинёвом:
    фильтр `gorod == kishinev` его отсеет, и это правильнее, чем приписать
    сельскую квартиру городу и сдвинуть медиану."""
    return GORODA.get(klyuch(znachenie), "")


# Тип сделки, feature 1. «Сдаю помесячно» и «Сдаю посуточно» - разные вещи:
# для расчёта доходности от аренды нужна помесячная, посуточная всё исказит.
SDELKI = _razvernut({
    "prodazha":       ["Продам", "Vând", "Vind"],
    "pokupka":        ["Куплю", "Cumpăr", "Cumpar"],
    "arenda":         ["Сдаю помесячно", "Сдаю", "Dau în chirie lunar", "Dau in chirie"],
    "arenda_sutki":   ["Сдаю посуточно", "Dau în chirie zilnic"],
    "snyat":          ["Сниму", "Iau în chirie", "Iau in chirie"],
    "obmen":          ["Меняю", "Schimb"],
})

# Кто продаёт, feature 795. Ради этого поля и делался фильтр «собственник».
PRODAVCY = _razvernut({
    "sobstvennik": ["Частное лицо", "Собственник", "Persoană fizică", "Persoana fizica"],
    "agentstvo":   ["Агентство", "Агенство", "Agenție imobiliară", "Agentie", "Agenție"],
    "zastroyshchik": ["Застройщик", "Dezvoltator"],
    "posrednik":   ["Посредник", "Intermediar"],
})

# Состояние квартиры, feature 253.
SOSTOYANIYA = _razvernut({
    "evroremont":    ["Eвроремонт", "Евроремонт", "Euroreparație", "Euroreparatie"],
    "horoshee":      ["Хорошее", "Bună", "Buna"],
    "srednee":       ["Среднее", "Medie", "Удовлетворительное"],
    "bez_remonta":   ["Без ремонта", "Fără reparație", "Fara reparatie", "Требует ремонта"],
    "chernovaya":     ["Черновой вариант", "Variantă albă", "Varianta alba", "Белый вариант"],
    "pod_klyuch":    ["Под ключ", "La cheie"],
    "chastichnyy":   ["Частичный ремонт", "Reparație parțială"],
    "svezhiy":       ["Свежий ремонт", "Reparație recentă"],
    "dizaynerskiy":  ["Дизайнерский ремонт", "Design individual"],
})

# Жилой фонд, feature 852 - самое рабочее деление для инвестора.
FONDY = _razvernut({
    "novostroy":  ["Новострой", "Bloc nou", "Construcție nouă"],
    "vtorichka":  ["Вторичное жильё", "Вторичка", "Vtorichka", "Fond locativ vechi", "Bloc vechi"],
})

# Тип здания, feature 247.
TIPY_DOMA = _razvernut({
    "monolit":    ["Монолит", "Monolit"],
    "kirpich":    ["Кирпич", "Cărămidă", "Caramida"],
    "panel":      ["Панель", "Panel", "Panouri"],
    "kotelec":    ["Котелец", "Cotileț", "Cotilet"],
    "blok":       ["Блок", "BCA", "Газоблок"],
    "derevo":     ["Дерево", "Lemn"],
})


def sektor(znachenie: str) -> str:
    return SEKTORY.get(klyuch(znachenie), "")


def sdelka(znachenie: str) -> str:
    return SDELKI.get(klyuch(znachenie), "")


def prodavec(znachenie: str) -> str:
    return PRODAVCY.get(klyuch(znachenie), "")


def sostoyanie(znachenie: str) -> str:
    return SOSTOYANIYA.get(klyuch(znachenie), "")


def fond(znachenie: str) -> str:
    return FONDY.get(klyuch(znachenie), "")


def tip_doma(znachenie: str) -> str:
    return TIPY_DOMA.get(klyuch(znachenie), "")
