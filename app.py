import os, logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, redirect, render_template_string, request
from fyers_apiv3 import fyersModel

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log = logging.getLogger("study")
CLIENT_ID=os.getenv("FYERS_CLIENT_ID","").strip()
SECRET=os.getenv("FYERS_SECRET","").strip()
REDIRECT_URI=os.getenv("FYERS_REDIRECT_URI",os.getenv("RENDER_EXTERNAL_URL","").rstrip("/")+"/callback").strip()
ACCESS_TOKEN=os.getenv("FYERS_ACCESS_TOKEN","").strip()
SYMBOL=os.getenv("FYERS_SYMBOL","NSE:NIFTYBANK-INDEX").strip()
DAYS=max(3,min(10,int(os.getenv("HISTORY_DAYS","5"))))
IST=ZoneInfo("Asia/Kolkata")
PAGE=r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="180"><title>3-Minute Market Study</title>
<style>body{font-family:Arial;background:#101722;color:#e9eef7;padding:16px;margin:0}main{max-width:1000px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.card{background:#1a2636;border:1px solid #2b3b50;border-radius:12px;padding:14px;margin:10px 0}.muted{color:#aab6c8}.big{font-size:1.4rem;font-weight:bold}.ok{color:#8ee0ad}.bad{color:#ff9c9c}table{width:100%;border-collapse:collapse;white-space:nowrap}td,th{padding:8px;border-bottom:1px solid #334;text-align:right}td:first-child,th:first-child{text-align:left}.scroll{overflow:auto}a{color:#9bc8ff}</style></head><body><main>
<h1>BankNifty — 3-minute market study</h1><p class="muted">Educational indicator dashboard only; no CALL/PUT instructions, option selection, or trade levels.</p>
<div class="grid">
<div class="card"><div class="muted">Data status</div><div class="big {{'ok' if ok else 'bad'}}">{{status}}</div><small>{{updated}}</small></div>
<div class="card"><div class="muted">Latest completed close</div><div class="big">{{close}}</div></div>
<div class="card"><div class="muted">EMA 9</div><div class="big">{{ema9}}</div></div>
<div class="card"><div class="muted">EMA 21</div><div class="big">{{ema21}}</div></div>
<div class="card"><div class="muted">RSI 14</div><div class="big">{{rsi}}</div></div>
<div class="card"><div class="muted">ATR 14</div><div class="big">{{atr}}</div></div>
<div class="card"><div class="muted">Session VWAP</div><div class="big">{{vwap}}</div></div>
<div class="card"><div class="muted">ADX 14 estimate</div><div class="big">{{adx}}</div></div></div>
<div class="card"><h3>Data validation</h3><p>{{note}}</p><p class="muted">Symbol: {{symbol}} · Interval: 3 minutes · Valid candles: {{count}}</p><p><a href="/login">Connect / re-authorize FYERS</a> · <a href="/health">Health check</a></p></div>
<div class="card"><h3>Latest completed candles</h3>{% if candles %}<div class="scroll"><table><tr><th>Time (IST)</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr>{% for c in candles %}<tr><td>{{c.t}}</td><td>{{c.o}}</td><td>{{c.h}}</td><td>{{c.l}}</td><td>{{c.c}}</td><td>{{c.v}}</td></tr>{% endfor %}</table></div>{% else %}<p class="muted">No validated candles.</p>{% endif %}</div>
<p class="muted">Refreshes every 180 seconds. Refresh does not guarantee a new candle or successful API response.</p></main></body></html>"""

def client():
    if not CLIENT_ID: raise RuntimeError("FYERS_CLIENT_ID is missing in the running process.")
    if not ACCESS_TOKEN: raise RuntimeError("No FYERS access token in this process. Authenticate first.")
    return fyersModel.FyersModel(client_id=CLIENT_ID,token=ACCESS_TOKEN,is_async=False,log_path="")

def get_candles():
    now=datetime.now(IST).replace(second=0,microsecond=0)
    bucket=(now.minute//3)*3
    end=now.replace(minute=bucket)-timedelta(minutes=3)
    start=end-timedelta(days=DAYS)
    resp=client().history(data={"symbol":SYMBOL,"resolution":"3","date_format":"1","range_from":start.strftime("%Y-%m-%d"),"range_to":end.strftime("%Y-%m-%d"),"cont_flag":"1"})
    if not isinstance(resp,dict): raise RuntimeError("Unexpected FYERS history response.")
    if resp.get("s")!="ok": raise RuntimeError("FYERS history failed: "+str(resp.get("message") or resp.get("code") or "unknown error"))
    now_ts=datetime.now(IST).timestamp(); by_ts={}
    for row in resp.get("candles",[]):
        try:
            ts=float(row[0]); o,h,l,c,v=map(float,row[1:6])
            if not all(map(lambda x: x==x and abs(x)!=float("inf"),[ts,o,h,l,c,v])): continue
            if min(o,h,l,c,v)<0 or h<max(o,c,l) or l>min(o,c,h): continue
            if ts+180>now_ts: continue
            by_ts[ts]={"ts":ts,"o":o,"h":h,"l":l,"c":c,"v":v,"t":datetime.fromtimestamp(ts,IST).strftime("%d-%b %H:%M")}
        except (ValueError,TypeError,IndexError,OverflowError,OSError): continue
    candles=[by_ts[k] for k in sorted(by_ts)]
    if len(candles)<60: raise RuntimeError(f"Only {len(candles)} valid completed candles; 60 required.")
    return candles

def ema(x,n):
    if len(x)<n:return None
    a=2/(n+1); z=sum(x[:n])/n
    for v in x[n:]:z=a*v+(1-a)*z
    return z
def rsi(x,n=14):
    if len(x)<=n:return None
    d=[x[i]-x[i-1] for i in range(1,len(x))]
    g=[max(v,0) for v in d]; l=[max(-v,0) for v in d]
    ag=sum(g[:n])/n; al=sum(l[:n])/n
    for i in range(n,len(d)):
        ag=((n-1)*ag+g[i])/n; al=((n-1)*al+l[i])/n
    return 100.0 if al==0 and ag>0 else (50.0 if al==0 else 100-100/(1+ag/al))
def wilder(x,n):
    if len(x)<n:return None
    z=sum(x[:n])/n
    for v in x[n:]:z=((n-1)*z+v)/n
    return z
def ranges(cs):
    return [max(cs[i]["h"]-cs[i]["l"],abs(cs[i]["h"]-cs[i-1]["c"]),abs(cs[i]["l"]-cs[i-1]["c"])) for i in range(1,len(cs))]
def atr(cs,n=14):return wilder(ranges(cs),n)
def adx(cs,n=14):
    if len(cs)<2*n+1:return None
    tr=[];pdm=[];mdm=[]
    for i in range(1,len(cs)):
        up=cs[i]["h"]-cs[i-1]["h"]; dn=cs[i-1]["l"]-cs[i]["l"]
        tr.append(max(cs[i]["h"]-cs[i]["l"],abs(cs[i]["h"]-cs[i-1]["c"]),abs(cs[i]["l"]-cs[i-1]["c"])))
        pdm.append(up if up>dn and up>0 else 0); mdm.append(dn if dn>up and dn>0 else 0)
    dx=[]
    for end in range(n,len(tr)+1):
        ta=wilder(tr[:end],n); pa=wilder(pdm[:end],n); ma=wilder(mdm[:end],n)
        if not ta:continue
        p=100*pa/ta; m=100*ma/ta
        dx.append(100*abs(p-m)/(p+m) if p+m else 0)
    return wilder(dx,n)
def vwap(cs):
    today=datetime.now(IST).date()
    day=[c for c in cs if datetime.fromtimestamp(c["ts"],IST).date()==today]
    vol=sum(c["v"] for c in day)
    return sum(((c["h"]+c["l"]+c["c"])/3)*c["v"] for c in day)/vol if vol>0 else None
def f(x,n=2):return "—" if x is None else f"{x:.{n}f}"

def page_data():
    d=dict(ok=False,status="Not connected",updated=datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S IST"),close="—",ema9="—",ema21="—",rsi="—",atr="—",adx="—",vwap="—",note="Waiting for FYERS data.",symbol=SYMBOL,count=0,candles=[])
    try:
        cs=get_candles(); x=[c["c"] for c in cs]
        d.update(ok=True,status="Connected",close=f(x[-1]),ema9=f(ema(x,9)),ema21=f(ema(x,21)),rsi=f(rsi(x)),atr=f(atr(cs)),adx=f(adx(cs)),vwap=f(vwap(cs)),note="FYERS response received; candle structure and completed intervals validated.",count=len(cs),candles=[dict(t=c["t"],o=f(c["o"]),h=f(c["h"]),l=f(c["l"]),c=f(c["c"]),v=f(c["v"],0)) for c in cs[-30:][::-1]])
    except Exception as e:
        log.exception("Market data refresh failed"); d["status"]="Data error"; d["note"]=str(e)[:300]
    return d

@app.get("/")
def home():return render_template_string(PAGE,**page_data())
@app.get("/health")
def health():return jsonify(ok=True,client_id_present=bool(CLIENT_ID),secret_present=bool(SECRET),access_token_present=bool(ACCESS_TOKEN),symbol=SYMBOL,timeframe="3")
@app.get("/login")
def login():
    if not CLIENT_ID or not SECRET or not REDIRECT_URI:return "FYERS_CLIENT_ID, FYERS_SECRET, or redirect URI is missing.",500
    s=fyersModel.SessionModel(client_id=CLIENT_ID,secret_key=SECRET,redirect_uri=REDIRECT_URI,response_type="code",grant_type="authorization_code")
    return redirect(s.generate_authcode())
@app.get("/callback")
def callback():
    global ACCESS_TOKEN
    code=request.args.get("auth_code","")
    if not code:return "Missing FYERS authorization code.",400
    if not CLIENT_ID or not SECRET or not REDIRECT_URI:return "FYERS OAuth configuration is incomplete.",500
    try:
        s=fyersModel.SessionModel(client_id=CLIENT_ID,secret_key=SECRET,redirect_uri=REDIRECT_URI,response_type="code",grant_type="authorization_code")
        s.set_token(code); result=s.generate_token()
        token=result.get("access_token","") if isinstance(result,dict) else ""
        if not token:return "FYERS did not return an access token. Check Render Logs.",502
        ACCESS_TOKEN=token.strip()
        return redirect("/")
    except Exception:
        log.exception("FYERS OAuth callback failed")
        return "FYERS login failed. Check Render Logs; secrets are not displayed.",500
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
