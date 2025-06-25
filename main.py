from fastapi import FastAPI, Request, HTTPException
import httpx
import os

app = FastAPI()

CAPITAL_API_KEY = os.getenv("CAPITAL_API_KEY")
CAPITAL_LOGIN = os.getenv("CAPITAL_LOGIN")
CAPITAL_PASSWORD = os.getenv("CAPITAL_PASSWORD")

CAPITAL_API_BASE = "https://demo-api.capital.com"

cst_token = None
security_token = None

async def start_session():
    global cst_token, security_token

    if not all([CAPITAL_API_KEY, CAPITAL_LOGIN, CAPITAL_PASSWORD]):
        raise Exception("❌ Environment variables not loaded.")

    async with httpx.AsyncClient() as client:
        url = f"{CAPITAL_API_BASE}/session"
        headers = {
            "X-CAP-API-KEY": CAPITAL_API_KEY
        }
        payload = {
            "identifier": CAPITAL_LOGIN,
            "password": CAPITAL_PASSWORD,
            "encryptedPassword": False
        }
        resp = await client.post(url, headers=headers, json=payload)

        if resp.status_code != 200:
            raise Exception(f"Session start failed: {resp.text}")

        cst_token = resp.headers.get("CST")
        security_token = resp.headers.get("X-SECURITY-TOKEN")

        if not cst_token or not security_token:
            raise Exception("Session tokens missing")

async def place_order(action, symbol, qty, sl, tp):
    global cst_token, security_token

    if not cst_token or not security_token:
        await start_session()

    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "CST": cst_token,
        "X-SECURITY-TOKEN": security_token,
        "Content-Type": "application/json"
    }

    capital_symbol = f"{symbol}.US"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{CAPITAL_API_BASE}/api/v1/instruments/search?searchTerm={capital_symbol}",
            headers=headers
        )
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

        order_resp = await client.post(
            f"{CAPITAL_API_BASE}/api/v1/orders",
            headers=headers,
            json=order_payload
        )

        if order_resp.status_code == 401:
            # Try refresh session
            await start_session()
            headers["CST"] = cst_token
            headers["X-SECURITY-TOKEN"] = security_token
            order_resp = await client.post(
                f"{CAPITAL_API_BASE}/api/v1/orders",
                headers=headers,
                json=order_payload
            )

        if order_resp.status_code != 200:
            raise Exception(f"Order failed: {order_resp.text}")

        return order_resp.json()

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

# ✅ Testavimo endpointas
@app.get("/test-env")
async def test_env():
    return {
        "api_key_loaded": CAPITAL_API_KEY is not None,
        "login_loaded": CAPITAL_LOGIN is not None,
        "password_loaded": CAPITAL_PASSWORD is not None
    }

@app.get("/")
def root():
    return {"message": "Botas veikia!"}


