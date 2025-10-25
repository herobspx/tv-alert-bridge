# daily_report.py — يولّد "صورة تقرير يومي" ويرسلها لتليجرام الساعة 1 صباحاً (KSA)
# يجلب بيانات اليوم عبر API الويب سيرفس: GET /logs/today
# و"ليس" من ملف CSV محلي (لأن الويب سيرفس والـ Worker على ملفات مختلفة في Render)

import os, io, asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv, find_dotenv
import httpx
import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from PIL import Image, ImageDraw, ImageFont

# ───────── إعداد البيئة ─────────
load_dotenv(find_dotenv())

BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS    = [x.strip() for x in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if x.strip()]
WEB_BASE    = os.getenv("WEB_BASE_URL", "https://tv-alert-bridge.onrender.com").rstrip("/")  # خدمة الويب
TIMEZONE    = ZoneInfo("Asia/Riyadh")

# أصول الصورة/الخط
BG_IMAGE    = os.path.join("assets", "report_bg.png")           # خلفية التقرير
FONT_AR     = os.path.join("assets", "Tajawal-Regular.ttf")     # خط عربي (اختياري)
TITLE       = "تقرير تنبيهات العملات الرقمية — COBOT"

if not BOT_TOKEN or not CHAT_IDS:
    raise RuntimeError("متغيرات البيئة TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_IDS مطلوبة.")

# ───────── أدوات مساعدة ─────────
def now_str(fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.now(TIMEZONE).strftime(fmt)

def today_date():
    return datetime.now(TIMEZONE).date()

def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """يحاول استخدام Tajawal، وإن تعذر يستخدم DejaVuSans ثم الافتراضي."""
    try:
        if os.path.exists(FONT_AR):
            return ImageFont.truetype(FONT_AR, size=size)
    except Exception:
        pass
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=size)
    except Exception:
        return ImageFont.load_default()

def normalize_for_binance(sym: str) -> str | None:
    """يحاول تحويل الرمز لصيغة Binance (أزواج USDT)."""
    s = str(sym).upper().strip()
    if s.endswith(".P"):  # بعض المنصات تضيف .P
        s = s[:-2]
    return s if s.endswith("USDT") else None

async def price_binance(client: httpx.AsyncClient, symbol: str) -> float | None:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        r = await client.get(url, timeout=10)
        if r.status_code == 200:
            return float(r.json().get("price"))
    except Exception:
        pass
    return None

async def price_yahoo(client: httpx.AsyncClient, symbol: str) -> float | None:
    """يدعم أسهم أمريكا (AAPL/NVDA/TSLA...) إن رغبت تستخدمه لاحقاً."""
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
    try:
        r = await client.get(url, timeout=10)
        if r.status_code == 200:
            result = r.json().get("quoteResponse", {}).get("result", [])
            if result:
                val = result[0].get("regularMarketPrice")
                return float(val) if val is not None else None
    except Exception:
        pass
    return None

async def fetch_today_rows() -> list[dict]:
    """يجلب تنبيهات اليوم من الويب سيرفس: /logs/today"""
    url = f"{WEB_BASE}/logs/today"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url)
        r.raise_for_status()
        items = r.json().get("items", [])
        rows: list[dict] = []
        for it in items:
            ts = it.get("timestamp")
            sym = it.get("symbol")
            side = it.get("side")
            price = it.get("price")
            if not (ts and sym and side and price is not None):
                continue
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            # تأكيد أن السجل لليوم ذاته (احتياط)
            if dt.date() != today_date():
                continue
            rows.append({
                "timestamp": dt,
                "symbol": str(sym),
                "side": str(side).upper(),
                "alert_price": float(price),
            })
        return rows

def draw_image(df: pd.DataFrame, W=1024, H=1024) -> bytes:
    """يرسم صورة التقرير: خلفية البوت + جدول مبسّط (الرمز | نوع الإشارة | سعر الإشعار | نسبة التغير)."""
    # الخلفية
    if os.path.exists(BG_IMAGE):
        bg = Image.open(BG_IMAGE).convert("RGB").resize((W, H))
    else:
        bg = Image.new("RGB", (W, H), (12, 16, 22))  # لون بديل إن لم توجد خلفية

    # تغميق خفيف لتحسين التباين
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 90))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(bg)
    title_f = load_font(48)
    head_f  = load_font(34)
    cell_f  = load_font(32)
    small_f = load_font(24)

    pad = 40
    # العنوان والتاريخ
    draw.text((pad, pad),
              f"{TITLE}\nالتاريخ: {today_date().strftime('%Y-%m-%d')} (KSA)",
              font=title_f, fill=(255, 255, 255))

    # الأعمدة المبسطة
    cols = ["الرمز", "نوع الإشارة", "السعر عند الإشعار", "نسبة التغير"]
    # مواضع أعمدة تقريبية — عدّلها لو حبّيت لاحقاً
    col_x = [pad, 400, 670, 900]
    y0 = 160
    row_h = 66

    # رؤوس الأعمدة
    for i, c in enumerate(cols):
        draw.text((col_x[i], y0), c, font=head_f, fill=(205, 225, 255))
    y = y0 + row_h

    # صفوف البيانات
    for _, r in df.iterrows():
        sym = str(r["symbol"])
        side = "🟢 CALL" if str(r["side"]).upper() == "CALL" else "🔴 PUT"
        p0 = float(r["alert_price"])
        p0s = f"{p0:,.6f}".rstrip('0').rstrip('.')
        chg = float(r["change_pct"])
        chg_s = f"{chg:+.2f}%"
        chg_col = (60, 220, 130) if chg >= 0 else (255, 90, 90)

        draw.text((col_x[0], y), sym,  font=cell_f, fill=(240, 240, 240))
        draw.text((col_x[1], y), side, font=cell_f, fill=(240, 240, 240))
        draw.text((col_x[2], y), p0s,  font=cell_f, fill=(230, 230, 230))
        draw.text((col_x[3], y), chg_s, font=cell_f, fill=chg_col)

        y += row_h
        if y > H - 120:
            break  # لو زاد عن مساحة الصورة

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
    """يجمع بيانات اليوم عبر API، يحسب نسبة التغير، يرسم الصورة، ويرسلها لتليجرام."""
    rows = await fetch_today_rows()
    if not rows:
        return

    df = pd.DataFrame(rows)

    # أسعار حالية: كريبتو (Binance) / أسهم (Yahoo) — تلقائي
    async with httpx.AsyncClient(timeout=12) as client:
        curr = {}
        for sym in sorted(df["symbol"].unique()):
            s = str(sym).upper().strip()
            b = normalize_for_binance(s)
            if b:  # رمز كريبتو USDT -> Binance
                curr_price = await price_binance(client, b)
            else:  # يفيد لاحقاً لو استخدمته للأسهم
                curr_price = await price_yahoo(client, s)
            curr[sym] = curr_price

    # دمج الأسعار
    df["current_price"] = df["symbol"].map(curr)
    df = df.dropna(subset=["current_price"])
    if df.empty:
        return

    # نسبة التغير
    df["change_pct"] = ((df["current_price"] - df["alert_price"]) / df["alert_price"]) * 100.0
    # ترتيب: الأحدث أولاً
    df = df.sort_values("timestamp", ascending=False)

    # توليد الصورة
    img_bytes = draw_image(df)  # bytes

    # إرسال الصورة إلى كل وجهة
    async with httpx.AsyncClient(timeout=20) as client:
        for cid in CHAT_IDS:
            files = {"photo": ("report.png", img_bytes, "image/png")}
            data = {
                "chat_id": cid,
                "caption": "تقرير COBOT اليومي — العملات الرقمية",
                "parse_mode": "HTML"
            }
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                              data=data, files=files)

async def main():
    print(">> Daily Report Worker started at", now_str())
    sched = AsyncIOScheduler(timezone=TIMEZONE)
    # يرسل التقرير يومياً الساعة 1 صباحاً بتوقيت الرياض
    sched.add_job(generate_and_send, "cron", hour=1, minute=0)
    sched.start()

    # للتجربة الفورية مرة واحدة عند الإقلاع (أزِل التعليق ثم انشر):
    # await generate_and_send()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
