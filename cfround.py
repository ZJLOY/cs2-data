"""
Один проход по лотам CSFloat для сделок: поиск по всему рынку, охота за редкими номерами и лоты ходовых предметов
и скинов с паттернами по очереди.

Общий файл: его запускает и закрытый анализатор (если свежих лотов от сборщика нет), и открытый дневной сборщик
ZJLOY/cs2-data (копия этого файла и sources.py; обновляется командой «python skins.py push»).
"""
import sources

DEAL_ALL = {"Skinport", "Buff163", "CSFloat", "Market.CSGO", "Waxpeer", "DMarket", "CS.Money", "Lis-Skins"}


def pattern_base(name):
    """«StatTrak™ AWP | PAW (Field-Tested)» → «AWP | PAW»."""
    for pre in ("StatTrak™ ", "Souvenir "):
        if name.startswith(pre):
            name = name[len(pre):]
    return name.rsplit(" (", 1)[0] if name.endswith(")") else name


def cheapest_fn(cfg, sp_raw, mk_raw):
    """cheapest(название, кроме_площадки) — самая дешёвая копия на площадках из deal_markets (как в проверке сделок)."""
    off = DEAL_ALL - set(cfg.get("deal_markets") or DEAL_ALL)
    approx = set(cfg.get("approx_markets", ["CS.Money"]))
    g = lambda src, n, col: ((mk_raw.get(src) or {}).get(n) or {}).get(col)

    def cheapest(n, skip=None):
        c = [("Skinport", (sp_raw.get(n) or {}).get("min_price")), ("Buff163", g("buff163", n, "buff_ask")),
             ("CSFloat", g("csfloat", n, "float_ask")), ("Market.CSGO", g("marketcsgo", n, "mcsgo")),
             ("Waxpeer", g("waxpeer", n, "wax_min")), ("DMarket", g("dmarket", n, "dm_ask")),
             ("CS.Money", g("csmoney", n, "csmoney")), ("Lis-Skins", g("lisskins", n, "lis_min"))]
        c = [x for m, x in c if x and m not in off and m not in approx and m != skip]
        return min(c) if c else None
    return cheapest


def wanted_names(cfg, sp_raw):
    """Ходовые предметы по фильтрам (для сравнения по float и лотов CSFloat)."""
    flt = cfg["filters"]
    out = set()
    for n, r in sp_raw.items():
        p = r.get("m7") or r.get("min_price")
        if (r.get("v30") or 0) >= flt["min_volume_30d"] and p and flt["min_price"] <= p <= flt["max_price"]:
            out.add(n)
    return out


def _turn(items, size, state, key):
    """Следующие size предметов по кругу, начиная с сохранённого места."""
    if not items or size <= 0:
        return [], 0
    start = int(state.get(key) or 0) % len(items)
    return (items[start:] + items[:start])[:size], start


def run(cfg, key, wanted, pat_names, pat_db, cbase, v30, rate, state, log=print, max_requests=None, reserve=10):
    """
    Проход по лотам CSFloat. state — словарь с местами в очередях (cf_rot, cf_prot, cf_hunt) и номерами скинов
    (cf_idx: {скин: [def_index, paint_index]}); функция его обновляет.
    Возвращает (лоты {название: [(цена, float, номер, наклейки, id, ссылка)]}, info как у sources.csfloat_lots).
    """
    n_cf = int(cfg.get("csfloat_lots_items", 70) or 0)
    by_vol = lambda n: -(v30.get(n) or 0)
    ranked = sorted((n for n in wanted if cbase(n)), key=by_vol)
    n_core = min(n_cf, int(cfg.get("csfloat_lots_core", 20)))
    core, rest = ranked[:n_core], ranked[n_core:]
    chunk, c_start = _turn(rest, n_cf - n_core, state, "cf_rot")
    liq = core + chunk
    p_budget = (cfg.get("patterns_max_price_rub") or 10 ** 9) / rate
    p_all = sorted((n for n in pat_names if n not in liq and cbase(n) and cbase(n) <= p_budget), key=by_vol)
    pn, p_start = _turn(p_all, int(cfg.get("csfloat_lots_pattern_items", 30)), state, "cf_prot")
    item_jobs = [(n, s) for n in liq for s in ("lowest_price", "lowest_float")] + [(n, "lowest_price") for n in pn]
    # поиск по всему рынку: свежие лоты, «лучшие сделки» и «наибольшие скидки» по оценке CSFloat, самый низкий float
    lo_c = int(float(cfg.get("csfloat_scan_min_usd", 1)) * 100)
    hi_c = int(float(cfg.get("csfloat_scan_max_usd") or cfg["filters"].get("max_price", 60)) * 100)
    scan = cfg.get("csfloat_scan", {"most_recent": 2, "best_deal": 3, "highest_discount": 2, "lowest_float": 2})
    scan_jobs = [{"sort_by": s, "min_price": lo_c, "max_price": hi_c, "pages": n, "tag": s} for s, n in scan.items() if n]
    # охота за номерами: один запрос на скин сразу по его редким номерам (пачками по csfloat_hunt_chunk)
    cf_idx = state.setdefault("cf_idx", {})
    max_tier = int(cfg.get("csfloat_hunt_max_tier", 2))
    hunt_bases = sorted(b for b in pat_db if b in cf_idx)
    hb, h_start = _turn(hunt_bases, int(cfg.get("csfloat_hunt_skins", 15)), state, "cf_hunt")
    hunt_jobs, ch = [], int(cfg.get("csfloat_hunt_chunk", 40))
    for b in hb:
        seeds = sorted({s for g in pat_db[b] if int(g.get("tier") or 1) <= max_tier for s in g["seeds"]})
        for i in range(0, len(seeds), ch):
            hunt_jobs.append({"def_index": cf_idx[b][0], "paint_index": cf_idx[b][1],
                              "paint_seed": ",".join(map(str, seeds[i:i + ch])),
                              "sort_by": "lowest_price", "max_price": int(p_budget * 100), "tag": "hunt"})
    # порядок важен при нехватке лимита: сначала свежие лоты и охота, потом поиск по рынку, потом перебор предметов
    first = [j for j in scan_jobs if j["sort_by"] == "most_recent"]
    jobs = first + hunt_jobs + [j for j in scan_jobs if j not in first] + item_jobs
    log(f"CSFloat: поиск по рынку ({sum(j['pages'] for j in scan_jobs)} стр.), охота за номерами — {len(hunt_jobs)} запросов "
        f"(скины с {h_start + 1}-го из {len(hunt_bases)}), лоты по {len(core)} самым ходовым, {len(chunk)} ходовым по очереди "
        f"(с {c_start + 1}-го из {len(rest)}) и {len(pn)} с паттернами (с {p_start + 1}-го из {len(p_all)})...")
    c_all, info = sources.csfloat_lots(jobs, key, reserve=reserve, log=log, max_requests=max_requests)
    done = info.get("done") or set()
    for n, di in (info.get("idx") or {}).items():
        cf_idx[pattern_base(n)] = list(di)
    if hunt_bases and info["requests"] > len(first) * 2:
        state["cf_hunt"] = (h_start + len(hb)) % len(hunt_bases)
    # очередь сдвигаем на столько предметов, сколько успели проверить (при нехватке лимита — продолжим с них же)
    if rest:
        state["cf_rot"] = (c_start + sum(n in done for n in chunk)) % len(rest)
    if p_all:
        state["cf_prot"] = (p_start + sum(n in done for n in pn)) % len(p_all)
    tags = info.get("tags") or {}
    log(f"  лотов: {sum(len(v) for v in c_all.values())} ({info['requests']} запросов, осталось {info['left']}); "
        f"поиск по рынку {sum(1 for t in tags.values() if t != 'hunt')}, охота {sum(1 for t in tags.values() if t == 'hunt')}; "
        f"проверено предметов {len(done)}")
    return c_all, info
