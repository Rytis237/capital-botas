from fastapi import FastAPI, Request, HTTPException
import httpx
import os

app = FastAPI()

IG_API_KEY = os.getenv("IG_API_KEY")
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")
IG_BASE_URL = "https://demo-api.ig.com/gateway/deal"

cst_token = None
security_token = None

async def ig_login():
    global cst_token, security_token

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "identifier": IG_USERNAME,
        "password": IG_PASSWORD
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{IG_BASE_URL}/session", headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"Login failed: {response.text}")

    cst_token = response.headers.get("CST")
    security_token = response.headers.get("X-SECURITY-TOKEN")
    if not cst_token or not security_token:
        raise Exception("Missing auth tokens from login response")

async def place_order(action, epic, size, stop_distance=None, limit_distance=None):
    global cst_token, security_token

    if not cst_token or not security_token:
        await ig_login()

    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": security_token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    direction = "BUY" if action.upper() == "BUY" else "SELL"

    payload = {
        "epic": epic,
        "expiry": "-",
        "direction": direction,
        "size": size,
        "orderType": "MARKET",
        "guaranteedStop": False,
        "forceOpen": True,
        "currencyCode": "USD"
    }

    if stop_distance:
        payload["stopDistance"] = stop_distance
    if limit_distance:
        payload["limitDistance"] = limit_distance

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{IG_BASE_URL}/positions/otc", headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"Order failed: {response.text}")

    return response.json()

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        action = data["action"]
        epic = data["epic"]
        size = float(data["qty"])
        sl = float(data.get("sl", 0))
        tp = float(data.get("tp", 0))

        # IG reikalauja STOP/LIMIT kaip atstumo, ne kainos
        stop_distance = sl if sl > 0 else None
        limit_distance = tp if tp > 0 else None

        result = await place_order(action, epic, size, stop_distance, limit_distance)
        return {"status": "success", "response": result}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/test-env")
def test_env():
    return {
        "IG_API_KEY_loaded": IG_API_KEY is not None,
        "IG_USERNAME_loaded": IG_USERNAME is not None,
        "IG_PASSWORD_loaded": IG_PASSWORD is not None
    }

@app.get("/")
def root():
    return {"message": "IG bot is running!"}

