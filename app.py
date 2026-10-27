import os
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template_string
from fyers_apiv3 import fyersModel

# Educational 3-minute market-data dashboard only.
# No options selection, trade calls, or entry/SL/target recommendations.
app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("market-study")
CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "").strip()
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
SYMBOL = os.getenv("FYERS_SYMBOL", "NSE:NIFTYBANK-INDEX").strip()
TIMEFRAME = "3"
HISTORY_DAYS = max(2, min(int(os.getenv("HISTORY_DAYS", "5")), 10))
REFRESH_SECONDS = 180
IST = ZoneInfo("Asia/Kolkata")

def fmt(x):
    return "—" if x is None else f"{x:,.2f}"

def fetch():
    if not CLIENT_ID or not ACCESS_TOKEN:
        raise RuntimeError("FYERS_CLIENT_ID or FYERS_ACCESS_TOKEN is missing in Render Environment.")
    fy = fyersModel.FyersModel(client_id=CLIENT_ID, token=ACCESS_TOKEN, is_async=False, log_path="")
    now = datetime.now(IST).replace(second=0, microsecond=0)
    end = now - timedelta(minutes=now.minute % 3 + 3)
    start = end - timedelta(days=HISTORY_DAYS)
    resp = fy.history(data={"symbol": SYMBOL, "resolution": TIMEFRAME, "date_format": "0",
        "range_from": str(int(start.timestamp())), "range_to": str(int(end.timestamp())), "cont_flag": "1"})
    if not isinstance(resp, dict) or resp.get("s") != "ok":
        raise RuntimeError("FYERS history request failed. Check token, symbol and data permissions.")
    data = {}
    for r in resp.get("candles", []):
        try:
            ts, o, h, l, c, v = r[:6]
            vals = [float(o), float(h), float(l), float(c), float(v)]
            if not all(x == x and abs(x) != float("inf") for x in vals): continue
            if min(vals[:4]) <= 0 or vals[1] < vals[2]: continue
            data[int(ts)] = {"ts": int(ts), "open": vals[0], "high": vals[1], "low": vals[2], "close": vals[3], "volume": max(0, vals[4])}
        except (ValueError, TypeError, IndexError, OverflowError):
            continue
    candles = [data[k] for k in sorted(data)]
    if len(candles) < 25:
        raise RuntimeError(f"Only {len(candles)} valid candles returned. Check market session and permissions.")
    return candles

def ema(xs, n):
    out = [None] * len(xs)
    if len(xs) < n: return out
    cur = sum(xs[:n]) / n
    out[n-1] = cur
    alpha = 2 / (n + 1)
    for i in range(n, len(xs)):
        cur = alpha * xs[i] + (1-alpha) * cur
        out[i] = cur
    return out

def rsi(xs, n=14):
    out = [None] * len(xs)
    if len(xs) <= n: return out
    changes = [xs[i] - xs[i-1] for i in range(1, len(xs))]
    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]
    ag, al = sum(gains[:n])/n, sum(losses[:n])/n
    def calc(g, l):
        return 100.0 if l == 0 and g > 0 else (50.0 if l == 0 else 100 - 100/(1+g/l))
    out[n] = calc(ag, al)
    for i in range(n+1, len(xs)):
        ag = (ag*(n-1) + gains[i-1])/n
        al = (al*(n-1) + losses[i-1])/n
        out[i] = calc(ag, al)
    return out

def make_data():
    cs = fetch()
    closes = [c["close"] for c in cs]
    e9, e21, rs = ema(closes, 9), ema(closes, 21), rsi(closes)
    tr = [c["high"]-c["low"] if i == 0 else max(c["high"]-c["low"], abs(c["high"]-cs[i-1]["close"]), abs(c["low"]-cs[i-1]["close"])) for i,c in enumerate(cs)]
    atr = [None]*len(cs)
    if len(cs) >= 14:
        a = sum(tr[:14])/14; atr[13] = a
        for i in range(14, len(cs)):
            a = (a*13 + tr[i])/14; atr[i] = a
    vwap, active, pv, vol = [None]*len(cs), None, 0.0, 0.0
    for i,c in enumerate(cs):
        day = datetime.fromtimestamp(c["ts"], timezone.utc).astimezone(IST).date()
        if day != active: active, pv, vol = day, 0.0, 0.0
        typical = (c["high"]+c["low"]+c["close"])/3
        pv += typical*c["volume"]; vol += c["volume"]
        if vol: vwap[i] = pv/vol
        c.update(ema9=e9[i], ema21=e21[i], rsi=rs[i], atr=atr[i], vwap=vwap[i])
    last = cs[-1]
    rows = []
    for c in reversed(cs[-30:]):
        dt = datetime.fromtimestamp(c["ts"], timezone.utc).astimezone(IST)
        rows.append({"time":dt.strftime("%d %b %I:%M %p"), "open":fmt(c["open"]), "high":fmt(c["high"]),
            "low":fmt(c["low"]), "close":fmt(c["close"]), "volume":f'{c["volume"]:,.0f}',
            "ema9":fmt(c["ema9"]), "ema21":fmt(c["ema21"]), "rsi":fmt(c["rsi"])})
    vols = [c["volume"] for c in cs[-21:-1]]
    return {"symbol":SYMBOL, "updated":datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST"),
        "candle_time":datetime.fromtimestamp(last["ts"], timezone.utc).astimezone(IST).strftime("%d %b %I:%M %p IST"),
        "close":fmt(last["close"]), "ema9":fmt(last["ema9"]), "ema21":fmt(last["ema21"]),
        "rsi":fmt(last["rsi"]), "atr":fmt(last["atr"]), "vwap":fmt(last["vwap"]),
        "volume":f'{last["volume"]:,.0f}', "avgvol":fmt(sum(vols)/len(vols) if vols else None),
        "count":len(cs), "rows":rows,
        "ema_note":"EMA 9 above EMA 21" if last["ema9"] > last["ema21"] else "EMA 9 at/below EMA 21",
        "vwap_note":"Close above session VWAP" if last["vwap"] and last["close"] > last["vwap"] else "Close at/below session VWAP"}

@app.template_filter("num")
def num(value): return fmt(value)

PAGE = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="{{ refresh }}"><title>3-Minute Market Study</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#131b2f;--line:#27344e;--text:#edf2ff;--muted:#9ba9c4;--blue:#78a9ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui;padding:20px}main{max-width:1200px;margin:auto}.head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}h1{font-size:25px;margin:0 0 5px}.muted,.sub{color:var(--muted);font-size:12px}.tag{border:1px solid var(--line);border-radius:99px;padding:6px 10px;color:var(--blue);height:max-content;font-size:12px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:15px;min-width:0}.label{font-size:12px;color:var(--muted);margin-bottom:7px}.value{font-size:22px;font-weight:700;overflow-wrap:anywhere}.sub{margin-top:6px}.note{background:#10192b;border-left:3px solid var(--blue);border-radius:7px;padding:12px;color:#cbd7ee;font-size:13px}h2{font-size:17px;margin:22px 0 10px}.wrap{overflow:auto;border:1px solid var(--line);border-radius:12px}table{width:100%;min-width:800px;border-collapse:collapse;background:var(--panel)}td,th{padding:10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap;font-variant-numeric:tabular-nums}th{font-size:12px;color:var(--muted);background:#17223a}td:first-child,th:first-child{text-align:left}footer{font-size:12px;color:var(--muted);margin:16px 0}
</style></head><body><main><div class="head"><div><h1>3-Minute Market Study Dashboard</h1><div class="muted">{{ d.symbol }} · 3-minute candles · Updated {{ d.updated }}</div></div><div class="tag">STUDY MODE · NO TRADE CALLS</div></div>
<div class="grid">
{% for label,value,sub in [('Latest completed close',d.close,d.candle_time),('EMA 9',d.ema9,'Short-period average'),('EMA 21',d.ema21,d.ema_note),('RSI (14)',d.rsi,'Momentum measure'),('Session VWAP',d.vwap,d.vwap_note),('ATR (14)',d.atr,'Recent range measure'),('Latest volume',d.volume,'Recent average: '+d.avgvol),('Valid candles',d.count,'History window: '+days|string+' days')] %}
<div class="card"><div class="label">{{ label }}</div><div class="value">{{ value }}</div><div class="sub">{{ sub }}</div></div>{% endfor %}
</div><div class="note">Learning/research display only. Indicators can be wrong and do not predict outcomes. No options are selected and no buy/sell recommendation, entry, stop-loss or target is generated.</div>
<h2>Latest 30 candles</h2><div class="wrap"><table><thead><tr><th>Time (IST)</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>EMA 9</th><th>EMA 21</th><th>RSI 14</th></tr></thead><tbody>
{% for r in d.rows %}<tr><td>{{ r.time }}</td><td>{{ r.open }}</td><td>{{ r.high }}</td><td>{{ r.low }}</td><td>{{ r.close }}</td><td>{{ r.volume }}</td><td>{{ r.ema9 }}</td><td>{{ r.ema21 }}</td><td>{{ r.rsi }}</td></tr>{% endfor %}
</tbody></table></div><footer>Auto-refresh: {{ refresh }} seconds. Uses completed historical candles returned by FYERS; refresh does not guarantee streaming real-time data.</footer></main></body></html>'''
ERROR = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><title>Data issue</title></head><body style="background:#0b1020;color:#edf2ff;font:16px system-ui;padding:24px"><main style="max-width:700px;margin:auto;background:#131b2f;padding:22px;border-radius:12px"><h1>3-Minute Market Study</h1><p><b>Data/API issue:</b> {{ message }}</p><p>Check Render Environment variables FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN, token validity, symbol and market-data permissions. Never share credentials in chat.</p><p>Health endpoint: /health · Retrying in 30 seconds.</p></main></body></html>'''

@app.route("/")
def home():
    try:
        return render_template_string(PAGE, d=make_data(), refresh=REFRESH_SECONDS, days=HISTORY_DAYS)
    except Exception as exc:
        log.exception("Dashboard data load failed")
        msg = str(exc) if "missing in Render Environment" in str(exc) else "Could not load market data. Check Render logs, FYERS token, symbol and permissions."
        return render_template_string(ERROR, message=msg), 503

@app.route("/health")
def health():
    ok = bool(CLIENT_ID and ACCESS_TOKEN)
    return jsonify({"status":"ok" if ok else "configuration_missing","credentials_configured":ok,
        "symbol":SYMBOL,"resolution":TIMEFRAME,"refresh_seconds":REFRESH_SECONDS,
        "mode":"educational_market_study_only"}), (200 if ok else 503)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","10000")))
