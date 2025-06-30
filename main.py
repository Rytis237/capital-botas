
from fastapi import FastAPI, Request, HTTPException
import httpx
import os
import json

app = FastAPI()

# IG API credentials from environment variables
IG_API_KEY = os.getenv("IG_API_KEY")
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")

IG_API_BASE = "https://demo-api.ig.com/gateway/deal"

# Session tokens
cst_token = None
x_security_token = None


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


async def get_epic_from_symbol(symbol: str) -> str:
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
        resp = await client.get(f"{IG_API_BASE}/markets?searchTerm={symbol}", headers=headers)
        if resp.status_code != 200:
            raise Exception(f"❌ Nepavyko gauti epic: {resp.text}")

        data = resp.json()
        results = data.get("markets", [])
        if not results:
            raise Exception("❌ Nerasta atitiktis epic simboliui")

        return results[0]["epic"]


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
        "stopDistance": float(sl),
        "limitDistance": float(tp),
        "currencyCode": "USD",
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


@app.post("/webhook")
async def webhook(request: Request):
    try:
        raw_body = await request.body()
        data = json.loads(raw_body)

        action = data["action"]
        epic = data["epic"]
        qty = 1.0  # arba kitas galiojantis dydis
        sl = float(data["sl"])
        tp = float(data["tp"])

        result = await place_order(action, epic, qty, sl, tp)
        confirmation = await get_deal_confirmation(result["dealReference"])

        return {
            "status": "success",
            "epic": epic,
            "qty": qty,
            "dealReference": result["dealReference"],
            "confirmation": confirmation
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"❌ Klaida: {str(e)}")

@app.get("/epic-info/{epic}")
async def epic_info(epic: str):
    try:
        info = await get_epic_info(epic)
        dealing = info.get("market", {}).get("dealingRules", {})
        return {
            "epic": epic,
            "minDealSize": dealing.get("minDealSize"),
            "dealSizeIncrement": dealing.get("dealSizeIncrement")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



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

async def get_epic_info(epic: str):
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
        raise Exception(f"Negalima gauti info apie epic: {resp.text}")
    return resp.json()

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
            raise Exception(f"❌ Nepavyko gauti deal confirm: {resp.text}")

        return resp.json()

