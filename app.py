import os
from datetime import datetime, timedelta, timezone
from flask import Flask, request, redirect, render_template_string
import requests
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

PAGE="""<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:Arial;background:#111;color:#eee;padding:18px}.card{background:#1d1d1d;padding:20px;border-radius:16px}.sig{font-size:44px;font-weight:bold}.call{color:#35d07f}.put{color:#ff5c6c}.wait{color:#bbb}a{color:white;background:#333;padding:12px;border-radius:10px;text-decoration:none}</style>
<h2>BankNifty 5M Signal</h2><div class="card">
<div class="sig {{cls}}">{{signal}}</div><p>Score: {{score}}/5</p>
<p>BankNifty spot: <b>{{spot}}</b></p><p>Suggested: <b>{{option}}</b></p>
<p>{{note}}</p>{% if contract %}<p><b>Budget option:</b> {{contract}}</p><p><b>Premium:</b> ₹{{premium}} × {{lot}} = <b>₹{{cost}}</b></p>{% endif %}</div><br><a href="/login">Connect FYERS</a>"""

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

@app.route("/")
def home():
    if not ACCESS_TOKEN:
        return render_template_string(PAGE,signal="WAIT",cls="wait",score=0,spot="—",option="Connect FYERS",contract=None,premium="—",cost="—",lot=LOT_SIZE,note="FYERS is not connected.")
    try:
        fy=fyersModel.FyersModel(client_id=CLIENT_ID,token=ACCESS_TOKEN,is_async=False,log_path="")
        now=datetime.now(timezone.utc); start=now-timedelta(days=5)
        r=fy.history({"symbol":"NSE:NIFTYBANK-INDEX","resolution":"5","date_format":"1","range_from":start.strftime("%Y-%m-%d"),"range_to":now.strftime("%Y-%m-%d"),"cont_flag":"1"})
        candles=r.get("candles",[])
        if len(candles)<50: raise ValueError("Not enough 5-minute candles returned by FYERS.")
        sig,score,spot=calc(candles); contract=None; premium="—"; cost="—"; lot=LOT_SIZE
        note="Technical signal only; not a guaranteed trade."
        if sig in ("CALL","PUT"):
            try:
                x=pick_budget_option(spot,sig)
                if x:
                    contract=x["symbol"]; premium=x["premium"]; cost=x["cost"]
                    note += " Budget filter: ₹30–₹65 premium." if x["within"] else " No contract was inside ₹30–₹65; nearest available premium is shown."
                else: note += " No suitable option contract returned."
            except Exception as oe: note += " Option-chain lookup failed: "+str(oe)
        return render_template_string(PAGE,signal=sig,cls=sig.lower(),score=abs(score),spot=round(spot,2),option=("CALL/PUT selected by signal" if sig in ("CALL","PUT") else "Wait"),contract=contract,premium=premium,cost=cost,lot=lot,note=note)
    except Exception as e:
        return render_template_string(PAGE,signal="WAIT",cls="wait",score=0,spot="—",option="—",contract=None,premium="—",cost="—",lot=LOT_SIZE,note="Data error: "+str(e))

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
