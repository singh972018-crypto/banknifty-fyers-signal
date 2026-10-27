import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, render_template_string, request
from fyers_apiv3 import fyersModel

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("banknifty-study")

# Keep the existing Render environment-variable names unchanged.
CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "").strip()
SECRET = os.getenv("FYERS_SECRET", "").strip()
REDIRECT_URI = os.getenv(
    "FYERS_REDIRECT_URI",
    os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/") + "/callback",
).strip()
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
SYMBOL = os.getenv("FYERS_SYMBOL", "NSE:NIFTYBANK-INDEX").strip()
TIMEFRAME = "3"
HISTORY_DAYS = max(2, min(10, int(os.getenv("HISTORY_DAYS", "5"))))
IST = ZoneInfo("Asia/Kolkata")

PAGE = r"""
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="180"><title>BankNifty 3-Minute Study</title>
<style>
:root{color-scheme:dark}body{font-family:Arial,sans-serif;background:#101722;color:#e9eef7;margin:0;padding:18px}
main{max-width:1050px;margin:auto}.muted{color:#aab6c8}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.card{background:#1a2636;border:1px solid #2b3b50;border-radius:12px;padding:15px;margin:10px 0}
.big{font-size:1.5rem;font-weight:700}.ok{color:#8ee0ad}.warn{color:#ffd27a}.bad{color:#ff9c9c}
table{border-collapse:collapse;width:100%;font-size:.92rem}td,th{text-align:right;padding:8px;border-bottom:1px solid #2b3b50}td:first-child,th:first-child{text-align:left}
code{overflow-wrap:anywhere}
</style></head><body><main>
<h1>BankNifty — 3-minute market study</h1>
<p class="muted">Educational market-data dashboard only. It does not issue trade calls, choose options, or provide entry/stop-loss/target instructions.</p>
<div class="grid">
<section class="card"><div class="muted">Data status</div><div class="big {{ 'ok' if data_ok else 'bad' }}">{{ status }}</div><div class="muted">{{ updated }}</div></section>
<section class="card"><div class="muted">Latest close</div><div class="big">{{ close }}</div><div class="muted">Index points</div></section>
<section class="card"><div class="muted">EMA 9 / EMA 21</div><div class="big">{{ ema9 }} / {{ ema21 }}</div><div class="muted">Trend context only</div></section>
<section class="card"><div class="muted">RSI (14)</div><div class="big">{{ rsi }}</div><div class="muted">Momentum context</div></section>
<section class="card"><div class="muted">ATR (14)</div><div class="big">{{ atr }}</div><div class="muted">Recent range estimate</div></section>
<section class="card"><div class="muted">Session VWAP</div><div class="big">{{ vwap }}</div><div class="muted">From returned candles</div></section></div>
<section class="card"><h2>Data validation</h2><p>{{ note }}</p>
<p class="muted">Symbol: <code>{{ symbol }}</code> · Timeframe: 3 minutes · Candles received: {{ count }}</p>
{% if not token_present %}<p class="warn">FYERS_ACCESS_TOKEN is not available to this running process. Check the existing Render environment variable and redeploy.</p>{% endif %}</section>
<section class="card"><h2>Recent completed candles</h2>{% if candles %}
<table><thead><tr><th>Time (IST)</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr></thead><tbody>
{% for c in candles %}<tr><td>{{ c.time }}</td><td>{{ c.open }}</td><td>{{ c.high }}</td><td>{{ c.low }}</td><td>{{ c.close }}</td><td>{{ c.volume }}</td></tr>{% endfor %}
</tbody></table>{% else %}<p class="muted">No candle data available yet.</p>{% endif %}</section>
<p class="muted">Refreshes every 180 seconds. Market hours, API permissions, and token validity can affect results.</p>
</main></body></html>
"""

def make_client():
    if not CLIENT_ID:
        raise RuntimeError("FYERS_CLIENT_ID is missing in the running process.")
    if not ACCESS_TOKEN:
        raise RuntimeError("FYERS_ACCESS_TOKEN is missing in the running process.")
    return fyersModel.FyersModel(client_id=CLIENT_ID, token=ACCESS_TOKEN, is_async=False, log_path="")

def completed_window():
    now = datetime.now(IST).replace(second=0, microsecond=0)
    bucket_minute = (now.minute // 3) * 3
    end = now.replace(minute=bucket_minute) - timedelta(minutes=3)
    return end - timedelta(days=HISTORY_DAYS), end

def get_history():
    fy = make_client()
    start, end = completed_window()
    # Match the date-format style of the previously working 5-minute app.
    response = fy.history(data={
        "symbol": SYMBOL, "resolution": TIMEFRAME, "date_format": "1",
        "range_from": start.strftime("%Y-%m-%d"),
        "range_to": end.strftime("%Y-%m-%d"), "cont_flag": "1",
    })
    if not isinstance(response, dict):
        raise RuntimeError("FYERS history response was not a JSON object.")
    if response.get("s") != "ok":
        message = response.get("message") or response.get("code") or "Unknown FYERS API error"
        raise RuntimeError(f"FYERS history request failed: {message}")
    candles = []
    for row in response.get("candles") or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            ts = float(row[0])
            dt = datetime.fromtimestamp(ts, IST)
            candles.append({"timestamp": ts, "time": dt.strftime("%d-%b %H:%M"),
                "open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
                "close": float(row[4]), "volume": float(row[5])})
        except (TypeError, ValueError, OverflowError, OSError):
            continue
    candles.sort(key=lambda c: c["timestamp"])
    now_ts = datetime.now(IST).timestamp()
    candles = [c for c in candles if c["timestamp"] + 180 <= now_ts]
    if len(candles) < 25:
        raise RuntimeError(f"Only {len(candles)} completed candles returned; at least 25 are needed.")
    return candles

def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = alpha * item + (1 - alpha) * value
    return value

def rsi(values, period=14):
    if len(values) <= period:
        return None
    changes = [values[i] - values[i-1] for i in range(1, len(values))]
    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = ((period - 1) * avg_gain + gains[i]) / period
        avg_loss = ((period - 1) * avg_loss + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(candles, period=14):
    if len(candles) <= period:
        return None
    trs = []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i-1]
        trs.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]), abs(cur["low"] - prev["close"])))
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = ((period - 1) * value + tr) / period
    return value

def session_vwap(candles):
    today = datetime.now(IST).date()
    day = [c for c in candles if datetime.fromtimestamp(c["timestamp"], IST).date() == today]
    total_pv = total_vol = 0.0
    for c in day:
        typical = (c["high"] + c["low"] + c["close"]) / 3
        vol = max(c["volume"], 0)
        total_pv += typical * vol
        total_vol += vol
    return total_pv / total_vol if total_vol else None

def fmt(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"

def dashboard_data():
    result = {"data_ok": False, "status": "Not connected",
        "updated": datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S IST"),
        "close": "—", "ema9": "—", "ema21": "—", "rsi": "—", "atr": "—", "vwap": "—",
        "note": "Waiting for a successful FYERS history response.", "symbol": SYMBOL,
        "count": 0, "candles": [], "token_present": bool(ACCESS_TOKEN)}
    try:
        candles = get_history()
        closes = [c["close"] for c in candles]
        result.update({"data_ok": True, "status": "Connected", "close": fmt(closes[-1]),
            "ema9": fmt(ema(closes, 9)), "ema21": fmt(ema(closes, 21)), "rsi": fmt(rsi(closes)),
            "atr": fmt(atr(candles)), "vwap": fmt(session_vwap(candles)),
            "note": "History response validated. Indicators are descriptive, not trading instructions.",
            "count": len(candles), "candles": [{"time": c["time"], "open": fmt(c["open"]),
            "high": fmt(c["high"]), "low": fmt(c["low"]), "close": fmt(c["close"]),
            "volume": fmt(c["volume"], 0)} for c in candles[-30:][::-1]]})
    except Exception as exc:
        log.exception("Dashboard data fetch failed")
        result["status"] = "Data error"
        result["note"] = str(exc)[:300]
    return result

@app.get("/")
def home():
    return render_template_string(PAGE, **dashboard_data())

@app.get("/health")
def health():
    # Return presence flags only; never expose credentials.
    return jsonify({"ok": True, "client_id_present": bool(CLIENT_ID),
        "access_token_present": bool(ACCESS_TOKEN), "symbol": SYMBOL, "timeframe": TIMEFRAME})

@app.get("/login")
def login():
    if not CLIENT_ID or not SECRET or not REDIRECT_URI:
        return "FYERS_CLIENT_ID, FYERS_SECRET and redirect URI must be configured in Render.", 500
    session = fyersModel.SessionModel(client_id=CLIENT_ID, secret_key=SECRET,
        redirect_uri=REDIRECT_URI, response_type="code", grant_type="authorization_code")
    return redirect(session.generate_authcode())

@app.get("/callback")
def callback():
    auth_code = request.args.get("auth_code", "")
    if not auth_code:
        return "Missing auth_code in FYERS callback.", 400
    if not CLIENT_ID or not SECRET or not REDIRECT_URI:
        return "FYERS OAuth configuration is incomplete.", 500
    try:
        session = fyersModel.SessionModel(client_id=CLIENT_ID, secret_key=SECRET,
            redirect_uri=REDIRECT_URI, response_type="code", grant_type="authorization_code")
        session.set_token(auth_code)
        response = session.generate_token()
        token = response.get("access_token") if isinstance(response, dict) else None
        if not token:
            log.error("FYERS OAuth did not return an access token.")
            return "FYERS login did not return an access token. Check Render Logs.", 502
        global ACCESS_TOKEN
        ACCESS_TOKEN = token.strip()
        return ("FYERS login successful for this running process. A Render restart discards this token; "
                "to persist it, update FYERS_ACCESS_TOKEN in Render Environment and redeploy.")
    except Exception:
        log.exception("FYERS OAuth callback failed")
        return "FYERS login failed. Check Render Logs; secret values are not shown.", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
