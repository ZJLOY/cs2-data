"""
Сборщик истории продаж CSFloat для анализатора скинов CS2.

Каждый запуск берёт предметы, которые дольше всех не обновлялись, и скачивает их последние продажи на CSFloat
(до 40 на предмет: цена, float, номер паттерна). Продажи копятся в sales.json.gz (за keep_days дней).
Работает только в неактивные часы владельца и не отнимает лимит CSFloat у основного сбора.

Список предметов (items.json) пересобирается раз в сутки:
  • скины с редкими паттернами (каталог cs2pattern-prices.com), чья обычная копия не дороже patterns_max_usd;
  • ходовые предметы Skinport: от min_volume_30d продаж за 30 дней, цена от min_price до max_price $.
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    import brotli
except ImportError:
    brotli = None

sys.stdout.reconfigure(encoding="utf-8")
CFG = json.load(open("config.json", encoding="utf-8"))
KEY = os.environ.get("CSFLOAT_API_KEY", "")
MSK = timezone(timedelta(hours=3))
UA = "Mozilla/5.0 (cs2-data harvester)"


class RateLimited(Exception):
    pass


def http_get(url, headers=None, timeout=60):
    h = {"User-Agent": UA, "Accept-Encoding": "br, gzip" if brotli else "gzip"}
    h.update(headers or {})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                raw, enc = r.read(), r.headers.get("Content-Encoding", "")
                if enc == "br":
                    raw = brotli.decompress(raw)
                elif enc == "gzip":
                    raw = gzip.decompress(raw)
                return raw, r.headers
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise RateLimited(url) from e
            last = e
            if e.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(3 * (attempt + 1))
    raise last


def get_json(url, headers=None):
    raw, h = http_get(url, headers)
    return json.loads(raw), h


# ---------- когда можно собирать ----------

def allowed(now):
    """Не в свободные часы владельца и не ближе guard_minutes к началу основного сбора (у него тот же лимит CSFloat)."""
    day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
    a, b = CFG["free_hours"][day]
    if a <= now.hour < b:
        return False, f"свободные часы ({day} {a}–{b} МСК)"
    for t in CFG["main_runs"].get(day, []):
        h, m = map(int, t.split(":"))
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if timedelta(0) <= start - now < timedelta(minutes=CFG["guard_minutes"]):
            return False, f"скоро основной сбор ({t} МСК)"
    return True, ""


# ---------- список предметов ----------

def pattern_base(name):
    for pre in ("StatTrak™ ", "Souvenir "):
        if name.startswith(pre):
            name = name[len(pre):]
    return name.rsplit(" (", 1)[0] if name.endswith(")") else name


def pattern_bases():
    """Скины, у которых бывают редкие паттерны (каталог cs2pattern-prices.com)."""
    raw, _ = http_get("https://cs2pattern-prices.com/weapons")
    html = raw.decode("utf-8", "replace")
    parts = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    t = "".join(parts).encode("latin-1", "backslashreplace").decode("unicode_escape", errors="ignore")
    weapons, _ = json.JSONDecoder().raw_decode(t[t.find('{"weapons":['):])
    out = set()
    for w in weapons["weapons"]:
        star = "★ " if w.get("category") in ("Knives", "Gloves") and not w["name"].startswith("★") else ""
        for sk in w["skins"]:
            out.add(f"{star}{w['name']} | {sk['name']}")
    return out


def build_items():
    q = "app_id=730&currency=USD"
    listings, _ = get_json(f"https://api.skinport.com/v1/items?{q}")
    sales, _ = get_json(f"https://api.skinport.com/v1/sales/history?{q}")
    price = {it["market_hash_name"]: it.get("min_price") for it in listings}
    vol = {it["market_hash_name"]: ((it.get("last_30_days") or {}).get("volume") or 0,
                                    (it.get("last_7_days") or {}).get("median")) for it in sales}
    bases = pattern_bases()
    cheap = {}
    for n, p in price.items():
        if p and not n.startswith("Souvenir "):
            b = pattern_base(n)
            if b in bases:
                cheap[b] = min(cheap.get(b, p), p)
    ok = {b for b, p in cheap.items() if p <= CFG["patterns_max_usd"]}
    pat = sorted(n for n in price if pattern_base(n) in ok and not n.startswith("Souvenir ") and n.endswith(")"))
    f = CFG["liquid"]
    liq = sorted(n for n, (v30, m7) in vol.items() if v30 >= f["min_volume_30d"] and m7
                 and f["min_price"] <= m7 <= f["max_price"] and n not in pat)
    print(f"Список: скинов с паттернами {len(ok)} ({len(pat)} названий), ходовых предметов {len(liq)}")
    return {"ts": int(time.time()), "patterns": pat, "liquid": liq}


# ---------- продажи CSFloat ----------

def csfloat_sales(name):
    url = f"https://csfloat.com/api/v1/history/{urllib.parse.quote(name, safe='')}/sales"
    data, h = get_json(url, {"Authorization": KEY} if KEY else None)
    if isinstance(data, dict):
        data = data.get("data") or data.get("sales") or []
    out = []
    for s in data:
        price, when = s.get("price"), s.get("sold_at") or s.get("created_at")
        if not price or not when:
            continue
        ts = int(datetime.fromisoformat(str(when).replace("Z", "+00:00")).timestamp()) if not isinstance(when, (int, float)) else int(when)
        item = s.get("item") or {}
        # сколько в продаже стоили наклейки — чтобы потом отсеять продажи, где цену задают наклейки
        st = sum(((x.get("reference") or {}).get("price") or 0) for x in item.get("stickers") or []) / 100
        fl = item.get("float_value")
        out.append([ts, price / 100, round(fl, 8) if fl is not None else None, item.get("paint_seed"), round(st, 2)])
    try:
        left = int(h.get("x-ratelimit-remaining"))
    except (TypeError, ValueError):
        left = None
    return out, left


def main():
    now = datetime.now(MSK)
    ok, why = allowed(now)
    if not ok and "--force" not in sys.argv:
        print("Пропуск:", why)
        return
    try:
        items = json.load(open("items.json", encoding="utf-8"))
    except (OSError, ValueError):
        items = {}
    try:
        data = json.load(gzip.open("sales.json.gz", "rt", encoding="utf-8"))
    except (OSError, ValueError):
        data = {"sales": {}, "fetched": {}}
    if not items or time.time() - items.get("ts", 0) > CFG["list_refresh_hours"] * 3600:
        try:
            items = build_items()
            json.dump(items, open("items.json", "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as e:
            print("Список не обновился:", str(e)[:150])
    if not items:
        sys.exit("Нет списка предметов")
    fetched = data["fetched"]
    t_now = int(time.time())
    # пора обновлять: паттерны — раз в patterns_every_hours, ходовые — раз в liquid_every_hours;
    # первыми — паттерны, внутри — то, что дольше всех не обновлялось
    due = [(0, fetched.get(n, 0), n) for n in items["patterns"]
           if t_now - fetched.get(n, 0) >= CFG["patterns_every_hours"] * 3600]
    due += [(1, fetched.get(n, 0), n) for n in items["liquid"]
            if t_now - fetched.get(n, 0) >= CFG["liquid_every_hours"] * 3600]
    due = [n for _, _, n in sorted(due)]
    deadline = time.time() + CFG["time_budget_s"]
    done, got, left = 0, 0, None
    for n in due:
        if time.time() > deadline or (left is not None and left <= CFG["reserve"]) or done >= CFG["max_requests"]:
            break
        try:
            rows, left = csfloat_sales(n)
        except RateLimited:
            print("CSFloat ограничил запросы — остальное в следующий раз")
            break
        except Exception as e:
            print(f"  {n}: {str(e)[:80]}")
            fetched[n] = t_now  # чтобы не застревать на одном предмете
            continue
        old = {(r[0], r[1]) for r in data["sales"].get(n, [])}
        new = [r for r in rows if (r[0], r[1]) not in old]
        data["sales"][n] = sorted(data["sales"].get(n, []) + new)
        fetched[n] = t_now
        done, got = done + 1, got + len(new)
        time.sleep(CFG["pause_s"])
    keep = t_now - CFG["keep_days"] * 86400
    for n in list(data["sales"]):
        data["sales"][n] = [r for r in data["sales"][n] if r[0] >= keep]
        if not data["sales"][n]:
            del data["sales"][n]
    data["updated"] = t_now
    with gzip.open("sales.json.gz", "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    total = sum(len(v) for v in data["sales"].values())
    print(f"Обновлено предметов: {done}, новых продаж: {got}; осталось запросов CSFloat: {left}; "
          f"в очереди: {max(0, len(due) - done)}; всего в базе: {total} продаж по {len(data['sales'])} предметам")
    json.dump({"updated": now.strftime("%Y-%m-%d %H:%M МСК"), "items": len(data["sales"]), "sales": total,
               "queue": max(0, len(due) - done)}, open("status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
