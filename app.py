# app.py — TV Alert Bridge → Telegram (Arabic, KSA time, image support, CSV logging)
import os
import json
import html
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv, find_dotenv
import httpx

# ---------- إعداد البيئة ----------
load_dotenv(find_dotenv())

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS  = [c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
ALERT_SECRET = os.getenv("ALERT_SECRET", "").strip() or "spxalert2025"

if not BOT_TOKEN or not CHAT_IDS:
    raise RuntimeError("يجب ضبط TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_IDS في البيئة.")

TG_SEND_MSG_API   = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
TG_SEND_PHOTO_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
KSA_TZ = ZoneInfo("Asia/Riyadh")

# ---------- سجل التنبيهات CSV ----------
import csv
LOG_DIR  = "logs"
LOG_FILE = os.path.join(LOG_DIR, "crypto_alerts.csv")
os.makedirs(LOG_DIR, exist_ok=True)

def log_alert(symbol: str, side: str, price):
    ts = datetime.now(KSA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([ts, str(symbol), str(side), str(price)])
    except Exception:
        # لا نكسر الويبهوك لو فشل اللوق
        pass

# ---------- أدوات ----------
def now_ksa_str(fmt: str = "%Y-%m-%d %H:%M:%S"):
    return datetime.now(KSA_TZ).strftime(fmt)

def map_side(value: str) -> str:
    """توحد الإشارة إلى CALL أو PUT فقط."""
    if not value:
        return "—"
    v = str(value).upper()
    if v in ("CALL", "BUY", "LONG", "1"):
        return "CALL"
    if v in ("PUT", "SELL", "SHORT", "-1"):
        return "PUT"
    return "—"

def pick_float(*vals):
    for v in vals:
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None

def extract_image_url(payload: dict):
    # نحاول كل الحقول الشائعة للصور من TradingView
    return (
        payload.get("screenshot_url")
        or payload.get("chart_image_url")
        or payload.get("chart_image")
        or payload.get("image")
        or payload.get("screenshot")
        or None
    )

# ---------- تطبيق FastAPI ----------
app = FastAPI(title="TradingView → Telegram Bridge", version="2.0")

@app.get("/")
def home():
    return {
        "ok": True,
        "bridge": "TradingView Bridge",
        "hint": "Use GET /health or POST /tv/{secret}"
    }

@app.get("/health")
def health():
    return {"ok": True, "bridge": "TradingView Bridge"}

@app.post("/tv/{secret}")
async def tv_webhook(secret: str, request: Request):
    # تحقق السر
    if secret != ALERT_SECRET:
        raise HTTPException(status_code=401, detail="invalid secret")

    # محاولة قراءة JSON بأمان
    raw_body = None
    try:
        payload = await request.json()
    except Exception:
        raw_body = (await request.body()).decode("utf-8", "ignore")
        try:
            payload = json.loads(raw_body)
        except Exception:
            payload = {"raw": raw_body}

    # التقاط الحقول من احتمالات مختلفة
    symbol   = (payload.get("symbol")
                or payload.get("ticker")
                or payload.get("sym")
                or "UNKNOWN")

    side_raw = (payload.get("side")
                or payload.get("signal")
                or payload.get("order_action")
                or payload.get("orderAction")
                or "")

    price    = pick_float(payload.get("price"), payload.get("close"), payload.get("last"))
    interval = str(payload.get("interval") or payload.get("tf") or "").upper().strip()
    note     = payload.get("note") or payload.get("message") or payload.get("comment") or ""

    side = map_side(side_raw)

    # نص عربي احترافي (CALL/PUT فقط)
    # ملاحظة: بناءً على طلبك حذفنا "شراء/بيع"
    # مثال نهائي:
    # 📊 BTCUSDT.P
    # 🟢 إشارة: CALL
    # 💵 السعر: 68930.12
    # ⏰ 2025-10-26 01:23:45 KSA
    icon = "🟢" if side == "CALL" else ("🔴" if side == "PUT" else "⚪")
    lines = [
        f"📊 <b>{html.escape(str(symbol))}</b>",
        f"{icon} <b>إشارة:</b> {html.escape(side)}",
    ]
    if price is not None:
        # تنسيق مبسّط للأرقام العشرية الطويلة
        ptxt = f"{price:,.6f}".rstrip('0').rstrip('.')
        lines.append(f"💵 <b>السعر:</b> {ptxt}")
    # حذفنا الإطار الزمني بناءً على تفضيلك الحالي
    lines.append(f"⏰ <b>{now_ksa_str()} KSA</b>")
    if note:
        lines.append(f"📝 <i>{html.escape(str(note))}</i>")

    caption = "\n".join(lines)

    # سجّل التنبيه لميزة التقرير اليومي
    log_alert(symbol, side, price)

    # إرسال تيليجرام (مع صورة الشارت إن وُجدت)
    image_url = extract_image_url(payload)

    async with httpx.AsyncClient(timeout=15) as client:
        for cid in CHAT_IDS:
            sent_with_photo = False
            if image_url:
                try:
                    r = await client.get(str(image_url))
                    if r.status_code == 200 and r.content:
                        files = {"photo": ("chart.jpg", r.content, "image/jpeg")}
                        data = {
                            "chat_id": cid,
                            "caption": caption,
                            "parse_mode": "HTML",
                            "disable_notification": False
                        }
                        await client.post(TG_SEND_PHOTO_API, data=data, files=files)
                        sent_with_photo = True
                except Exception:
                    sent_with_photo = False

            if not sent_with_photo:
                await client.post(TG_SEND_MSG_API, json={
                    "chat_id": cid,
                    "text": caption,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                })

    return JSONResponse({"ok": True})
