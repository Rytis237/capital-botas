from fastapi import FastAPI, Request, HTTPException
import os
import httpx

app = FastAPI()

# 🔐 Aplinkos kintamieji
CAPITAL_API_KEY = os.getenv("CAPITAL_API_KEY")
CAPITAL_LOGIN = os.getenv("CAPITAL_LOGIN")
CAPITAL_PASSWORD = os.getenv("CAPITAL_PASSWORD")

CAPITAL_API_BASE = "https://demo-api-capital.backend-capital.com"

# 🔐 Sesijos tokenai
cst_token = None
security_token = None

# 📡 Sesijos pradžia
async def start_session():
    global cst_token, security_token

    if not all([CAPITAL_API_KEY, CAPITAL_LOGIN, CAPITAL_PASSWORD]):
        raise Exception("❌ Trūksta environment kintamųjų.")

    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "identifier": CAPITAL_LOGIN,
        "password": CAPITAL_PASSWORD,
        "encryptedPassword": False
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{CAPITAL_API_BASE}/session", headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"❌ Prisijungimo klaida: {response.text}")

    cst_token = response.headers.get("CST")
    security_token = response.headers.get("X-SECURITY-TOKEN")

    if not cst_token or not security_token:
        raise Exception("❌ Nepavyko gauti sesijos tokenų.")

# 📈 Pavedimo atlikimas
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

    symbol_code = f"{symbol}.US"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{CAPITAL_API_BASE}/api/v1/instruments/search?searchTerm={symbol_code}",
            headers=headers
        )
        if resp.status_code != 200 or not resp.json().get("results"):
            raise Exception("❌ Instrumentas nerastas.")

        epic = resp.json()["results"][0]["epic"]

        order_payload = {
            "epic": epic,
            "direction": action.upper(),
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

        if order_resp.status_code != 200:
            raise Exception(f"❌ Order nepavyko: {order_resp.text}")

        return order_resp.json()

# 📥 Webhook endpoint
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        action = data["action"]
        symbol = data["symbol"]
        qty = float(data["qty"])
        sl = float(data["sl"])
        tp = float(data["tp"])

        result = await place_order(action, symbol, qty, sl, tp)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# 🔧 Test endpoint
@app.get("/test-env")
def test_env():
    return {
        "api_key": CAPITAL_API_KEY is not None,
        "login": CAPITAL_LOGIN is not None,
        "password": CAPITAL_PASSWORD is not None
    }

# 🏁 Pagrindinis puslapis
@app.get("/")
def root():
    return {"message": "Capital Botas veikia ✅"}

