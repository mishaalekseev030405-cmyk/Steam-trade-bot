
import os
import asyncio
import httpx

async def main():
    key = os.getenv("MARKET_CSGO_API_KEY")

    if not key:
        print("ERROR: API key not found")
        return

    url = "https://market.csgo.com/api/v2/get-money"
    params = {"key": key}

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, params=params)
        print("HTTP status:", response.status_code)

        data = response.json()
        print("API success:", data.get("success"))

        if data.get("success"):
            print("API connection successful")
        else:
            print("API error:", data.get("error"))

asyncio.run(main())
