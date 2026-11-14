import json, math, os, time
from pathlib import Path
import httpx
ROOT = Path(__file__).resolve().parent
BASE = 'https://market.csgo.com/api/v2'
BATCH_SIZE = 20

def positive(x):
    if isinstance(x, dict): x=x.get('RUB')
    try:
        v=float(x)
        return v if math.isfinite(v) and v>0 else None
    except (ValueError,TypeError,OverflowError): return None

def read(path,default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError,ValueError): return default

def write(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)

def fetch(client,endpoint,params=None):
    for attempt in range(3):
        try:
            response=client.get(BASE+endpoint,params=params)
            response.raise_for_status()
            data=response.json()
            if not isinstance(data,dict) or data.get('success') is False:
                raise ValueError('Unexpected API response')
            return data
        except (httpx.HTTPError,ValueError):
            if attempt==2: raise
            time.sleep(2**attempt)

def scan():
    key=os.environ.get('MARKET_CSGO_API_KEY','').strip()
    if not key: raise RuntimeError('MARKET_CSGO_API_KEY missing')
    progress=ROOT/'scan_progress.json'
    state=read(progress,{})
    if not isinstance(state,dict): state={}
    with httpx.Client(timeout=30) as client:
        index=fetch(client,'/full-history/all.json').get('history')
        if not isinstance(index,dict): raise ValueError('History catalog unavailable')
        names=sorted(k for k in index if isinstance(k,str) and k.strip())
        if not names: raise ValueError('Empty catalog')
        cursor=max(0,int(state.get('cursor',0)))%len(names)
        selected=[names[(cursor+i)%len(names)] for i in range(min(BATCH_SIZE,len(names)))]
        print('Catalog:',len(names),'Cursor:',cursor,'Batch:',len(selected),flush=True)
        results=[]; checked_offers=0; failures=0
        for name in selected:
            try:
                hist=fetch(client,'/full-history/'+str(index[name])+'.json').get('data',{})
                if not isinstance(hist,dict): continue
                sales=positive(hist.get('sales7d'))
                average=positive(hist.get('average7d'))
                if sales is None or sales<20 or average is None: continue
                # Historical prices can be in different currencies/units.
                # Do not infer profitability unless RUB unit is explicitly verified.
                history_currency=hist.get('currency')
                if history_currency!='RUB':
                    print('SKIP unverified history currency:',name,flush=True)
                    continue
                payload=fetch(client,'/search-list-items-by-hash-name-all',{'key':key,'list_hash_name[]':name})
                if payload.get('currency')!='RUB': continue
                groups=payload.get('data',{})
                offers=groups.get(name,[]) if isinstance(groups,dict) else []
                if not isinstance(offers,list): continue
                for offer in offers:
                    if not isinstance(offer,dict): continue
                    checked_offers+=1
                    raw=positive(offer.get('price'))
                    item_id=offer.get('id')
                    if raw is None or item_id is None: continue
                    buy=raw/100
                    if not 50<=buy<=500: continue
                    # Historical average must be confirmed RUB, with amount units verified separately.
                    # Conservative: emit candidates for manual review, not profit assertions.
                    results.append({'name':name,'item_id':str(item_id),'buy_price_rub':round(buy,2),'historical_average_raw':average,'sales7d':int(sales),'status':'manual_review_required'})
            except (httpx.HTTPError,ValueError,TypeError,KeyError) as exc:
                failures+=1
                print('Item error:',name,type(exc).__name__,flush=True)
            time.sleep(.25)
    write(progress,{'cursor':(cursor+len(selected))%len(names),'catalog_size':len(names)})
    print('Offers checked:',checked_offers,'Failures:',failures,'Review candidates:',len(results),flush=True)
    return results[:30]
