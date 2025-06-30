import asyncio
from fastapi import FastAPI, Request, HTTPException
import httpx
import os

app = FastAPI()

IG_API_KEY = os.getenv("IG_API_KEY")
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")
IG_API_BASE = "https://demo-api.ig.com/gateway/deal"

cst_token = None
x_security_token = None

# Laikysime aktyvias pozicijas su sl ir tp
active_positions = {}

async def ig_login():
    global cst_token, x_security_token
    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "identifier": IG_USERNAME,
        "password": IG_PASSWORD,
        "encryptedPassword": False
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{IG_API_BASE}/session", headers=headers, json=payload)
        if resp.status_code != 200:
            raise Exception(f"❌ Prisijungimo klaida: {resp.text}")
        cst_token = resp.headers.get("CST")
        x_security_token = resp.headers.get("X-SECURITY-TOKEN")
        if not cst_token or not x_security_token:
            raise Exception("❌ Nepavyko gauti autentifikacijos tokenų")

async def get_price(epic: str):
    global cst_token, x_security_token
    if not cst_token or not x_security_token:
        await ig_login()
    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Accept": "application/json"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{IG_API_BASE}/prices/{epic}", headers=headers)
        if resp.status_code != 200:
            raise Exception(f"Negalima gauti kainos: {resp.text}")
        data = resp.json()
        # Grąžinsime ask ir bid kainas
        return {
            "bid": data["prices"][0]["bid"],
            "ask": data["prices"][0]["ask"]
        }

async def close_position(deal_id, size, direction):
    global cst_token, x_security_token
    if not cst_token or not x_security_token:
        await ig_login()
    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    # Uždarome poziciją priešinga kryptimi
    close_direction = "SELL" if direction == "BUY" else "BUY"
    order_payload = {
        "dealId": deal_id,
        "direction": close_direction,
        "size": float(size),
        "orderType": "MARKET",
        "currencyCode": "EUR"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{IG_API_BASE}/positions/otc/close", headers=headers, json=order_payload)
        if resp.status_code != 200:
            raise Exception(f"❌ Uždarymo klaida: {resp.text}")
        return resp.json()

async def monitor_positions():
    while True:
        try:
            for deal_id, pos in list(active_positions.items()):
                epic = pos["epic"]
                sl = pos["sl"]
                tp = pos["tp"]
                direction = pos["direction"]
                size = pos["size"]

                prices = await get_price(epic)
                bid = prices["bid"]
                ask = prices["ask"]

                # Jeigu BUY pozicija - sl tikrinam bid, tp tikrinam bid
                # Jeigu SELL pozicija - sl tikrinam ask, tp tikrinam ask
                price_to_check = bid if direction == "BUY" else ask

                if (direction == "BUY" and (price_to_check <= sl or price_to_check >= tp)) or \
                   (direction == "SELL" and (price_to_check >= sl or price_to_check <= tp)):
                    print(f"Uždaryti poziciją {deal_id} - kaina pasiekė SL arba TP")
                    await close_position(deal_id, size, direction)
                    del active_positions[deal_id]

        except Exception as e:
            print("Klaida monitoringo metu:", e)

        await asyncio.sleep(5)  # kas 5 sek patikrinti kainas

@app.on_event("startup")
async def startup_event():
    await ig_login()
    asyncio.create_task(monitor_positions())

async def place_order(action, epic, qty, sl, tp):
    global cst_token, x_security_token
    if not cst_token or not x_security_token:
        await ig_login()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    direction = action.upper()
    order_payload = {
        "epic": epic,
        "direction": direction,
        "size": float(qty),
        "orderType": "MARKET",
        "guaranteedStop": False,
        "forceOpen": True,
        "currencyCode": "EUR",
        "expiry": "-"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{IG_API_BASE}/positions/otc", headers=headers, json=order_payload)
        if resp.status_code == 401:
            await ig_login()
            headers["CST"] = cst_token
            headers["X-SECURITY-TOKEN"] = x_security_token
            resp = await client.post(f"{IG_API_BASE}/positions/otc", headers=headers, json=order_payload)
        if resp.status_code != 200:
            raise Exception(f"❌ Orderio klaida: {resp.text}")
        result = resp.json()

        # Išsaugom poziciją aktyvių stebėjimui
        deal_id = result.get("dealId") or result.get("dealReference")
        if deal_id:
            active_positions[deal_id] = {
                "epic": epic,
                "sl": sl,
                "tp": tp,
                "direction": direction,
                "size": qty
            }

        return result

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        action = data["action"]    # "BUY" arba "SELL"
        epic = data["epic"]
        qty = float(data.get("qty", 0.08))
        sl = float(data["sl"])
        tp = float(data["tp"])
        result = await place_order(action, epic, qty, sl, tp)
        return {"status": "success", "order": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

