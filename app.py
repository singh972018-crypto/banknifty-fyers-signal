import os
from datetime import datetime, timedelta, timezone
from flask import Flask, request, redirect, render_template_string
import requests
from fyers_apiv3 import fyersModel

app = Flask(__name__)

CLIENT_ID=os.getenv("FYERS_CLIENT_ID","")
SECRET=os.getenv("FYERS_SECRET","")
REDIRECT_URI=os.getenv("FYERS_REDIRECT_URI", os.getenv("RENDER_EXTERNAL_URL","").rstrip("/") + "/callback")
ACCESS_TOKEN=os.getenv("FYERS_ACCESS_TOKEN","")
MIN_PREMIUM=float(os.getenv("MIN_PREMIUM","30"))
MAX_PREMIUM=float(os.getenv("MAX_PREMIUM","65"))
LOT_SIZE=int(os.getenv("BANKNIFTY_LOT_SIZE","30"))

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
<div class="card"><h3>🟢 LIVE ANALYSIS A — Budget band ₹2,000</h3>
<div class="sig {{sig_a_cls}}">{{sig_a}}</div>
<p><b>{{strength_a}}</b> &nbsp; Score: <b>{{score_a}}/4</b> &nbsp; <span class="small">Signal comes from live BankNifty indicators</span></p>
<div class="row"><span>BankNifty spot</span><b>{{spot}}</b></div>
<div class="row"><span>Reference option</span><b>{{contract_a}}</b></div>
<div class="row"><span>Live premium</span><b>₹{{premium_a}}</b></div>
<div class="row"><span>Approx. 1-lot value</span><b>₹{{cost_a}}</b></div>
<p class="small">Live-market reference only. No order placement is performed by this app.</p></div>

<div class="card"><h3>🔵 LIVE ANALYSIS B — Budget band ₹5,000</h3>
<div class="sig {{sig_b_cls}}">{{sig_b}}</div>
<p><b>{{strength_b}}</b> &nbsp; Score: <b>{{score_b}}/4</b> &nbsp; <span class="small">Signal comes from live BankNifty indicators</span></p>
<div class="row"><span>BankNifty spot</span><b>{{spot}}</b></div>
<div class="row"><span>Reference option</span><b>{{contract_b}}</b></div>
<div class="row"><span>Live premium</span><b>₹{{premium_b}}</b></div>
<div class="row"><span>Approx. 1-lot value</span><b>₹{{cost_b}}</b></div>
<p class="small">Live-market reference only. No order placement is performed by this app.</p></div>

<div class="card"><h3>🟣 LIVE ANALYSIS C — Highest-confidence setup</h3>
<div class="sig {{sig_c_cls}}">{{sig_c}}</div>
<p><b>{{strength_c}}</b> &nbsp; Score: <b>{{score_c}}/4</b> &nbsp; <span class="small">Signal comes from live BankNifty indicators</span></p>
<div class="row"><span>BankNifty spot</span><b>{{spot}}</b></div>
<div class="row"><span>Reference option</span><b>{{contract_c}}</b></div>
<div class="row"><span>Live premium</span><b>₹{{premium_c}}</b></div>
<div class="row"><span>Approx. 1-lot value</span><b>₹{{cost_c}}</b></div>
<div class="row"><span>Confirmation score</span><b>{{conf_c}}/3</b></div>
<p class="small">Chosen from the live indicator/confirmation score; this is not a prediction of future price.</p></div>
<div class="card"><h3>📊 4 Core Signal Conditions</h3>
<div class="debug">
<div class="row"><span>1. EMA 9 / EMA 21 Trend</span><b class="{{c1_cls}}">{{c1}}</b></div>
<div class="row"><span>2. Price vs VWAP</span><b class="{{c2_cls}}">{{c2}}</b></div>
<div class="row"><span>3. RSI Momentum</span><b class="{{c3_cls}}">{{c3}}</b></div>
<div class="row"><span>4. Volume Confirmation</span><b class="{{c4_cls}}">{{c4}}</b></div>
</div></div>
<div class="card"><h3>🧭 Strength Confirmations</h3>
<div class="row"><span>ADX + DI Trend Strength</span><b class="{{x1_cls}}">{{x1}}</b></div>
<div class="row"><span>Candle Confirmation</span><b class="{{x2_cls}}">{{x2}}</b></div>
<div class="row"><span>ATR Volatility</span><b class="{{x3_cls}}">{{x3}}</b></div>
</div>
<div class="card"><h3>📈 Indicator Data</h3>
<div class="row"><span>Price</span><b>{{price}}</b></div>
<div class="row"><span>EMA 9</span><b>{{ema9}}</b></div>
<div class="row"><span>EMA 21</span><b>{{ema21}}</b></div>
<div class="row"><span>VWAP</span><b>{{vwap}}</b></div>
<div class="row"><span>RSI</span><b>{{rsi}}</b></div>
<div class="row"><span>Current Volume</span><b>{{volume}}</b></div>
<div class="row"><span>Average Volume</span><b>{{avg_volume}}</b></div>
<div class="row"><span>ADX</span><b>{{adx}}</b></div>
<div class="row"><span>ATR</span><b>{{atr}}</b></div>
<div class="row"><span>Candle Range</span><b>{{candle_range}}</b></div>
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
    if len(close)<60:
        raise ValueError("Not enough 5-minute candles for signal calculation.")

    price=close[-1]
    e9=ema(close[-60:],9)
    e21=ema(close[-60:],21)

    # Session-style VWAP from the returned candles.
    typical=[(h+l+c)/3 for h,l,c in zip(high,low,close)]
    total_volume=sum(volume)
    vwap=sum(tp*v for tp,v in zip(typical,volume))/total_volume if total_volume else price

    # RSI(14), using the same simple-average method as the original project.
    changes=[close[i]-close[i-1] for i in range(1,len(close))]
    recent=changes[-14:]
    gains=sum(max(x,0) for x in recent)/14
    losses=sum(max(-x,0) for x in recent)/14
    rsi=100.0 if losses==0 else 100-(100/(1+gains/losses))

    # Volume confirmation against the previous 20 completed candles.
    current_volume=volume[-1]
    avg_volume=sum(volume[-21:-1])/20 if len(volume)>=21 else sum(volume)/len(volume)

    # ADX(14) -- trend-strength filter.
    tr=[]; plus_dm=[]; minus_dm=[]
    for i in range(1,len(close)):
        up=high[i]-high[i-1]
        down=low[i-1]-low[i]
        tr.append(max(high[i]-low[i],abs(high[i]-close[i-1]),abs(low[i]-close[i-1])))
        plus_dm.append(up if up>down and up>0 else 0.0)
        minus_dm.append(down if down>up and down>0 else 0.0)
    n=14
    if len(tr)>=n:
        atr14=sum(tr[-n:])/n
        pdi=100*(sum(plus_dm[-n:])/n)/(atr14 or 1)
        mdi=100*(sum(minus_dm[-n:])/n)/(atr14 or 1)
        dx=100*abs(pdi-mdi)/(pdi+mdi) if (pdi+mdi) else 0.0
        # A compact rolling ADX estimate from the latest 14 DX values.
        dxs=[]
        for j in range(max(n-1,len(tr)-n),len(tr)):
            a=max(0,j-n+1); b=j+1
            atr=sum(tr[a:b])/len(tr[a:b]) or 1
            p=100*(sum(plus_dm[a:b])/len(plus_dm[a:b]))/atr
            m=100*(sum(minus_dm[a:b])/len(minus_dm[a:b]))/atr
            dxs.append(100*abs(p-m)/(p+m) if p+m else 0.0)
        adx=sum(dxs)/len(dxs) if dxs else dx
    else:
        atr14=0.0; pdi=mdi=adx=0.0

    # ATR as a volatility filter. Compare current candle range with ATR.
    candle_range=high[-1]-low[-1]
    atr_ok=candle_range >= atr14*0.60 if atr14>0 else True

    # Candle confirmation: body direction + close location.
    body=abs(close[-1]-close[-2])
    bull_candle=close[-1]>close[-2] and body >= candle_range*0.35 if candle_range>0 else False
    bear_candle=close[-1]<close[-2] and body >= candle_range*0.35 if candle_range>0 else False

    # Core indicators + strength confirmations.
    core_call=[e9>e21,price>vwap,rsi>=52,current_volume>avg_volume]
    core_put=[e9<e21,price<vwap,rsi<=48,current_volume>avg_volume]
    call_score=sum(core_call); put_score=sum(core_put)

    # ADX confirms trend direction; candle confirms immediate price action;
    # ATR confirms enough movement. These are confirmations, not extra core votes.
    call_confirmations=[adx>=20 and pdi>mdi,bull_candle,atr_ok]
    put_confirmations=[adx>=20 and mdi>pdi,bear_candle,atr_ok]
    call_conf=sum(call_confirmations); put_conf=sum(put_confirmations)

    # Require 3/4 core conditions. Then use confirmations to classify strength.
    if call_score>=3 and call_score>put_score:
        signal="CALL"
        strength="STRONG" if call_score==4 and call_conf>=2 else ("NORMAL" if call_conf>=1 else "CAUTION")
        score=call_score
        conditions=["PASS" if x else "FAIL" for x in core_call]
        confirmations=["PASS" if x else "FAIL" for x in call_confirmations]
    elif put_score>=3 and put_score>call_score:
        signal="PUT"
        strength="STRONG" if put_score==4 and put_conf>=2 else ("NORMAL" if put_conf>=1 else "CAUTION")
        score=-put_score
        conditions=["PASS" if x else "FAIL" for x in core_put]
        confirmations=["PASS" if x else "FAIL" for x in put_confirmations]
    else:
        signal="WAIT"
        score=call_score if call_score>=put_score else -put_score
        conditions=[]
        for i in range(4):
            if core_call[i] and not core_put[i]: conditions.append("CALL PASS")
            elif core_put[i] and not core_call[i]: conditions.append("PUT PASS")
            else: conditions.append("FAIL")
        confirmations=["—","—","—"]
        strength="WATCH"

    return {"signal":signal,"score":score,"strength":strength,"spot":price,
            "ema9":e9,"ema21":e21,"vwap":vwap,"rsi":rsi,
            "volume":current_volume,"avg_volume":avg_volume,
            "adx":adx,"atr":atr14,"candle_range":candle_range,
            "conditions":conditions,"confirmations":confirmations}

def pick_budget_option(spot, signal):
    headers={"Authorization":f"{CLIENT_ID}:{ACCESS_TOKEN}"}
    params={"symbol":"NSE:NIFTYBANK-INDEX","strikecount":25,"greeks":"1"}
    r=requests.get("https://api-t1.fyers.in/data/options-chain-v3",headers=headers,params=params,timeout=12)
    r.raise_for_status()
    chain=r.json().get("data",{}).get("optionsChain",[])
    typ="CE" if signal=="CALL" else "PE"
    def is_type(x):
        ot=str(x.get("option_type","")).upper()
        sym=str(x.get("symbol","")).upper()
        return ot==typ or sym.endswith(typ)
    legs=[x for x in chain if is_type(x) and float(x.get("ltp",0) or 0)>0]
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

def pick_budget_option(spot, signal, max_budget):
    headers={"Authorization":f"{CLIENT_ID}:{ACCESS_TOKEN}"}
    params={"symbol":"NSE:NIFTYBANK-INDEX","strikecount":25,"greeks":"1"}
    r=requests.get("https://api-t1.fyers.in/data/options-chain-v3",headers=headers,params=params,timeout=12)
    r.raise_for_status()
    chain=r.json().get("data",{}).get("optionsChain",[])
    typ="CE" if signal=="CALL" else "PE"
    def is_type(x):
        ot=str(x.get("option_type","")).upper()
        sym=str(x.get("symbol","")).upper()
        return ot==typ or sym.endswith(typ)
    legs=[x for x in chain if is_type(x) and float(x.get("ltp",0) or 0)>0]
    affordable=[x for x in legs if float(x["ltp"])*LOT_SIZE <= max_budget]
    if not affordable: return None
    chosen=min(affordable,key=lambda x:(abs(float(x["strike_price"])-spot),-float(x.get("ltp",0))))
    premium=float(chosen["ltp"])
    return {"symbol":chosen.get("symbol","—"),"premium":round(premium,2),"cost":round(premium*LOT_SIZE,2)}

def make_levels(entry,signal):
    entry=float(entry)
    return round(entry*0.85,2),round(entry*1.25,2),round(entry*1.40,2)

def condition_class(value):
    if value=="PASS" or "PASS" in value: return "pass"
    if value=="FAIL": return "fail"
    return "neutral"

@app.route("/")
def home():
    base=dict(signal="WAIT",cls="wait",score=0,spot="—",strength="—",
        c1="—",c2="—",c3="—",c4="—",c1_cls="neutral",c2_cls="neutral",c3_cls="neutral",c4_cls="neutral",
        x1="—",x2="—",x3="—",x1_cls="neutral",x2_cls="neutral",x3_cls="neutral",
        price="—",ema9="—",ema21="—",vwap="—",rsi="—",volume="—",avg_volume="—",adx="—",atr="—",candle_range="—",
        sig_a="WAIT",sig_a_cls="wait",strength_a="—",score_a=0,contract_a="—",premium_a="—",cost_a="—",
        sig_b="WAIT",sig_b_cls="wait",strength_b="—",score_b=0,contract_b="—",premium_b="—",cost_b="—",
        sig_c="WAIT",sig_c_cls="wait",strength_c="—",score_c=0,contract_c="—",premium_c="—",cost_c="—",conf_c=0)
    if not ACCESS_TOKEN: return render_template_string(PAGE,**base)
    try:
        fy=fyersModel.FyersModel(client_id=CLIENT_ID,token=ACCESS_TOKEN,is_async=False,log_path="")
        now=datetime.now(timezone.utc); start=now-timedelta(days=5)
        response=fy.history({"symbol":"NSE:NIFTYBANK-INDEX","resolution":"5","date_format":"1","range_from":start.strftime("%Y-%m-%d"),"range_to":now.strftime("%Y-%m-%d"),"cont_flag":"1"})
        candles=response.get("candles",[])
        if len(candles)<60: raise ValueError("Not enough 5-minute candles returned by FYERS.")
        result=calc(candles); sig=result["signal"]; score=result["score"]; spot=result["spot"]
        cond=result["conditions"]; conf=result["confirmations"]; conf_count=sum(x=="PASS" for x in conf)
        cards=[None,None]
        if sig in ("CALL","PUT"):
            for i,budget in enumerate((2000,5000)):
                try: cards[i]=pick_budget_option(spot,sig,budget)
                except Exception: cards[i]=None
        strongest=(sig in ("CALL","PUT") and abs(score)==4 and conf_count>=2)
        citem=cards[1] if strongest and cards[1] else (cards[0] or cards[1])
        def vals(item, budget):
            # IMPORTANT: the signal comes from the live index indicators.
            # Option-chain availability must NOT turn a valid CALL/PUT signal into WAIT.
            if not item:
                return (sig, sig.lower(), result["strength"], abs(score),
                        f"No option ≤ ₹{budget:,}", "—", "—")
            return (sig, sig.lower(), result["strength"], abs(score),
                    item["symbol"], item["premium"], item["cost"])
        a=vals(cards[0],2000)
        b=vals(cards[1],5000)
        c=vals(citem,5000 if strongest else 2000)
        return render_template_string(PAGE,signal=sig,cls=sig.lower(),score=abs(score),strength=result["strength"],spot=round(spot,2),
            c1=cond[0],c2=cond[1],c3=cond[2],c4=cond[3],c1_cls=condition_class(cond[0]),c2_cls=condition_class(cond[1]),c3_cls=condition_class(cond[2]),c4_cls=condition_class(cond[3]),
            x1=conf[0],x2=conf[1],x3=conf[2],x1_cls=condition_class(conf[0]),x2_cls=condition_class(conf[1]),x3_cls=condition_class(conf[2]),
            price=round(result["spot"],2),ema9=round(result["ema9"],2),ema21=round(result["ema21"],2),vwap=round(result["vwap"],2),rsi=round(result["rsi"],2),volume=round(result["volume"],0),avg_volume=round(result["avg_volume"],0),adx=round(result["adx"],1),atr=round(result["atr"],2),candle_range=round(result["candle_range"],2),
            sig_a=a[0],sig_a_cls=a[1],strength_a=a[2],score_a=a[3],contract_a=a[4],premium_a=a[5],cost_a=a[6],
            sig_b=b[0],sig_b_cls=b[1],strength_b=b[2],score_b=b[3],contract_b=b[4],premium_b=b[5],cost_b=b[6],
            sig_c=c[0],sig_c_cls=c[1],strength_c=c[2],score_c=c[3],contract_c=c[4],premium_c=c[5],cost_c=c[6],conf_c=conf_count)
    except Exception as e:
        base["signal"]="WAIT"
        return render_template_string(PAGE,**base)

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
