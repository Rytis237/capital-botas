from fastapi import FastAPI, Request
import httpx
import os
import json

app = FastAPI()

FXOPEN_BASE_URL = os.getenv("FXOPEN_BASE_URL")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_KEY = os.getenv("CLIENT_KEY")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")


async def fxopen_auth():
    """Gauti access token iš FXOpen API"""
    url = f"{FXOPEN_BASE_URL}/auth/token"
    headers = {"Content-Type": "application/json"}
    payload = {
        "client_id": CLIENT_ID,
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json().get("access_token")


async def place_order(token, symbol, action, qty):
    url = f"{FXOPEN_BASE_URL}/orders"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    order_payload = {
        "symbol": symbol,
        "side": action.upper(),
        "quantity": qty,
        "type": "market",
        "time_in_force": "GTC"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=order_payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()

        action = data.get("action")  # "BUY" arba "SELL"
        symbol = data.get("symbol")  # pvz. "SPY"
        qty = 0.01  # fiksuotas kiekis

        if not all([action, symbol]):
            return {
                "status": "error",
                "message": "Trūksta būtinų laukų: action arba symbol"
            }

        token = await fxopen_auth()
        order_response = await place_order(token, symbol, action, qty)

        return {
            "status": "success",
            "order": order_response
        }

    except httpx.HTTPStatusError as e:
        return {
            "status": "error",
            "message": f"HTTP klaida: {e.response.status_code} - {e.response.text}"
        }
    except httpx.RequestError as e:
        return {
            "status": "error",
            "message": f"Tinklo klaida: {str(e)} | {repr(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Klaida: {str(e)} | {repr(e)}"
        }


@app.get("/")
def root():
    return {"message": "✅ FXOpen botas veikia!"}


@app.get("/test-env")
def test_env():
    return {
        "FXOPEN_BASE_URL_loaded": FXOPEN_BASE_URL is not None,
        "CLIENT_ID_loaded": CLIENT_ID is not None,
        "CLIENT_KEY_loaded": CLIENT_KEY is not None,
        "CLIENT_SECRET_loaded": CLIENT_SECRET is not None
    }

