# app.py — TV → Telegram Alert Bridge (Riyadh time, CALL/PUT only)
import os
import html
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv, find_dotenv
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

# ── إعداد البيئة ────────────────────────────────────────────────────────────────
load_dotenv(find_dotenv())

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS_RAW = os.getenv("TELEGRAM_CHAT_IDS", "").strip()
ALERT_SECRET = os.getenv("ALERT_SECRET", "").strip()

def _split_ids(raw: str):
    # نقبل فاصلة أو فاصلة منقوطة أو مسافات
    seps = [",", ";"]
    for s in seps:
        raw = raw.replace(s, " ")
    return [x for x in (p.strip() for p in raw.split()) if x]

CHAT_IDS = _split_ids(CHAT_IDS_RAW)

if not BOT_TOKEN or not CHAT_IDS or not ALERT_SECRET:
    raise RuntimeError("Missing env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, ALERT_SECRET")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# ── تطبيق FastAPI ───────────────────────────────────────────────────────────────
app = FastAPI(title="TV → Telegram Alert Bridge")

@app.get("/health")
def health():
    return {"ok": True}

# ── مساعدات ────────────────────────────────────────────────────────────────────
def norm_side(raw: str):
    """أعد تصنيف الإشارة بحيث تكون CALL أو PUT فقط."""
    if not raw:
        return "PUT"  # افتراضيًا نرمي غير المعروف لـ PUT لتجنّب إشارات شراء خاطئة
    s = raw.upper().strip()
    if s in {"CALL", "BUY", "1", "LONG"}:
        return "CALL"
    if s in {"PUT", "SELL", "-1", "SHORT"}:
        return "PUT"
    return "PUT"

def side_text_and_emoji(side: str):
    if side == "CALL":
        return "CALL (شراء)", "🟢"
    else:
        return "PUT (بيع)", "🔴"

def riyadh_now():
    return datetime.now(ZoneInfo("Asia/Riyadh")).strftime("%Y-%m-%d %H:%M:%S KSA")

# ── نقطة استقبال TradingView ───────────────────────────────────────────────────
@app.post("/tv/{secret}")
async def tv_alert(secret: str, request: Request):
    if secret != ALERT_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")

    # نقبل كلا التنسيقات: symbol/ticker, price/close, interval/tf, side/order_action
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode("utf-8", "ignore")}

    symbol   = (payload.get("symbol") or payload.get("ticker") or payload.get("SYMBOL") or "").upper() or "UNKNOWN"
    price    = payload.get("price", payload.get("close", "N/A"))
    interval = payload.get("interval", payload.get("tf", "1H"))
    side_in  = payload.get("side", payload.get("order_action", ""))

    side = norm_side(side_in)
    side_text, side_emoji = side_text_and_emoji(side)
    now_str = riyadh_now()

    # تتبّع في اللوج
    print(f"ALERT v2 -> symbol={symbol} side={side} price={price} interval={interval}")

    # رسالة تيليجرام (عربية مختصرة ومرتبة)
    lines = [
        f"📊 <b>{html.escape(symbol)}</b>",
        f"{side_emoji} إشارة: <b>{side_text}</b>",
        f"💵 السعر الحالي: <b>{html.escape(str(price))}</b>",
        f"🕓 الإطار الزمني: <b>{html.escape(str(interval))}</b>",
        f"⏰ <b>{now_str}</b>",
    ]
    text = "\n".join(lines)

    async with httpx.AsyncClient(timeout=10) as client:
        for cid in CHAT_IDS:
            await client.post(
                TG_API,
                json={
                    "chat_id": cid,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )

    return {"ok": True}
