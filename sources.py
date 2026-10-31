"""
Источники данных.

  Skinport     — публичный API, лоты и история продаж (24ч/7д/30д/90д). Ключ не нужен.
  csgotrader   — бесплатные ежедневные выгрузки цен Steam, Buff163, CSFloat, CS.Money. Ключ не нужен.
  Steam        — priceoverview: объём продаж за 24 часа. Жёсткий лимит, поэтому только для портфеля.
  CSFloat API  — реальные продажи с float. Нужен ключ (csfloat.com → профиль → Developers).
"""

import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from datetime import datetime

try:
    import brotli
except ImportError:
    brotli = None

UA = "Mozilla/5.0 (cs2-skin-tracker)"


class RateLimited(Exception):
    pass


def http_get(url, headers=None, retries=3, timeout=60):
    h = {"User-Agent": UA, "Accept-Encoding": "br, gzip" if brotli else "gzip"}
    h.update(headers or {})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                raw = r.read()
                enc = r.headers.get("Content-Encoding", "")
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
    raw, hdr = http_get(url, headers)
    return json.loads(raw), hdr


# ---------- Skinport ----------

def skinport(currency="USD"):
    if brotli is None:
        raise RuntimeError("Для Skinport нужна библиотека brotli:  python -m pip install brotli")
    q = f"app_id=730&currency={currency}"
    listings, _ = get_json(f"https://api.skinport.com/v1/items?{q}")
    sales, _ = get_json(f"https://api.skinport.com/v1/sales/history?{q}")
    out = {}
    for it in listings:
        out[it["market_hash_name"]] = {
            "url": it.get("item_page"),
            "min_price": it.get("min_price"), "med_price": it.get("median_price"),
            "qty": it.get("quantity") or 0,
        }
    for it in sales:
        r = out.setdefault(it["market_hash_name"], {"url": it.get("item_page"), "qty": 0})
        for k, period in (("24", "last_24_hours"), ("7", "last_7_days"),
                          ("30", "last_30_days"), ("90", "last_90_days")):
            p = it.get(period) or {}
            r["v" + k] = p.get("volume") or 0
            r["m" + k] = p.get("median")
    return out


# ---------- csgotrader (Steam, Buff163, CSFloat, CS.Money) ----------

def _price(v):
    if isinstance(v, dict):
        v = v.get("price")
    return v if isinstance(v, (int, float)) and v > 0 else None


def csgotrader():
    """Возвращает ({источник: {название: {колонка: цена}}}, время обновления, ошибки)."""
    result, errors, stamps = {}, [], []
    g = lambda v, k: v.get(k) if isinstance(v, dict) else None
    parsers = {
        "steam": lambda v: {"steam24": _price(g(v, "last_24h")), "steam7": _price(g(v, "last_7d")),
                            "steam30": _price(g(v, "last_30d")), "steam90": _price(g(v, "last_90d"))},
        "buff163": lambda v: {"buff_ask": _price(g(v, "starting_at")), "buff_bid": _price(g(v, "highest_order"))},
        "csfloat": lambda v: {"float_ask": _price(g(v, "starting_at")) or _price(v),
                              "float_bid": _price(g(v, "highest_order"))},
        "csmoney": lambda v: {"csmoney": _price(v)},
    }
    for src, parse in parsers.items():
        try:
            data, hdr = get_json(f"https://prices.csgotrader.app/latest/{src}.json")
            if hdr.get("Last-Modified"):
                stamps.append(int(parsedate_to_datetime(hdr["Last-Modified"]).timestamp()))
            result[src] = {n: parse(v) for n, v in data.items() if v is not None}
        except Exception as e:  # один упавший источник не должен ломать остальные
            errors.append(f"{src}: {e}")
    return result, (min(stamps) if stamps else None), errors


# ---------- Market.CSGO ----------

def market_csgo():
    """Минимальная цена лота и число продаж на market.csgo.com: {название: {mcsgo, mcsgo_vol}}."""
    d, _ = get_json("https://market.csgo.com/api/v2/prices/USD.json")
    out = {}
    for it in d.get("items", []):
        try:
            p = float(it.get("price") or 0)
            out[it["market_hash_name"]] = {"mcsgo": p if p > 0 else None, "mcsgo_vol": int(it.get("volume") or 0)}
        except (ValueError, KeyError):
            continue
    return out


# ---------- Waxpeer ----------

def waxpeer():
    """Минимальная цена и число лотов на Waxpeer: {название: {wax_min, wax_qty}}. Цены у них в тысячных долях $."""
    d, _ = get_json("https://api.waxpeer.com/v1/prices?game=csgo&minified=1")
    return {it["name"]: {"wax_min": it["min"] / 1000 if it.get("min") else None, "wax_qty": it.get("count") or 0}
            for it in d.get("items", []) if it.get("name")}


# ---------- DMarket (нужен ключ: публичный + секретный) ----------

DMARKET = "https://api.dmarket.com"


def dmarket_request(method, path, params, public_key, secret_key, body=None):
    """
    Подписанный запрос к DMarket. Подпись: Ed25519 от строки
    метод + путь с параметрами + тело + время, в заголовке X-Request-Sign с префиксом «dmar ed25519».
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    ts = str(int(time.time()))
    q = urllib.parse.urlencode(params or {})
    route = path + ("?" + q if q else "")
    data = json.dumps(body, separators=(",", ":")) if body is not None else ""
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(secret_key.strip())[:32])
    sign = key.sign((method + route + data + ts).encode()).hex()
    headers = {"X-Api-Key": public_key.strip(), "X-Sign-Date": ts, "X-Request-Sign": "dmar ed25519 " + sign,
               "Accept": "application/json", "User-Agent": UA}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(DMARKET + route, data=data.encode() if body is not None else None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited(path) from e
        raise


def dmarket_get(path, params, public_key, secret_key):
    return dmarket_request("GET", path, params, public_key, secret_key)


def dmarket_prices(titles, public_key, secret_key, log=print):
    """Лучший лот и лучшая заявка на DMarket пачками по 100: {название: {dm_ask, dm_bid, dm_offers, dm_orders}}."""
    out, titles = {}, list(titles)
    for i in range(0, len(titles), 100):
        body = {"filter": {"game": "a8db", "titles": titles[i:i + 100]}, "limit": "100"}
        r = None
        for attempt in range(4):
            try:
                r = dmarket_request("POST", "/marketplace-api/v1/aggregated-prices", {}, public_key, secret_key, body)
                break
            except RateLimited:
                time.sleep(5 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, ConnectionError):  # обрыв соединения — повторяем
                time.sleep(2 * (attempt + 1))
        if r is None:
            log(f"  DMarket: пачка {i // 100 + 1} не загрузилась — пропущена")
            continue
        for p in r.get("aggregatedPrices", []):
            ask = int((p.get("offerBestPrice") or {}).get("Amount") or 0) / 100
            bid = int((p.get("orderBestPrice") or {}).get("Amount") or 0) / 100
            out[p["title"]] = {"dm_ask": ask or None, "dm_bid": bid or None,
                               "dm_offers": int(p.get("offerCount") or 0), "dm_orders": int(p.get("orderCount") or 0)}
        time.sleep(0.3)
    return out


def dmarket_lots(titles, public_key, secret_key, threads=4, log=print):
    """
    Самые дешёвые лоты DMarket (до 100 на предмет) с float, паттерном и наклейками — для сделок как у Lis-Skins.
    Возвращает {название: {"total": всего лотов, "lots": [(цена, float, паттерн, наклейки, id лота, ссылка осмотра)]}}.
    Лоты с блокировкой обмена пропускаем.
    """
    from concurrent.futures import ThreadPoolExecutor

    def one(t):
        r = None
        for attempt in range(3):
            try:
                r = dmarket_get("/marketplace-api/v2/offers",
                                {"gameId": "a8db", "title": t, "limit": 100, "currency": "USD",
                                 "orderBy": "price", "orderDir": "asc"}, public_key, secret_key)
                break
            except RateLimited:
                time.sleep(5 * (attempt + 1))
            except Exception:  # обрыв соединения — пробуем ещё раз
                time.sleep(1 + attempt)
        if r is None:
            return t, None
        lots = []
        for o in r.get("items") or []:
            a = o.get("attributes") or {}
            c = a.get("cs2") or {}
            if a.get("title") != t or o.get("locked") or (a.get("tradeLockDays") or 0) > 0:
                continue
            try:
                price = int(o["priceCents"]) / 100
            except (KeyError, ValueError, TypeError):
                continue
            fl = c.get("float")
            fl = float(fl) if fl not in (None, "", "0") else None
            st = tuple((s.get("name") or "", float(s.get("wear") or 0)) for s in (c.get("stickers") or []) if s.get("name"))
            lots.append((price, fl, c.get("paintSeed"), st, o.get("offerId"), c.get("inspectInGameUri")))
        return t, {"total": int(r.get("total") or len(lots)), "lots": lots}

    out, failed = {}, 0
    with ThreadPoolExecutor(threads) as ex:
        for t, res in ex.map(one, list(titles)):
            if res is None:
                failed += 1
            else:
                out[t] = res
    if failed:
        log(f"  DMarket: лоты не загрузились для {failed} предметов")
    return out


def dmarket_sales(title, public_key, secret_key, limit=20):
    """Последние продажи предмета на DMarket: [{ts, price, float, seed, stickers}]."""
    r = dmarket_get("/trade-aggregator/v1/last-sales", {"gameId": "a8db", "title": title, "limit": limit},
                    public_key, secret_key)
    out = []
    for s in r.get("sales", []):
        a = s.get("offerAttributes") or s.get("orderAttributes") or {}
        try:
            out.append({"ts": int(s["date"]), "price": float(s["price"]), "float": a.get("floatValue"),
                        "seed": a.get("paintSeed"), "kind": s.get("txOperationType"),
                        "stickers": [st.get("name") for st in (a.get("stickers") or []) if st.get("name")]})
        except (KeyError, ValueError):
            continue
    return out


# ---------- Lis-Skins: все лоты с float и наклейками ----------

LIS_URL = "https://lis-skins.com/market_export_json/api_csgo_full.json"


def lisskins(keep_floats, keep_stickers):
    """
    Потоком читает выгрузку Lis-Skins (2,5 млн лотов), не загружая её целиком в память.
    Возвращает:
      agg      — {название: {"lis_min": мин. цена, "lis_qty": число лотов}}
      floats   — {название: [(цена, float, паттерн, наклейки, id, ссылка), ...]} для названий из keep_floats
      stickers — [(название, цена, float, наклейки, id, ссылка)] — лоты с наклейками, если keep_stickers(название)
      prices   — {название: [цены всех лотов]} — чтобы сказать, каким по цене стоит лот на странице предмета
      cheap    — {название: [5 самых дешёвых лотов без блокировки обмена]} для названий из keep_floats — для «Скидки»
    Наклейки: [(полное название, износ)].
    """
    import ijson
    req = urllib.request.Request(LIS_URL, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    resp = urllib.request.urlopen(req, timeout=180)
    src = gzip.GzipFile(fileobj=resp) if resp.headers.get("Content-Encoding") == "gzip" else resp
    agg, floats, stick, prices, cheap = {}, {}, [], {}, {}
    for it in ijson.items(src, "items.item", use_float=True):
        name, price = it.get("name"), it.get("price")
        if not name or not price:
            continue
        prices.setdefault(name, []).append(price)
        a = agg.get(name)
        if a is None:
            agg[name] = {"lis_min": price, "lis_qty": 1}
        else:
            a["lis_qty"] += 1
            if price < a["lis_min"]:
                a["lis_min"] = price
        if it.get("unlock_at"):  # лот ещё заблокирован для обмена — для сравнения не берём
            continue
        st = tuple((s.get("name_full") or "Sticker | " + (s.get("name") or ""), float(s.get("wear") or 0))
                   for s in (it.get("stickers") or []))
        fl = it.get("item_float")
        fl = float(fl) if fl not in (None, "") else None
        rec = (price, fl, it.get("item_paint_seed"), st, it.get("id"), it.get("item_link"))
        if name in keep_floats:
            if fl is not None:
                floats.setdefault(name, []).append(rec)
            c = cheap.setdefault(name, [])
            if len(c) < 5 or price < c[-1][0]:
                c.append(rec)
                c.sort(key=lambda x: x[0])
                del c[5:]
        if st and keep_stickers(name):
            stick.append((name,) + rec)
    return agg, floats, stick, prices, cheap


# ---------- Skinport: лента продаж в реальном времени ----------

def skinport_feed(seconds, log=print):
    """Слушает официальную ленту продаж Skinport (Socket.IO) и возвращает проданные предметы."""
    try:
        import socketio
    except ImportError:
        log("  нужна библиотека python-socketio:  python -m pip install \"python-socketio[client]\" msgpack")
        return []
    sales, seen = [], set()
    sio = socketio.Client(serializer="msgpack", reconnection=False)

    @sio.event
    def connect():
        sio.emit("saleFeedJoin", {"currency": "USD", "locale": "en", "appid": 730})

    @sio.on("saleFeed")
    def on_feed(data):
        if data.get("eventType") != "sold":
            return
        for s in data.get("sales") or []:
            sid = s.get("saleId") or s.get("id")
            name, price = s.get("marketHashName"), s.get("salePrice")
            if not sid or not name or not price or sid in seen:
                continue
            seen.add(sid)
            sales.append({
                "id": int(sid), "name": name, "price": price / 100, "ts": int(time.time()),
                "float": s.get("wear"), "pattern": s.get("pattern"),
                "stickers": [(st.get("name") or "", float(st.get("wear") or 0)) for st in (s.get("stickers") or [])],
            })

    try:
        sio.connect("https://skinport.com", transports=["websocket"], wait_timeout=30,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                           "(KHTML, like Gecko) Chrome/141.0 Safari/537.36",
                             "Origin": "https://skinport.com"})
        end = time.time() + seconds
        while time.time() < end:
            sio.sleep(1)
        sio.disconnect()
    except Exception as e:
        # уточняем причину: 403 от Cloudflare значит, что с этого адреса ленту не пускают
        why = ""
        try:
            http_get("https://skinport.com/socket.io/?EIO=4&transport=polling", retries=1, timeout=20)
            why = "сервер ленты отвечает, отказ на этапе websocket"
        except urllib.error.HTTPError as he:
            why = f"HTTP {he.code}" + (" (Cloudflare не пускает этот адрес)" if he.code == 403 else "")
        except Exception as he:
            why = str(he)[:80]
        log(f"  лента Skinport недоступна: {e} — {why}")
    return sales


# ---------- картинки и редкость предметов (открытая база ByMykel/CSGO-API) ----------

STEAM_IMG = "https://community.akamai.steamstatic.com/economy/image/"


def item_looks():
    """{market_hash_name: (код картинки Steam, цвет редкости)} для всех предметов CS2."""
    raw, _ = http_get("https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/all.json", timeout=180)
    d = json.loads(raw)
    out = {}
    for v in (d.values() if isinstance(d, dict) else d):
        n, img = v.get("market_hash_name") or v.get("name"), v.get("image") or ""
        if n and img:
            # храним только код картинки — общий адрес Steam добавляется в отчёте
            out[n] = (img.replace(STEAM_IMG, "").split("/")[0] if img.startswith(STEAM_IMG) else img,
                      (v.get("rarity") or {}).get("color"))
    return out


def skin_crates():
    """{название скина без износа: [кейсы, из которых он выпадает]} — для признака «снят с выпадения»."""
    raw, _ = http_get("https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins.json", timeout=300)
    out = {}
    for s in json.loads(raw):
        if s.get("name"):
            out[s["name"]] = sorted({c["name"] for c in s.get("crates") or [] if c.get("name")})
    return out


def marketcsgo_history(names, key, raw=False):
    """История реальных продаж на Market.CSGO (нужен бесплатный ключ). До 50 названий за запрос."""
    q = urllib.parse.urlencode([("key", key)] + [("list_hash_name[]", n) for n in names])
    d, _ = get_json(f"https://market.csgo.com/api/v2/get-list-items-info?{q}")
    return d


def marketcsgo_purchases(key, days=90, step_days=30):
    """
    Покупки на Market.CSGO (нужен ключ): [{"lot_id", "name", "price", "currency", "date"}].
    Метод history отдаёт все операции; берём только покупки, где предмет уже передан (stage 2).
    Цена в ответе — в сотых долях рубля (RUB) или тысячных долях доллара/евро.
    """
    out, seen, now = [], set(), int(time.time())
    start = now - days * 86400
    while start < now:
        end = min(now, start + step_days * 86400)
        q = urllib.parse.urlencode({"key": key, "date": start, "date_end": end})
        d, _ = get_json(f"https://market.csgo.com/api/v2/history?{q}")
        if isinstance(d, dict) and d.get("success") is False:
            raise ValueError(str(d.get("error") or d)[:150])
        for it in (d.get("data") if isinstance(d, dict) else None) or []:
            if str(it.get("event") or "").lower() != "buy" or str(it.get("stage") or "") != "2":
                continue
            iid = str(it.get("item_id") or it.get("id") or "")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            cur = str(it.get("currency") or "RUB").upper()
            try:
                price = float(it.get("paid") or it.get("price") or 0) / (100 if cur == "RUB" else 1000)
                ts = int(float(it.get("time") or 0))
            except (TypeError, ValueError):
                continue
            if price <= 0 or not it.get("market_hash_name"):
                continue
            out.append({"lot_id": iid, "name": it["market_hash_name"], "price": price, "currency": cur,
                        "date": datetime.fromtimestamp(ts).date().isoformat() if ts else ""})
        start = end
        time.sleep(1)
    return out


def cbr_usd(day=None):
    """Курс доллара ЦБ РФ: (рублей за $1, дата курса 'ГГГГ-ММ-ДД'). day — дата 'ГГГГ-ММ-ДД' (по умолчанию сегодня).
    В выходные ЦБ курс не публикует — берём ближайший предыдущий рабочий день."""
    from datetime import date as _d, timedelta
    if day is None:
        d, _ = get_json("https://www.cbr-xml-daily.ru/daily_json.js")
        return d["Valute"]["USD"]["Value"], d["Date"][:10]
    t = _d.fromisoformat(day)
    for _ in range(10):
        try:
            d, _ = get_json(f"https://www.cbr-xml-daily.ru/archive/{t:%Y/%m/%d}/daily_json.js")
            return d["Valute"]["USD"]["Value"], day
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            t -= timedelta(days=1)
    raise RuntimeError(f"нет курса ЦБ на {day}")


# ---------- Pricempire (цены многих площадок одним запросом) ----------

PE_API = "https://api.pricempire.com"


def pricempire_get(path, key, params=None):
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    d, _ = get_json(PE_API + path + q, {"Authorization": f"Bearer {key}"})
    return d


def pricempire_trader(key):
    """
    Бесплатный уровень Pricempire (1000 запросов в месяц, один запрос — все предметы):
    Buff163 — средняя цена за 7/30/60/90 дней (видно тренд за 3 месяца) и Skins.com — самый дешёвый лот.
    Цены в ответе — в центах.
    """
    d = pricempire_get("/v4/trader/items/prices", key,
                       {"app_id": 730, "currency": "USD", "sources": "buff163,skins", "avg": "true", "median": "true"})
    c = lambda v: v / 100 if v else None
    out = {}
    for it in d:
        row = {}
        for p in it.get("prices") or []:
            if p.get("provider_key") == "buff163":
                row.update({"bf_m7": c(p.get("median_7")), "bf_m30": c(p.get("median_30")),
                            "bf_m60": c(p.get("median_60")), "bf_m90": c(p.get("median_90"))})
            elif p.get("provider_key") == "skins" and p.get("price"):
                row.update({"skins_min": c(p["price"]), "skins_qty": p.get("count"),
                            "skins_link": (p.get("meta") or {}).get("link")})
        if row:
            out[it["market_hash_name"]] = row
    return out


# ---------- Steam: инвентарь ----------

def steam_id64(text):
    """SteamID64 из числа, ссылки на профиль (/profiles/… или /id/…) или ника в ссылке."""
    text = text.strip().rstrip("/")
    m = re.search(r"(\d{17})", text)
    if m:
        return m.group(1)
    m = re.search(r"/id/([^/?#]+)", text)
    vanity = m.group(1) if m else text
    raw, _ = http_get(f"https://steamcommunity.com/id/{urllib.parse.quote(vanity)}/?xml=1")
    m = re.search(rb"<steamID64>(\d{17})</steamID64>", raw)
    if not m:
        raise ValueError(f"Профиль «{vanity}» не найден")
    return m.group(1).decode()


def steam_inventory(steamid, props=None):
    """Предметы CS2 из открытого инвентаря Steam: {market_hash_name: количество} (только продаваемые).
    Если передан список props, добавляет в него (название, float, номер паттерна) каждого предмета —
    Steam отдаёт их в asset_properties. Предметы на удержании после обмена Steam публично не показывает."""
    counts, start = {}, None
    while True:
        url = f"https://steamcommunity.com/inventory/{steamid}/730/2?l=english&count=2000"
        if start:
            url += f"&start_assetid={start}"
        try:
            d, _ = get_json(url)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ValueError("Инвентарь скрыт. В Steam: Профиль → Редактировать → Приватность → "
                                 "«Инвентарь: Открытый».") from e
            raise
        if not d or not d.get("assets"):
            break
        desc = {(x["classid"], x.get("instanceid", "0")): x for x in d.get("descriptions", [])}
        ap = {}
        for p in d.get("asset_properties") or []:
            v = {q.get("name"): q.get("int_value") or q.get("float_value") for q in p.get("asset_properties") or []}
            ap[str(p.get("assetid"))] = v
        for a in d["assets"]:
            x = desc.get((a["classid"], a.get("instanceid", "0")))
            if x and x.get("marketable"):
                n = x["market_hash_name"]
                counts[n] = counts.get(n, 0) + int(a.get("amount", 1))
                v = ap.get(str(a["assetid"])) or {}
                if props is not None and v.get("Wear Rating"):
                    seed = v.get("Pattern Template")
                    props.append((n, float(v["Wear Rating"]), int(seed) if seed is not None else None))
        if not d.get("more_items"):
            break
        start = d.get("last_assetid")
        time.sleep(2)
    return counts


# ---------- Steam priceoverview ----------

def _money(s):
    if not s:
        return None
    s = re.sub(r"[^\d.,]", "", s)
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def steam_overview(names, delay=3.5, log=print):
    out = {}
    for i, n in enumerate(names):
        url = ("https://steamcommunity.com/market/priceoverview/?appid=730&currency=1&market_hash_name="
               + urllib.parse.quote(n))
        try:
            d, _ = get_json(url)
            if d.get("success"):
                out[n] = {"lowest": _money(d.get("lowest_price")), "median": _money(d.get("median_price")),
                          "volume": int(re.sub(r"\D", "", d.get("volume", "0")) or 0)}
        except RateLimited:
            log("  Steam ограничил запросы (429) — остальные предметы пропущены до следующего запуска.")
            break
        except Exception as e:
            log(f"  Steam: {n}: {e}")
        if i + 1 < len(names):
            time.sleep(delay)
    return out


# ---------- CSFloat API (нужен ключ) ----------

def _ts(v):
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


HARVEST_URL = "https://github.com/ZJLOY/cs2-data/releases/download/data/sales.json.gz"


def harvest_sales(url=HARVEST_URL):
    """Продажи CSFloat, которые копит открытый сборщик ZJLOY/cs2-data в неактивные часы:
    {"sales": {название: [[время, цена $, float, номер паттерна, наклейки $], ...]}, "updated": время}."""
    raw, _ = http_get(url, retries=2, timeout=120)
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass  # уже распаковано
    return json.loads(raw)


def harvest_hunt(url=HARVEST_URL.replace("sales.json.gz", "hunt.json")):
    """Ночная охота за номерами от сборщика: {"ts": время, "lots": [[название, цена $, float, номер, id лота,
    ссылка осмотра, когда выставлен, оценка CSFloat $], ...]}."""
    raw, _ = http_get(url, retries=2, timeout=60)
    return json.loads(raw)


def csfloat_sales(name, api_key=None):
    """Последние продажи предмета на CSFloat (до 40): [{ts, price($), float}]. Ключ не обязателен.
    Продажи, где цену заметно задают наклейки (дороже 30% цены продажи), пропускаем."""
    url = f"https://csfloat.com/api/v1/history/{urllib.parse.quote(name, safe='')}/sales"
    data, _ = get_json(url, headers={"Authorization": api_key} if api_key else None)
    if isinstance(data, dict):
        data = data.get("data") or data.get("sales") or []
    out = []
    for s in data:
        price = s.get("price")
        ts = _ts(s.get("sold_at") or s.get("created_at"))
        if not price or not ts:
            continue
        item = s.get("item") or {}
        st = sum(((x.get("reference") or {}).get("price") or 0) for x in item.get("stickers") or [])
        if st > 0.3 * price:
            continue
        out.append({"ts": ts, "price": price / 100, "float": item.get("float_value"), "seed": item.get("paint_seed")})
    return out


def lis_api(path, key, params=None):
    """Запрос к API Lis-Skins (нужен ключ из профиля lis-skins.com)."""
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    raw, _ = http_get("https://api.lis-skins.com/v1/" + path + q, retries=2, timeout=30,
                      headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    return json.loads(raw)


BAD_PURCHASE = ("return", "cancel", "refund", "error", "fail", "reject")


def lis_purchases(key, days=365):
    """
    Покупки на Lis-Skins (нужен ключ): [{"lot_id", "purchase_id", "name", "price"($), "date", "status"}].
    Возвраты и отменённые покупки пропускаем.
    """
    out, page = [], 1
    start = int(time.time()) - days * 86400
    while page <= 100:
        d = lis_api("market/history", key, {"page": page, "start_unix_time": start})
        items = d.get("data") if isinstance(d, dict) else d
        if isinstance(items, dict):  # {"data": {"purchases": [...]}} и подобное
            items = next((v for v in items.values() if isinstance(v, list)), [])
        if not items:
            break
        for p in items:
            skins = p.get("skins") or p.get("items") or ([p] if (p.get("name") or p.get("market_hash_name")) else [])
            when = p.get("created_at") or p.get("date") or p.get("purchased_at")
            for s in skins:
                st = str(s.get("status") or p.get("status") or "")
                name = s.get("name") or s.get("market_hash_name")
                price = s.get("price") or s.get("price_usd")
                if not name or price is None or any(b in st.lower() for b in BAD_PURCHASE):
                    continue
                ts = _ts(when) if when else None
                out.append({"lot_id": str(s.get("id") or s.get("skin_id") or ""), "name": name, "price": float(price),
                            "float": s.get("item_float"),
                            "purchase_id": str(p.get("id") or p.get("purchase_id") or ""), "status": st,
                            "date": datetime.fromtimestamp(ts).date().isoformat() if ts else ""})
        meta = (d.get("meta") or {}) if isinstance(d, dict) else {}
        last = meta.get("last_page") or (meta.get("pagination") or {}).get("last_page")
        if not last or page >= int(last):
            break
        page += 1
    return out


def skinout_lots(keep_floats):
    """
    Все лоты SkinOut.gg одной выгрузкой (так просит сам сайт: pagination=false). У лотов есть float и цена,
    номера паттерна и наклеек нет. Возвращает (floats, cheap, slugs):
      floats — {название: [(цена, float, None, (), id лота, "")]} для названий из keep_floats
      cheap  — {название: [5 самых дешёвых лотов]}, slugs — {название: адрес страницы предмета}
    """
    raw, _ = http_get("https://skinout.gg/api/market/items?pagination=false&float_min=0",
                      headers={"Accept": "application/json"}, retries=2, timeout=300)
    d = json.loads(raw)
    floats, cheap, slugs = {}, {}, {}
    for x in d.get("items") or []:
        name = x.get("market_hash_name") or x.get("name")
        if name not in keep_floats or x.get("locked"):
            continue
        try:
            price, fl = float(x["price"]), float(x["float"]) if x.get("float") else None
        except (TypeError, ValueError, KeyError):
            continue
        if price <= 0:
            continue
        rec = (price, fl, None, (), str(x.get("id")), "")
        slugs[name] = x.get("name_id") or ""
        if fl:
            floats.setdefault(name, []).append(rec)
        cheap.setdefault(name, []).append(rec)
    for v in list(floats.values()) + list(cheap.values()):
        v.sort(key=lambda r: r[0])
    cheap = {n: v[:5] for n, v in cheap.items()}
    return floats, cheap, slugs


TRADEIT = "https://tradeit.gg/api/v2/inventory/data?gameId=730"


def tradeit_groups(max_pages=40, log=print):
    """Все предметы магазина Tradeit.gg: {название: номер группы} (по 500 групп на запрос)."""
    out = {}
    for page in range(max_pages):
        raw, _ = http_get(f"{TRADEIT}&offset={page * 500}&limit=500", retries=2, timeout=90)
        items = json.loads(raw).get("items") or []
        for x in items:
            if x.get("name") and x.get("groupId"):
                out[x["name"]] = x["groupId"]
        if not items:  # страница бывает и меньше 500 — идём, пока не придёт пустая
            break
        time.sleep(1)
    return out


def tradeit_lots(groups, delay=1.0, log=print):
    """
    Все копии предметов на Tradeit.gg по номерам групп {название: группа}: у каждой копии float и номер паттерна,
    а цена у всех копий одна. Копии с блокировкой обмена пропускаем.
    Возвращает {название: [(цена, float, паттерн, (), id, ссылка осмотра)]}.
    """
    out = {}
    for name, gid in groups.items():
        try:
            raw, _ = http_get(f"{TRADEIT}&offset=0&limit=200&groupId={gid}", retries=1, timeout=60)
        except RateLimited:
            log("  Tradeit ограничил запросы — остальное в следующий раз")
            break
        except urllib.error.HTTPError as e:
            log(f"  Tradeit ответил {e.code} — остальное в следующий раз")
            break
        except Exception as e:
            log(f"  Tradeit: {name}: {str(e)[:80]}")
            continue
        for x in json.loads(raw).get("items") or []:
            lock = x.get("tradeLockDay")
            if (isinstance(lock, int) and lock > 0) or isinstance(lock, list):
                continue
            price = (x.get("storePrice") or 0) / 100
            if price <= 0:
                continue
            insp = f"steam://run/730//+csgo_econ_action_preview%20{x['insl']}" if x.get("insl") else ""
            out.setdefault(x.get("name") or name, []).append(
                (price, x.get("floatValue") or None, x.get("patternIndex"), (), str(x.get("assetId")), insp))
        time.sleep(delay)
    for v in out.values():
        v.sort(key=lambda r: r[0])
    return out


def _cf_sticker(name):
    name = name or "?"
    return name if name.startswith(("Sticker |", "Patch |")) else "Sticker | " + name


def csfloat_lots(jobs, api_key, reserve=10, log=print):
    """
    Лоты CSFloat (нужен ключ), только «купить сейчас». jobs — [(название, sort_by)], где sort_by —
    lowest_price (самые дешёвые) или lowest_float (самые низкие float); по 50 лотов на запрос.
    Останавливается, когда лимит запросов почти исчерпан.
    Возвращает ({название: [(цена, float, паттерн, наклейки, id лота, ссылка осмотра)]} без повторов,
    {"requests", "left", "reset", "done" — названия, по которым запрос прошёл}).
    """
    # jobs: (название, sort_by) — лоты одного предмета; или словарь параметров поиска по всему рынку
    # (sort_by, min_price/max_price в центах, def_index+paint_index+paint_seed «286,41» и т.п.) с "pages" — сколько страниц
    out, seen = {}, set()
    info = {"requests": 0, "left": None, "reset": None, "done": set(), "idx": {}, "pred": {}, "tags": {}}
    stop = False
    queue = list(jobs)
    while queue:
        job = queue.pop(0)
        if stop:
            break
        if isinstance(job, dict):
            params, pages, tag = {k: v for k, v in job.items() if k not in ("pages", "tag")}, int(job.get("pages", 1)), job.get("tag")
            name = None
        else:
            name, sort = job
            params, pages, tag = {"market_hash_name": name, "sort_by": sort}, 1, None
        cursor = None
        for _ in range(pages):
            if info["left"] is not None and info["left"] <= reserve:
                log(f"  CSFloat: лимит запросов почти исчерпан (осталось {info['left']}) — остальное в следующий раз")
                stop = True
                break
            q = urllib.parse.urlencode({**params, "limit": 50, "type": "buy_now", **({"cursor": cursor} if cursor else {})})
            try:
                raw, h = http_get(f"https://csfloat.com/api/v1/listings?{q}", headers={"Authorization": api_key},
                                  retries=2, timeout=40)
            except RateLimited:
                log("  CSFloat ограничил запросы — остальное в следующий раз")
                stop = True
                break
            except Exception as e:
                seeds = str(params.get("paint_seed") or "").split(",")
                if getattr(e, "code", None) == 400 and len(seeds) > 1:  # слишком много номеров сразу — делим пополам
                    info["requests"] += 1
                    half = len(seeds) // 2
                    queue[:0] = [{**job, "paint_seed": ",".join(seeds[:half])}, {**job, "paint_seed": ",".join(seeds[half:])}]
                else:
                    log(f"  CSFloat: {name or params.get('sort_by')}: {str(e)[:80]}")
                break
            info["requests"] += 1
            if name:
                info["done"].add(name)
            try:
                info["left"], info["reset"] = int(h.get("x-ratelimit-remaining")), h.get("x-ratelimit-reset")
            except (TypeError, ValueError):
                pass
            d = json.loads(raw)
            for x in (d.get("data") if isinstance(d, dict) else d) or []:
                it = x.get("item") or {}
                lid, price = str(x.get("id")), (x.get("price") or 0) / 100
                if x.get("type", "buy_now") != "buy_now" or x.get("state", "listed") != "listed" or lid in seen or price <= 0:
                    continue
                seen.add(lid)
                n = it.get("market_hash_name") or name
                if it.get("def_index") is not None and it.get("paint_index"):
                    info["idx"][n] = (it["def_index"], it["paint_index"])  # номера скина — для поиска по паттернам
                ref = x.get("reference") or {}
                if ref.get("predicted_price"):
                    info["pred"][lid] = ref["predicted_price"] / 100  # оценка CSFloat с учётом float
                if tag:
                    info["tags"][lid] = tag
                st = tuple((_cf_sticker(s.get("name")), round(s.get("wear") or 0, 3)) for s in it.get("stickers") or [])
                out.setdefault(n, []).append(
                    (price, it.get("float_value") or None, it.get("paint_seed"), st, lid, it.get("inspect_link") or ""))
            cursor = d.get("cursor") if isinstance(d, dict) else None
            time.sleep(0.3)
            if not cursor:
                break
    for v in out.values():
        v.sort(key=lambda r: r[0])
    return out, info


# ---------- cs2pattern-prices.com: реальные продажи CSFloat по редким паттернам ----------
PATTERN_SITE = "https://cs2pattern-prices.com"


def _rsc(html):
    """Склеивает данные страницы Next.js (self.__next_f.push) в одну строку."""
    parts = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    return "".join(parts).encode("latin-1", "backslashreplace").decode("unicode_escape", errors="ignore")


def pattern_catalog():
    """Каталог сайта: [(название на рынке без износа, ссылка на группу, название группы, тир)]."""
    raw, _ = http_get(PATTERN_SITE + "/weapons", retries=2, timeout=60)
    t = _rsc(raw.decode("utf-8", "replace"))
    j = t.find('{"weapons":[')
    weapons, _ = json.JSONDecoder().raw_decode(t[j:])
    out = []
    for w in weapons["weapons"]:
        star = "★ " if w.get("category") in ("Knives", "Gloves") and not w["name"].startswith("★") else ""
        for sk in w["skins"]:
            name = f"{star}{w['name']} | {sk['name']}"
            for g in sk["groups"]:
                tier = re.search(r"T(\d+)$", g["label"])
                out.append((name, f"/weapons/{w['slug']}/{sk['slug']}/{g['slug']}", g["label"],
                            int(tier.group(1)) if tier else 1))
    return out


def pattern_group(href):
    """
    Одна группа паттернов: номера паттернов и последние реальные продажи CSFloat (до 50):
    [номер, износ, "st"/"normal", цена, дата]. Продажи с наклейками не берём — наклейки завышают цену.
    Сводные медианы сайта не используем: они за всё время и смешивают дорогие и дешёвые номера группы.
    """
    raw, _ = http_get(PATTERN_SITE + href, retries=2, timeout=60)
    html = raw.decode("utf-8", "replace")
    seeds = sorted({int(x) for x in re.findall(re.escape(href) + r"/(\d+)", html)})
    t = _rsc(html)
    sales, seen = [], set()
    head = re.compile(r'\{"id":(\d+),"csfloatId":"\d+","patternIndex":(\d+),"wearCondition":"(FN|MW|FT|WW|BS)",'
                      r'"floatValue":[\d.eE-]+,"priceUsd":([\d.]+),"soldAt":"(\d{4}-\d\d-\d\d)[^"]*","stickers":(null|\[)')
    for m in head.finditer(t):
        sid, seed, wear, price, day, st = m.groups()
        k = t.find('"isStattrak":', m.end())
        flag = t[k + 13:k + 18] if k >= 0 else "null"
        if sid in seen or st != "null":
            continue
        seen.add(sid)
        fv = re.search(r'"floatValue":([0-9.eE-]+)', m.group(0))
        sales.append([int(seed), wear, "st" if flag.startswith("true") else "normal", float(price), day,
                      float(fv.group(1)) if fv else None])
    return {"seeds": seeds, "sales": sales}


def pattern_prices(names, threads=2, log=print):
    """
    Цены редких паттернов для предметов из names (названия без износа, как на рынке).
    Возвращает {название: [{"label", "tier", "url", "seeds", "wear", "seed"}]}.
    Сайт небольшой — качаем в 2 потока и только нужные предметы.
    """
    from concurrent.futures import ThreadPoolExecutor
    cat = [c for c in pattern_catalog() if c[0] in names]

    def one(c):
        for attempt in range(4):
            try:
                time.sleep(0.5)  # сайт небольшой — не торопимся
                return c, pattern_group(c[1])
            except RateLimited:  # просит подождать — ждём и пробуем снова
                time.sleep(15 * (attempt + 1))
            except Exception:
                return c, None
        return c, None

    out, failed = {}, 0
    with ThreadPoolExecutor(threads) as ex:
        for (name, href, label, tier), g in ex.map(one, cat):
            if not g or not g["seeds"]:
                failed += 1
                continue
            out.setdefault(name, []).append({"label": label, "tier": tier, "url": PATTERN_SITE + href, **g})
    if failed:
        log(f"  паттерны: не загрузились {failed} групп из {len(cat)}")
    return out


# ---------- Waxpeer: все лоты (открытая выгрузка CSV), float и паттерн — из ссылки осмотра ----------
def _varint(b, i):
    r = sh = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << sh
        sh += 7
        if x < 0x80:
            return r, i


def _proto(b):
    out, i = {}, 0
    while i < len(b):
        k, i = _varint(b, i)
        f, t = k >> 3, k & 7
        if t == 0:
            v, i = _varint(b, i)
        elif t == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        elif t == 5:
            v, i = b[i:i + 4], i + 4
        elif t == 1:
            v, i = b[i:i + 8], i + 8
        else:
            raise ValueError("wire type")
        out.setdefault(f, []).append(v)
    return out


def inspect_decode(link):
    """
    Ссылка осмотра нового формата CS2 (steam://run/730//+csgo_econ_action_preview%20<hex>) содержит сам предмет:
    первый байт — ключ, всё XOR этим ключом, дальше 0x00, protobuf CEconItemPreviewDataBlock и 4 байта контрольной суммы.
    Возвращает (float, паттерн, [(номер наклейки, потёртость)]) или None.
    """
    import struct
    try:
        raw = bytes.fromhex(link.rsplit("%20", 1)[-1])
        key = raw[0]
        p = _proto(bytes(x ^ key for x in raw)[1:-4])
        fl = struct.unpack("<f", struct.pack("<I", p[7][0]))[0] if 7 in p else None
        st = []
        for blob in p.get(12, []):
            q = _proto(blob)
            if 2 in q:
                st.append((q[2][0], struct.unpack("<f", q[3][0])[0] if 3 in q else 0.0))
        return fl, (p.get(8) or [0])[0], st
    except Exception:
        return None


_STICKER_NAMES = None


def sticker_names():
    """Номер наклейки → её название на рынке (открытая база ByMykel/CSGO-API)."""
    global _STICKER_NAMES
    if _STICKER_NAMES is None:
        try:
            d, _ = get_json("https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/stickers.json")
            _STICKER_NAMES = {int(x["def_index"]): x.get("market_hash_name") or x["name"]
                              for x in d if x.get("def_index")}
        except Exception:
            _STICKER_NAMES = {}
    return _STICKER_NAMES


MCSGO_EXPORT = "https://market.csgo.com/api/full-export/"
CERT_LINK = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20"


def mcsgo_lots(keep_floats, keep_stickers, min_transfer=0, threads=4, log=print):
    """
    Все лоты Market.CSGO (открытая выгрузка, без ключа, ~120 файлов по 10 000 лотов).
    float, паттерн и наклейки берём из сертификата осмотра (как ссылку осмотра у Waxpeer).
    min_transfer — не брать лоты продавцов, у которых шанс передать предмет ниже (поле chance_to_transfer, %).
    Возвращает:
      floats   — {название: [(цена, float, паттерн, наклейки, id лота, ссылка осмотра)]} для keep_floats
      stickers — [(название, цена, float, паттерн, наклейки, id, ссылка)] — если keep_stickers(название)
      cheap    — {название: [5 самых дешёвых лотов]} для keep_floats — для «Скидки»
      prices   — {название: [цены всех лотов]} — каким по цене стоит лот среди лотов предмета
    """
    from concurrent.futures import ThreadPoolExecutor
    idx, _ = get_json(MCSGO_EXPORT + "USD.json")
    fmt = {c: i for i, c in enumerate(idx["format"])}
    i_price, i_id, i_name, i_cert = fmt["price"], fmt["id"], fmt["market_hash_name"], fmt["inspect_certificate"]
    i_ch = fmt.get("chance_to_transfer")
    names = sticker_names()
    floats, stick, cheap, prices = {}, [], {}, {}

    def part(f):
        for attempt in range(3):
            try:
                return get_json(MCSGO_EXPORT + f)[0]
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 + attempt * 3)

    failed = 0
    with ThreadPoolExecutor(threads) as ex:
        futs = [ex.submit(part, f) for f in idx["items"]]
        for fu in futs:
            try:
                rows = fu.result()
            except Exception:
                failed += 1
                continue
            for r in rows or []:
                try:
                    name, price = r[i_name], int(r[i_price]) / 1000
                except (TypeError, ValueError, IndexError):
                    continue
                if price <= 0:
                    continue
                prices.setdefault(name, []).append(price)
                want_f = name in keep_floats
                if not (want_f or keep_stickers(name)):
                    continue
                if i_ch is not None and (r[i_ch] or 0) < min_transfer:
                    continue
                cert = r[i_cert]
                dec = inspect_decode(CERT_LINK + cert) if cert else None
                if not dec:
                    continue
                fl, seed, st = dec
                st = tuple((names.get(sid) or f"Sticker #{sid}", round(w, 3)) for sid, w in st)
                rec = (price, fl if fl else None, seed, st, str(r[i_id]), CERT_LINK + cert)
                if want_f:
                    if fl:
                        floats.setdefault(name, []).append(rec)
                    c = cheap.setdefault(name, [])
                    if len(c) < 5 or price < c[-1][0]:
                        c.append(rec)
                        c.sort(key=lambda x: x[0])
                        del c[5:]
                if st and keep_stickers(name):
                    stick.append((name,) + rec)
    if failed:
        log(f"  Market.CSGO: не загрузились {failed} из {len(idx['items'])} частей выгрузки")
    for v in floats.values():
        v.sort(key=lambda x: x[0])
    return floats, stick, cheap, prices


def waxpeer_lots(keep_floats, keep_stickers):
    """
    Все лоты Waxpeer одной выгрузкой (без ключа), как у Lis-Skins, но у каждого лота своя ссылка.
    Лоты с блокировкой обмена в выгрузку не попадают.
    Возвращает:
      floats   — {название: [(цена, float, паттерн, наклейки, id лота, ссылка осмотра)]} для названий из keep_floats
      stickers — [(название, цена, float, паттерн, наклейки, id, ссылка)] — лоты с наклейками, если keep_stickers(название)
      cheap    — {название: [5 самых дешёвых лотов]} для keep_floats — для «Скидки»
    """
    import csv
    import io
    names = sticker_names()
    req = urllib.request.Request("https://api.waxpeer.com/v1/prices/snapshot?format=csv&game=csgo",
                                 headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    resp = urllib.request.urlopen(req, timeout=300)
    src = gzip.GzipFile(fileobj=resp) if resp.headers.get("Content-Encoding") == "gzip" else resp
    rows = csv.reader(io.TextIOWrapper(src, encoding="utf-8", newline=""))
    head = next(rows)
    ci = {c: i for i, c in enumerate(head)}
    i_id, i_name, i_price, i_insp = ci["item_id"], ci["name"], ci["price"], ci["inspect"]
    floats, stick, cheap = {}, [], {}
    for r in rows:
        try:
            name, link = r[i_name], r[i_insp]
        except IndexError:
            continue
        want_f = name in keep_floats
        if not link or not (want_f or keep_stickers(name)):
            continue
        dec = inspect_decode(link)
        if not dec:
            continue
        fl, seed, st = dec
        price = int(r[i_price]) / 1000
        if price <= 0:
            continue
        st = tuple((names.get(sid) or f"Sticker #{sid}", round(w, 3)) for sid, w in st)
        rec = (price, fl if fl else None, seed, st, r[i_id], link)
        if want_f:
            if fl:
                floats.setdefault(name, []).append(rec)
            c = cheap.setdefault(name, [])
            if len(c) < 5 or price < c[-1][0]:
                c.append(rec)
                c.sort(key=lambda x: x[0])
                del c[5:]
        if st and keep_stickers(name):
            stick.append((name,) + rec)
    for v in floats.values():
        v.sort(key=lambda x: x[0])
    return floats, stick, cheap

