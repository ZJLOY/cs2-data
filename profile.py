import time, json, sys, pickle, gzip
import sources
T = {}
def t(name, f):
    s = time.time()
    try:
        r = f()
    except Exception as e:
        print(name, "ERR", str(e)[:200]); r = None
    T[name] = round(time.time() - s, 1); print(name, T[name], "s", flush=True)
    return r
sp = t("skinport", sources.skinport)
liq = {n for n, r in (sp or {}).items() if (r.get("v30") or 0) >= 20 and 0.5 <= (r.get("m7") or r.get("min_price") or 0) <= 80}
print("liquid", len(liq))
mk = t("csgotrader", sources.csgotrader)
t("market_csgo", sources.market_csgo)
r = t("lisskins_all_stickers", lambda: sources.lisskins(liq, lambda n: True))
if r:
    agg, fl, st, pr, ch = r
    print("lis names", len(agg), "float lots", sum(map(len, fl.values())), "sticker lots", len(st), "all prices", sum(map(len, pr.values())))
    print("pickle gz MB floats", len(gzip.compress(pickle.dumps(fl))) / 1e6, "stick", len(gzip.compress(pickle.dumps(st))) / 1e6,
          "prices", len(gzip.compress(pickle.dumps(pr))) / 1e6)
r = t("mcsgo_lots", lambda: sources.mcsgo_lots(liq, lambda n: True, min_transfer=70))
if r:
    fl, st, ch, pr = r
    print("mc float lots", sum(map(len, fl.values())), "sticker lots", len(st), "prices", sum(map(len, pr.values())))
    print("gz MB", len(gzip.compress(pickle.dumps(r))) / 1e6)
print(json.dumps(T))
