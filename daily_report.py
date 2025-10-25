# daily_report.py
import io, os, json, math
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import httpx

KSA_TZ = ZoneInfo("Asia/Riyadh")
W, H = 1280, 720
M = 48
BG_PATH = os.getenv("REPORT_BG", "assets/report_bg.png")
AR_FONT = os.getenv("AR_FONT_PATH", None)  # اختياري

def _font(size: int) -> ImageFont.FreeTypeFont:
    if AR_FONT and os.path.exists(AR_FONT):
        try:
            return ImageFont.truetype(AR_FONT, size)
        except Exception:
            pass
    # fallback
    return ImageFont.truetype("DejaVuSans.ttf", size)

def _load_bg() -> Image.Image:
    if BG_PATH and os.path.exists(BG_PATH):
        try:
            bg = Image.open(BG_PATH).convert("RGB")
            return bg.resize((W, H), Image.LANCZOS)
        except Exception:
            pass
    # خلفية بديلة بسيطة
    img = Image.new("RGB", (W, H), (12, 16, 22))
    grad = Image.linear_gradient("L").resize((W, H))
    img.paste(Image.new("RGB", (W, H), (20, 26, 36)), mask=grad)
    return img

def _draw_table(canvas: ImageDraw.ImageDraw, title_font, head_font, cell_font, alerts):
    # إطار شفاف فوق الخلفية
    x, y = M, M + 90
    w, h = W - 2*M, H - (y + M)
    radius = 20
    rect = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rdraw = ImageDraw.Draw(rect)
    rdraw.rounded_rectangle((0, 0, w, h), radius, fill=(0, 0, 0, 160), outline=(255, 255, 255, 25), width=2)
    canvas.bitmap((x, y), rect)

    # العناوين
    cols = ["العملة", "الإشارة", "السعر"]
    col_w = [int(w*0.45), int(w*0.25), int(w*0.30)]
    col_x = [x+24, x+24 + col_w[0], x+24 + col_w[0] + col_w[1]]
    head_y = y + 24
    for i, c in enumerate(cols):
        canvas.text((col_x[i], head_y), c, font=head_font, fill=(220, 230, 255))
    # خط فاصل
    canvas.line((x+16, head_y+48, x+w-16, head_y+48), fill=(255,255,255,40), width=2)

    row_y = head_y + 58
    for item in alerts:
        sym  = item.get("symbol","—")
        side = item.get("side","—")     # CALL أو PUT
        price = item.get("price","—")

        # رمز جانبي بسيط أخضر/أحمر
        badge_r = 10
        badge_col = (34,197,94) if str(side).upper()=="CALL" else (239, 68, 68)
        canvas.ellipse((col_x[1]-32, row_y+8-badge_r, col_x[1]-32+2*badge_r, row_y+8+2*badge_r), fill=badge_col)

        canvas.text((col_x[0], row_y), f"{sym}", font=cell_font, fill=(240, 244, 255))
        canvas.text((col_x[1], row_y), f"{side}", font=cell_font, fill=(240, 244, 255))
        canvas.text((col_x[2], row_y), f"{price}", font=cell_font, fill=(240, 244, 255))

        row_y += 50
        if row_y > y + h - 60:
            break

async def generate_daily_report(TG_API: str, CHAT_IDS: list[str]) -> dict:
    """
    TG_API: مثال https://api.telegram.org/bot<token>/sendPhoto
    CHAT_IDS: قائمة معرفات القنوات/المجموعات كسلاسل (قد تبدأ بـ -100)
    """
    # 1) جهّز اللوحة
    bg = _load_bg()
    draw = ImageDraw.Draw(bg)
    title_font = _font(44)
    head_font  = _font(28)
    cell_font  = _font(26)
    sub_font   = _font(22)

    now = datetime.now(tz=KSA_TZ)
    title = "📊 تقرير COBOT اليومي"
    sub   = f"KSA {now:%H:%M}  {now:%d-%m-%Y}"

    draw.text((M, M), title, font=title_font, fill=(255,255,255))
    draw.text((M, M+54), sub,   font=sub_font,   fill=(185,195,210))

    # 2) اقرأ آخر الإشعارات المخزّنة من الذاكرة المؤقتة (ملف JSON) لو عندك
    #   هنا مثال مبسّط: لو ما عندنا ملف نقرأ من fallback “تنبيهات اليوم”
    alerts_path = os.getenv("ALERTS_CACHE_PATH", "/tmp/alerts.json")
    alerts = []
    try:
        if os.path.exists(alerts_path):
            with open(alerts_path, "r", encoding="utf-8") as f:
                alerts = json.load(f)
    except Exception:
        alerts = []
    # لو فاضي، اعرض رسالة لطيفة بس
    if not alerts:
        alerts = [
            {"symbol":"BTCUSDT.P","side":"CALL","price":"—"},
            {"symbol":"ETHUSDT.P","side":"PUT","price":"—"},
        ]

    _draw_table(draw, title_font, head_font, cell_font, alerts)

    # عبارة إخلاء المسؤولية
    disclaimer = "⚠️ جميع ما يُطرح يُعد اجتهادًا فرديًا ولا يُعتبر توصية شراء أو بيع أو احتفاظ بأي ورقة مالية."
    draw.text((M, H- M - 10), disclaimer, font=sub_font, fill=(200,210,220))

    # 3) احفظ إلى بايتس
    buf = io.BytesIO()
    bg.save(buf, format="PNG", optimize=True)
    buf.seek(0)

    # 4) أرسل كتلقرام sendPhoto (multipart)
    errors = []
    async with httpx.AsyncClient(timeout=20) as client:
        for cid in CHAT_IDS:
            cid = cid.strip()
            if not cid: 
                continue
            try:
                files = {"photo": ("report.png", buf.getvalue(), "image/png")}
                data  = {
                    "chat_id": cid,
                    "caption": "📈 تقرير COBOT اليومي",
                    "parse_mode": "HTML",
                    "disable_notification": True,
                }
                resp = await client.post(TG_API, data=data, files=files)
                print(f"[REPORT] chat={cid} -> {resp.status_code} {resp.text[:200]}")
                if resp.status_code != 200:
                    errors.append((cid, resp.text))
            except Exception as e:
                errors.append((cid, str(e)))

    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True}
