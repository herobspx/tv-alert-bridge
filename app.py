import os
import html
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv, find_dotenv

# تحميل المتغيرات
load_dotenv(find_dotenv())

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS  = [x.strip() for x in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if x.strip()]
ALERT_SECRET = os.getenv("ALERT_SECRET", "").strip()
BRIDGE_NAME  = os.getenv("BRIDGE_NAME", "COBOT Bridge").strip()

if not BOT_TOKEN or not CHAT_IDS or not ALERT_SECRET:
    raise RuntimeError("❌ تأكد من ضبط TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_IDS و ALERT_SECRET في البيئة.")

TG_SEND_MSG   = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
TG_SEND_PHOTO = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
KSA_TZ = ZoneInfo("Asia/Riyadh")

app = FastAPI(title=f"COBOT Bridge ({BRIDGE_NAME})")

# ======================= دوال المساعدة =======================
async def send_telegram_message(text: str):
    async with httpx.AsyncClient(timeout=15) as client:
        for cid in CHAT_IDS:
            await client.post(TG_SEND_MSG, json={
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            })

async def send_telegram_photo(image_path: str = None, image_bytes: bytes = None, caption: str = ""):
    async with httpx.AsyncClient(timeout=30) as client:
        for cid in CHAT_IDS:
            files, data = {}, {"chat_id": cid, "caption": caption, "parse_mode": "HTML"}
            if image_path:
                files["photo"] = (os.path.basename(image_path), open(image_path, "rb"), "image/png")
            elif image_bytes:
                files["photo"] = ("report.png", image_bytes, "image/png")
            else:
                raise ValueError("لم يتم توفير صورة للإرسال.")
            await client.post(TG_SEND_PHOTO, data=data, files=files)

def map_side(value: str):
    if not value:
        return "غير معروف", "⚪️"
    v = str(value).upper()
    if v in ("CALL", "BUY", "LONG", "1"): return "CALL", "🟢"
    if v in ("PUT", "SELL", "SHORT", "-1"): return "PUT", "🔴"
    return "غير معروف", "⚪️"

def fmt_num(v):
    try: return f"{float(v):,.6f}".rstrip("0").rstrip(".")
    except Exception: return str(v)

# ======================= المسارات =======================
@app.get("/")
def home(): return {"ok": True, "bridge": BRIDGE_NAME}

@app.get("/health")
def health(): return {"ok": True, "tz": "Asia/Riyadh", "bridge": BRIDGE_NAME}

@app.post("/tv/{secret}")
async def tv_alert(secret: str, request: Request):
    if secret != ALERT_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret key")

    try:
        payload = await request.json()
    except Exception:
        raw = (await request.body()).decode("utf-8", "ignore")
        try: payload = json.loads(raw)
        except Exception: payload = {"raw": raw}

    symbol  = payload.get("ticker") or payload.get("symbol") or "?"
    side_raw = payload.get("side") or payload.get("order_action") or ""
    side, emoji = map_side(side_raw)
    price = payload.get("close") or payload.get("price")
    timeframe = payload.get("interval") or payload.get("timeframe") or "—"

    lines = [
        f"📊 <b>{html.escape(str(symbol))}</b>",
        f"{emoji} <b>إشارة:</b> {html.escape(side)}",
    ]
    if price: lines.append(f"💵 <b>السعر:</b> {fmt_num(price)}")
    if timeframe != "—": lines.append(f"🕓 <b>الإطار الزمني:</b> {html.escape(timeframe)}")

    lines.append("⚠️ جميع مايُطرح يُعتبر اجتهاد فردي ولا يُعتبر توصية شراء أو بيع أو احتفاظ بأي ورقة مالية ⚠️")
    caption = "\n".join(lines)

    image_url = (payload.get("chart_image_url") or payload.get("screenshot_url") or payload.get("image"))
    async with httpx.AsyncClient(timeout=15) as client:
        if image_url:
            try:
                r = await client.get(image_url)
                if r.status_code == 200:
                    files = {"photo": ("chart.jpg", r.content, "image/jpeg")}
                    for cid in CHAT_IDS:
                        data = {"chat_id": cid, "caption": caption, "parse_mode": "HTML"}
                        await client.post(TG_SEND_PHOTO, data=data, files=files)
                    return {"ok": True, "photo": True}
            except Exception:
                pass

    await send_telegram_message(caption)
    return {"ok": True}

# ======================= مسار إرسال التقرير =======================
try:
    from daily_report import generate_daily_report
except Exception:
    generate_daily_report = None

@app.get("/generate-report")
@app.post("/generate-report")
async def generate_report():
    """إرسال التقرير اليومي كصورة (يستدعي دالة generate_daily_report من daily_report.py)."""
    if generate_daily_report is None:
        await send_telegram_message("❌ لم يتم العثور على ملف daily_report.py أو الدالة generate_daily_report.")
        return {"ok": False, "error": "missing daily_report.py"}

    try:
        result = generate_daily_report(app)
    except TypeError:
        result = generate_daily_report()

    caption = result.get("caption", "📈 تقرير COBOT اليومي")

    if isinstance(result, dict):
        if "image_path" in result and result["image_path"]:
            await send_telegram_photo(image_path=result["image_path"], caption=caption)
            return {"ok": True, "mode": "image_path"}
        elif "image_bytes" in result and result["image_bytes"]:
            await send_telegram_photo(image_bytes=result["image_bytes"], caption=caption)
            return {"ok": True, "mode": "image_bytes"}

    await send_telegram_message(str(result))
    return {"ok": True, "mode": "text"}
