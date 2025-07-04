from fastapi import FastAPI, Request
import httpx
import os
import hmac
import hashlib
import time
import json

app = FastAPI()

# ENV kintamieji (užpildyk .env faile ar aplinkoje)
TOKEN_ID = os.getenv("FXOPEN_TOKEN_ID")
API_KEY = os.getenv("FXOPEN_API_KEY")
API_SECRET = os.getenv("FXOPEN_API_SECRET")
ACCOUNT_ID = os.getenv("FXOPEN_ACCOUNT_ID")  # jei reikia

API_BASE = "https://api.ticktrader.com/api/v2"  # Pasitikrink, ar ne kitoks endpointas

# Funkcija HMAC pasirašymui
def sign_request(payload: str, secret: str):
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


async def send_request(method: str, path: str, body: dict = None):
    timestamp = str(int(time.time() * 1000))
    body_json = json.dumps(body) if body else ""
    message = timestamp + method.upper() + path + body_json
    signature = sign_request(message, API_SECRET)

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "x-ticktrader-timestamp": timestamp,
        "x-ticktrader-signature": signature,
        "Content-Type": "application/json"
    }

    url = API_BASE + path

    async with httpx.AsyncClient() as client:
        if method.lower() == "post":
            resp = await client.post(url, headers=headers, json=body)
        elif method.lower() == "get":
            resp = await client.get(url, headers=headers, params=body)
        else:
            raise Exception(f"Unsupported method {method}")

    if resp.status_code not in [200, 201]:
        raise Exception(f"API klaida: {resp.status_code} - {resp.text}")

    return resp.json()

# Fiksuotas pozicijos dydis
QTY = 1

# Atidaryti poziciją
async def open_position(epic: str, action: str, sl: float = None, tp: float = None):
    path = "/positions"
    side = "Buy" if action.lower() == "buy" else "Sell"

    order = {
        "accountId": ACCOUNT_ID,
        "symbol": epic,
        "side": side,
        "quantity": QTY,
        "orderType": "Market",
        "timeInForce": "GoodTillCancel",
    }

    if sl:
        order["stopLoss"] = {"price": sl}
    if tp:
        order["takeProfit"] = {"price": tp}

    return await send_request("post", path, order)


# Gauti visas atidarytas pozicijas
async def get_positions():
    path = f"/accounts/{ACCOUNT_ID}/positions"
    return await send_request("get", path)


# Uždarom poziciją pagal positionId
async def close_position(position_id: str):
    path = "/positions/close"
    body = {
        "accountId": ACCOUNT_ID,
        "positionId": position_id,
        "quantity": QTY
    }
    return await send_request("post", path, body)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()

        action = data.get("action")  # "buy" arba "sell"
        epic = data.get("epic")      # pvz. "SPY" ar "AAPL"
        sl = data.get("sl")          # optional stop loss price
        tp = data.get("tp")          # optional take profit price

        # Atidarome poziciją
        order_resp = await open_position(epic, action, sl, tp)

        # Grąžinam atsakymą į webhook užklausą
        return {
            "status": "success",
            "orderResponse": order_resp
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/")
def root():
    return {"message": "✅ FXOpen TickTrader botas veikia!"}

