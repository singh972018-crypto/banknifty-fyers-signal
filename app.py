"""
BankNifty 3-minute Study Dashboard
Educational market-data analysis only. Does not select option contracts,
provide trade entry/exit recommendations, or place orders.
"""
import os
import math
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, render_template_string, request

try:
    from fyers_apiv3 import fyersModel
except Exception:
    fyersModel = None

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("banknifty-study")

# Keep the existing Render/FYERS environment variable names.
CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "").strip()
SECRET = os.getenv("FYERS_SECRET", "").strip()
REDIRECT_URI = os.getenv(
    "FYERS_REDIRECT_URI",
    os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/") + "/callback"
).strip()
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "").strip()

INDEX_SYMBOL = "NSE:NIFTYBANK-INDEX"
TIMEFRAME = "3"
CANDLE_SECONDS = 180
HISTORY_DAYS = max(3, min(10, int(os.getenv("FYERS_HISTORY_DAYS", "5"))))
IST = ZoneInfo("Asia/Kolkata")


def now_ist():
    return datetime.now(IST)


def num(value, default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def fmt(value, digits=2):
    value = num(value)
    return "—" if value is None else f"{value:,.{digits}f}"


app.jinja_env.filters["fmt"] = fmt

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="45">
<title>BankNifty 3-Minute Study Dashboard</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0b1220;color:#edf3ff;font:15px/1.5 system-ui,Arial,sans-serif}
main{max-width:1050px;margin:auto;padding:18px}
header,.topline{display:flex;gap:12px;justify-content:space-between;align-items:center;flex-wrap:wrap}
h1{font-size:25px;margin:0}h2{font-size:18px;margin:0 0 12px}
.muted,.small,.label,.foot{color:#9fb0c8}
.small,.foot{font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:12px;margin:14px 0}
.card{background:#121c2e;border:1px solid #26354c;border-radius:14px;padding:16px;min-width:0}
.pill{border:1px solid #34445e;border-radius:24px;padding:6px 10px;display:inline-block}
a{color:#7dd3fc}
.signal{font-size:32px;font-weight:800}.CALL,.bull,.pass{color:#4ade80}.PUT,.bear,.fail{color:#fb7185}.WAIT,.warn{color:#fbbf24}.neutral{color:#9fb0c8}
.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.metric{background:#0d1727;padding:10px;border-radius:9px;min-width:0}
.value{font-size:17px;font-weight:700;overflow-wrap:anywhere}
table{width:100%;border-collapse:collapse}td,th{text-align:left;border-bottom:1px solid #26354c;padding:8px 4px;font-size:13px;overflow-wrap:anywhere}
.error{border-color:#7f1d1d;color:#fecaca}
.notice{background:#251f10;border-color:#66531d;color:#f6df9a}
button{background:#26354c;color:#fff;border:0;border-radius:9px;padding:10px 13px;font-size:14px}
@media(max-width:420px){main{padding:12px}h1{font-size:22px}.card{padding:13px}}
</style>
</head>
<body><main>
<header>
 <div><h1>BankNifty 3-Minute Study Dashboard</h1><div class="muted">Completed 3-minute candles · educational analysis only</div></div>
 <div><span class="pill">Timeframe: 3m</span> &nbsp; <a href="/">Refresh now</a></div>
</header>
<div class="card notice" style="margin-top:14px">For learning and observation only. A directional bias is not a prediction or a trading recommendation.</div>
{% if error %}<div class="card error" style="margin-top:14px"><h2>Data/API error</h2>{{error}}<p class="small">No analysis is shown when data is invalid or unavailable.</p></div>{% endif %}
{% if r %}
<div class="grid">
 <section class="card"><div class="label">Directional study bias</div><div class="signal {{r.bias}}">{{r.bias}}</div>
 <div class="muted">Bullish checks {{r.bull_score}}/4 · Bearish checks {{r.bear_score}}/4</div>
 <p class="small">Last completed candle: {{r.candle_time}}</p><p class="small">This is a descriptive indicator summary, not an options signal.</p></section>
 <section class="card"><h2>Index candle</h2><div class="metrics">
  <div class="metric"><div class="label">Close</div><div class="value">{{r.close|fmt}}</div></div>
  <div class="metric"><div class="label">Candle range</div><div class="value">{{r.candle_range|fmt}}</div></div>
  <div class="metric"><div class="label">ATR 14</div><div class="value">{{r.atr|fmt}}</div></div>
  <div class="metric"><div class="label">Volume</div><div class="value">{{r.volume|fmt(0)}}</div></div>
 </div></section>
</div>
<div class="grid">
 <section class="card"><h2>Indicator values</h2><table>
 <tr><td>EMA 9</td><td>{{r.ema9|fmt}}</td></tr><tr><td>EMA 21</td><td>{{r.ema21|fmt}}</td></tr>
 <tr><td>Session VWAP</td><td>{{r.vwap|fmt}}</td></tr><tr><td>RSI 14</td><td>{{r.rsi|fmt}}</td></tr>
 <tr><td>ADX estimate</td><td>{{r.adx|fmt}}</td></tr><tr><td>+DI / -DI estimates</td><td>{{r.pdi|fmt}} / {{r.mdi|fmt}}</td></tr>
 <tr><td>Average volume (20)</td><td>{{r.avg_volume|fmt(0)}}</td></tr><tr><td>Completed candles</td><td>{{r.candle_count}}</td></tr>
 </table></section>
 <section class="card"><h2>Condition checks</h2><table>
 {% for label, value, status in r.checks %}<tr><td>{{label}}</td><td class="{{status}}">{{value}}</td></tr>{% endfor %}
 </table><p class="small">ADX/DI values are lightweight estimates, not a broker-grade indicator implementation.</p></section>
</div>
{% endif %}
<div class="card"><h2>Connection</h2><p class="small">Credentials configured: {{ "Yes" if configured else "No" }}. Token value is never displayed.</p>
<a href="/login">Connect / refresh FYERS login</a> &nbsp; <a href="/health">Health check</a></div>
<p class="foot">Refreshes every 45 seconds; refresh does not create a new candle. The dashboard uses only completed candles. Data can be delayed or unavailable. It does not select option contracts, give trade levels, or place orders.</p>
</main></body></html>"""


def make_fyers():
    if fyersModel is None:
        raise RuntimeError("Missing fyers-apiv3 package. Check requirements.txt.")
    if not CLIENT_ID or not ACCESS_TOKEN:
        raise RuntimeError(
            "Set FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN in Render Environment."
        )
    return fyersModel.FyersModel(
        client_id=CLIENT_ID, token=ACCESS_TOKEN, is_async=False, log_path=""
    )


def api_error(data, fallback="FYERS request failed"):
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error") or data.get("code") or fallback)
    return fallback


def fetch_candles():
    fy = make_fyers()
    end = now_ist()
    start = end - timedelta(days=HISTORY_DAYS)
    response = fy.history({
        "symbol": INDEX_SYMBOL,
        "resolution": TIMEFRAME,
        "date_format": "1",
        "range_from": start.strftime("%Y-%m-%d"),
        "range_to": end.strftime("%Y-%m-%d"),
        "cont_flag": "1",
    })
    if not isinstance(response, dict) or response.get("s") != "ok":
        raise RuntimeError(api_error(response, "Could not fetch 3-minute history."))

    now_epoch = int(datetime.now(timezone.utc).timestamp())
    unique = {}
    for row in response.get("candles") or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            ts = int(row[0])
            # FYERS candle timestamps are treated as candle-open times.
            if ts + CANDLE_SECONDS > now_epoch:
                continue
            o, high, low, close, volume = [num(x) for x in row[1:6]]
            if any(x is None for x in (o, high, low, close, volume)):
                continue
            if close <= 0 or high < low or high < max(o, close) or low > min(o, close):
                continue
            unique[ts] = {
                "ts": ts, "open": o, "high": high, "low": low,
                "close": close, "volume": max(0.0, volume)
            }
        except (TypeError, ValueError, OverflowError):
            continue

    candles = sorted(unique.values(), key=lambda x: x["ts"])
    if len(candles) < 35:
        raise RuntimeError(
            f"Only {len(candles)} valid completed 3-minute candles returned; need at least 35."
        )
    return candles


def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None
    changes = [values[i] - values[i-1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr_series(candles, period=14):
    tr = []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i-1]
        tr.append(max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"])
        ))
    if len(tr) < period:
        return None
    # Wilder-style smoothing after initial average.
    value = sum(tr[:period]) / period
    series = [None] * (period - 1) + [value]
    for item in tr[period:]:
        value = (value * (period - 1) + item) / period
        series.append(value)
    return series[-1]


def adx_di_estimate(candles, period=14):
    if len(candles) < period + 2:
        return None, None, None
    trs, plus_dm, minus_dm = [], [], []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i-1]
        up = cur["high"] - prev["high"]
        down = prev["low"] - cur["low"]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(cur["high"] - cur["low"],
                       abs(cur["high"] - prev["close"]),
                       abs(cur["low"] - prev["close"])))

    dxs = []
    pdi = mdi = 0.0
    # Rolling estimate is intentionally labeled an estimate.
    start = max(0, len(trs) - (period * 2))
    for end in range(start + period - 1, len(trs)):
        tr_sum = sum(trs[end-period+1:end+1])
        if tr_sum <= 0:
            dxs.append(0.0)
            continue
        pdi = 100.0 * sum(plus_dm[end-period+1:end+1]) / tr_sum
        mdi = 100.0 * sum(minus_dm[end-period+1:end+1]) / tr_sum
        dxs.append(100.0 * abs(pdi-mdi) / (pdi+mdi) if pdi+mdi else 0.0)
    if not dxs:
        return None, None, None
    return sum(dxs[-period:]) / len(dxs[-period:]), pdi, mdi


def session_vwap(candles):
    latest_day = datetime.fromtimestamp(
        candles[-1]["ts"], timezone.utc
    ).astimezone(IST).date()
    selected = [
        c for c in candles
        if datetime.fromtimestamp(c["ts"], timezone.utc).astimezone(IST).date() == latest_day
    ]
    pv = sum(((c["high"] + c["low"] + c["close"]) / 3.0) * c["volume"] for c in selected)
    volume = sum(c["volume"] for c in selected)
    return pv / volume if volume > 0 else None


def analyze(candles):
    closes = [c["close"] for c in candles]
    last = candles[-1]
    e9, e21 = ema(closes, 9), ema(closes, 21)
    r = rsi(closes)
    a = atr_series(candles)
    adx, pdi, mdi = adx_di_estimate(candles)
    vwap = session_vwap(candles)
    if any(x is None for x in (e9, e21, r, a, adx, pdi, mdi, vwap)):
        raise RuntimeError("Indicator data incomplete; wait for more valid candles.")

    volumes = [c["volume"] for c in candles]
    avg_volume = sum(volumes[-21:-1]) / min(20, len(volumes[-21:-1])) if len(volumes) > 1 else 0.0
    candle_range = last["high"] - last["low"]
    body = abs(last["close"] - last["open"])
    bull_candle = last["close"] > last["open"] and candle_range > 0 and body >= candle_range * 0.35
    bear_candle = last["close"] < last["open"] and candle_range > 0 and body >= candle_range * 0.35
    volume_ok = avg_volume > 0 and last["volume"] > avg_volume
    trend_up, trend_down = e9 > e21, e9 < e21
    above_vwap, below_vwap = last["close"] > vwap, last["close"] < vwap
    rsi_bull, rsi_bear = 52 <= r <= 68, 32 <= r <= 48

    bull_checks = [trend_up, above_vwap, rsi_bull, volume_ok]
    bear_checks = [trend_down, below_vwap, rsi_bear, volume_ok]
    bull_score, bear_score = sum(bull_checks), sum(bear_checks)
    if bull_score >= 3 and bull_score > bear_score:
        bias = "BULLISH BIAS"
    elif bear_score >= 3 and bear_score > bull_score:
        bias = "BEARISH BIAS"
    else:
        bias = "MIXED / WAIT"

    candle_status = "Bullish body" if bull_candle else "Bearish body" if bear_candle else "Small/neutral body"
    checks = [
        ("EMA 9 vs EMA 21", "Fast EMA above slow" if trend_up else "Fast EMA below slow" if trend_down else "EMAs equal", "bull" if trend_up else "bear" if trend_down else "neutral"),
        ("Close vs session VWAP", "Above VWAP" if above_vwap else "Below VWAP" if below_vwap else "At VWAP", "bull" if above_vwap else "bear" if below_vwap else "neutral"),
        ("RSI 14", f"{r:.1f} — bullish zone" if rsi_bull else f"{r:.1f} — bearish zone" if rsi_bear else f"{r:.1f} — neutral/extended", "bull" if rsi_bull else "bear" if rsi_bear else "neutral"),
        ("Volume vs prior 20", "Above average" if volume_ok else "Not above average", "pass" if volume_ok else "neutral"),
        ("ADX / DI estimate", f"ADX {adx:.1f}; +DI {'>' if pdi > mdi else '<='} -DI", "bull" if adx >= 20 and pdi > mdi else "bear" if adx >= 20 and mdi > pdi else "neutral"),
        ("Latest candle body", candle_status, "bull" if bull_candle else "bear" if bear_candle else "neutral"),
        ("ATR volatility", f"ATR {a:.2f}; range {candle_range:.2f}", "neutral"),
    ]
    stamp = datetime.fromtimestamp(last["ts"], timezone.utc).astimezone(IST)
    return {
        "bias": bias, "bull_score": bull_score, "bear_score": bear_score,
        "close": last["close"], "ema9": e9, "ema21": e21, "vwap": vwap,
        "rsi": r, "volume": last["volume"], "avg_volume": avg_volume,
        "adx": adx, "pdi": pdi, "mdi": mdi, "atr": a,
        "candle_range": candle_range, "candle_count": len(candles),
        "candle_time": stamp.strftime("%d-%b-%Y %I:%M:%S %p IST"),
        "checks": checks,
    }


@app.route("/")
def home():
    result = None
    error = None
    if not CLIENT_ID or not ACCESS_TOKEN:
        error = "Set FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN in Render Environment."
    else:
        try:
            result = analyze(fetch_candles())
        except Exception as exc:
            log.exception("Dashboard data/analysis failed")
            error = str(exc)
    return render_template_string(
        PAGE, r=result, error=error,
        configured=bool(CLIENT_ID and ACCESS_TOKEN)
    )


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "timeframe": "3m",
        "credentials_configured": bool(CLIENT_ID and ACCESS_TOKEN),
        "server_time_ist": now_ist().isoformat(),
        "order_placement": False,
    })


@app.route("/login")
def login():
    if fyersModel is None:
        return "Missing fyers-apiv3 package; check requirements.txt.", 500
    if not CLIENT_ID or not SECRET:
        return "FYERS_CLIENT_ID or FYERS_SECRET is missing in Render Environment.", 500
    if not REDIRECT_URI:
        return "FYERS_REDIRECT_URI is missing. Set it to your Render URL + /callback.", 500
    try:
        session = fyersModel.SessionModel(
            client_id=CLIENT_ID, secret_key=SECRET, redirect_uri=REDIRECT_URI,
            response_type="code", grant_type="authorization_code"
        )
        return redirect(session.generate_authcode())
    except Exception:
        log.exception("Could not start FYERS login")
        return "Could not start FYERS login. Check Render logs and OAuth settings.", 500


@app.route("/callback")
def callback():
    global ACCESS_TOKEN
    code = request.args.get("auth_code") or request.args.get("code")
    if not code:
        return "Missing auth_code/code in callback URL.", 400
    if fyersModel is None:
        return "Missing fyers-apiv3 package.", 500
    if not CLIENT_ID or not SECRET or not REDIRECT_URI:
        return "FYERS OAuth environment variables are not configured correctly.", 500
    try:
        session = fyersModel.SessionModel(
            client_id=CLIENT_ID, secret_key=SECRET, redirect_uri=REDIRECT_URI,
            response_type="code", grant_type="authorization_code"
        )
        session.set_token(code)
        response = session.generate_token()
        token = response.get("access_token", "") if isinstance(response, dict) else ""
        if not token:
            log.warning("FYERS token generation failed: %s", api_error(response, "No token returned"))
            return "FYERS login failed. Check OAuth settings and Render logs; token was not displayed.", 400
        ACCESS_TOKEN = token
        log.info("FYERS authentication succeeded. Update FYERS_ACCESS_TOKEN in Render Environment to persist across restarts.")
        return (
            "FYERS authentication succeeded. To keep it after a Render restart, "
            "update FYERS_ACCESS_TOKEN in Render Environment and redeploy/restart."
        ), 200
    except Exception:
        log.exception("FYERS callback failed")
        return "FYERS callback failed. Check Render logs; secrets are not displayed.", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")), debug=False)
