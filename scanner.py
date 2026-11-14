"""Read-only watchlist scanner; no purchasing endpoints."""
import json, math, os, time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parent
BASE="https://market.csgo.com/api/v2"
def number(x):
    try:
        v=float(x)
        return v if math.isfinite(v) and v>0 else None
    except (TypeError,ValueError,OverflowError): return None
def fetch(client,url,params=None):
    for attempt in range(3):
        try:
            response=client.get(url,params=params)
            response.raise_for_status()
            data=response.json()
            if not isinstance(data,dict) or data.get("success") is False: raise ValueError("API rejected request")
            return data
        except (httpx.HTTPError,ValueError):
            if attempt==2: raise
            time.sleep(2**attempt)
def scan():
    key=os.getenv("MARKET_CSGO_API_KEY","").strip()
    if not key: raise RuntimeError("MARKET_CSGO_API_KEY missing")
    names=json.loads((ROOT/'watchlist.json').read_text(encoding='utf-8'))
    if not isinstance(names,list) or not all(isinstance(x,str) and x.strip() for x in names): raise ValueError("Invalid watchlist")
    names=list(dict.fromkeys(names))
    if not names: return []
    path=ROOT/'scan_progress.json'
    state=json.loads(path.read_text()) if path.exists() else {}
    cursor=int(state.get('cursor',0))%len(names)
    selected=[names[(cursor+i)%len(names)] for i in range(min(10,len(names)))]
    results=[]
    with httpx.Client(timeout=25) as client:
        index=fetch(client,BASE+'/full-history/all.json').get('history',{})
        if not isinstance(index,dict): raise ValueError('Invalid history index')
        for name in selected:
            try:
                history_id=index.get(name)
                if history_id is None: continue
                history=fetch(client,BASE+'/full-history/'+str(history_id)+'.json').get('data',{})
                sales=number(history.get('sales7d',{}).get('RUB'))
avg=number(history.get('average7d',{}).get('RUB'))
                if not sales or sales<20 or not avg: continue
                payload=fetch(client,BASE+'/search-list-items-by-hash-name-all',{'key':key,'list_hash_name[]':name})
                if payload.get('currency')!='RUB': continue
                groups=payload.get('data',{})
                offers=groups.get(name,[]) if isinstance(groups,dict) else []
                if not isinstance(offers,list): continue
                for offer in offers:
                    if not isinstance(offer,dict): continue
                    price=number(offer.get('price'))
                    item_id=offer.get('id')
                    if price is None or item_id is None or not str(item_id).strip(): continue
                    price/=100
                    if not 50<=price<=500: continue
                    reference=avg*0.85 # historical estimate, not executable bid
                    profit=reference*0.9-price
                    if math.isfinite(profit) and profit>=50 and profit/price>=0.10:
                        results.append({'name':name,'item_id':str(item_id),'buy_price':round(price,2),'sell_reference':round(reference,2),'sales7d':int(sales),'reference_type':'discounted_7d_average'})
            except (httpx.HTTPError,ValueError,TypeError,KeyError) as error:
                print('Item failed:',name,type(error).__name__)
            time.sleep(0.3)
    path.write_text(json.dumps({'cursor':(cursor+len(selected))%len(names)},indent=2)+'\n')
    return sorted(results,key=lambda x:x['sell_reference']*.9-x['buy_price'],reverse=True)[:30]
