# daily_report.py
# -*- coding: utf-8 -*-

import os
import io
import json
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

# دعم العربية (اختياري)
HAS_AR = False
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_AR = True
except Exception:
    HAS_AR = False

# ================= إعدادات عامة =================
KSA_TZ = ZoneInfo("Asia/Riyadh")
CANVAS_W, CANVAS_H = 1280, 720
MARGIN = 48

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
BG_PATH = os.path.join(ASSETS_DIR, "report_bg.png")       # خلفية التقرير
FALLBACK_BG = None                                        # يُنشئ تدرّج إذا ما وُجدت خلفية
FONT_DIR_CANDIDATES = [
    ASSETS_DIR,
    "/usr/share/fonts",
    "/usr/share/fonts/truetype",
    "/usr/share/fonts/truetype/noto",
]
# جرّب خطوط عربية شائعة، وإلاّ سيستخدم PIL الافتراضي
ARABIC_FONT_CANDIDATES = [
    "NotoNaskhArabic-Regular.ttf",
    "NotoSansArabic-Regular.ttf",
    "Amiri-Regular.ttf",
    "Cairo-Regular.ttf",
    "Tajawal-Regular.ttf",
    "Almarai-Regular.ttf",
]
LATIN_FONT_CANDIDATES = [
    "Inter-Regular.ttf",
    "DejaVuSans.ttf",
]

TITLE = "📊 تقرير COBOT اليومي"
SUBTITLE_TMPL = "KSA {ts} – تنبيهات اليوم"

# ================= أدوات مساعدة =================
def _find_font_path(name_list):
    for base in FONT_DIR_CANDIDATES:
        for name in name_list:
            p = os.path.join(base, name)
            if os.path.isfile(p):
                return p
    return None

def _load_font(size=36, prefer_arabic=True):
    """تحميل خط (عربي إن أمكن)."""
    if prefer_arabic:
        fp = _find_font_path(ARABIC_FONT_CANDIDATES)
        if fp:
            return ImageFont.truetype(fp, size)
    # لاتيني/احتياطي
    fp = _find_font_path(LATIN_FONT_CANDIDATES)
    if fp:
        return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

def ar(x: str) -> str:
    """تهيئة عرض العربية عند توفر المكتبات."""
    if not isinstance(x, str):
        x = str(x)
    if HAS_AR:
        return get_display(arabic_reshaper.reshape(x))
    return x

def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    """
    قياس عرض/ارتفاع النص بطريقة متوافقة مع الإصدارات.
    Pillow>=10: textbbox
    أقدم: textlength (عرض فقط) + تقدير الارتفاع.
    """
    if hasattr(draw, "textbbox"):
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
        return (x1 - x0, y1 - y0)
    # سقوط رجعي
    try:
        w = draw.textlength(text, font=font)
    except Exception:
        # fallback أخير جدًا
        w = len(text) * (font.size * 0.55)
    # تقدير ارتفاع سطري بسيط
    h = font.size + math.ceil(font.size * 0.3)
    return (int(w), int(h))

def _load_bg():
    if os.path.isfile(BG_PATH):
        bg = Image.open(BG_PATH).convert("RGB")
        return ImageOps.fit(bg, (CANVAS_W, CANVAS_H), Image.LANCZOS)
    # خلفية تدرّجية احتياطية
    base = Image.new("RGB", (CANVAS_W, CANVAS_H), (12, 16, 22))
    overlay = Image.new("RGB", (CANVAS_W, CANVAS_H), (18, 25, 35))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=80))
    base.paste(overlay, (0, 0), Image.new("L", (CANVAS_W, CANVAS_H), 120))
    return base

def _load_today_rows():
    """
    تحميل صفوف اليوم من مصدر محلي بسيط:
    - إذا وجد ملف ./data/alerts.json يستخدمه.
    - وإلا يرجّع قائمة فاضية.
    تنسيق كل صف:
      {"symbol":"BTCUSDT.P","side":"CALL|PUT","price": 67210.2}
    """
    data_path = os.path.join(os.path.dirname(__file__), "data", "alerts.json")
    try:
        if os.path.isfile(data_path):
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # فلترة اليوم بالتاريخ KSA (اختياري)
            today = datetime.now(KSA_TZ).date()
            rows = []
            for x in data:
                # نتساهل لو ما فيه وقت
                sym = x.get("symbol") or x.get("ticker") or ""
                side = (x.get("side") or "").upper()
                price = x.get("price") or x.get("close") or x.get("last") or ""
                ts = x.get("ts") or x.get("time") or x.get("datetime") or ""
                # إضافة مباشرة
                rows.append({
                    "symbol": str(sym),
                    "side": "CALL" if side == "CALL" else ("PUT" if side == "PUT" else side),
                    "price": price
                })
            return rows
    except Exception:
        pass
    return []

def _draw_header(draw: ImageDraw.ImageDraw, title_f: ImageFont.ImageFont, meta_f: ImageFont.ImageFont):
    title = ar(TITLE)
    ts = datetime.now(KSA_TZ).strftime("%Y-%m-%d %H:%M KSA")
    sub = ar(SUBTITLE_TMPL.format(ts=ts))

    # قياسات
    t_w, t_h = _measure_text(draw, title, title_f)
    b_w, b_h = _measure_text(draw, sub, meta_f)

    x = MARGIN
    y = MARGIN

    # ظل خفيف
    draw.text((x+2, y+2), title, font=title_f, fill=(0, 0, 0))
    draw.text((x, y), title, font=title_f, fill=(255, 255, 255))
    y += t_h + 8

    # سطر فرعي بمحاذاة يمين
    draw.text((x+2, y+2), sub, font=meta_f, fill=(0, 0, 0))
    draw.text((x, y), sub, font=meta_f, fill=(210, 218, 230))

    return y + b_h + 16  # نهاية رأس الصفحة

def _draw_table(draw: ImageDraw.ImageDraw, rows, font: ImageFont.ImageFont, small_f: ImageFont.ImageFont, top_y: int):
    # رؤوس الأعمدة
    headers = [ar("الرمز"), ar("الإشارة"), ar("السعر الحالي")]
    col_ratio = [0.42, 0.20, 0.38]   # نسب العرض
    col_x = [MARGIN]
    for i in range(1, len(col_ratio)):
        col_x.append(MARGIN + int(sum(col_ratio[:i]) * (CANVAS_W - 2*MARGIN)))
    col_w = [int(r * (CANVAS_W - 2*MARGIN)) for r in col_ratio]

    row_h = font.size + 22
    head_h = font.size + 24

    # ترويسة
    y = top_y
    # خلفية الترويسة شبه شفافة
    draw.rectangle([MARGIN, y, CANVAS_W - MARGIN, y + head_h], fill=(30, 40, 60, 120))
    for i, h in enumerate(headers):
        draw.text((col_x[i] + 12, y + 8), h, font=font, fill=(235, 240, 248))
    y += head_h + 6

    if not rows:
        msg = ar("لا توجد تنبيهات اليوم.")
        draw.text((MARGIN + 12, y + 8), msg, font=font, fill=(210, 218, 230))
        return

    # صفوف البيانات
    for r in rows:
        # شريط خلفي خفيف لكل صف
        draw.rectangle([MARGIN, y, CANVAS_W - MARGIN, y + row_h], fill=(20, 28, 38, 90))
        sym = ar(str(r.get("symbol", "")))
        side = (r.get("side") or "").upper()
        side_disp = ar("CALL") if side == "CALL" else ar("PUT")
        price = r.get("price", "")

        # الرمز
        draw.text((col_x[0] + 12, y + 10), sym, font=font, fill=(240, 244, 248))
        # الإشارة
        color = (36, 201, 105) if side == "CALL" else (235, 76, 66)
        draw.text((col_x[1] + 12, y + 10), side_disp, font=font, fill=color)
        # السعر
        draw.text((col_x[2] + 12, y + 10), ar(str(price)), font=font, fill=(230, 232, 238))

        y += row_h + 6

def _compose_image(rows):
    # خلفية
    bg = _load_bg().convert("RGB")
    draw = ImageDraw.Draw(bg)

    # خطوط
    title_f = _load_font(46, prefer_arabic=True)
    meta_f  = _load_font(28, prefer_arabic=True)
    cell_f  = _load_font(34, prefer_arabic=True)
    small_f = _load_font(24, prefer_arabic=True)

    # رأس
    next_y = _draw_header(draw, title_f, meta_f)
    # جدول
    _draw_table(draw, rows, cell_f, small_f, next_y + 8)

    # تنبيه توضيحي أسفل الصورة
    note = ar("⚠️ جميع ما يُطرح يُعد اجتهادًا فرديًا ولا يُعتبر توصية شراء أو بيع أو احتفاظ بأي ورقة مالية.")
    _, note_h = _measure_text(draw, note, small_f)
    draw.text((MARGIN, CANVAS_H - MARGIN - note_h),
              note, font=small_f, fill=(210, 218, 230))

    # إخراج
    buf = io.BytesIO()
    bg.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

async def _send_photo_to_tg(client: httpx.AsyncClient, TG_API: str, chat_id: str, image_bytes: bytes, caption: str = ""):
    url = f"{TG_API}/sendPhoto"
    files = {"photo": ("report.png", image_bytes, "image/png")}
    data = {"chat_id": chat_id, "caption": caption}
    return await client.post(url, data=data, files=files)

# ================= الدالة الرئيسية =================
async def generate_daily_report(TG_API: str, CHAT_IDS):
    """
    تُنشئ تقرير اليوم وترسله كصورة إلى قنوات/محادثات تليجرام في CHAT_IDS (قائمة).
    يعتمد على ملف data/alerts.json إن وُجد. وإلا يعرض رسالة "لا توجد تنبيهات".
    """
    # جلب صفوف اليوم
    rows = _load_today_rows()

    # تركيب الصورة
    img_buf = _compose_image(rows)
    img_bytes = img_buf.getvalue()

    # عنوان الصورة
    ts = datetime.now(KSA_TZ).strftime("%Y-%m-%d %H:%M KSA")
    caption = ar(f"📊 تقرير COBOT اليومي — {ts}")

    results = []
    async with httpx.AsyncClient(timeout=20) as client:
        for raw_cid in CHAT_IDS:
            cid = str(raw_cid).strip()
            try:
                resp = await _send_photo_to_tg(client, TG_API, cid, img_bytes, caption=caption)
                ok = False
                try:
                    ok = bool(resp.json().get("ok"))
                except Exception:
                    ok = resp.status_code == 200
                results.append((cid, ok, resp.status_code))
            except Exception as e:
                results.append((cid, False, f"exc: {e}"))

    # نتيجة تُستخدم في endpoint
    return {
        "ok": all(r[1] for r in results) if results else True,
        "results": results,
        "count": len(results),
    }
