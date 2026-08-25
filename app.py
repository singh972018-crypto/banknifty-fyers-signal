import os
from datetime import datetime, timedelta, timezone
from flask import Flask, request, redirect, render_template_string
import requests
import json
import gspread
from google.oauth2.service_account import Credentials
from fyers_apiv3 import fyersModel

app = Flask(__name__)
CLIENT_ID=os.getenv("FYERS_CLIENT_ID","")
SECRET=os.getenv("FYERS_SECRET","")
REDIRECT_URI=os.getenv(
    "FYERS_REDIRECT_URI",
    os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/") + "/callback"
)
ACCESS_TOKEN=os.getenv("FYERS_ACCESS_TOKEN","")
MIN_PREMIUM=float(os.getenv("MIN_PREMIUM","30"))
MAX_PREMIUM=float(os.getenv("MAX_PREMIUM","65"))
LOT_SIZE=int(os.getenv("BANKNIFTY_LOT_SIZE","30"))
GOOGLE_SHEET_ID=os.getenv("GOOGLE_SHEET_ID","")
GOOGLE_SERVICE_ACCOUNT_JSON=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON","")


PAGE="""<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<style>
body{font-family:Arial;background:#111;color:#eee;padding:18px}
.card{background:#1d1d1d;padding:20px;border-radius:16px;margin-bottom:12px}
.sig{font-size:44px;font-weight:bold}.call{color:#35d07f}.put{color:#ff5c6c}.wait{color:#bbb}
.row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #333}
.small{color:#aaa;font-size:13px}a{color:white;background:#333;padding:12px;border-radius:10px;text-decoration:none}
</style>
<h2>BankNifty 5M Signal</h2>
<div class="card"><b>🔄 Auto-refresh: ON</b><br>
<span class="small">Page refreshes every 5 minutes to fetch the latest signal.</span></div>
<div class="card">
<div class="sig {{cls}}">{{signal}}</div>
<p>Score: {{score}}/5</p>
<p>BankNifty spot: <b>{{spot}}</b></p>
<div class="row"><span>Option</span><b>{{contract}}</b></div>
<div class="row"><span>Entry</span><b>₹{{entry}}</b></div>
<div class="row"><span>Stop Loss</span><b>₹{{sl}}</b></div>
<div class="row"><span>Target 1</span><b>₹{{t1}}</b></div>
<div class="row"><span>Target 2</span><b>₹{{t2}}</b></div>
<div class="row"><span>Exit</span><b>{{exit_rule}}</b></div>
<p>{{note}}</p>
<p class="small">Levels are estimates from the current option premium and 5-minute signal; not guaranteed execution prices.</p>
</div>
<br><a href="/login">Connect FYERS</a>"""


def calc(c):
    close=[float(x[4]) for x in c]
    high=[float(x[2]) for x in c]; low=[float(x[3]) for x in c]; vol=[float(x[5]) for x in c]
    def ema(a,n):
        k=2/(n+1); e=a[0]
        for x in a[1:]: e=x*k+e*(1-k)
        return e
    e9=ema(close[-50:],9); e21=ema(close[-50:],21)
    vwap=sum(((h+l+x)/3)*v for h,l,x,v in zip(high,low,close,vol))/(sum(vol) or 1)
    d=[close[i]-close[i-1] for i in range(1,len(close))]
    g=sum(max(x,0) for x in d[-14:])/14; l=sum(max(-x,0) for x in d[-14:])/14
    rsi=100 if l==0 else 100-100/(1+g/l)
    score=(close[-1]>e9)+(e9>e21)+(close[-1]>vwap)+(rsi>=55)
    score-=((close[-1]<e9)+(e9<e21)+(close[-1]<vwap)+(rsi<=45))
    if score>=3: sig="CALL"
    elif score<=-3: sig="PUT"
    else: sig="WAIT"
    return sig,score,close[-1]

def pick_budget_option(spot, signal):
    headers={"Authorization":f"{CLIENT_ID}:{ACCESS_TOKEN}"}
    params={"symbol":"NSE:NIFTYBANK-INDEX","strikecount":25,"greeks":"1"}
    r=requests.get("https://api-t1.fyers.in/data/options-chain-v3",headers=headers,params=params,timeout=12)
    r.raise_for_status(); data=r.json().get("data",{}); chain=data.get("optionsChain",[])
    typ="CE" if signal=="CALL" else "PE"
    legs=[x for x in chain if x.get("option_type")==typ and float(x.get("ltp",0) or 0)>0]
    in_range=[x for x in legs if MIN_PREMIUM<=float(x["ltp"])<=MAX_PREMIUM]
    candidates=in_range or legs
    if not candidates: return None
    if in_range:
        chosen=min(in_range,key=lambda x:(abs(float(x["strike_price"])-spot),-float(x.get("volume",0))))
    else:
        mid=(MIN_PREMIUM+MAX_PREMIUM)/2
        chosen=min(legs,key=lambda x:(abs(float(x["ltp"])-mid),abs(float(x["strike_price"])-spot)))
    premium=float(chosen["ltp"]); cost=premium*LOT_SIZE
    return {"symbol":chosen.get("symbol","—"),"premium":round(premium,2),"cost":round(cost,2),"lot":LOT_SIZE,"within":bool(in_range)}


JOURNAL_HEADERS = [
    "timestamp_utc","signal","score","banknifty_spot","option_symbol",
    "entry","stop_loss","target_1","target_2","exit_rule",
    "status","exit_price","pnl_per_lot","notes"
]

def get_journal_sheet():
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.sheet1
    if not ws.get_all_values():
        ws.append_row(JOURNAL_HEADERS, value_input_option="USER_ENTERED")
    return ws

def journal_signal(signal, score, spot, contract, entry, sl, t1, t2, exit_rule, note):
    if not contract or contract == "—" or entry in ("—", None):
        return
    try:
        ws = get_journal_sheet()
        if ws is None:
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        values = ws.get_all_values()
        # Refreshing the page must not create duplicate rows for the same
        # signal/contract in the same 5-minute candle.
        if len(values) > 1:
            last = values[-1]
            if len(last) >= 5:
                try:
                    last_dt = datetime.strptime(last[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    cur_dt = datetime.strptime(now, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    same_bucket = (int(last_dt.timestamp()) // 300) == (int(cur_dt.timestamp()) // 300)
                except Exception:
                    same_bucket = False
                if same_bucket and last[1] == signal and last[4] == contract:
                    return

        ws.append_row([
            now, signal, score, round(float(spot), 2), contract,
            float(entry), float(sl), float(t1), float(t2), exit_rule,
            "OPEN", "", "", note
        ], value_input_option="USER_ENTERED")
    except Exception as e:
        # Journal failure never breaks the signal page.
        print("Google Sheet journal error:", e)

def make_levels(entry, signal):
    """Conservative option-premium risk levels.

    Uses a 15% stop and 25% / 40% profit targets. The levels are guidance
    only; the user should exit if the signal reverses before targets.
    """
    entry = float(entry)
    sl = round(entry * 0.85, 2)
    t1 = round(entry * 1.25, 2)
    t2 = round(entry * 1.40, 2)
    return sl, t1, t2


@app.route("/")
def home():
    if not ACCESS_TOKEN:
        return render_template_string(
            PAGE, signal="WAIT", cls="wait", score=0, spot="—",
            contract="—", entry="—", sl="—", t1="—", t2="—",
            exit_rule="Connect FYERS", note="FYERS is not connected."
        )

    try:
        fy=fyersModel.FyersModel(
            client_id=CLIENT_ID, token=ACCESS_TOKEN,
            is_async=False, log_path=""
        )
        now=datetime.now(timezone.utc)
        start=now-timedelta(days=5)

        r=fy.history({
            "symbol":"NSE:NIFTYBANK-INDEX",
            "resolution":"5",
            "date_format":"1",
            "range_from":start.strftime("%Y-%m-%d"),
            "range_to":now.strftime("%Y-%m-%d"),
            "cont_flag":"1"
        })

        candles=r.get("candles", [])
        if len(candles) < 50:
            raise ValueError("Not enough 5-minute candles returned by FYERS.")

        sig,score,spot=calc(candles)

        contract = "—"
        entry = sl = t1 = t2 = "—"
        exit_rule = "WAIT / no trade"
        note = "Technical signal only; not a guaranteed trade."

        if sig in ("CALL","PUT"):
            try:
                selected = pick_budget_option(spot, sig)
                if selected:
                    contract = selected["symbol"]
                    entry = round(float(selected["premium"]), 2)
                    sl, t1, t2 = make_levels(entry, sig)
                    exit_rule = f"Exit at T1/T2 or immediately if signal reverses to {('PUT' if sig=='CALL' else 'CALL')}."
                    if selected.get("within_budget"):
                        note += f" Budget premium target: ₹{MIN_PREMIUM:.0f}–₹{MAX_PREMIUM:.0f}."
                    else:
                        note += " No contract was inside the preferred premium range."
                else:
                    note += " No suitable option contract was returned."
            except Exception as oe:
                note += " Option-chain lookup failed: " + str(oe)

        journal_signal(
            sig, abs(score), spot, contract, entry, sl, t1, t2,
            exit_rule, note
        )

        return render_template_string(
            PAGE, signal=sig, cls=sig.lower(), score=abs(score),
            spot=round(spot,2), contract=contract, entry=entry,
            sl=sl, t1=t1, t2=t2, exit_rule=exit_rule, note=note
        )

    except Exception as e:
        return render_template_string(
            PAGE, signal="WAIT", cls="wait", score=0, spot="—",
            contract="—", entry="—", sl="—", t1="—", t2="—",
            exit_rule="No trade", note="Data error: "+str(e)
        )

@app.route("/login")
def login():
    if not CLIENT_ID or not SECRET:
        return "FYERS_CLIENT_ID / FYERS_SECRET is missing in Render Environment Variables.", 500
    if not REDIRECT_URI:
        return "FYERS_REDIRECT_URI is missing. Set it to your Render URL + /callback.", 500

    s=fyersModel.SessionModel(
        client_id=CLIENT_ID,
        secret_key=SECRET,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code"
    )
    return redirect(s.generate_authcode())

@app.route("/callback")
def callback():
    global ACCESS_TOKEN
    code=request.args.get("auth_code")
    if not code:
        return "Missing auth_code. FYERS did not return an authorization code.", 400

    if not CLIENT_ID or not SECRET or not REDIRECT_URI:
        return "FYERS OAuth environment variables are not configured correctly in Render.", 500

    try:
        s=fyersModel.SessionModel(
            client_id=CLIENT_ID,
            secret_key=SECRET,
            redirect_uri=REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code"
        )
        s.set_token(code)
        r=s.generate_token()
        token=r.get("access_token","")
        if not token:
            return "<h3>FYERS login failed</h3><pre>"+str(r)+"</pre>", 400

        ACCESS_TOKEN=token
        return redirect("/")
    except Exception as e:
        return "<h3>FYERS login error</h3><pre>"+str(e)+"</pre>", 500

@app.get("/health")
def health(): return {"ok":True}

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
    
