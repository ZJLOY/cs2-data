"""Номера рисунков из справочника Forky; цены и сделки в справочнике отсутствуют."""
from datetime import datetime, timezone

GUIDE = "https://steamcommunity.com/sharedfiles/filedetails/?id=3613249488"

# (Название группы, якорь раздела, тир из гайда или None, номера в порядке автора).
CATALOG = {
    'Glock-18 | Grinder': [
        ('Чёрный затвор №1', '8456384', None,
         [916]),
        ('Чёрный затвор №2', '8456386', None,
         [384]),
        ('Чёрный затвор №3', '8453622', None,
         [811]),
    ],
    'Glock-18 | Red Tire': [
        ('Надпись Rush B', '8453641', None,
         [620]),
    ],
    'Glock-18 | High Beam': [
        ('Сплошная полоса', '8453655', None,
         [897]),
    ],
    'Glock-18 | Moonrise': [
        ('Звезда по центру', '8456870', None,
         [19, 109, 142, 165, 194, 237, 302, 403, 475, 487, 509, 800, 958]),
    ],
    'Glock-18 | Reactor': [
        ('Зубы', '8453700', None,
         [281]),
    ],
    'USP-S | Alpine Camo': [
        ('Синий узор №1', '8453726', None,
         [674]),
        ('Синий узор №2', '8453727', None,
         [490]),
        ('Синий узор №3', '8453728', None,
         [704]),
    ],
    'P250 | Bengal Tiger': [
        ('Максимум оранжевого', '8453741', None,
         [55, 204, 217, 227, 268, 277, 460, 654, 714, 760, 778]),
        ('Максимум белого', '8453742', None,
         [34, 159, 539, 623, 677, 715, 811]),
    ],
    'P250 | Nevermore': [
        ('Ворон по центру', '8453758', 1,
         [73, 127, 708, 923]),
    ],
    'P250 | Crimson Kimono': [
        ('Красный верх', '8453777', None,
         [20]),
    ],
    'P250 | Mint Kimono': [
        ('Зелёная рукоять', '8453780', None,
         [2, 9, 32, 37, 72, 81, 90, 97]),
        ('Зелёный кончик', '8453781', None,
         [12, 17, 60, 66, 70, 74, 76, 83, 86, 100, 104]),
        ('Чёрно-белый узор', '8453782', None,
         [24, 43, 54, 64, 65]),
    ],
    'Five-SeveN | Neon Kimono': [
        ('Максимум зелёного', '8453816', None,
         [452]),
        ('Максимум белого', '8453819', None,
         [442]),
    ],
    'Five-SeveN | Berries And Cherries': [
        ('Максимум синего', '8453851', None,
         [449, 73]),
        ('Максимум красного', '8453852', None,
         [182, 60]),
    ],
    'Tec-9 | Sandstorm': [
        ('Максимум фиолетового', '8453853', None,
         [70, 328, 862, 583, 552, 696, 705, 86, 83, 271, 654, 858, 911, 572, 487, 296,
          460]),
    ],
    'Tec-9 | Ice Cap': [
        ('Максимум синего', '8453889', 1,
         [146, 261, 760, 910, 916, 774]),
    ],
    'Sawed-Off | Brake Light': [
        ('Полностью красный (Hot Rod)', '8453930', 1,
         [22, 29]),
    ],
    'XM1014 | Elegant Vines': [
        ('Роза по центру', '8453931', None,
         [827]),
    ],
    'XM1014 | Seasons': [
        ('Spectrum Fade', '8453932', None,
         [26, 78, 115, 130, 182, 234, 286, 334, 338, 390, 442, 494, 546, 598, 605, 650,
          659, 698, 955]),
    ],
    'XM1014 | XOXO': [
        ('Максимум розового', '8453933', 1,
         [443, 372, 218, 16, 51]),
    ],
    'XM1014 | Ziggy': [
        ('Максимум фиолетового', '8453986', None,
         [703, 399]),
    ],
    'Nova | Windblown': [
        ('Птица на стволе', '8453990', None,
         [780, 887, 126]),
    ],
    'MAG-7 | Sonar': [
        ('Максимум бирюзового', '8454006', None,
         [412]),
    ],
    'MAC-10 | Last Dive': [
        ('Череп по центру', '8454032', None,
         [386]),
        ('Череп и ныряльщик', '8454033', None,
         [407]),
        ('Череп, ныряльщик и ракушка', '8454034', None,
         [509]),
        ('Дерево по центру', '8454035', None,
         [748]),
    ],
    "UMP-45 | Minotaur's Labyrinth": [
        ('Минотавр по центру', '8456251', None,
         [272, 9]),
    ],
    'UMP-45 | Moonrise': [
        ('Звезда сзади', '8456278', None,
         [11, 26, 57, 60, 63, 73, 78, 80, 110, 115, 130, 150, 156, 163, 167, 178,
          182, 192, 206, 219, 227, 230, 234, 240, 262, 267, 269, 271, 279, 282, 286, 307,
          323, 334, 336, 338, 374, 375, 377, 382, 386, 390, 430, 438, 441, 442, 449, 463,
          467, 485, 490, 494, 522, 542, 546, 548, 555, 576, 583, 594, 596, 598, 605, 613,
          646, 650, 657, 663, 664, 666, 668, 682, 698, 709, 739, 750, 761, 774, 776, 782,
          783, 785, 786, 798, 799, 802, 813, 851, 853, 865, 873, 891, 895, 903, 904, 917,
          920, 937, 945, 957, 969]),
        ('Звезда спереди', '8456279', None,
         [32, 39, 54, 76, 85, 98, 134, 162, 242, 295, 200, 326, 332, 343, 348, 359,
          364, 398, 415, 424, 450, 454, 476, 486, 488, 499, 520, 528, 566, 580, 586, 622,
          625, 655, 671, 672, 673, 742, 787, 805, 816, 894, 898, 902, 916, 992, 994]),
        ('Без луны', '8456282', None,
         [56, 61, 72, 143, 145, 152, 174, 214, 220, 309, 316, 322, 361, 371, 388, 413,
          421, 459, 465, 483, 501, 536, 556, 590, 607, 614, 637, 651, 656, 669, 695, 727,
          743, 766, 826, 835, 842, 845, 856, 879, 889, 910, 911, 914]),
    ],
    'Galil AR | Phoenix Blacklight': [
        ('Феникс по центру', '8456290', None,
         [775, 963, 619, 978, 432, 419, 289, 729]),
    ],
    'Galil AR | CAUTION!': [
        ('Падающий человек сзади', '8456292', None,
         [93, 147]),
        ('Падающий человек на рукояти', '8456322', None,
         [614]),
        ('Надпись по центру', '8456323', None,
         [58]),
    ],
    'Galil AR | Sandstorm': [
        ('Максимум фиолетового', '8456327', None,
         [761, 583]),
        ('Максимум песочного', '8456329', None,
         [555, 449]),
    ],
    'Galil AR | Crimson Tsunami': [
        ('Максимум волн', '8456330', None,
         [22]),
    ],
    'M4A4 | Daybreak': [
        ('Солнце по центру', '8456336', 1,
         [2, 18, 28, 43, 52, 68, 71, 74, 111, 129, 133, 154, 155, 157, 180, 213,
          274, 293, 297, 301, 303, 306, 328, 330, 370, 399, 408, 412, 452, 456, 461, 479,
          497, 527, 561, 571, 611, 618, 635, 686, 745, 746, 753, 760, 775, 789, 808, 821,
          852, 871, 893, 908, 943, 965, 979, 996]),
    ],
    'AWP | Electric Hive': [
        ('Максимум оранжевого', '8456361', None,
         [253]),
        ('Максимум оранжевого — следующие по рейтингу', '8456361', None,
         [54, 767, 611, 697, 42, 894, 354, 835, 117, 540, 384, 143, 96, 376]),
        ('Максимум синего', '8456365', None,
         [273]),
        ('Максимум синего — следующие по рейтингу', '8456365', None,
         [436, 902, 23, 853, 262, 185, 598, 851, 385, 138]),
    ],
    '★ Sport Gloves | Ultra Violent': [
        ('Фиолетовый узор №1', '8733281', None,
         [665]),
        ('Фиолетовый узор №2', '8733305', None,
         [503]),
        ('Фиолетовый узор №3', '8733307', None,
         [908]),
        ('Бирюзовый узор №1', '8733311', None,
         [344]),
        ('Бирюзовый узор №2', '8733322', None,
         [542]),
    ],
    '★ Stiletto Knife | Scorched': [
        ('Чёрный узор, тир 1', '8800967', 1,
         [543, 791, 980]),
        ('Чёрный узор, тир 2', '8800978', 2,
         [62, 244, 266, 284, 446, 929]),
        ('Чёрный узор, тир 3', '8800979', 3,
         [11, 109, 451, 453, 513, 746]),
    ],
}

# Противоречия в подписи иллюстрации и основном списке автора.
GUIDE_NOTES = {
    ("Galil AR | Phoenix Blacklight", 775): "В списке 775, под иллюстрацией 755.",
    ("★ Sport Gloves | Ultra Violent", 665): "В списке и заголовке 665, в подписи 655.",
    ("P250 | Nevermore", 923): "Два ворона.",
}

WEARS = {"Factory New": "FN", "Minimal Wear": "MW", "Field-Tested": "FT",
         "Well-Worn": "WW", "Battle-Scarred": "BS"}


def variant(name):
    """Разбирает market_hash_name, в том числе ★ StatTrak™ Stiletto Knife."""
    prefix, sep, exterior = name.rpartition(" (")
    if not sep or not exterior.endswith(")"):
        return None
    wear = WEARS.get(exterior[:-1])
    if not wear:
        return None
    kind = "normal"
    if prefix.startswith("Souvenir "):
        kind, prefix = "souvenir", prefix.removeprefix("Souvenir ")
    elif prefix.startswith(("StatTrak™ ", "★ StatTrak™ ")):
        kind, prefix = "st", prefix.replace("StatTrak™ ", "", 1)
    if prefix in CATALOG:
        return prefix, wear, kind
    return None


def merge(db, sales_by_name):
    """Добавляет справочник и реальные сделки CSFloat к базе, сохраняя другие источники.

    Строка sales: [seed, wear, kind, USD, дата UTC, float, timestamp UTC].
    Для оценки паттерна подходят строки архива с известными float, seed и стоимостью
    наклеек <5% цены. Дата без времени из старых агрегатов не идентифицирует сделку.
    """
    merged = dict(db or {})
    by_base = {}
    for name, rows in (sales_by_name or {}).items():
        v = variant(name)
        if v:
            base, wear, kind = v
            by_base.setdefault(base, []).append((wear, kind, rows))
    for base, definitions in CATALOG.items():
        existing = merged.get(base, [])
        old = {g["label"]: g for g in existing if g.get("source") == "forky"}
        groups = []
        lookup = {}
        for label, section, tier, seeds in definitions:
            group = {"label": label, "tier": tier if tier is not None else 3,
                     "guide_tier": tier, "source": "forky", "url": GUIDE + "#" + section,
                     "seeds": list(seeds), "sales": []}
            notes = {str(s): GUIDE_NOTES[base, s] for s in seeds if (base, s) in GUIDE_NOTES}
            if notes:
                group["notes"] = notes
            # Только собственные строки с точным временем. Другие форматы остаются
            # в исходных группах, разные продажи одного экземпляра сохраняются.
            evidence = {tuple(row) for row in old.get(label, {}).get("sales", [])
                        if len(row) == 7 and row[0] in seeds}
            groups.append((group, evidence))
            for seed in seeds:
                lookup.setdefault(seed, []).append(evidence)
        for wear, kind, rows in by_base.get(base, []):
            for row in rows:
                if len(row) < 5:
                    continue
                ts, price, fl, seed, sticker_value = row[:5]
                matches = lookup.get(seed)
                if (not matches or not ts or not price or price <= 0 or fl is None
                        or sticker_value is None or sticker_value >= price * 0.05):
                    continue
                day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
                sale = (seed, wear, kind, price, day, fl, ts)
                for evidence in matches:
                    evidence.add(sale)
        for group, evidence in groups:
            group["sales"] = [list(row) for row in sorted(evidence, key=lambda row: (row[6], row))]
        merged[base] = [group for group, _ in groups] + [g for g in existing if g.get("source") != "forky"]
    return merged
