from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
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

# Saugo atidarytas pozicijas: dealId -> dict su info ir SL, TP
open_positions = {}

async def ig_login():
    global cst_token, x_security_token

    if not IG_API_KEY or not IG_USERNAME or not IG_PASSWORD:
        raise Exception("❌ Trūksta IG API kintamųjų (env variables)")

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

async def ensure_tokens():
    global cst_token, x_security_token
    if not cst_token or not x_security_token:
        await ig_login()

async def place_order(action, epic, qty):
    await ensure_tokens()

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

        return resp.json()

async def get_deal_confirmation(deal_reference: str):
    await ensure_tokens()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{IG_API_BASE}/confirms/{deal_reference}", headers=headers)
        if resp.status_code != 200:
            raise Exception(f"❌ Nepavyko gauti deal confirm: {resp.text}")
        return resp.json()

async def get_positions():
    await ensure_tokens()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{IG_API_BASE}/positions", headers=headers)
        if resp.status_code != 200:
            raise Exception(f"❌ Nepavyko gauti pozicijų: {resp.text}")
        return resp.json()

async def get_market_price(epic):
    # Gaunam paskutinę kainą, naudodami /markets endpoint
    await ensure_tokens()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{IG_API_BASE}/markets/{epic}", headers=headers)
        if resp.status_code != 200:
            raise Exception(f"❌ Nepavyko gauti rinkos kainos: {resp.text}")
        data = resp.json()
        # Grąžinam paskutinę kainą (bid arba offer, priklausomai nuo direction)
        return data.get("market", {}).get("snapshot", {}).get("bid"), data.get("market", {}).get("snapshot", {}).get("offer")

async def close_position(deal_id, epic, size, direction):
    await ensure_tokens()

    close_direction = "SELL" if direction == "BUY" else "BUY"

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    order_payload = {
        "dealId": deal_id,
        "epic": epic,
        "size": float(size),
        "direction": close_direction,
        "orderType": "MARKET",
        "guaranteedStop": False,
        "forceOpen": False,
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
            raise Exception(f"❌ Uždarymo orderio klaida: {resp.text}")

        return resp.json()

async def monitor_positions():
    while True:
        to_remove = []
        for deal_id, pos in open_positions.items():
            try:
                bid, offer = await get_market_price(pos["epic"])
                current_price = bid if pos["direction"] == "BUY" else offer
                if current_price is None:
                    continue
                sl = pos["sl"]
                tp = pos["tp"]

                # Tikrinti ar pasiektas sl arba tp
                if (pos["direction"] == "BUY" and (current_price <= sl or current_price >= tp)) or \
                   (pos["direction"] == "SELL" and (current_price >= sl or current_price <= tp)):
                    print(f"Uždarymas pozicijos {deal_id}, kaina: {current_price}")
                    await close_position(deal_id, pos["epic"], pos["size"], pos["direction"])
                    to_remove.append(deal_id)

            except Exception as e:
                print(f"Monitoringo klaida: {e}")

        for deal_id in to_remove:
            open_positions.pop(deal_id, None)

        await asyncio.sleep(5)  # kartoti kas 5 sek.

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(monitor_positions())

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()

        action = data["action"]  # BUY arba SELL
        epic = data["epic"]
        qty = float(data.get("qty", 1))  # fiksuotas qty arba gaunamas iš alert
        sl = float(data["sl"])  # Stop Loss kaina (pvz., 1.1234)
        tp = float(data["tp"])  # Take Profit kaina

        order_result = await place_order(action, epic, qty)
        deal_ref = order_result.get("dealReference")
        if not deal_ref:
            raise Exception("Nėra dealReference atsakyme")

        confirm = await get_deal_confirmation(deal_ref)
        deal_id = confirm.get("dealId")
        if not deal_id:
            raise Exception("Nėra dealId patvirtinime")

        # Išsaugom pozicijos info stebėjimui
        open_positions[deal_id] = {
            "epic": epic,
            "size": qty,
            "direction": action.upper(),
            "sl": sl,
            "tp": tp,
        }

        return {
            "status": "success",
            "dealReference": deal_ref,
            "dealId": deal_id,
            "epic": epic,
            "qty": qty,
            "sl": sl,
            "tp": tp
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"❌ Klaida: {str(e)}")

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
