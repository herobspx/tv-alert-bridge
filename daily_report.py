# daily_report.py
# -*- coding: utf-8 -*-

import os
import io
import math
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ====== دعم العربية (اختياري) ======
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_AR = True
except Exception:
    HAS_AR = False

# ====== إعدادات عامة ======
KSA_TZ = ZoneInfo("Asia/Riyadh")

# أبعاد الصورة
CANVAS_W, CANVAS_H = 1280, 720
MARGIN = 56

# ألوان
WHITE = (245, 245, 245)
SOFT_WHITE = (225, 225, 230)
DIM_WHITE = (200, 200, 205)
BLACK = (10, 12, 16)
CARD_BG = (18, 20, 26, 220)
GREEN = (66, 186, 150)
RED = (225, 82, 79)
AMBER = (255, 193, 7)

# مسارات الخطوط/الخلفية (اختر ما يناسبك أو اتركها افتراضية)
FONT_BOLD_PATH = os.getenv("AR_FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_REG_PATH  = os.getenv("AR_FONT_REG",  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
BG_PATH        = os.getenv("REPORT_BG_PATH", "assets/report_bg.png")  # ضع صورتك هنا

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        # fallback عام
        return ImageFont.load_default()

def _ar(text: str) -> str:
    """تهيئة نص عربي (اختياري)"""
    if not text:
        return text
    if not HAS_AR:
        return text
    try:
        reshaped = arabic_reshaper.reshape(text)
        bidi_txt = get_display(reshaped)
        return bidi_txt
    except Exception:
        return text

def _load_background(canvas_w: int, canvas_h: int) -> Image.Image:
    if os.path.exists(BG_PATH):
        try:
            bg = Image.open(BG_PATH).convert("RGB").resize((canvas_w, canvas_h), Image.LANCZOS)
            # إضافة تمويه خفيف + طبقة غامقة لتعزيز الوضوح
            bg_blur = bg.filter(ImageFilter.GaussianBlur(2))
            dark = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 90))
            bg_blur.paste(dark, (0, 0), dark)
            return bg_blur.convert("RGB")
        except Exception:
            pass
    # خلفية تدرّجية بسيطة في حال عدم توفر الصورة
    base = Image.new("RGB", (canvas_w, canvas_h), BLACK)
    return base

def _draw_header(draw: ImageDraw.ImageDraw, title_f: ImageFont.FreeTypeFont, sub_f: ImageFont.FreeTypeFont):
    now = datetime.now(KSA_TZ)
    title  = _ar("📈 تقرير COBOT اليومي")
    sub    = _ar(f"KSA {now:%H:%M  %Y-%m-%d}")

    # عنوان
    draw.text((MARGIN, MARGIN), title, font=title_f, fill=WHITE)

    # سطر التاريخ في أقصى اليمين
    sub_w, _ = draw.textsize(sub, font=sub_f)
    draw.text((CANVAS_W - MARGIN - sub_w, MARGIN + 6), sub, font=sub_f, fill=SOFT_WHITE)

def _draw_card(draw: ImageDraw.ImageDraw, x1, y1, x2, y2, radius=20):
    """بطاقة نصف شفافة لطيفة للخلفية وراء الجدول."""
    card = Image.new("RGBA", (x2 - x1, y2 - y1), CARD_BG)
    # حواف ناعمة
    mask = Image.new("L", (x2 - x1, y2 - y1), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, x2 - x1, y2 - y1), radius=radius, fill=255)
    return card, mask

def _format_number(v):
    try:
        if v is None:
            return "-"
        if isinstance(v, str):
            return v
        if abs(v) >= 1000:
            return f"{v:,.2f}"
        # أسعار الكريبتو قد تحتاج 4 منازل
        return f"{v:.4f}" if v < 10 else f"{v:.2f}"
    except Exception:
        return str(v)

def _signal_label(side_raw: str) -> tuple[str, tuple[int,int,int]]:
    s = (side_raw or "").upper().strip()
    if s in ("BUY", "CALL", "1", "LONG"):
        return _ar("CALL"), GREEN
    if s in ("SELL", "PUT", "-1", "SHORT"):
        return _ar("PUT"), RED
    return _ar("—"), AMBER

async def _fetch_alerts(source_url: str | None) -> list[dict]:
    """
    يجلب تنبيهات اليوم من API. شكل متوقع لكل عنصر:
    { "symbol": "BTCUSDT.P", "price": 67890.12, "side": "CALL" }
    """
    url = source_url or os.getenv("REPORT_SOURCE_URL") or "http://localhost:8000/alerts/today"
    try:
        timeout = httpx.Timeout(10.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []

def _draw_table(img: Image.Image, draw: ImageDraw.ImageDraw, rows: list[dict], fonts: dict):
    """
    يرسم جدولاً بسيطاً: [الرمز | السعر | الإشارة]
    """
    title_f = fonts["title"]
    head_f  = fonts["head"]
    cell_f  = fonts["cell"]

    # بطاقة خلفية للجدول
    top = MARGIN + 80
    left = MARGIN
    right = CANVAS_W - MARGIN
    bottom = CANVAS_H - MARGIN

    card, mask = _draw_card(draw, left, top, right, bottom, radius=24)
    img.paste(card, (left, top), mask)

    # رؤوس الأعمدة
    headers = [_ar("الرمز"), _ar("السعر"), _ar("الإشارة")]
    # نسّب الأعمدة: رمز 45% | سعر 30% | إشارة 25%
    col_w = [0.45, 0.30, 0.25]
    x_positions = [left + 32]
    x_positions.append(x_positions[0] + int((right - left - 64) * col_w[0]))
    x_positions.append(x_positions[1] + int((right - left - 64) * col_w[1]))

    y = top + 24

    # خط فاصل خفيف تحت الرأس
    draw.text((x_positions[0], y), headers[0], font=head_f, fill=SOFT_WHITE)
    draw.text((x_positions[1], y), headers[1], font=head_f, fill=SOFT_WHITE)
    draw.text((x_positions[2], y), headers[2], font=head_f, fill=SOFT_WHITE)
    y += 40
    draw.line((left + 24, y, right - 24, y), fill=(255,255,255,50), width=1)
    y += 12

    row_h = 44
    max_rows = max(1, (bottom - y - 24) // row_h)

    if not rows:
        # لا توجد بيانات
        msg = _ar("لا توجد تنبيهات اليوم")
        draw.text((left + 32, y + 8), msg, font=cell_f, fill=DIM_WHITE)
        return

    # قص على الأكثر ليستوعب البطاقة
    rows = rows[:max_rows]

    for r in rows:
        sym = str(r.get("symbol") or r.get("ticker") or "-")
        price = r.get("price") or r.get("close") or r.get("last") or None
        side_raw = r.get("side") or r.get("action")

        sig_txt, sig_color = _signal_label(str(side_raw or ""))

        draw.text((x_positions[0], y), _ar(sym), font=cell_f, fill=WHITE)
        draw.text((x_positions[1], y), _ar(_format_number(price)), font=cell_f, fill=SOFT_WHITE)
        draw.text((x_positions[2], y), sig_txt, font=cell_f, fill=sig_color)

        y += row_h

async def generate_daily_report(TG_API: str, CHAT_IDS: list[str | int], source_url: str | None = None) -> dict:
    """
    الدالة الأساسية:
    - تجلب بيانات التنبيهات من API (إن توفّر).
    - تنشئ صورة تقرير بخلفية.
    - ترسلها للقنوات/المجموعات المحددة.
    """
    # 1) جلب التنبيهات
    alerts = await _fetch_alerts(source_url)

    # 2) إنشاء الصورة
    img = _load_background(CANVAS_W, CANVAS_H)
    draw = ImageDraw.Draw(img)

    # خطوط
    title_f = _load_font(FONT_BOLD_PATH, 44)
    head_f  = _load_font(FONT_BOLD_PATH, 28)
    cell_f  = _load_font(FONT_REG_PATH, 26)

    fonts = {"title": title_f, "head": head_f, "cell": cell_f}

    # هيدر
    _draw_header(draw, title_f, _load_font(FONT_REG_PATH, 22))

    # جدول
    _draw_table(img, draw, alerts, fonts)

    # 3) إخراج إلى بافر PNG
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)

    # 4) إرسال الصورة إلى كل قناة
    results = []
    caption_text = (
        "📈 تقرير COBOT اليومي\n"
        "⚠️ جميع ما يُطرح يُعد اجتهادًا فرديًا ولا يُعتبر توصية شراء أو بيع أو احتفاظ بأي ورقة مالية."
    )

    timeout = httpx.Timeout(20.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for cid in CHAT_IDS:
            files = {"photo": ("report.png", buf.getvalue(), "image/png")}
            data = {
                "chat_id": str(cid),
                "caption": caption_text.strip() or "تقرير COBOT اليومي",
                "parse_mode": "HTML",
                "disable_notification": True,
            }
            try:
                resp = await client.post(TG_API, data=data, files=files)
                ok = bool(resp.status_code == 200 and resp.json().get("ok", True))
                results.append({"chat_id": str(cid), "ok": ok, "status": resp.status_code, "resp": resp.text[:200]})
            except Exception as e:
                results.append({"chat_id": str(cid), "ok": False, "error": str(e)})

    return {
        "status": "sent",
        "count": len(results),
        "results": results,
    }
