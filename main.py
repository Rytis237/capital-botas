from fastapi import FastAPI, Request, HTTPException
import httpx
import os
import json

app = FastAPI()

FXOPEN_CLIENT_ID = os.getenv("FXOPEN_CLIENT_ID")
FXOPEN_CLIENT_SECRET = os.getenv("FXOPEN_CLIENT_SECRET")
FXOPEN_BASE_URL = os.getenv("FXOPEN_BASE_URL", "https://ttdemo.fxopen.com:8443")

ACCESS_TOKEN = None

async def get_access_token():
    global ACCESS_TOKEN

    url = f"{FXOPEN_BASE_URL}/token"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "client_credentials",
        "client_id": FXOPEN_CLIENT_ID,
        "client_secret": FXOPEN_CLIENT_SECRET
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=headers, data=data)
            resp.raise_for_status()
            token_data = resp.json()
            ACCESS_TOKEN = token_data["access_token"]
        except httpx.HTTPStatusError as e:
            raise Exception(f"❌ HTTP klaida ({e.response.status_code}): {e.response.text}")
        except httpx.RequestError as e:
            raise Exception(f"❌ Tinklo klaida: {e}")
        except Exception as e:
            raise Exception(f"❌ Nenumatyta klaida: {str(e)}")


async def place_order(action: str, symbol: str, sl: float, tp: float):
    global ACCESS_TOKEN
    if not ACCESS_TOKEN:
        await get_access_token()

    url = f"{FXOPEN_BASE_URL}/connect/trading/open_trade"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "Symbol": symbol,
        "Volume": 0.01,  # Fiksuotas kiekis
        "Side": "buy" if action.upper() == "BUY" else "sell",
        "Type": "market",
        "StopLossPrice": sl,
        "TakeProfitPrice": tp
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return {"status": "success", "response": resp.json()}
        except httpx.HTTPStatusError as e:
            return {
                "status": "error",
                "message": f"HTTP klaida {e.response.status_code}: {e.response.text}"
            }
        except httpx.RequestError as e:
            return {"status": "error", "message": f"Tinklo klaida: {str(e)}"}
        except Exception as e:
            return {"status": "error", "message": f"Nenumatyta klaida: {str(e)}"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        body = await request.body()
        data = json.loads(body)

        action = data.get("action")
        symbol = data.get("symbol")
        sl = float(data.get("sl"))
        tp = float(data.get("tp"))

        if not all([action, symbol, sl, tp]):
            raise ValueError("Trūksta laukų: action, symbol, sl, tp")

        return await place_order(action, symbol, sl, tp)

    except Exception as e:
        return {"status": "error", "message": f"❌ Klaida: {str(e)}"}


@app.get("/")
def root():
    return {"message": "✅ FXOpen botas veikia!"}


@app.get("/test-env")
def test_env():
    return {
        "FXOPEN_CLIENT_ID": FXOPEN_CLIENT_ID is not None,
        "FXOPEN_CLIENT_SECRET": FXOPEN_CLIENT_SECRET is not None,
        "FXOPEN_BASE_URL": FXOPEN_BASE_URL
    }
