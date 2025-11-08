from fastapi import FastAPI, Request, HTTPException
import requests
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
ALERT_SECRET = os.getenv("ALERT_SECRET", "")


def format_signal(symbol:str=None, side:str=None, price=None, tf=None):
    # تطبيع المدخلات
    symbol = (symbol or "").strip()
    side   = (side or "").strip().upper()
    tf     = (str(tf or "")).strip()
    # تحويل مختصر
    if side in ("CALL","LONG","BUY","UP"): side = "CALL 🔵"
    elif side in ("PUT","SHORT","SELL","DOWN"): side = "PUT 🔴"
    # تنسيق السعر
    try:
        price = float(price)
        price_txt = f"{price:,.2f}"
    except Exception:
        price_txt = str(price or "-")
    # بناء النص
    msg = []
    if symbol: msg.append(f"📊 {symbol}")
    if side:   msg.append(f"إشارة : {side}")
    msg.append(f"💵 السعر: {price_txt}")
    if tf:     msg.append(f"🕒 الإطار الزمني: {tf}")
    msg.append("⚠️ جميع ما يُطرح لا يُعدّ توصية مالية.")
    return "\n".join(msg)

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
