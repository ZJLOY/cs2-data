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
    t0 = time.time()

    # цены площадок — чтобы выбрать предметы так же, как анализатор
    sp = sources.skinport()
    sp = {n: r for n, r in sp.items() if r.get("qty") or r.get("v90")}
    mk, _, errors = sources.csgotrader()
    for e in errors:
        print("  не удалось:", e)
    try:
        mk["marketcsgo"] = sources.market_csgo()
    except Exception as e:
        print("  Market.CSGO: не удалось:", str(e)[:100])
    if "Lis-Skins" in (deal.get("deal_markets") or ["Lis-Skins"]):
        try:  # только самые низкие цены Lis-Skins (сами лоты анализатор скачивает сам)
            mk["lisskins"] = sources.lisskins(set(), lambda n: False)[0]
        except Exception as e:
            print("  Lis-Skins: не удалось:", str(e)[:100])
    try:
        rate = sources.cbr_usd()[0]
    except Exception:
        rate = deal.get("usd_rub_fallback", 80.0)
    rate *= 1 + deal.get("rub_markup", 0.021)
    print(f"Цены площадок: Skinport {len(sp)}, " + ", ".join(f"{k} {len(v)}" for k, v in mk.items())
          + f" — за {time.time() - t0:.0f} с")

    # цены редких паттернов — раз в pattern_refresh_days дней (или когда поменялся бюджет)
    pat = load("pat_db.json.gz", {})
    budget_key = f"{deal.get('patterns_max_price_rub')}|v2"
    if (not pat.get("db") or pat.get("budget") != budget_key
            or time.time() - pat.get("ts", 0) > deal.get("pattern_refresh_days", 3) * 86400
            or (CFG.get("extra_patterns") and "sf" not in pat)):  # скины extra_patterns ещё не добавлены
        t = time.time()
        budget = (deal.get("patterns_max_price_rub") or 10 ** 9) / rate
        cheap = {}
        for n, r in sp.items():
            if r.get("min_price"):
                b = cfround.pattern_base(n)
                cheap[b] = min(cheap.get(b, r["min_price"]), r["min_price"])
        try:
            db = sources.pattern_prices({b for b, p in cheap.items() if p <= budget})
            # скины без цен на сайте (extra_patterns): лучшие номера по Skinflow, продажи — свои (ниже, каждый запуск)
            sf = {}
            for b in CFG.get("extra_patterns") or []:
                if b in db or not cheap.get(b) or cheap[b] > budget:
                    continue
                try:
                    seeds, url = sources.skinflow_seeds(b)
                    if seeds:
                        sf[b] = {"seeds": seeds, "url": url}
                    else:
                        print(f"  {b}: на Skinflow нет разбора паттернов — только копим продажи")
                except Exception as e:
                    print(f"  {b}: Skinflow не ответил: {str(e)[:80]}")
                    if b in (pat.get("sf") or {}):
                        sf[b] = pat["sf"][b]
            if db:
                pat = {"ts": int(time.time()), "budget": budget_key, "db": db, "sf": sf}
                save("pat_db.json.gz", pat)
            print(f"Паттерны: предметов {len(db)}, групп {sum(map(len, db.values()))} за {time.time() - t:.0f} с")
        except Exception as e:
            print("Паттерны: не удалось:", str(e)[:150])
    pat_db = pat.get("db") or {}

    # лоты CSFloat — тот же поиск, что в анализаторе; запросов не больше day_cf_requests (лимит ~200 в час на ключ)
    data = load("sales.json.gz", {"sales": {}, "fetched": {}})
    # группы из своих продаж — для скинов без цен на cs2pattern-prices.com (номера по Skinflow)
    if pat.get("sf"):
        for b, v in pat["sf"].items():
            pat["db"][b] = [sources.own_pattern_group(b, v["seeds"], v["url"], data.get("sales") or {})]
        pat_db = pat["db"]
        save("pat_db.json.gz", pat)
        print("Паттерны по своим продажам: " + ", ".join(f"{b} — продаж лучших номеров {len(pat_db[b][0]['sales'])}"
                                                     for b in pat["sf"]))
    for b, di in (data.get("idx") or {}).items():  # номера скинов, которые узнал ночной сборщик, — для охоты
        state.setdefault("cf_idx", {}).setdefault(b, di)
    cbase = (lambda ch: lambda n: ch(n, "CSFloat"))(cfround.cheapest_fn(deal, sp, mk))
    wanted = cfround.wanted_names(deal, sp)
    pat_names = {n for n in sp if cfround.pattern_base(n) in pat_db}
    t = time.time()
    lots, info = cfround.run(deal, KEY, wanted, pat_names, pat_db, cbase, {n: r.get("v30") or 0 for n, r in sp.items()},
                             rate, state, max_requests=int(CFG.get("day_cf_requests", 95)), reserve=10)
    print(f"  за {time.time() - t:.0f} с")
    if info["requests"]:
        save("cf_lots.json", {"ts": int(time.time()), "lots": lots,
                              "info": {"requests": info["requests"], "left": info["left"], "reset": info["reset"],
                                       "done": sorted(info["done"]), "idx": info["idx"], "pred": info["pred"],
                                       "tags": info["tags"]}})
    save("day_state.json", state)

    # история продаж CSFloat: ходовые предметы (сначала самые продаваемые), каждый — раз в day_sales_hours часов
    data.setdefault("fetched", {})
    t_now, every = int(time.time()), float(CFG.get("day_sales_hours", 6)) * 3600
    due = sorted((n for n in wanted if t_now - data["fetched"].get(n, 0) >= every), key=lambda n: -(sp[n].get("v30") or 0))
    deadline = t0 + float(CFG.get("day_time_budget_s", 600))
    done, got, left = harvest.collect_sales(data, due, deadline, int(CFG.get("day_sales_max", 200)))
    data["updated"] = t_now
    save("sales.json.gz", data)
    print(f"Продажи CSFloat: обновлено предметов {done}, новых продаж {got}; в очереди {max(0, len(due) - done)}; "
          f"осталось запросов {left}")
    json.dump({"updated": now.strftime("%Y-%m-%d %H:%M МСК"), "lots": sum(map(len, lots.values())),
               "cf_requests": info["requests"], "sales_items": done, "queue": max(0, len(due) - done)},
              open("day_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Готово за {time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
