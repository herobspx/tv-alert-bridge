# daily_report.py — يولّد صورة تقرير يومي من تنبيهات العملات ويرسلها للتيليجرام (1 صباحًا KSA)
import os, io, asyncio, csv
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv, find_dotenv
import httpx
import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from PIL import Image, ImageDraw, ImageFont

load_dotenv(find_dotenv())
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS    = [x.strip() for x in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if x.strip()]
TIMEZONE    = ZoneInfo("Asia/Riyadh")
LOG_FILE    = os.path.join("logs", "crypto_alerts.csv")
BG_IMAGE    = os.path.join("assets", "report_bg.png")
FONT_AR     = os.path.join("assets", "Tajawal-Regular.ttf")  # اختياري
TITLE       = "تقرير تنبيهات العملات الرقمية — COBOT"

if not BOT_TOKEN or not CHAT_IDS:
    raise RuntimeError("TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_IDS مطلوبة")

def now_str(fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.now(TIMEZONE).strftime(fmt)

def today_date():
    return datetime.now(TIMEZONE).date()

def norm_symbol(sym: str) -> str | None:
    s = str(sym).upper().strip()
    if s.endswith(".P"): s = s[:-2]
    if s.endswith("USDT"): return s
    return None

async def binance_price(client: httpx.AsyncClient, symbol: str) -> float | None:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        r = await client.get(url, timeout=10)
        if r.status_code == 200:
            return float(r.json().get("price"))
    except Exception:
        pass
    return None

def load_font(size: int):
    try:
        if os.path.exists(FONT_AR):
            return ImageFont.truetype(FONT_AR, size=size)
    except Exception:
        pass
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=size)
    except Exception:
        return ImageFont.load_default()

def draw_image(df: pd.DataFrame, W=1024, H=1024) -> bytes:
    # خلفية
    if os.path.exists(BG_IMAGE):
        bg = Image.open(BG_IMAGE).convert("RGB").resize((W, H))
    else:
        bg = Image.new("RGB", (W, H), (12, 16, 22))
    # تغميق خفيف لتباين النص
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 90))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(bg)
    title_f = load_font(48)
    head_f  = load_font(34)
    cell_f  = load_font(32)
    small_f = load_font(24)

    pad = 40
    draw.text((pad, pad), f"{TITLE}\nالتاريخ: {today_date().strftime('%Y-%m-%d')} (KSA)", font=title_f, fill=(255,255,255))

    # أعمدة مبسطة: الرمز | نوع الإشارة | السعر عند الإشعار | نسبة التغير
    cols = ["الرمز", "نوع الإشارة", "السعر عند الإشعار", "نسبة التغير"]
    col_x = [pad, 400, 670, 900]
    y0 = 160
    row_h = 66

    # الرؤوس
    for i, c in enumerate(cols):
        draw.text((col_x[i], y0), c, font=head_f, fill=(205, 225, 255))
    y = y0 + row_h

    for _, r in df.iterrows():
        sym = str(r["symbol"])
        side = "🟢 CALL" if str(r["side"]).upper()=="CALL" else "🔴 PUT"
        p0 = float(r["alert_price"])
        p0s = f"{p0:,.6f}".rstrip('0').rstrip('.')
        chg = float(r["change_pct"])
        chg_s = f"{chg:+.2f}%"
        chg_col = (60, 220, 130) if chg >= 0 else (255, 90, 90)

        draw.text((col_x[0], y), sym,  font=cell_f, fill=(240,240,240))
        draw.text((col_x[1], y), side, font=cell_f, fill=(240,240,240))
        draw.text((col_x[2], y), p0s,  font=cell_f, fill=(230,230,230))
        draw.text((col_x[3], y), chg_s, font=cell_f, fill=chg_col)

        y += row_h
        if y > H - 120:
            break

    # ملخص سفلي
    total = len(df)
    calls = int((df["side"].str.upper() == "CALL").sum())
    puts  = total - calls
    footer = f"📈 CALL: {calls}   📉 PUT: {puts}   📊 الإجمالي: {total}   ⏰ {now_str()}"
    draw.text((pad, H - 80), footer, font=small_f, fill=(210, 225, 255))

    buf = io.BytesIO()
    bg.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

async def generate_and_send():
    if not os.path.exists(LOG_FILE):
        return

    rows = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        rd = csv.reader(f)
        for ts, sym, side, price in rd:
            # بيانات اليوم فقط
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if dt.date() == today_date():
                rows.append({"timestamp": dt, "symbol": sym, "side": side, "alert_price": float(price)})

    if not rows:
        return

    df = pd.DataFrame(rows)

    # أسعار حالية من Binance
    async with httpx.AsyncClient(timeout=10) as client:
        current = {}
        for sym in sorted(df["symbol"].unique()):
            b = norm_symbol(sym)
            current[sym] = await binance_price(client, b) if b else None

    df["current_price"] = df["symbol"].map(current)
    df = df.dropna(subset=["current_price"])
    if df.empty:
        return
    df["change_pct"] = ((df["current_price"] - df["alert_price"]) / df["alert_price"]) * 100.0
    df = df.sort_values("timestamp", ascending=False)

    img = draw_table_image := draw_image(df)  # bytes

    async with httpx.AsyncClient(timeout=20) as client:
        for cid in CHAT_IDS:
            files = {"photo": ("report.png", img, "image/png")}
            data = {"chat_id": cid, "caption": "تقرير COBOT اليومي — العملات الرقمية", "parse_mode": "HTML"}
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", data=data, files=files)

    # تهيئة السجل لليوم التالي: إزالة سجلات اليوم
    keep = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        rd = csv.reader(f)
        for ts, sym, side, price in rd:
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if dt.date() != today_date():
                keep.append([ts, sym, side, price])
    with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(keep)

async def main():
    print(">> Daily Report Worker started at", now_str())
    sched = AsyncIOScheduler(timezone=TIMEZONE)
    sched.add_job(generate_and_send, "cron", hour=1, minute=0)  # 1:00 AM KSA
    sched.start()
    # للتجربة الفورية، أزل التعليق عن السطر التالي، ثم احفظ/انشر:
    # await generate_and_send()
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
