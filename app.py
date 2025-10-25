# app.py
import os
import html
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

import asyncio
import httpx

# ---- تحميل المتغيرات ----
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv())
except Exception:
    pass

BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_IDS_RAW = os.getenv("TELEGRAM_CHAT_IDS", "")
ALERT_SECRET = os.getenv("ALERT_SECRET", "")
BRIDGE_NAME  = os.getenv("BRIDGE_NAME", "TV→Telegram Bridge")

if not BOT_TOKEN or not CHAT_IDS_RAW or not ALERT_SECRET:
    raise RuntimeError("Missing env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, ALERT_SECRET")

# تهيئة تليجرام
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
CHAT_IDS: List[str] = [c.strip() for c in CHAT_IDS_RAW.split(";") if c.strip()]

# FastAPI
app = FastAPI(title="TV–Telegram Alert Bridge")

# تخزين بسيط للرسائل (آخر 1000) كي يستخدمها التقرير
ALERT_BUFFER: List[Dict[str, Any]] = []
MAX_BUFFER = 1000
KSA_TZ = "Asia/Riyadh"

# ---- دوال مساعدة ----
def now_ksa_iso() -> str:
    # طابع زمني لوجي فقط
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def normalize_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    نوحّد الحقول الواردة من TradingView قدر الإمكان.
    """
    def g(*keys, default=""):
        for k in keys:
            if k in data and data[k] not in (None, ""):
                return data[k]
        return default

    symbol   = g("ticker", "symbol", "SYMBOL", default=g("TICKER", default="?"))
    exchange = g("exchange", "EXCHANGE", "market")
    interval = g("interval", "INTERVAL")
    price    = g("close", "price", "PRICE")
    side_raw = (g("side", "action", "order_action", default="").strip().upper())

    if side_raw in ("BUY", "CALL", "1", "LONG"):
        side = "CALL"
        side_emoji = "🟢"
        side_ar = "إشارة"
    elif side_raw in ("SELL", "PUT", "-1", "SHORT"):
        side = "PUT"
        side_emoji = "🔴"
        side_ar = "إشارة"
    else:
        side = "غير معروف"
        side_emoji = "⚪️"
        side_ar = "إشارة"

    note = g("note", "message", "text")

    return {
        "symbol": str(symbol),
        "exchange": str(exchange) if exchange else "",
        "interval": str(interval) if interval else "",
        "price": float(price) if f"{price}".replace(".","",1).isdigit() else price,
        "side": side,
        "side_emoji": side_emoji,
        "side_ar": side_ar,
        "note": str(note) if note else "",
    }

def format_telegram_message(p: Dict[str, Any]) -> str:
    """
    تنسيق الرسالة بالعربية (HTML) + إخلاء مسؤولية.
    """
    symbol = html.escape(p["symbol"])
    price  = p["price"]
    interval = html.escape(p["interval"]) if p["interval"] else ""
    side   = p["side"]
    side_emoji = p["side_emoji"]

    lines = []
    lines.append(f"<b>📊 {symbol}</b>")
    lines.append(f"{p['side_ar']} : <b>{side}</b> {side_emoji}")
    if isinstance(price, (int, float)):
        lines.append(f"💵 <b>السعر:</b> {price}")
    else:
        lines.append(f"💵 <b>السعر:</b> {html.escape(str(price))}")
    if interval:
        lines.append(f"🕒 <b>الإطار الزمني:</b> {interval}")

    # إخلاء مسؤولية حديث
    lines.append("⚠️ <i>جميع ما يُطرح يُعتبر اجتهادًا فرديًا ولا يُعدّ توصية شراء أو بيع أو احتفاظ بأي ورقة مالية.</i>")

    return "\n".join(lines)

async def send_to_telegram(text: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        tasks = []
        for cid in CHAT_IDS:
            payload = {
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            tasks.append(client.post(TG_API, json=payload))
        await asyncio.gather(*tasks, return_exceptions=True)

def push_to_buffer(entry: Dict[str, Any]) -> None:
    ALERT_BUFFER.append(entry)
    if len(ALERT_BUFFER) > MAX_BUFFER:
        del ALERT_BUFFER[: len(ALERT_BUFFER) - MAX_BUFFER]

# ---- نقاط الخدمة ----
@app.get("/health")
def health():
    return {"ok": True, "bridge": BRIDGE_NAME, "time": now_ksa_iso()}

@app.post("/tv/{secret}")
async def tv_webhook(secret: str, request: Request):
    if secret != ALERT_SECRET:
        raise HTTPException(status_code=401, detail="invalid secret")

    # قراءة جسم الطلب
    try:
        data = await request.json()
    except Exception:
        body = await request.body()
        try:
            data = json.loads(body.decode("utf-8", "ignore"))
        except Exception:
            data = {"raw": (await request.body()).decode("utf-8", "ignore")}

    # توحيد حقول TradingView
    payload = normalize_payload(data)

    # تحضير رسالة تليجرام
    text = format_telegram_message(payload)

    # إرسال
    await send_to_telegram(text)

    # تخزين في الذاكرة ليستخدمه التقرير
    entry = {
        "ts": now_ksa_iso(),
        "symbol": payload["symbol"],
        "side": payload["side"],
        "interval": payload["interval"],
        "price": payload["price"],
        "note": payload["note"],
    }
    push_to_buffer(entry)

    return {"ok": True, "sent": True}

@app.get("/alerts")
def list_alerts(limit: int = 100) -> List[Dict[str, Any]]:
    """
    ترجع آخر التنبيهات (تُستخدم بواسطة daily_report.py).
    """
    if limit <= 0:
        limit = 100
    return ALERT_BUFFER[-limit:]

# ---- استيراد مولّد التقرير (اختياري) ----
try:
    from daily_report import generate_daily_report  # يجب أن تكون async وتستقبل (TG_API, CHAT_IDS)
except Exception:
    generate_daily_report = None

@app.get("/generate_report")
async def generate_report():
    """
    استدعاء يدوي لإنتاج صورة التقرير وإرسالها للتليجرام.
    daily_report.generate_daily_report يجب أن تكون:
        async def generate_daily_report(TG_API: str, chat_ids: List[str]) -> dict:
            ...
    """
    if generate_daily_report is None:
        raise HTTPException(status_code=500, detail="daily_report.py غير موجود في المشروع")

    try:
        # مهم: نمرّر TG_API و CHAT_IDS كما طلبت
        result = await generate_daily_report(TG_API, CHAT_IDS)
        return {"status": "Report generated and sent", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"report error: {e}")


# صفحة جذر بسيطة
@app.get("/")
def root():
    return JSONResponse({"service": BRIDGE_NAME, "endpoints": ["/health", "/tv/{secret}", "/alerts", "/generate_report"]})
