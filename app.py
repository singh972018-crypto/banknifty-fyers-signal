import os, math, logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template_string

try:
    from fyers_apiv3 import fyersModel
except Exception:
    fyersModel = None

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret")
logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
log = logging.getLogger("banknifty3m")
FYERS_CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "").strip()
FYERS_ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
# Retained for compatibility with existing hosting environment:
FYERS_SECRET = os.getenv("FYERS_SECRET", "").strip()
FYERS_REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI", "").strip()
MIN_PREMIUM = float(os.getenv("MIN_PREMIUM", "30"))
MAX_PREMIUM = float(os.getenv("MAX_PREMIUM", "65"))
USE_PREMIUM_FILTER = os.getenv("USE_PREMIUM_FILTER", "false").strip().lower() in ("1","true","yes","on")
BANKNIFTY_LOT_SIZE = int(os.getenv("BANKNIFTY_LOT_SIZE", "30"))
HISTORY_DAYS = max(2, min(10, int(os.getenv("FYERS_HISTORY_DAYS", "5"))))
TIMEFRAME, CANDLE_SECONDS = "3", 180
INDEX_SYMBOL = "NSE:NIFTYBANK-INDEX"
IST = ZoneInfo("Asia/Kolkata")

def now_ist():
    return datetime.now(IST)

def num(v, default=None):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError, OverflowError):
        return default

def money(v):
    v = num(v)
    return "—" if v is None else f"{v:,.2f}"

@app.template_filter("money")
def money_filter(v):
    return money(v)

def make_fyers():
    if fyersModel is None:
        raise RuntimeError("Missing fyers-apiv3 package.")
    if not FYERS_CLIENT_ID or not FYERS_ACCESS_TOKEN:
        raise RuntimeError("Set FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN in hosting environment.")
    return fyersModel.FyersModel(client_id=FYERS_CLIENT_ID, token=FYERS_ACCESS_TOKEN, log_path="")

def api_error(data, fallback="FYERS request failed"):
    return str(data.get("message") or data.get("error") or fallback) if isinstance(data, dict) else fallback

def fetch_candles():
    fy = make_fyers()
    end = now_ist()
    start = end - timedelta(days=HISTORY_DAYS)
    data = fy.history({"symbol": INDEX_SYMBOL, "resolution": TIMEFRAME, "date_format": "1",
        "range_from": start.strftime("%Y-%m-%d"), "range_to": end.strftime("%Y-%m-%d"), "cont_flag": "1"})
    if not isinstance(data, dict) or data.get("s") != "ok":
        raise RuntimeError(api_error(data, "Could not fetch 3-minute candles."))
    now_epoch, unique, invalid = int(datetime.now(timezone.utc).timestamp()), {}, 0
    for row in data.get("candles") or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            invalid += 1
            continue
        try:
            ts = int(row[0])
            opn, high, low, close, volume = [num(x) for x in row[1:6]]
            if any(x is None for x in (opn, high, low, close, volume)):
                invalid += 1
                continue
            if min(opn, high, low, close) <= 0 or high < max(opn, close, low) or low > min(opn, close, high):
                invalid += 1
                continue
            # FYERS timestamps are treated as candle-open timestamps.
            if ts + CANDLE_SECONDS > now_epoch:
                continue
            unique[ts] = {"ts":ts, "open":opn, "high":high, "low":low, "close":close, "volume":max(0.0,volume)}
        except (TypeError, ValueError, OverflowError):
            invalid += 1
    candles = sorted(unique.values(), key=lambda c:c["ts"])
    if len(candles) < 35:
        raise RuntimeError(f"Only {len(candles)} valid completed 3-minute candles; need 35.")
    last = candles[-1]
    age = max(0, now_epoch - (last["ts"] + CANDLE_SECONDS))
    current = now_ist()
    in_session = current.weekday() < 5 and (current.hour,current.minute) >= (9,15) and (current.hour,current.minute) <= (15,30)
    if in_session and age > 12*60:
        raise RuntimeError(f"Latest candle is stale ({age//60} minutes old); check FYERS data.")
    log.info("Accepted candles=%d invalid_rows=%d latest_age_sec=%d", len(candles), invalid, age)
    return candles

def ema(xs, period):
    if len(xs) < period: return None
    alpha, value = 2/(period+1), sum(xs[:period])/period
    for x in xs[period:]: value = alpha*x + (1-alpha)*value
    return value

def rsi(xs, period=14):
    if len(xs) <= period: return None
    changes = [xs[i]-xs[i-1] for i in range(1,len(xs))]
    gains, losses = [max(x,0) for x in changes], [max(-x,0) for x in changes]
    ag, al = sum(gains[:period])/period, sum(losses[:period])/period
    for i in range(period,len(changes)):
        ag, al = (ag*(period-1)+gains[i])/period, (al*(period-1)+losses[i])/period
    if al == 0: return 100.0 if ag > 0 else 50.0
    return 100-100/(1+ag/al)

def atr(cs, period=14):
    tr = []
    for i in range(1,len(cs)):
        c, prev = cs[i], cs[i-1]
        tr.append(max(c["high"]-c["low"], abs(c["high"]-prev["close"]), abs(c["low"]-prev["close"])))
    return sum(tr[-period:])/period if len(tr) >= period else None

def adx_estimate(cs, period=14):
    plus, minus, trs = [], [], []
    for i in range(1,len(cs)):
        c, prev = cs[i], cs[i-1]
        up, down = c["high"]-prev["high"], prev["low"]-c["low"]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
        trs.append(max(c["high"]-c["low"], abs(c["high"]-prev["close"]), abs(c["low"]-prev["close"])))
    dx = []
    for end in range(period-1,len(trs)):
        start = end-period+1
        total = sum(trs[start:end+1])
        if total <= 0: continue
        pd = 100*sum(plus[start:end+1])/total
        md = 100*sum(minus[start:end+1])/total
        dx.append(100*abs(pd-md)/(pd+md) if pd+md else 0.0)
    return sum(dx[-period:])/period if len(dx) >= period else None

def session_vwap(cs):
    day = datetime.fromtimestamp(cs[-1]["ts"],timezone.utc).astimezone(IST).date()
    today = [c for c in cs if datetime.fromtimestamp(c["ts"],timezone.utc).astimezone(IST).date() == day]
    volume = sum(c["volume"] for c in today)
    if volume <= 0: return None
    return sum(((c["high"]+c["low"]+c["close"])/3)*c["volume"] for c in today)/volume

def analyze(cs):
    closes, last = [c["close"] for c in cs], cs[-1]
    e9, e21, rv, av, dx, vw = ema(closes,9), ema(closes,21), rsi(closes), atr(cs), adx_estimate(cs), session_vwap(cs)
    if any(x is None for x in (e9,e21,rv,av,dx)) or av <= 0:
        raise RuntimeError("Indicators incomplete; wait for more valid candles.")
    bull = bear = 0
    checks = []
    if e9 > e21: bull += 1; checks.append(("EMA 9/21","Short EMA above long EMA","good"))
    elif e9 < e21: bear += 1; checks.append(("EMA 9/21","Short EMA below long EMA","bad"))
    else: checks.append(("EMA 9/21","EMAs equal","neutral"))
    if vw is None: checks.append(("Session VWAP","Unavailable: index volume missing/zero","neutral"))
    elif last["close"] > vw: bull += 1; checks.append(("Session VWAP","Close above VWAP","good"))
    elif last["close"] < vw: bear += 1; checks.append(("Session VWAP","Close below VWAP","bad"))
    else: checks.append(("Session VWAP","Close at VWAP","neutral"))
    if 52 <= rv <= 68: bull += 1; checks.append(("RSI 14",f"{rv:.1f}: moderate positive momentum","good"))
    elif 32 <= rv <= 48: bear += 1; checks.append(("RSI 14",f"{rv:.1f}: moderate negative momentum","bad"))
    else: checks.append(("RSI 14",f"{rv:.1f}: neutral/extended","neutral"))
    if dx >= 18 and e9 != e21:
        if e9 > e21: bull += 1; checks.append(("ADX estimate",f"{dx:.1f}: trend-strength filter active","good"))
        else: bear += 1; checks.append(("ADX estimate",f"{dx:.1f}: trend-strength filter active","bad"))
    else: checks.append(("ADX estimate",f"{dx:.1f}: weak/unclear trend","neutral"))
    if last["high"]-last["low"] > 1.8*av: checks.append(("Candle range","Unusually wide; volatility elevated","neutral"))
    else: checks.append(("Candle range","Within broad recent range","neutral"))
    bias = "BULLISH BIAS" if bull >= 3 and bull > bear else "BEARISH BIAS" if bear >= 3 and bear > bull else "NEUTRAL / MIXED"
    dt = datetime.fromtimestamp(last["ts"],timezone.utc).astimezone(IST)
    age = max(0,int(datetime.now(timezone.utc).timestamp())-(last["ts"]+CANDLE_SECONDS))
    return {"bias":bias,"bull":bull,"bear":bear,"spot":last["close"],"ema9":e9,"ema21":e21,
        "rsi":rv,"atr":av,"adx":dx,"vwap":vw,"checks":checks,"count":len(cs),
        "time":dt.strftime("%d-%b-%Y %I:%M:%S %p IST"),"age":round(age/60,1),"volume":last["volume"]}

HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="45"><title>BankNifty 3-Minute Study</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#edf3ff;font:15px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:18px}
header,.grid{display:flex;gap:12px;flex-wrap:wrap;justify-content:space-between}.grid{margin:14px 0}.card{background:#121c2e;border:1px solid #26354c;border-radius:13px;padding:15px;flex:1;min-width:245px}
h1{font-size:24px;margin:0}h2{font-size:17px;margin:0 0 10px}.muted,.label,.foot{color:#9fb0c8}.label{font-size:12px}.signal{font-size:27px;font-weight:800}.good{color:#4ade80}.bad{color:#fb7185}.neutral{color:#fbbf24}
.metrics{display:flex;gap:8px;flex-wrap:wrap}.metric{background:#0d1727;padding:9px;border-radius:8px;flex:1;min-width:105px}.value{font-size:17px;font-weight:650;overflow-wrap:anywhere}
table{width:100%;border-collapse:collapse}td{border-bottom:1px solid #26354c;padding:8px 5px;font-size:13px}.error{border-color:#7f1d1d;color:#fecaca}.small,.foot{font-size:12px}.pill{border:1px solid #26354c;border-radius:20px;padding:5px 9px}a{color:#7dd3fc}.notice{padding:10px;border:1px solid #67521a;background:#211c0e;border-radius:9px;color:#f6d98b;margin:14px 0}
</style></head><body><main><header><div><h1>BankNifty 3-Minute Study Dashboard</h1><div class="muted">Completed 3-minute candles · educational analysis only</div></div><div><span class="pill">Timeframe: 3m</span> <a href="/">Refresh now</a></div></header>
<div class="notice">For learning and observation only. A directional bias is not a prediction or a trading recommendation.</div>
{% if error %}<section class="card error"><h2>Data/API error</h2>{{error}}<p class="small">No analysis is shown when data is invalid or unavailable.</p></section>{% endif %}
{% if r %}<div class="grid"><section class="card"><div class="label">Market-study reading</div><div class="signal {% if r.bias == 'BULLISH BIAS' %}good{% elif r.bias == 'BEARISH BIAS' %}bad{% else %}neutral{% endif %}">{{r.bias}}</div><div class="muted">Bullish checks {{r.bull}} · Bearish checks {{r.bear}}</div><p class="small">Latest completed candle: {{r.time}}</p><p class="small">Candle age: {{r.age}} min</p></section>
<section class="card"><h2>Index data</h2><div class="metrics"><div class="metric"><div class="label">Last close</div><div class="value">{{r.spot|money}}</div></div><div class="metric"><div class="label">ATR 14</div><div class="value">{{r.atr|money}}</div></div><div class="metric"><div class="label">Latest volume</div><div class="value">{{r.volume|int}}</div></div><div class="metric"><div class="label">Candles loaded</div><div class="value">{{r.count}}</div></div></div></section></div>
<div class="grid"><section class="card"><h2>Indicators</h2><table><tr><td>EMA 9</td><td>{{r.ema9|money}}</td></tr><tr><td>EMA 21</td><td>{{r.ema21|money}}</td></tr><tr><td>RSI 14</td><td>{{r.rsi|money}}</td></tr><tr><td>Session VWAP</td><td>{{r.vwap|money}}</td></tr><tr><td>ADX estimate</td><td>{{r.adx|money}}</td></tr></table><p class="small">VWAP is unavailable if the index feed has no usable volume.</p></section>
<section class="card"><h2>Indicator checks</h2><table>{% for name,val,status in r.checks %}<tr><td>{{name}}</td><td class="{{status}}">{{val}}</td></tr>{% endfor %}</table></section></div>{% endif %}
<p class="foot">Auto-refreshes every 45 seconds; this does not create a new candle every refresh. Indicators may be wrong and data can be delayed. No option contracts, entry/exit levels, or order placement are provided.</p></main></body></html>'''

@app.route("/")
def home():
    result, error = None, None
    try:
        result = analyze(fetch_candles())
    except Exception as exc:
        log.exception("Dashboard analysis failed")
        error = str(exc)
    return render_template_string(HTML, r=result, error=error)

@app.route("/health")
def health():
    return jsonify({"ok":True,"timeframe":"3m","credentials_configured":bool(FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN),
        "order_placement":False,"mode":"educational_analysis_only","server_time_ist":now_ist().isoformat()})

if __name__ == "__main__":
    if app.secret_key == "change-this-secret":
        log.warning("FLASK_SECRET_KEY is not set; configure a unique secret.")
    app.run(host=os.getenv("HOST","0.0.0.0"), port=int(os.getenv("PORT","5000")), debug=False)
