"""
Дневной сборщик: в свободные часы владельца (когда ночной сборщик harvest.py не работает) готовит для закрытого
анализатора то, что раньше тот скачивал сам и тратил на это минуты GitHub:

  • cf_lots.json   — лоты CSFloat для сделок: поиск по всему рынку, охота за редкими номерами, ходовые предметы
                     и скины с паттернами по очереди (тот же поиск, что в анализаторе — общий файл cfround.py);
  • sales.json.gz  — история продаж CSFloat по ходовым предметам: каждый — не реже раза в day_sales_hours часов;
  • pat_db.json.gz — цены редких паттернов (cs2pattern-prices.com), раз в pattern_refresh_days дней.

Настройки поиска (deal.json) — копия нужных настроек анализатора, её обновляет команда «python skins.py push».
Свои настройки — в config.json (ключи day_*). Время — по Москве.
"""
import gzip
import json
import sys
import time
from datetime import datetime

import cfround
import forky
import harvest
import sources
from harvest import CFG, KEY, MSK


def load(path, default):
    try:
        if path.endswith(".gz"):
            return json.load(gzip.open(path, "rt", encoding="utf-8"))
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(path, obj):
    if path.endswith(".gz"):
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    else:
        json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


def pattern_base(name):
    return cfround.pattern_base(name.replace("★ StatTrak™ ", "★ ", 1))


def priority_sales(lis_lots, cf_lots, pat_db, fetched, now, every, budget, limit=25):
    """Refresh titles with affordable rare listings before the regular sales queue."""
    seeds = {base: {int(seed) for group in groups for seed in group["seeds"]} for base, groups in pat_db.items()}
    lowest = {}
    for market in (lis_lots, cf_lots):
        for name, rows in market.items():
            eligible = seeds.get(pattern_base(name))
            if not eligible or name.startswith("Souvenir ") or now - fetched.get(name, 0) < every:
                continue
            best = min((price for price, fl, seed, *_ in rows
                        if fl is not None and str(seed).isdigit() and int(seed) in eligible and price <= budget),
                       default=None)
            if best is not None:
                lowest[name] = min(best, lowest.get(name, best))
    return sorted(lowest, key=lambda name: (fetched.get(name, 0), lowest[name], name))[:limit]


def main():
    now = datetime.now(MSK)
    night, _ = harvest.allowed(now)
    if night and "--force" not in sys.argv:
        print("Пропуск: неактивные часы — сейчас работает ночной сборщик")
        return
    if not KEY:
        sys.exit("Нет ключа CSFLOAT_API_KEY")
    deal = load("deal.json", None)
    if not deal:
        sys.exit("Нет deal.json (его отправляет «python skins.py push»)")
    state = load("day_state.json", {})
    pat = load("pat_db.json.gz", {})
    t0 = time.time()

    # цены площадок — чтобы выбрать предметы так же, как анализатор
    mk, _, errors = sources.csgotrader()
    for e in errors:
        print("  не удалось:", e)
    try:
        mk["marketcsgo"] = sources.market_csgo()
    except Exception as e:
        print("  Market.CSGO: не удалось:", str(e)[:100])
    data = harvest.load_sales()
    sp = sources.market_snapshot(mk.get("marketcsgo", {}), data.get("sales", {}))
    lis_lots = {}
    if "Lis-Skins" in (deal.get("deal_markets") or ["Lis-Skins"]):
        bases = set(pat.get("db") or {}) | set(forky.CATALOG)
        catalog = sp.keys() | data["sales"].keys() | (mk.get("csfloat") or {}).keys()
        lis_names = {name for name in catalog if pattern_base(name) in bases and not name.startswith("Souvenir ")}
        try:
            mk["lisskins"], lis_lots, _, _, _ = sources.lisskins(lis_names, lambda n: False)
        except Exception as e:
            print("  Lis-Skins: не удалось:", str(e)[:100])
    try:
        rate = sources.cbr_usd()[0]
    except Exception:
        rate = deal.get("usd_rub_fallback", 80.0)
    rate *= 1 + deal.get("rub_markup", 0.021)
    print(f"Цены площадок: каталог {len(sp)}, " + ", ".join(f"{k} {len(v)}" for k, v in mk.items())
          + f" — за {time.time() - t0:.0f} с")

    # цены редких паттернов — раз в pattern_refresh_days дней (или когда поменялся бюджет)
    budget_key = f"{deal.get('patterns_max_price_rub')}|v2"
    if (not pat.get("db") or pat.get("budget") != budget_key
            or time.time() - pat.get("ts", 0) > deal.get("pattern_refresh_days", 3) * 86400):
        t = time.time()
        budget = (deal.get("patterns_max_price_rub") or 10 ** 9) / rate
        cheap = {}
        for n, r in sp.items():
            if r.get("min_price"):
                b = cfround.pattern_base(n)
                cheap[b] = min(cheap.get(b, r["min_price"]), r["min_price"])
        try:
            db = sources.pattern_prices({b for b, p in cheap.items() if p <= budget})
            if db:
                pat = {"ts": int(time.time()), "budget": budget_key, "db": db}
                save("pat_db.json.gz", pat)
            print(f"Паттерны: предметов {len(db)}, групп {sum(map(len, db.values()))} за {time.time() - t:.0f} с")
        except Exception as e:
            print("Паттерны: не удалось:", str(e)[:150])
    pat_db = pat.get("db") or {}

    # лоты CSFloat — тот же поиск, что в анализаторе; запросов не больше day_cf_requests (лимит ~200 в час на ключ)
    pat_db = forky.merge(pat_db, data["sales"])
    for b, di in (data.get("idx") or {}).items():  # номера скинов, которые узнал ночной сборщик, — для охоты
        state.setdefault("cf_idx", {}).setdefault(b, di)
    cbase = (lambda ch: lambda n: ch(n, "CSFloat"))(cfround.cheapest_fn(deal, sp, mk))
    wanted = cfround.wanted_names(deal, sp)
    guide_names = {name for name in sp.keys() | data["sales"].keys() if forky.variant(name)}
    pat_names = {n for n in sp if pattern_base(n) in pat_db} | guide_names
    t = time.time()
    lots, info = cfround.run(deal, KEY, wanted, pat_names, pat_db, cbase, {n: r.get("v30") or 0 for n, r in sp.items()},
                             rate, state, max_requests=int(CFG.get("day_cf_requests", 95)), reserve=10)
    print(f"  за {time.time() - t:.0f} с")
    if info["requests"]:
        save("cf_lots.json", {"ts": int(time.time()), "lots": lots,
                              "info": {"requests": info["requests"], "left": info["left"], "reset": info["reset"],
                                       "done": sorted(info["done"]), "idx": info["idx"], "pred": info["pred"],
                                       "tags": info["tags"], "details": info.get("details", {})}})
    save("day_state.json", state)

    # история продаж CSFloat: ходовые предметы (сначала самые продаваемые), каждый — раз в day_sales_hours часов
    data.setdefault("fetched", {})
    t_now, every = int(time.time()), float(CFG.get("day_sales_hours", 6)) * 3600
    budget = (deal.get("patterns_max_price_rub") or 10 ** 9) / rate
    priority = priority_sales(lis_lots, lots, pat_db, data["fetched"], t_now, every, budget)
    priority_set = set(priority)
    due = priority + sorted((n for n in wanted | pat_names if n not in priority_set and t_now - data["fetched"].get(n, 0) >= every),
                 key=lambda n: (data["fetched"].get(n, 0), n not in pat_names,
                                -((sp.get(n) or {}).get("v30") or 0), n))
    print(f"История CSFloat: в начале очереди {len(priority)} предметов с редкими лотами в бюджете")
    deadline = t0 + float(CFG.get("day_time_budget_s", 600))
    done, got, left = harvest.collect_sales(data, due, deadline, int(CFG.get("day_sales_max", 200)))
    data["updated"] = t_now
    save("sales.json.gz", data)
    pat["db"] = forky.merge(pat_db, data["sales"])
    save("pat_db.json.gz", pat)
    guide_groups = [g for groups in pat["db"].values() for g in groups if g.get("source") == "forky"]
    print(f"Forky: предметов {len(forky.CATALOG)}, групп {len(guide_groups)}, "
          f"групп с продажами CSFloat {sum(bool(g['sales']) for g in guide_groups)}")
    print(f"Продажи CSFloat: обновлено предметов {done}, новых продаж {got}; в очереди {max(0, len(due) - done)}; "
          f"осталось запросов {left}")
    json.dump({"updated": now.strftime("%Y-%m-%d %H:%M МСК"), "lots": sum(map(len, lots.values())),
               "cf_requests": info["requests"], "sales_items": done, "queue": max(0, len(due) - done)},
              open("day_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Готово за {time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
