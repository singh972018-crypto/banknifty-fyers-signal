import os
from datetime import datetime, timedelta, timezone
from flask import Flask, request, redirect, render_template_string
from fyers_apiv3 import fyersModel

app = Flask(__name__)
CLIENT_ID=os.getenv("FYERS_CLIENT_ID","")
SECRET=os.getenv("FYERS_SECRET","")
REDIRECT_URI=os.getenv("FYERS_REDIRECT_URI","")
ACCESS_TOKEN=os.getenv("FYERS_ACCESS_TOKEN","")

PAGE="""<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:Arial;background:#111;color:#eee;padding:18px}.card{background:#1d1d1d;padding:20px;border-radius:16px}.sig{font-size:44px;font-weight:bold}.call{color:#35d07f}.put{color:#ff5c6c}.wait{color:#bbb}a{color:white;background:#333;padding:12px;border-radius:10px;text-decoration:none}</style>
<h2>BankNifty 5M Signal</h2><div class="card">
<div class="sig {{cls}}">{{signal}}</div><p>Score: {{score}}/5</p>
<p>BankNifty spot: <b>{{spot}}</b></p><p>Suggested: <b>{{option}}</b></p>
<p>{{note}}</p></div><br><a href="/login">Connect FYERS</a>"""

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

@app.route("/")
def home():
    if not ACCESS_TOKEN:
        return render_template_string(PAGE,signal="WAIT",cls="wait",score=0,spot="—",option="Connect FYERS",note="FYERS is not connected.")
    try:
        fy=fyersModel.FyersModel(client_id=CLIENT_ID,token=ACCESS_TOKEN,is_async=False,log_path="")
        now=datetime.now(timezone.utc); start=now-timedelta(days=5)
        r=fy.history({"symbol":"NSE:NIFTYBANK-INDEX","resolution":"5","date_format":"1",
                      "range_from":start.strftime("%Y-%m-%d"),"range_to":now.strftime("%Y-%m-%d"),"cont_flag":"1"})
        sig,score,spot=calc(r.get("candles",[]))
        atm=round(spot/100)*100
        opt="ATM "+str(atm) if sig=="WAIT" else ("CALL "+str(atm)+" / "+str(atm+100) if sig=="CALL" else "PUT "+str(atm)+" / "+str(atm-100))
        return render_template_string(PAGE,signal=sig,cls=sig.lower(),score=abs(score),spot=round(spot,2),option=opt,note="Technical signal only; not a guaranteed trade.")
    except Exception as e:
        return render_template_string(PAGE,signal="WAIT",cls="wait",score=0,spot="—",option="—",note="Data error: "+str(e))

@app.route("/login")
def login():
    s=fyersModel.SessionModel(client_id=CLIENT_ID,secret_key=SECRET,redirect_uri=REDIRECT_URI,response_type="code",grant_type="authorization_code")
    return redirect(s.generate_authcode())

@app.route("/callback")
def callback():
    code=request.args.get("auth_code")
    if not code: return "Missing auth_code",400
    s=fyersModel.SessionModel(client_id=CLIENT_ID,secret_key=SECRET,redirect_uri=REDIRECT_URI,response_type="code",grant_type="authorization_code")
    s.set_token(code)
    r=s.generate_token()
    return "<h3>FYERS login complete</h3><p>Put the returned access_token into Render as FYERS_ACCESS_TOKEN.</p><pre>"+str(r.get("access_token",""))+"</pre>"

@app.get("/health")
def health(): return {"ok":True}

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
