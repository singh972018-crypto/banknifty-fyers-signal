import os
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, redirect, render_template_string
from fyers_apiv3 import fyersModel

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("banknifty-study")

CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "")
SECRET = os.getenv("FYERS_SECRET", "")
REDIRECT_URI = os.getenv(
    "FYERS_REDIRECT_URI",
    os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/") + "/callback"
)
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "")
IST = ZoneInfo("Asia/Kolkata")
SYMBOL = "NSE:NIFTYBANK-INDEX"

PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="180">
<title>BankNifty 3M Market Study</title>
<style>
*{box-sizing:border-box}
body{font-family:Arial,sans-serif;background:#111;color:#eee;padding:16px;margin:0}
h2{margin:8px 0 16px}
.card{background:#1d1d1d;padding:18px;border-radius:15px;margin-bottom:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.sig{font-size:30px;font-weight:bold;margin:12px 0}
.bull{color:#35d07f}.bear{color:#ff6878}.neutral{color:#bbb}
.row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid #333}
.row span{color:#aaa}
.pass{color:#35d07f;font-weight:bold}.fail{color:#ff6878;font-weight:bold}
.small{color:#aaa;font-size:13px;line-height:1.5}
a{display:inline-block;color:white;background:#333;padding:12px 16px;border-radius:10px;text-decoration:none}
.warn{border-left:4px solid #d5a64a}
</style>
</head>
<body>
<h2>BankNifty 3M Market Study</h2>
<div class="card">
<b>Auto-refresh: ON</b>
<p class="small">Refreshes every 3 minutes. Analysis uses completed 3-minute candles only.</p>
<div class="row"><span>Data status</span><b>{{ data_status }}</b></div>
<div class="row"><span>Last completed candle (IST)</span><b>{{ candle_time }}</b></div>
<div class="row"><span>BankNifty spot</span><b>{{ spot }}</b></div>
</div>

<div class="grid">
<div class="card">
<h3>🟢 A — Trend study</h3>
<div class="sig {{trend_cls}}">{{trend}}</div>
<p class="small">{{trend_note}}</p>
<div class="row"><span>EMA 9 / EMA 21</span><b>{{ema9}} / {{ema21}}</b></div>
</div>
<div class="card">
<h3>🔵 B — Momentum study</h3>
<div class="sig {{momentum_cls}}">{{momentum}}</div>
<p class="small">{{momentum_note}}</p>
<div class="row"><span>RSI (Wilder 14)</span><b>{{rsi}}</b></div>
<div class="row"><span>Price vs session VWAP</span><b>{{vwap_state}}</b></div>
</div>
<div class="card">
<h3>🟣 C — Volatility study</h3>
<div class="sig {{vol_cls}}">{{volatility}}</div>
<p class="small">{{vol_note}}</p>
<div class="row"><span>ATR 14</span><b>{{atr}}</b></div>
<div class="row"><span>ADX 14</span><b>{{adx}}</b></div>
</div>
</div>

<div class="card">
<h3>📊 Indicator conditions</h3>
<div class="row"><span>EMA trend</span><b class="{{ema_cls}}">{{ema_state}}</b></div>
<div class="row"><span>VWAP position</span><b class="{{vwap_cls}}">{{vwap_state}}</b></div>
<div class="row"><span>RSI momentum</span><b class="{{rsi_cls}}">{{rsi_state}}</b></div>
<div class="row"><span>Volume vs previous 20 candles</span><b class="{{volume_cls}}">{{volume_state}}</b></div>
<div class="row"><span>ADX trend strength</span><b>{{adx_state}}</b></div>
<div class="row"><span>Latest candle</span><b class="{{candle_cls}}">{{candle_state}}</b></div>
</div>

<div class="card">
<h3>📈 Indicator data</h3>
<div class="row"><span>Close</span><b>{{spot}}</b></div>
<div class="row"><span>EMA 9</span><b>{{ema9}}</b></div>
<div class="row"><span>EMA 21</span><b>{{ema21}}</b></div>
<div class="row"><span>Session VWAP</span><b>{{vwap}}</b></div>
<div class="row"><span>RSI 14</span><b>{{rsi}}</b></div>
<div class="row"><span>Current volume</span><b>{{volume}}</b></div>
<div class="row"><span>Average volume (previous 20)</span><b>{{avg_volume}}</b></div>
<div class="row"><span>ADX 14</span><b>{{adx}}</b></div>
<div class="row"><span>ATR 14</span><b>{{atr}}</b></div>
<div class="row"><span>Candle range</span><b>{{candle_range}}</b></div>
</div>

<div class="card warn">
<b>Educational market analysis only</b>
<p class="small">This dashboard describes index trend, momentum and volatility. It does not select option contracts, provide buy/sell instructions, or place orders. Indicator readings can be wrong and are not predictions.</p>
</div>
<a href="/login">Connect FYERS</a>
</body></html>
"""

def ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    value = float(values[0])
    for item in values[1:]:
        value = float(item) * k + value * (1.0 - k)
    return value

def wilder_rsi(closes, period=14):
    if len(closes) <= period:
        return None
    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def wilder_adx(highs, lows, closes, period=14):
    if len(closes) < period * 2 + 1:
        return None, None, None
    trs, plus_dm, minus_dm = [], [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i-1]),
                       abs(lows[i] - closes[i-1])))
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)

    tr_s = sum(trs[:period])
    plus_s = sum(plus_dm[:period])
    minus_s = sum(minus_dm[:period])
    dx_values = []

    for i in range(period, len(trs)):
        tr_s = tr_s - (tr_s / period) + trs[i]
        plus_s = plus_s - (plus_s / period) + plus_dm[i]
        minus_s = minus_s - (minus_s / period) + minus_dm[i]
        pdi = 100.0 * plus_s / tr_s if tr_s else 0.0
        mdi = 100.0 * minus_s / tr_s if tr_s else 0.0
        denom = pdi + mdi
        dx_values.append(100.0 * abs(pdi - mdi) / denom if denom else 0.0)

    if len(dx_values) < period:
        return None, None, None
    adx = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx = (adx * (period - 1) + dx) / period
    pdi = 100.0 * plus_s / tr_s if tr_s else 0.0
    mdi = 100.0 * minus_s / tr_s if tr_s else 0.0
    return adx, pdi, mdi

def prepare_completed_candles(raw_candles, now=None):
    now = now or datetime.now(timezone.utc)
    completed = []
    for candle in raw_candles:
        if len(candle) < 6:
            continue
        try:
            stamp = datetime.fromtimestamp(float(candle[0]), timezone.utc)
            # FYERS 3-minute candle timestamp denotes candle start.
            if stamp + timedelta(minutes=3) <= now:
                completed.append((stamp, [float(x) for x in candle[1:6]]))
        except (TypeError, ValueError, OverflowError):
            continue
    completed.sort(key=lambda item: item[0])
    return completed

def calculate_study(candles):
    if len(candles) < 60:
        raise ValueError("Not enough completed 3-minute candles (need at least 60).")

    stamps = [x[0] for x in candles]
    opens = [x[1][0] for x in candles]
    highs = [x[1][1] for x in candles]
    lows = [x[1][2] for x in candles]
    closes = [x[1][3] for x in candles]
    volumes = [x[1][4] for x in candles]

    # Restrict VWAP to the latest IST calendar trading session.
    session_date = stamps[-1].astimezone(IST).date()
    session_indices = [i for i, stamp in enumerate(stamps)
                       if stamp.astimezone(IST).date() == session_date]
    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in session_indices]
    session_volumes = [volumes[i] for i in session_indices]
    total_volume = sum(session_volumes)
    vwap = (sum(p * v for p, v in zip(typical, session_volumes)) / total_volume
            if total_volume else closes[-1])

    e9 = ema(closes[-60:], 9)
    e21 = ema(closes[-60:], 21)
    rsi = wilder_rsi(closes, 14)
    adx, pdi, mdi = wilder_adx(highs, lows, closes, 14)

    tr_values = []
    for i in range(1, len(closes)):
        tr_values.append(max(highs[i] - lows[i],
                             abs(highs[i] - closes[i-1]),
                             abs(lows[i] - closes[i-1])))
    atr = None
    if len(tr_values) >= 14:
        atr = sum(tr_values[:14]) / 14.0
        for tr in tr_values[14:]:
            atr = (atr * 13.0 + tr) / 14.0

    current_volume = volumes[-1]
    previous = volumes[-21:-1]
    avg_volume = sum(previous) / len(previous) if previous else 0.0
    candle_range = highs[-1] - lows[-1]
    candle_body = closes[-1] - opens[-1]

    ema_state = "Bullish" if e9 > e21 else "Bearish" if e9 < e21 else "Flat"
    vwap_state = "Above VWAP" if closes[-1] > vwap else "Below VWAP" if closes[-1] < vwap else "At VWAP"
    rsi_state = "Positive momentum" if rsi is not None and rsi >= 55 else (
        "Negative momentum" if rsi is not None and rsi <= 45 else "Neutral momentum")
    volume_state = "Above average" if current_volume > avg_volume else "At/below average"
    candle_state = "Bull candle" if candle_body > 0 else "Bear candle" if candle_body < 0 else "Doji/flat"

    bullish_votes = sum([e9 > e21, closes[-1] > vwap, rsi is not None and rsi >= 55])
    bearish_votes = sum([e9 < e21, closes[-1] < vwap, rsi is not None and rsi <= 45])

    # Descriptive market state only: disagreement is explicitly neutral.
    if bullish_votes >= 2 and bearish_votes == 0:
        trend, trend_cls = "Bullish structure", "bull"
        trend_note = "At least two trend/momentum measures lean positive; not a trade instruction."
    elif bearish_votes >= 2 and bullish_votes == 0:
        trend, trend_cls = "Bearish structure", "bear"
        trend_note = "At least two trend/momentum measures lean negative; not a trade instruction."
    else:
        trend, trend_cls = "Mixed / neutral", "neutral"
        trend_note = "Indicators disagree or lack confirmation; direction is unclear."

    if rsi is not None and rsi >= 55:
        momentum, momentum_cls = "Positive", "bull"
        momentum_note = "RSI is in the positive-momentum zone."
    elif rsi is not None and rsi <= 45:
        momentum, momentum_cls = "Negative", "bear"
        momentum_note = "RSI is in the negative-momentum zone."
    else:
        momentum, momentum_cls = "Neutral", "neutral"
        momentum_note = "RSI is between the positive and negative zones."

    if adx is not None and atr is not None and adx >= 20:
        volatility, vol_cls = "Trend strength elevated", "neutral"
        vol_note = "ADX indicates trend strength, not trend direction."
    else:
        volatility, vol_cls = "No strong trend reading", "neutral"
        vol_note = "ADX is below 20 or not yet available."

    return {
        "stamp": stamps[-1].astimezone(IST).strftime("%d-%m-%Y %H:%M:%S"),
        "spot": closes[-1], "ema9": e9, "ema21": e21, "vwap": vwap,
        "rsi": rsi, "volume": current_volume, "avg_volume": avg_volume,
        "adx": adx, "atr": atr, "candle_range": candle_range,
        "ema_state": ema_state, "vwap_state": vwap_state,
        "rsi_state": rsi_state, "volume_state": volume_state,
        "adx_state": ("Trend strength elevated" if adx is not None and adx >= 20
                      else "Weak / unavailable"),
        "candle_state": candle_state,
        "trend": trend, "trend_cls": trend_cls, "trend_note": trend_note,
        "momentum": momentum, "momentum_cls": momentum_cls,
        "momentum_note": momentum_note,
        "volatility": volatility, "vol_cls": vol_cls, "vol_note": vol_note,
        "ema_cls": "pass" if e9 > e21 else "fail" if e9 < e21 else "neutral",
        "vwap_cls": "pass" if closes[-1] > vwap else "fail" if closes[-1] < vwap else "neutral",
        "rsi_cls": "pass" if rsi is not None and rsi >= 55 else "fail" if rsi is not None and rsi <= 45 else "neutral",
        "volume_cls": "pass" if current_volume > avg_volume else "neutral",
        "candle_cls": "pass" if candle_body > 0 else "fail" if candle_body < 0 else "neutral",
    }

def blank_context(status="Waiting for FYERS connection"):
    return dict(
        data_status=status, candle_time="—", spot="—",
        trend="Unavailable", trend_cls="neutral", trend_note="Connect FYERS to load data.",
        momentum="Unavailable", momentum_cls="neutral", momentum_note="—",
        volatility="Unavailable", vol_cls="neutral", vol_note="—",
        ema9="—", ema21="—", vwap="—", rsi="—", volume="—",
        avg_volume="—", adx="—", atr="—", candle_range="—",
        ema_state="—", vwap_state="—", rsi_state="—", volume_state="—",
        adx_state="—", candle_state="—", ema_cls="neutral",
        vwap_cls="neutral", rsi_cls="neutral", volume_cls="neutral",
        candle_cls="neutral"
    )

@app.route("/")
def home():
    context = blank_context()
    if not ACCESS_TOKEN:
        return render_template_string(PAGE, **context)
    try:
        fy = fyersModel.FyersModel(
            client_id=CLIENT_ID, token=ACCESS_TOKEN,
            is_async=False, log_path=""
        )
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=7)
        response = fy.history({
            "symbol": SYMBOL, "resolution": "3", "date_format": "1",
            "range_from": start.strftime("%Y-%m-%d"),
            "range_to": now.strftime("%Y-%m-%d"), "cont_flag": "1"
        })
        if not isinstance(response, dict) or response.get("s") == "error":
            raise RuntimeError("FYERS history error: " + str(response))
        raw = response.get("candles", [])
        completed = prepare_completed_candles(raw, now)
        result = calculate_study(completed)
        context = blank_context("Connected — completed candles loaded")
        context.update({
            "candle_time": result["stamp"], "spot": f'{result["spot"]:.2f}',
            "trend": result["trend"], "trend_cls": result["trend_cls"],
            "trend_note": result["trend_note"],
            "momentum": result["momentum"], "momentum_cls": result["momentum_cls"],
            "momentum_note": result["momentum_note"],
            "volatility": result["volatility"], "vol_cls": result["vol_cls"],
            "vol_note": result["vol_note"],
            "ema9": f'{result["ema9"]:.2f}', "ema21": f'{result["ema21"]:.2f}',
            "vwap": f'{result["vwap"]:.2f}',
            "rsi": f'{result["rsi"]:.2f}' if result["rsi"] is not None else "—",
            "volume": f'{result["volume"]:.0f}',
            "avg_volume": f'{result["avg_volume"]:.0f}',
            "adx": f'{result["adx"]:.1f}' if result["adx"] is not None else "—",
            "atr": f'{result["atr"]:.2f}' if result["atr"] is not None else "—",
            "candle_range": f'{result["candle_range"]:.2f}',
            "ema_state": result["ema_state"], "vwap_state": result["vwap_state"],
            "rsi_state": result["rsi_state"], "volume_state": result["volume_state"],
            "adx_state": result["adx_state"], "candle_state": result["candle_state"],
            "ema_cls": result["ema_cls"], "vwap_cls": result["vwap_cls"],
            "rsi_cls": result["rsi_cls"], "volume_cls": result["volume_cls"],
            "candle_cls": result["candle_cls"]
        })
    except Exception:
        log.exception("Dashboard calculation/data error")
        context = blank_context("Data/calculation error — check Render logs")
    return render_template_string(PAGE, **context)

@app.route("/login")
def login():
    if not CLIENT_ID or not SECRET:
        return "FYERS_CLIENT_ID / FYERS_SECRET is missing in Render Environment Variables.", 500
    if not REDIRECT_URI or REDIRECT_URI.endswith("/callback") is False:
        return "Set FYERS_REDIRECT_URI to your Render URL ending in /callback.", 500
    session = fyersModel.SessionModel(
        client_id=CLIENT_ID, secret_key=SECRET, redirect_uri=REDIRECT_URI,
        response_type="code", grant_type="authorization_code"
    )
    return redirect(session.generate_authcode())

@app.route("/callback")
def callback():
    global ACCESS_TOKEN
    code = request.args.get("auth_code")
    if not code:
        return "Missing auth_code from FYERS.", 400
    try:
        session = fyersModel.SessionModel(
            client_id=CLIENT_ID, secret_key=SECRET, redirect_uri=REDIRECT_URI,
            response_type="code", grant_type="authorization_code"
        )
        session.set_token(code)
        result = session.generate_token()
        token = result.get("access_token", "")
        if not token:
            return "<h3>FYERS login failed</h3><pre>" + str(result) + "</pre>", 400
        ACCESS_TOKEN = token
        log.info("FYERS authorization completed. Token retained in process memory.")
        return redirect("/")
    except Exception:
        log.exception("FYERS OAuth callback failed")
        return "FYERS login failed. Check Render logs.", 500

@app.get("/health")
def health():
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
