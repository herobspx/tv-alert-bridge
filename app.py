import os, html, asyncio, csv
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv
import httpx

# تحميل المتغيرات من .env
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_IDS = [x.strip() for x in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if x.strip()]
ALERT_SECRET = os.getenv("ALERT_SECRET", "")
BRIDGE_NAME = os.getenv("BRIDGE_NAME", "TradingView Bridge")

if not BOT_TOKEN or not CHAT_IDS or not ALERT_SECRET:
    raise RuntimeError("❌ Missing environment variables: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, or ALERT_SECRET")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
app = FastAPI(title=f"TV → Telegram Alert Bridge: {BRIDGE_NAME}")

# 🩺 فحص الصحة
@app.get("/health")
def health():
    return {"ok": True, "bridge": BRIDGE_NAME}

# 📨 استقبال تنبيهات من TradingView
@app.post("/tv/{secret}")
async def tv_alert(secret: str, request: Request):
    if secret != ALERT_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret key")

    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode("utf-8", "ignore")}

    # استخراج البيانات
    symbol = payload.get("ticker") or payload.get("symbol") or "?"
    side = (payload.get("side") or payload.get("order_action") or "").upper()
    price = payload.get("close") or payload.get("price")
    timeframe = payload.get("interval") or payload.get("timeframe") or "—"

    # -------- نص عربي مبسّط (مع الفريم والتحذير الجديد) --------
    icon = "🟢" if side == "CALL" else ("🔴" if side == "PUT" else "⚪")

    lines = [
        f"📊 <b>{html.escape(str(symbol))}</b>",
        f"{icon} <b>إشارة:</b> {html.escape(side)}",
    ]

    if price is not None:
        ptxt = f"{price:,.6f}".rstrip('0').rstrip('.')
        lines.append(f"💵 <b>السعر:</b> {ptxt}")

    if timeframe and timeframe != "—":
        lines.append(f"🕓 <b>الإطار الزمني:</b> {html.escape(timeframe)}")

    # ⚠️ التحذير الجديد
    lines.append("⚠️ جميع مايُطرح يُعتبر اجتهاد فردي ولا يُعتبر توصية شراء أو بيع أو احتفاظ بأي ورقة مالية ⚠️")

    caption = "\n".join(lines)

    # إرسال للتليجرام
    async with httpx.AsyncClient(timeout=10) as client:
        for cid in CHAT_IDS:
            await client.post(
                TG_API,
                json={
                    "chat_id": cid,
                    "text": caption,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )

    # حفظ التنبيه في CSV (لتقرير اليوم)
    log_path = "alerts_log.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([now, symbol, side, price, timeframe])

    return {"ok": True, "symbol": symbol, "side": side, "price": price}


# 🚀 تشغيل محلي (اختياري)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
