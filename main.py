from fastapi import FastAPI, Request, HTTPException
import httpx
import os
import json
import asyncio

app = FastAPI()

IG_API_KEY = os.getenv("IG_API_KEY")
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")
IG_API_BASE = "https://demo-api.ig.com/gateway/deal"

cst_token = None
x_security_token = None

# Atsidarytos pozicijos stebėjimui
open_position = None

# ========== IG prisijungimas ==========
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

# ========== Gauti EPIC pagal simbolį ==========
async def get_epic_from_symbol(symbol: str) -> str:
    if not cst_token or not x_security_token:
        await ig_login()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{IG_API_BASE}/markets?searchTerm={symbol}", headers=headers)
        if resp.status_code != 200:
            raise Exception(f"❌ EPIC klaida: {resp.text}")

        data = resp.json()
        results = data.get("markets", [])
        if not results:
            raise Exception("❌ Nerasta atitiktis EPIC")

        return results[0]["epic"]

# ========== Pateikti orderį ==========
async def place_order(action, epic, qty):
    if not cst_token or not x_security_token:
        await ig_login()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    payload = {
        "epic": epic,
        "direction": action,
        "size": float(qty),
        "orderType": "MARKET",
        "forceOpen": True,
        "guaranteedStop": False,
        "currencyCode": "EUR",
        "expiry": "-"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{IG_API_BASE}/positions/otc", headers=headers, json=payload)
        if resp.status_code != 200:
            raise Exception(f"❌ Orderio klaida: {resp.text}")

        data = resp.json()
        return data.get("dealReference")

# ========== Patvirtinti sandorį ==========
async def get_deal_confirmation(deal_reference: str):
    if not cst_token or not x_security_token:
        await ig_login()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{IG_API_BASE}/confirms/{deal_reference}", headers=headers)
        if resp.status_code != 200:
            raise Exception(f"❌ Confirm klaida: {resp.text}")
        return resp.json()

# ========== Gauti rinkos kainą ==========
async def get_market_price(epic: str) -> float:
    if not cst_token or not x_security_token:
        await ig_login()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{IG_API_BASE}/markets/{epic}", headers=headers)
        if resp.status_code != 200:
            raise Exception(f"❌ Kainos gavimo klaida: {resp.text}")

        data = resp.json()
        return data["snapshot"]["bid"]

# ========== Uždaryti poziciją ==========
async def close_position(deal_id: str, direction: str, epic: str, qty: float):
    if not cst_token or not x_security_token:
        await ig_login()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "_method": "DELETE"
    }

    close_dir = "SELL" if direction == "BUY" else "BUY"

    payload = {
        "dealId": deal_id,
        "direction": close_dir,
        "epic": epic,
        "size": qty,
        "orderType": "MARKET"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{IG_API_BASE}/positions/otc", headers=headers, json=payload)
        if resp.status_code != 200:
            raise Exception(f"❌ Uždarymo klaida: {resp.text}")

# ========== Stebėjimo ciklas ==========
async def monitor_position():
    global open_position
    if not open_position:
        return

    epic = open_position["epic"]
    sl = open_position["sl"]
    tp = open_position["tp"]
    deal_id = open_position["deal_id"]
    direction = open_position["direction"]
    qty = open_position["qty"]

    try:
        current_price = await get_market_price(epic)

        if (direction == "BUY" and (current_price <= sl or current_price >= tp)) or \
           (direction == "SELL" and (current_price >= sl or current_price <= tp)):

            await close_position(deal_id, direction, epic, qty)
            print(f"✅ Pozicija uždaryta ties kaina {current_price}")
            open_position = None

    except Exception as e:
        print(f"❌ Stebėjimo klaida: {e}")

# ========== Webhook ==========
@app.post("/webhook")
async def webhook(request: Request):
    global open_position
    try:
        data = await request.json()

        action = data["action"].upper()
        symbol = data["symbol"]
        sl = float(data["sl"])
        tp = float(data["tp"])
        qty = 1

        epic = await get_epic_from_symbol(symbol)
        deal_reference = await place_order(action, epic, qty)
        confirmation = await get_deal_confirmation(deal_reference)

        if confirmation.get("dealStatus") != "ACCEPTED":
            return {"status": "error", "message": f"Order rejected: {confirmation.get('reason')}", "confirmation": confirmation}

        open_position = {
            "epic": epic,
            "deal_id": confirmation.get("dealId"),
            "direction": action,
            "sl": sl,
            "tp": tp,
            "qty": qty
        }

        return {
            "status": "success",
            "symbol": symbol,
            "epic": epic,
            "dealReference": deal_reference,
            "confirmation": confirmation
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

# ========== Atnaujinimo ciklas ==========
@app.on_event("startup")
async def startup_event():
    async def price_check_loop():
        while True:
            await monitor_position()
            await asyncio.sleep(2)  # tikrina kas 2 sek

    asyncio.create_task(price_check_loop())

# ========= Testas =========
@app.get("/")
def root():
    return {"message": "✅ IG botas veikia!"}

@app.get("/test-env")
def test_env():
    return {
        "IG_API_KEY_loaded": IG_API_KEY is not None,
        "IG_USERNAME_loaded": IG_USERNAME is not None,
        "IG_PASSWORD_loaded": IG_PASSWORD is not None
    }


