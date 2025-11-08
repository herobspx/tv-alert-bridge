import os, re, hmac, hashlib
from typing import Any, Dict
import httpx
from fastapi import FastAPI, Request, HTTPException

# تحميل .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

def _clean(s: str) -> str:
    # تنظيف التوكن من المحارف الخفية (BOM/ZWSP)
    return re.sub(r'[\u200B-\u200D\uFEFF]', '', (s or '').strip())

BOT_TOKEN = _clean(os.getenv("BOT_TOKEN", ""))
CHAT_ID_DEFAULT = _clean(os.getenv("CHAT_ID", ""))
ALERT_SECRET = _clean(os.getenv("ALERT_SECRET", ""))

app = FastAPI(title="tv-alert-bridge", version="1.0.0")

async def tg_send(chat_id: str, text: str) -> bool:
    if not BOT_TOKEN or not chat_id or not text:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, data={"chat_id": chat_id, "text": text})
        return r.status_code == 200 and r.json().get("ok") is True

def format_msg(payload: Dict[str, Any]) -> str:
    # يدعم صيغ مختلفة من TradingView: text/message/fields…
    symbol = payload.get("symbol") or payload.get("ticker") or payload.get("SYMBOL") or ""
    side   = payload.get("side") or payload.get("SIDE") or payload.get("signal") or payload.get("SIGNAL") or ""
    price  = payload.get("price") or payload.get("PRICE") or payload.get("close") or payload.get("CLOSE") or ""
    tf     = payload.get("timeframe") or payload.get("TIMEFRAME") or payload.get("tf") or ""
    note   = payload.get("text") or payload.get("message") or payload.get("note") or ""

    # رسالة بسيطة ومناسبة للقناة
    lines = []
    if note:   lines.append(str(note))
    if symbol: lines.append(f"الرمز: {symbol}")
    if side:   lines.append(f"الإشارة: {side}")
    if price:  lines.append(f"السعر: {price}")
    if tf:     lines.append(f"الفريم: {tf}")
    if not lines:
        lines = ["تنبيه من TradingView"]
    return "\n".join(lines)

def verify_secret(header_secret: str, body_secret: str) -> bool:
    exp = ALERT_SECRET
    if not exp:
        return True  # لو ما ضبطت سر، لا تتحقق (يفضل تضبطه)
    cand = _clean(header_secret) or _clean(body_secret)
    return hmac.compare_digest(exp, cand)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/send")
async def send(req: Request):
    # إرسال يدوي: {"text": "...", "chat_id":"-100..."}
    try:
        p = await req.json()
    except Exception as e:
        raise HTTPException(400, f"invalid json: {e}")
    text = _clean(p.get("text", ""))
    chat_id = _clean(p.get("chat_id", CHAT_ID_DEFAULT))
    if not text:
        raise HTTPException(400, "text is required")
    if not chat_id:
        raise HTTPException(400, "chat_id missing")
    ok = await tg_send(chat_id, text)
    if not ok:
        raise HTTPException(500, "telegram send failed")
    return {"ok": True}

@app.post("/webhook")
async def webhook(req: Request):
    # استقبال تنبيه TradingView
    header_secret = _clean(req.headers.get("X-Alert-Secret", ""))
    try:
        payload = await req.json()
    except Exception as e:
        raise HTTPException(400, f"invalid json: {e}")

    body_secret = _clean(str(payload.get("secret", "")))
    if not verify_secret(header_secret, body_secret):
        raise HTTPException(401, "invalid secret")

    chat_id = _clean(payload.get("chat_id", CHAT_ID_DEFAULT))
    if not chat_id:
        raise HTTPException(400, "chat_id missing (env CHAT_ID or body.chat_id)")
    text = format_msg(payload)
    ok = await tg_send(chat_id, text)
    if not ok:
        raise HTTPException(500, "telegram send failed")
    return {"ok": True}
