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
open_positions = {}  # saugo atidarytas pozicijas {epic: {"direction": ..., "sl": ..., "tp": ...}}


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


async def get_market_price(epic: str):
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
            raise Exception("❌ Nepavyko gauti rinkos kainos")
        data = resp.json()
        bid = float(data["snapshot"]["bid"])
        offer = float(data["snapshot"]["offer"])
        return (bid + offer) / 2


async def close_position(epic: str, direction: str):
    if not cst_token or not x_security_token:
        await ig_login()
    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": x_security_token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    opposite = "SELL" if direction == "BUY" else "BUY"
    payload = {
        "epic": epic,
        "direction": opposite,
        "size": 1,
        "orderType": "MARKET"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{IG_API_BASE}/positions/otc", headers=headers, json=payload)
        return resp.status_code == 200


async def monitor_position(epic: str):
    await asyncio.sleep(5)  # delay before starting monitoring
    while epic in open_positions:
        try:
            price = await get_market_price(epic)
            data = open_positions[epic]
            direction = data["direction"]
            sl = data["sl"]
            tp = data["tp"]

            if direction == "BUY" and (price <= sl or price >= tp):
                await close_position(epic, direction)
                del open_positions[epic]
            elif direction == "SELL" and (price >= sl or price <= tp):
                await close_position(epic, direction)
                del open_positions[epic]
        except Exception as e:
            print(f"❌ Klaida stebint poziciją: {e}")
        await asyncio.sleep(3)


async def place_order(action, epic, qty):
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
    order_payload = {
        "epic": epic,
        "direction": action,
        "size": qty,
        "orderType": "MARKET",
        "forceOpen": True,
        "guaranteedStop": False,
        "currencyCode": "EUR",
        "expiry": "-"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{IG_API_BASE}/positions/otc", headers=headers, json=order_payload)
        if resp.status_code != 200:
            raise Exception(f"❌ Orderio klaida: {resp.text}")
        return resp.json()


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        action = data["action"].upper()
        symbol = data["symbol"]
        qty = 1
        sl = float(data["sl"])
        tp = float(data["tp"])

        # gauti epic
        epic = await get_epic_from_symbol(symbol)
        result = await place_order(action, epic, qty)

        open_positions[epic] = {"direction": action, "sl": sl, "tp": tp}
        asyncio.create_task(monitor_position(epic))

        return {
            "status": "success",
            "message": f"✅ Pozicija atidaryta {action} {symbol} ({epic})",
            "dealReference": result.get("dealReference")
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


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
            raise Exception("❌ Nepavyko gauti epic")
        markets = resp.json().get("markets", [])
        if not markets:
            raise Exception("❌ Nerasta atitinkamo instrumento")
        return markets[0]["epic"]


@app.get("/")
def root():
    return {"message": "✅ IG botas veikia (su SL/TP stebėjimu)!"}


@app.get("/test-env")
def test_env():
    return {
        "IG_API_KEY_loaded": IG_API_KEY is not None,
        "IG_USERNAME_loaded": IG_USERNAME is not None,
        "IG_PASSWORD_loaded": IG_PASSWORD is not None
    }


