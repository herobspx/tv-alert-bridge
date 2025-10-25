import os
import io
import math
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# دعم العربية (اختياري — لو غير متوفر نكمل بدونه)
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_AR = True
except Exception:
    HAS_AR = False

# ------------ إعدادات عامة ------------
KSA_TZ = ZoneInfo("Asia/Riyadh")
CANVAS_W, CANVAS_H = 1280, 720
MARGIN = 48
BG_BLUR = 3
BG_DARKEN = 120  # مستوى تغميق (0 شفاف - 255 أسود)

TITLE = "📊 تقرير COBOT اليومي"
SUBTITLE = lambda: datetime.now(KSA_TZ).strftime("بتاريخ %Y-%m-%d %H:%M KSA")

# ألوان وهوية
COLOR_ACCENT = (46, 204, 113)  # أخضر أنيق
COLOR_TEXT = (245, 245, 247)   # نص فاتح
COLOR_MUTED = (200, 200, 205)
COLOR_TABLE_BG = (10, 12, 18, 220)  # طبقة نصف شفافة
COLOR_ROW_ODD = (255, 255, 255, 12)
COLOR_ROW_EVEN = (255, 255, 255, 20)
COLOR_BORDER = (255, 255, 255, 40)

# الأعمدة (اسم، العرض النسبي)
COLUMNS = [
    ("الرمز", 0.30),
    ("الإشارة", 0.18),
    ("السعر", 0.22),
    ("الملاحظة", 0.30),
]

# خطوط (حاولنا نوفّق بين بيئات مختلفة)
def load_font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for path in [p for p in candidates if p]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    # fallback
    return ImageFont.load_default()

FONT_TITLE   = load_font(52, bold=True)
FONT_SUB     = load_font(28)
FONT_HEAD    = load_font(30, bold=True)
FONT_CELL    = load_font(28)

# إعادة تشكيل و اتجاه نص عربي (لو توفّر)
def ar(txt: str) -> str:
    if not txt:
        return ""
    if not HAS_AR:
        return txt
    try:
        return get_display(arabic_reshaper.reshape(txt))
    except Exception:
        return txt

# قراءة صورة خلفية (صورة البوت) إن توفرت عبر متغير بيئة
def load_bg_image():
    # جرّب مسارين شائعين، أو استخدم ENV
    bg_path_env = os.getenv("REPORT_BG_PATH", "").strip()
    candidates = [
        bg_path_env,
        "/opt/render/project/src/assets/group_hero.png",  # لو رفعتها داخل المشروع
        "/opt/render/project/src/assets/bot_bg.png",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            try:
                return Image.open(p).convert("RGB")
            except Exception:
                pass
    # خلفية متدرجة بديلة
    grad = Image.new("RGB", (CANVAS_W, CANVAS_H), (12, 14, 20))
    gdraw = ImageDraw.Draw(grad)
    for y in range(CANVAS_H):
        t = y / CANVAS_H
        r = int(12 + 10 * t)
        g = int(14 + 22 * t)
        b = int(20 + 40 * t)
        gdraw.line([(0, y), (CANVAS_W, y)], fill=(r, g, b))
    return grad

# رسم مستطيل بزوايا دائرية
def round_rect(draw, xy, radius, fill, outline=None, width=1):
    (x1, y1, x2, y2) = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

# جلب بيانات التنبيهات من API خارجي
def fetch_alerts():
    """
    يُتوقع من ALERTS_API_URL أن يُرجع JSON على شكل قائمة من العناصر:
    [
      {"symbol": "BTCUSDT.P", "side": "CALL", "price": 27123.5, "note": "اختياري"},
      ...
    ]
    """
    url = os.getenv("ALERTS_API_URL", "").strip()
    if not url:
        # بيانات تجريبية — للتجربة السريعة
        return [
            {"symbol": "BTCUSDT.P",  "side": "CALL", "price": 67589.12, "note": "تنبيه تجريبي"},
            {"symbol": "ETHUSDT.P",  "side": "PUT",  "price": 3950.10,  "note": ""},
            {"symbol": "BNBUSDT.P",  "side": "PUT",  "price": 1112.74,  "note": ""},
            {"symbol": "EVAUSDT.P",  "side": "CALL", "price": 9.3709,    "note": ""},
            {"symbol": "ZECUSDT.P",  "side": "PUT",  "price": 272.78,    "note": ""},
            {"symbol": "XRPUSDT.P",  "side": "CALL", "price": 2.5933,    "note": ""},
        ]
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            if not isinstance(data, list):
                raise ValueError("Unexpected alerts payload")
            return data
    except Exception as e:
        # رجّع بيانات بسيطة بدل الفشل
        return [
            {"symbol": "BTCUSDT.P",  "side": "CALL", "price": 67589.12, "note": f"fallback: {e}"},
        ]

def fmt_price(p):
    try:
        v = float(p)
        if v >= 1000: return f"{v:,.2f}"
        if v >= 1:    return f"{v:.4f}"
        return f"{v:.6f}"
    except Exception:
        return str(p)

def side_emoji(side):
    s = str(side or "").upper()
    if s == "CALL": return "🟢 CALL"
    if s == "PUT":  return "🔴 PUT"
    return "⚪️ غير معروف"

# ------------- مولّد التقرير (يُستدعى من app.py) -------------
def generate_daily_report(app=None):
    alerts = fetch_alerts()

    # حفّظ خلفية
    bg = load_bg_image().resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
    # تغميق خفيف وطمس بسيط
    dark = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, BG_DARKEN))
    bg = bg.filter(ImageFilter.GaussianBlur(BG_BLUR))
    bg.paste(dark, (0, 0), dark)

    im = bg.convert("RGBA")
    draw = ImageDraw.Draw(im)

    # عنوان
    draw.text((MARGIN, MARGIN),
              ar(TITLE), fill=COLOR_TEXT, font=FONT_TITLE, anchor="la")
    draw.text((MARGIN, MARGIN + 64),
              ar(SUBTITLE()), fill=COLOR_MUTED, font=FONT_SUB, anchor="la")

    # إطار الجدول
    top = MARGIN + 64 + 40
    table_x1 = MARGIN
    table_x2 = CANVAS_W - MARGIN
    table_y1 = top + 32
    row_h = 60
    header_h = 64
    n_rows = max(1, min(len(alerts), 10))  # لا نعرض أكثر من 10 في الصورة الافتراضية
    table_y2 = table_y1 + header_h + n_rows * row_h

    # خلفية الجدول
    rr = (table_x1, table_y1, table_x2, table_y2)
    round_rect(draw, rr, radius=18, fill=COLOR_TABLE_BG, outline=COLOR_BORDER, width=2)

    # تقسيم الأعمدة
    w = table_x2 - table_x1
    col_widths = [int(w * c[1]) for c in COLUMNS]
    # ضبط آخر عمود ليأخذ الباقي
    col_widths[-1] = w - sum(col_widths[:-1])

    # رسم الهيدر
    x = table_x1
    for (name, _), cw in zip(COLUMNS, col_widths):
        draw.text((x + cw - 16, table_y1 + header_h/2),
                  ar(name), fill=COLOR_TEXT, font=FONT_HEAD, anchor="ra")
        x += cw

    # خط فاصل تحت الهيدر
    draw.line([(table_x1 + 12, table_y1 + header_h),
               (table_x2 - 12, table_y1 + header_h)],
              fill=COLOR_BORDER, width=2)

    # الصفوف
    y = table_y1 + header_h
    for idx in range(n_rows):
        row = alerts[idx]
        symbol = str(row.get("symbol", "—"))
        side   = side_emoji(row.get("side"))
        price  = fmt_price(row.get("price"))
        note   = row.get("note", "") or "—"

        # خلفية صف
        fill_row = COLOR_ROW_EVEN if idx % 2 == 0 else COLOR_ROW_ODD
        draw.rectangle([(table_x1, y), (table_x2, y + row_h)], fill=fill_row)

        # نصوص الأعمدة (محاذاة يمين للعربية)
        x = table_x1
        cells = [symbol, side, price, note]
        for cval, cw in zip(cells, col_widths):
            draw.text((x + cw - 16, y + row_h/2),
                      ar(str(cval)), fill=COLOR_TEXT, font=FONT_CELL, anchor="ra")
            x += cw

        y += row_h

    # تذييل بسيط
    footer = "⚠️ جميع ما يطرح هو اجتهاد فردي ولا يُعتبر توصية شراء/بيع/احتفاظ"
    draw.text((CANVAS_W - MARGIN, table_y2 + 24),
              ar(footer), fill=(220, 220, 225), font=FONT_SUB, anchor="ra")

    out_path = "/tmp/daily_report.png"
    im.convert("RGB").save(out_path, "PNG", optimize=True)
    return {"image_path": out_path, "caption": "📊 تقرير COBOT اليومي"}
