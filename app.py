# app.py
# -*- coding: utf-8 -*-

import os
import html
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv, find_dotenv

# تحميل متغيرات البيئة
load_dotenv(dotenv_path=find_dotenv())

# ========= الإعدادات =========
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS_RAW = os.getenv("TELEGRAM_CHAT_IDS", "").strip()
ALERT_SECRET = os.getenv("ALERT_SECRET", "").strip()
BRIDGE_NAME = os.getenv("BRIDGE_NAME", "TV → Telegram Bridge").strip()

if not BOT_TOKEN or not CHAT_IDS_RAW or not ALERT_SECRET:
    raise RuntimeError("❌ Missing env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, ALERT_SECRET")

# معالجة معرفات التليجرام المتعددة
CHAT_IDS = [cid.strip() for sep in [",", ";", "\n"] for cid in CHAT_IDS_RAW.split(sep) if cid.strip()]
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

KSA_TZ = ZoneInfo("Asia/Riyadh")

app = FastAPI(title="TV → Telegram Alert Bridge")


# ========= أدوات مساعدة =========
async def tg_send_text(text: str):
    """إرسال الرسالة إلى كل قناة في TELEGRAM_CHAT_IDS"""
    async with httpx.AsyncClient(timeout=10) as client:
        tasks = []
        for cid in CHAT_IDS:
            tasks.append(client.post(
                TG_API,
                json={
                    "chat_id": cid,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
            ))
        if tasks:
            await asyncio.gather(*tasks)


def normalize_side(v: str) -> str:
    """توحيد نوع الإشارة"""
    if not v:
        return ""
    v = v.strip().upper()
    if v in ("BUY", "CALL", "1", "LONG"):
        return "CALL"
    if v in ("SELL", "PUT", "-1", "SHORT"):
        return "PUT"
    return ""


# ========= Endpoints =========
@app.get("/")
def root():
    return {"ok": True, "bridge": BRIDGE_NAME}


@app.get("/health")
def health():
    return {"ok": True, "bridge": BRIDGE_NAME}


@app.post("/tv/{secret}")
async def tv_webhook(secret: str, request: Request):
    """استقبال تنبيهات TradingView"""
    if secret != ALERT_SECRET:
        raise HTTPException(status_code=401, detail="invalid secret")

    try:
        payload = await request.json()
    except Exception:
        raw = (await request.body()).decode("utf-8", "ignore")
        payload = {"raw": raw}

    ticker = payload.get("ticker") or payload.get("symbol") or payload.get("SYMBOL") or ""
    side_raw = payload.get("side") or payload.get("action") or payload.get("order_action") or ""
    side = normalize_side(side_raw)

    price = payload.get("close") or payload.get("price") or payload.get("PRICE")
    interval = payload.get("interval") or payload.get("tf") or payload.get("INTERVAL")

    # تجهيز الرسالة
    title = html.escape(ticker.strip() or "—")
    side_txt = "CALL" if side == "CALL" else ("PUT" if side == "PUT" else "غير معروف")
    side_emoji = "🟢" if side == "CALL" else ("🔴" if side == "PUT" else "⚪️")

    lines = [
        f"<b>📊 {title}</b>",
        f"إشارة: <b>{side_txt}</b> {side_emoji}"
    ]

    if price is not None:
        try:
            price_f = float(price)
            lines.append(f"السعر: <b>{price_f:g}</b> 💵")
        except Exception:
            lines.append(f"السعر: <b>{html.escape(str(price))}</b> 💵")

    if interval:
        lines.append(f"الإطار الزمني: <b>{html.escape(str(interval))}</b> ⏱")

    # نص الإخلاء الجديد
    lines.append("⚠️ <i>جميع مايُطرح يُعَبِّر عن اجتهاد فردي، ولا يُعْتَبَر توصية شراء أو بيع أو احتفاظ بأي ورقة مالية.</i> ⚠️")

    text = "\n".join(lines)
    await tg_send_text(text)

    return {"ok": True}


# ========= توليد التقرير اليومي =========
try:
    from daily_report import generate_daily_report
except Exception:
    generate_daily_report = None


@app.get("/generate_report")
async def generate_report():
    """نقطة استدعاء التقرير اليومي"""
    if generate_daily_report is None:
        raise HTTPException(status_code=500, detail="daily_report.py غير موجود في المشروع")
    try:
        generate_daily_report()  # ← تم إزالة await ✅
        return {"status": "Report generated and sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"report error: {e}")


# ========= النهاية =========
