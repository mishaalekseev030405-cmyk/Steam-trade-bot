import json, os
from pathlib import Path
import httpx
from scanner import scan
ROOT=Path(__file__).resolve().parent

def main():
    print('CS2 MARKET SCANNER — READ ONLY',flush=True)
    results=scan()
    (ROOT/'latest_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Candidates for manual review:',len(results),flush=True)
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    chat=os.getenv('TELEGRAM_OWNER_ID','').strip()
    if results and token and chat:
        msg='CS2 scanner: '+str(len(results))+' offers for manual review. No purchases made. Check GitHub artifact latest_results.json.'
        try:
            with httpx.Client(timeout=15) as client:
                response=client.post('https://api.telegram.org/bot'+token+'/sendMessage',json={'chat_id':chat,'text':msg})
                response.raise_for_status()
                if not response.json().get('ok'): print('Telegram API rejected message')
        except (httpx.HTTPError,ValueError) as exc:
            print('Telegram delivery failed:',type(exc).__name__)
    print('Real purchases: 0',flush=True)
if __name__=='__main__': main()
