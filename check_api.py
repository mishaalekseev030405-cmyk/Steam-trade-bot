import asyncio, os, httpx
async def main():
    key=os.getenv('MARKET_CSGO_API_KEY','').strip()
    if not key: raise RuntimeError('MARKET_CSGO_API_KEY missing')
    async with httpx.AsyncClient(timeout=20) as client:
        response=await client.get('https://market.csgo.com/api/v2/get-money',params={'key':key})
        response.raise_for_status()
        data=response.json()
        if not isinstance(data,dict) or data.get('success') is not True:
            raise RuntimeError('Market API authentication or response failed')
    print('Market API check OK')
if __name__=='__main__': asyncio.run(main())
