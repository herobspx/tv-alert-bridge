import os


def _arabic_interval(tf) -> str:
    s = str(tf).strip().upper()
    if s.endswith("S"):
        n = s[:-1] or "0"
        n_int = int(float(n))
        unit = "ثانية" if n_int == 1 else "ثوان"
        return f"{n_int} {unit}"
    if s.endswith("H"):
        n = s[:-1] or "0"
        n_int = int(float(n))
        unit = "ساعة" if n_int == 1 else "ساعات"
        return f"{n_int} {unit}"
    # افتراضي دقائق
    try:
        n_int = int(float(s))
        unit = "دقيقة" if n_int == 1 else "دقائق"
        return f"{n_int} {unit}"
    except:
        return s or "-"


from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

BOT_TOKEN   = os.getenv("BOT_TOKEN")
CHAT_ID     = os.getenv("CHAT_ID")
ALERT_SECRET= os.getenv("ALERT_SECRET")

app = FastAPI()
client = httpx.AsyncClient(timeout=15.0)

def _fmt_tv_message(payload: dict) -> str:
    # رسالة افتراضية مبسطة؛ نقدر نرجع تنسيقك العربي لاحقًا بعد ما نثبت الإرسال
    return payload.get("text") or (
        f"📊 {payload.get('symbol','?')}\n"
        f"إشارة : {payload.get('side','?')}\n"
        f"💵 السعر: {payload.get('price','?')}\n"
        f"🕒 الإطار الزمني: {payload.get('timeframe','?')}\n"
        f"⚠️ جميع ما يُطرح لا يُعدّ توصية."
    )

async def tg_send(text: str, parse_mode: str | None = None):
    if not BOT_TOKEN or not CHAT_ID:
        return False, "BOT_TOKEN/CHAT_ID not set"
    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        data["parse_mode"] = parse_mode
    try:
        r = await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=data)
        ok = False
        info = None
        try:
            info = r.json()
            ok = bool(info.get("ok"))  # Telegram-style ok
        except Exception:
            info = {"status": r.status_code, "text": r.text}
        return (True, info) if ok else (False, info)
    except Exception as e:
        return False, str(e)

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/send")
async def send(req: Request):
    payload = await req.json()
    text = payload.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="missing 'text'")
    ok, info = await tg_send(text)
    if not ok:
        return JSONResponse({"ok": False, "reason": "telegram_failed", "info": info}, status_code=502)
    return {"ok": True}

@app.post("/webhook")
async def webhook(req: Request):
    payload = await req.json()
    # قبول السر من الهيدر أو JSON
    header_secret = req.headers.get("X-Alert-Secret")
    body_secret   = payload.get("secret")
    valid = (ALERT_SECRET and header_secret == ALERT_SECRET) or (ALERT_SECRET and body_secret == ALERT_SECRET)
    if not valid:
        raise HTTPException(status_code=400, detail="invalid secret")

    text = _fmt_tv_message(payload)
    ok, info = await tg_send(text)
    if not ok:
        return JSONResponse({"ok": False, "reason": "telegram_failed", "info": info}, status_code=502)
    return {"ok": True}
