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
REDIRECT_URI=os.getenv("FYERS_REDIRECT_URI", os.getenv("RENDER_EXTERNAL_URL","").rstrip("/") + "/callback")
ACCESS_TOKEN=os.getenv("FYERS_ACCESS_TOKEN","")
MIN_PREMIUM=float(os.getenv("MIN_PREMIUM","30"))
MAX_PREMIUM=float(os.getenv("MAX_PREMIUM","65"))
LOT_SIZE=int(os.getenv("BANKNIFTY_LOT_SIZE","30"))
GOOGLE_SHEET_ID=os.getenv("GOOGLE_SHEET_ID","")
GOOGLE_SERVICE_ACCOUNT_JSON=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON","")

# Render Secret File support
if not GOOGLE_SERVICE_ACCOUNT_JSON:
    secret_file = "/etc/secrets/google_service_account.json"
    if os.path.exists(secret_file):
        with open(secret_file, "r", encoding="utf-8") as f:
            GOOGLE_SERVICE_ACCOUNT_JSON = f.read()

PAGE="""<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<style>
body{font-family:Arial;background:#111;color:#eee;padding:18px}
.card{background:#1d1d1d;padding:20px;border-radius:16px;margin-bottom:12px}
.sig{font-size:44px;font-weight:bold}.call{color:#35d07f}.put{color:#ff5c6c}.wait{color:#bbb}
.row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #333}
.pass{color:#35d07f;font-weight:bold}.fail{color:#ff5c6c;font-weight:bold}.neutral{color:#bbb}
.small{color:#aaa;font-size:13px}.debug{font-size:14px;line-height:1.5}
a{color:white;background:#333;padding:12px;border-radius:10px;text-decoration:none}
</style>
<h2>BankNifty 5M Signal</h2>
<div class="card"><b>🔄 Auto-refresh: ON</b><br><span class="small">Page refreshes every 5 minutes to fetch the latest signal.</span></div>
<div class="card">
<div class="sig {{cls}}">{{signal}}</div>
<p><b>Score: {{score}}/5</b></p>
<p>BankNifty spot: <b>{{spot}}</b></p>
<div class="row"><span>Option</span><b>{{contract}}</b></div>
<div class="row"><span>Entry</span><b>₹{{entry}}</b></div>
<div class="row"><span>Stop Loss</span><b>₹{{sl}}</b></div>
<div class="row"><span>Target 1</span><b>₹{{t1}}</b></div>
<div class="row"><span>Target 2</span><b>₹{{t2}}</b></div>
<div class="row"><span>Exit</span><b>{{exit_rule}}</b></div>
<p>{{note}}</p></div>
<div class="card"><h3>📊 5 Signal Conditions</h3>
<div class="debug">
<div class="row"><span>1. Price vs EMA 9</span><b class="{{c1_cls}}">{{c1}}</b></div>
<div class="row"><span>2. EMA 9 vs EMA 21</span><b class="{{c2_cls}}">{{c2}}</b></div>
<div class="row"><span>3. Price vs VWAP</span><b class="{{c3_cls}}">{{c3}}</b></div>
<div class="row"><span>4. RSI</span><b class="{{c4_cls}}">{{c4}}</b></div>
<div class="row"><span>5. Volume</span><b class="{{c5_cls}}">{{c5}}</b></div>
</div></div>
<div class="card"><h3>📈 Indicator Data</h3>
<div class="row"><span>Price</span><b>{{price}}</b></div>
<div class="row"><span>EMA 9</span><b>{{ema9}}</b></div>
<div class="row"><span>EMA 21</span><b>{{ema21}}</b></div>
<div class="row"><span>VWAP</span><b>{{vwap}}</b></div>
<div class="row"><span>RSI</span><b>{{rsi}}</b></div>
<div class="row"><span>Current Volume</span><b>{{volume}}</b></div>
<div class="row"><span>Average Volume</span><b>{{avg_volume}}</b></div>
</div>
<div class="card"><p>Technical signal only; not a guaranteed trade.</p>
<p class="small">Levels are estimates from the current option premium and 5-minute signal; not guaranteed execution prices.</p></div>
<br><a href="/login">Connect FYERS</a>
"""

def ema(values, period):
    if not values: return 0.0
    k=2/(period+1)
    e=float(values[0])
    for x in values[1:]:
        e=float(x)*k+e*(1-k)
    return e

def calc(candles):
    close=[float(x[4]) for x in candles]
    high=[float(x[2]) for x in candles]
    low=[float(x[3]) for x in candles]
    volume=[float(x[5]) for x in candles]
    if len(close)<50: raise ValueError("Not enough candles for signal calculation.")

    e9=ema(close[-50:],9)
    e21=ema(close[-50:],21)
    typical=[(h+l+c)/3 for h,l,c in zip(high,low,close)]
    total_volume=sum(volume)
    vwap=sum(tp*v for tp,v in zip(typical,volume))/total_volume if total_volume>0 else close[-1]

    changes=[close[i]-close[i-1] for i in range(1,len(close))]
    recent=changes[-14:]
    gains=sum(max(x,0) for x in recent)/14
    losses=sum(max(-x,0) for x in recent)/14
    rsi=100.0 if losses==0 else 100-(100/(1+gains/losses))

    current_volume=volume[-1]
    avg_volume=sum(volume[-21:-1])/len(volume[-21:-1]) if len(volume)>=21 else sum(volume)/len(volume)
    price=close[-1]

    call_conditions=[price>e9,e9>e21,price>vwap,rsi>=55,current_volume>avg_volume]
    put_conditions=[price<e9,e9<e21,price<vwap,rsi<=45,current_volume>avg_volume]
    call_score=sum(call_conditions)
    put_score=sum(put_conditions)

    if call_score>=4: signal="CALL"; score=call_score
    elif put_score>=4: signal="PUT"; score=-put_score
    else:
        signal="WAIT"
        score=call_score if call_score>=put_score else -put_score

    if signal=="CALL":
        conditions=["PASS" if x else "FAIL" for x in call_conditions]
    elif signal=="PUT":
        conditions=["PASS" if x else "FAIL" for x in put_conditions]
    else:
        conditions=[]
        for i in range(5):
            if call_conditions[i]: conditions.append("CALL PASS")
            elif put_conditions[i]: conditions.append("PUT PASS")
            else: conditions.append("FAIL")

    return {"signal":signal,"score":score,"spot":price,"ema9":e9,"ema21":e21,
            "vwap":vwap,"rsi":rsi,"volume":current_volume,"avg_volume":avg_volume,
            "conditions":conditions}

def pick_budget_option(spot, signal):
    headers={"Authorization":f"{CLIENT_ID}:{ACCESS_TOKEN}"}
    params={"symbol":"NSE:NIFTYBANK-INDEX","strikecount":25,"greeks":"1"}
    r=requests.get("https://api-t1.fyers.in/data/options-chain-v3",headers=headers,params=params,timeout=12)
    r.raise_for_status()
    chain=r.json().get("data",{}).get("optionsChain",[])
    typ="CE" if signal=="CALL" else "PE"
    legs=[x for x in chain if x.get("option_type")==typ and float(x.get("ltp",0) or 0)>0]
    in_range=[x for x in legs if MIN_PREMIUM<=float(x["ltp"])<=MAX_PREMIUM]
    candidates=in_range or legs
    if not candidates: return None
    if in_range:
        chosen=min(in_range,key=lambda x:(abs(float(x["strike_price"])-spot),-float(x.get("volume",0))))
        within=True
    else:
        mid=(MIN_PREMIUM+MAX_PREMIUM)/2
        chosen=min(legs,key=lambda x:(abs(float(x["ltp"])-mid),abs(float(x["strike_price"])-spot)))
        within=False
    premium=float(chosen["ltp"])
    return {"symbol":chosen.get("symbol","—"),"premium":round(premium,2),
            "cost":round(premium*LOT_SIZE,2),"lot":LOT_SIZE,"within":within}

JOURNAL_HEADERS=["timestamp_utc","signal","score","banknifty_spot","option_symbol","entry","stop_loss","target_1","target_2","exit_rule","status","exit_price","pnl_per_lot","notes"]

def get_journal_sheet():
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        print("Google Sheet ENV variables are missing.")
        return None
    info=json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    creds=Credentials.from_service_account_info(info,scopes=scopes)
    gc=gspread.authorize(creds)
    sh=gc.open_by_key(GOOGLE_SHEET_ID)
    ws=sh.sheet1
    if not ws.get_all_values(): ws.append_row(JOURNAL_HEADERS,value_input_option="USER_ENTERED")
    return ws

def journal_signal(signal,score,spot,contract,entry,sl,t1,t2,exit_rule,note):
    if not contract or contract=="—" or entry in ("—",None): return
    try:
        ws=get_journal_sheet()
        if ws is None: return
        now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        values=ws.get_all_values()
        if len(values)>1:
            last=values[-1]
            if len(last)>=5:
                try:
                    last_dt=datetime.strptime(last[0],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    cur_dt=datetime.strptime(now,"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    same_bucket=(int(last_dt.timestamp())//300)==(int(cur_dt.timestamp())//300)
                except Exception: same_bucket=False
                if same_bucket and last[1]==signal and last[4]==contract: return
        ws.append_row([now,signal,score,round(float(spot),2),contract,float(entry),float(sl),float(t1),float(t2),exit_rule,"OPEN","","",note],value_input_option="USER_ENTERED")
        print("Google Sheet journal row added.")
    except Exception as e:
        print("Google Sheet journal error:",e)

def make_levels(entry,signal):
    entry=float(entry)
    return round(entry*0.85,2),round(entry*1.25,2),round(entry*1.40,2)

def condition_class(value):
    if value=="PASS" or "PASS" in value: return "pass"
    if value=="FAIL": return "fail"
    return "neutral"

@app.route("/")
def home():
    if not ACCESS_TOKEN:
        return render_template_string(PAGE,signal="WAIT",cls="wait",score=0,spot="—",contract="—",entry="—",sl="—",t1="—",t2="—",exit_rule="Connect FYERS",note="FYERS is not connected.",c1="—",c2="—",c3="—",c4="—",c5="—",c1_cls="neutral",c2_cls="neutral",c3_cls="neutral",c4_cls="neutral",c5_cls="neutral",price="—",ema9="—",ema21="—",vwap="—",rsi="—",volume="—",avg_volume="—")

    try:
        fy=fyersModel.FyersModel(client_id=CLIENT_ID,token=ACCESS_TOKEN,is_async=False,log_path="")
        now=datetime.now(timezone.utc)
        start=now-timedelta(days=5)
        response=fy.history({"symbol":"NSE:NIFTYBANK-INDEX","resolution":"5","date_format":"1","range_from":start.strftime("%Y-%m-%d"),"range_to":now.strftime("%Y-%m-%d"),"cont_flag":"1"})
        candles=response.get("candles",[])
        if len(candles)<50: raise ValueError("Not enough 5-minute candles returned by FYERS.")

        result=calc(candles)
        sig=result["signal"]; score=result["score"]; spot=result["spot"]
        contract="—"; entry=sl=t1=t2="—"; exit_rule="WAIT / no trade"
        note="Technical signal only; not a guaranteed trade."

        if sig in ("CALL","PUT"):
            try:
                selected=pick_budget_option(spot,sig)
                if selected:
                    contract=selected["symbol"]; entry=round(float(selected["premium"]),2)
                    sl,t1,t2=make_levels(entry,sig)
                    reverse_signal="PUT" if sig=="CALL" else "CALL"
                    exit_rule=f"Exit at T1/T2 or immediately if signal reverses to {reverse_signal}."
                    if selected.get("within"):
                        note+=f" Budget premium target: ₹{MIN_PREMIUM:.0f}–₹{MAX_PREMIUM:.0f}."
                    else: note+=" No contract was inside the preferred premium range."
                else: note+=" No suitable option contract was returned."
            except Exception as oe: note+=" Option-chain lookup failed: "+str(oe)

        journal_signal(sig,abs(score),spot,contract,entry,sl,t1,t2,exit_rule,note)

        conditions=result["conditions"]
        c1,c2,c3,c4,c5=conditions

        return render_template_string(PAGE,signal=sig,cls=sig.lower(),score=abs(score),spot=round(spot,2),
            contract=contract,entry=entry,sl=sl,t1=t1,t2=t2,exit_rule=exit_rule,note=note,
            c1=c1,c2=c2,c3=c3,c4=c4,c5=c5,c1_cls=condition_class(c1),c2_cls=condition_class(c2),
            c3_cls=condition_class(c3),c4_cls=condition_class(c4),c5_cls=condition_class(c5),
            price=round(result["spot"],2),ema9=round(result["ema9"],2),ema21=round(result["ema21"],2),
            vwap=round(result["vwap"],2),rsi=round(result["rsi"],2),volume=round(result["volume"],0),
            avg_volume=round(result["avg_volume"],0))
    except Exception as e:
        return render_template_string(PAGE,signal="WAIT",cls="wait",score=0,spot="—",contract="—",entry="—",sl="—",t1="—",t2="—",exit_rule="No trade",note="Data error: "+str(e),
            c1="—",c2="—",c3="—",c4="—",c5="—",c1_cls="neutral",c2_cls="neutral",c3_cls="neutral",c4_cls="neutral",c5_cls="neutral",
            price="—",ema9="—",ema21="—",vwap="—",rsi="—",volume="—",avg_volume="—")

@app.route("/login")
def login():
    if not CLIENT_ID or not SECRET: return "FYERS_CLIENT_ID / FYERS_SECRET is missing in Render Environment Variables.",500
    if not REDIRECT_URI: return "FYERS_REDIRECT_URI is missing. Set it to your Render URL + /callback.",500
    s=fyersModel.SessionModel(client_id=CLIENT_ID,secret_key=SECRET,redirect_uri=REDIRECT_URI,response_type="code",grant_type="authorization_code")
    return redirect(s.generate_authcode())

@app.route("/callback")
def callback():
    global ACCESS_TOKEN
    code=request.args.get("auth_code")
    if not code: return "Missing auth_code. FYERS did not return an authorization code.",400
    if not CLIENT_ID or not SECRET or not REDIRECT_URI: return "FYERS OAuth environment variables are not configured correctly in Render.",500
    try:
        s=fyersModel.SessionModel(client_id=CLIENT_ID,secret_key=SECRET,redirect_uri=REDIRECT_URI,response_type="code",grant_type="authorization_code")
        s.set_token(code)
        r=s.generate_token()
        token=r.get("access_token","")
        if not token: return "<h3>FYERS login failed</h3><pre>"+str(r)+"</pre>",400
        ACCESS_TOKEN=token
        return redirect("/")
    except Exception as e: return "<h3>FYERS login error</h3><pre>"+str(e)+"</pre>",500

@app.get("/health")
def health(): return {"ok":True}

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
    
