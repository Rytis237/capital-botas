from fastapi import FastAPI, Request, HTTPException
import httpx
import os

app = FastAPI()

CAPITAL_API_BASE = "https://demoapi.capital.com"
CAPITAL_CLIENT_ID = os.getenv("CAPITAL_CLIENT_ID")
CAPITAL_CLIENT_SECRET = os.getenv("CAPITAL_CLIENT_SECRET")

auth_token = None

async def get_auth_token():
    global auth_token
    if auth_token:
        return auth_token

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{CAPITAL_API_BASE}/oauth2/token", data={
            "grant_type": "client_credentials",
            "client_id": CAPITAL_CLIENT_ID,
            "client_secret": CAPITAL_CLIENT_SECRET
        })
        if resp.status_code != 200:
            raise Exception(f"Auth failed: {resp.text}")
        data = resp.json()
        auth_token = data["access_token"]
        return auth_token

async def place_order(action, symbol, qty, sl, tp):
    token = await get_auth_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    capital_symbol = f"{symbol}.US"

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CAPITAL_API_BASE}/api/v1/instruments/search?searchTerm={capital_symbol}", headers=headers)
        if resp.status_code != 200 or not resp.json().get("results"):
            raise Exception("Instrument not found")
        instrument_id = resp.json()["results"][0]["epic"]

    direction = "BUY" if action.upper() == "BUY" else "SELL"

    order_payload = {
        "epic": instrument_id,
        "direction": direction,
        "size": float(qty),
        "orderType": "MARKET",
        "forceOpen": True,
        "stopLevel": float(sl),
        "limitLevel": float(tp),
        "guaranteedStop": False
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{CAPITAL_API_BASE}/api/v1/orders", headers=headers, json=order_payload)
        if resp.status_code != 200:
            raise Exception(f"Order failed: {resp.text}")
        return resp.json()

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        action = data["action"]
        symbol = data["symbol"]
        sl = float(data["sl"])
        tp = float(data["tp"])
        qty = float(data["qty"])

        order_resp = await place_order(action, symbol, qty, sl, tp)
        return {"status": "success", "order": order_resp}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
