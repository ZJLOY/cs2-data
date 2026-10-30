"""Разовая проверка параметров поиска лотов CSFloat (что работает и что приходит в ответе)."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
KEY = os.environ.get("CSFLOAT_API_KEY", "")


def get(params):
    url = "https://csfloat.com/api/v1/listings?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": KEY, "User-Agent": "Mozilla/5.0"}), timeout=40) as r:
            return json.loads(r.read()), {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read()[:300].decode("utf-8", "replace")}, {}


def show(title, params):
    d, h = get(params)
    rows = d.get("data") if isinstance(d, dict) else d
    print(f"\n== {title}: {params}\n   лимит: {h}")
    if not isinstance(rows, list):
        print("   ответ:", str(d)[:300])
        return None
    print(f"   лотов: {len(rows)}; ключи ответа: {list(d.keys()) if isinstance(d, dict) else 'list'}; cursor: {str(d.get('cursor'))[:40] if isinstance(d, dict) else None}")
    for x in rows[:3]:
        it = x.get("item") or {}
        print("   ", it.get("market_hash_name"), "| цена", x.get("price"), "| float", it.get("float_value"), "| seed", it.get("paint_seed"),
              "| def", it.get("def_index"), "paint", it.get("paint_index"), "| scm", (it.get("scm") or {}).get("price"),
              "| predicted", x.get("reference", {}).get("predicted_price") if isinstance(x.get("reference"), dict) else None,
              "| ref", json.dumps(x.get("reference"))[:160], "| created", x.get("created_at"))
    if rows:
        print("   ключи лота:", list(rows[0].keys()), "| ключи item:", list((rows[0].get("item") or {}).keys())[:40])
    return rows


base = {"type": "buy_now", "limit": 50}
show("лучшая сделка", {**base, "sort_by": "best_deal", "min_price": 100, "max_price": 6000})
show("наибольшая скидка", {**base, "sort_by": "highest_discount", "min_price": 100, "max_price": 6000})
show("самые новые", {**base, "sort_by": "most_recent", "min_price": 100, "max_price": 6000})
show("низкий float", {**base, "sort_by": "lowest_float", "min_price": 100, "max_price": 6000})
r = show("по номеру паттерна (MP7 Amberline #286)", {**base, "sort_by": "lowest_price", "market_hash_name": "MP7 | Amberline (Factory New)"})
if r:
    it = r[0]["item"]
    show("def+paint+seed", {**base, "sort_by": "lowest_price", "def_index": it.get("def_index"), "paint_index": it.get("paint_index"), "paint_seed": 286})
    show("def+paint, несколько seed через запятую", {**base, "def_index": it.get("def_index"), "paint_index": it.get("paint_index"), "paint_seed": "286,41,209"})
