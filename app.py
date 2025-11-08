from fastapi import FastAPI, Request, HTTPException
import requests
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
ALERT_SECRET = os.getenv("ALERT_SECRET", "")

app = FastAPI()

def tg_send(chat_id: str, text: str) -> bool:
    if not BOT_TOKEN or not chat_id or not text:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception:
        return False

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/send")
async def send_message(request: Request):
    data = await request.json()
    text = data.get("text", "")
    if tg_send(CHAT_ID, text):
        return {"ok": True}
    raise HTTPException(status_code=500, detail="telegram send failed")

@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Alert-Secret") != ALERT_SECRET:
        raise HTTPException(status_code=400, detail="invalid secret")

    data = await request.json()
    text = data.get("text", "")
    if tg_send(CHAT_ID, text):
        return {"ok": True}
    raise HTTPException(status_code=500, detail="telegram send failed")
