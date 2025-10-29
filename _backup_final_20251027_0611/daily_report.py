# daily_report.py
# -*- coding: utf-8 -*-

import os, io, json, httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

HAS_AR = False
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_AR = True
except Exception:
    pass

KSA_TZ = ZoneInfo("Asia/Riyadh")
CANVAS_W, CANVAS_H = 1280, 720
MARGIN = 48
BG_PATH = "assets/report_bg.png"


def _ar(txt):
    if HAS_AR:
        return get_display(arabic_reshaper.reshape(str(txt)))
    return str(txt)


def _measure_text(draw, text, font):
    """يدعم Pillow الحديثة (بدل textsize)"""
    if hasattr(draw, "textbbox"):
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
        return x1 - x0, y1 - y0
    elif hasattr(draw, "textlength"):
        w = draw.textlength(text, font=font)
        return w, font.size
    else:
        return len(text) * (font.size * 0.5), font.size


def _load_font(size=36):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _load_bg():
    if os.path.exists(BG_PATH):
        bg = Image.open(BG_PATH).convert("RGB").resize((CANVAS_W, CANVAS_H))
        dark = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 100))
        bg.paste(dark, (0, 0), dark)
        return bg
    return Image.new("RGB", (CANVAS_W, CANVAS_H), (18, 25, 35))


def _draw_header(draw, title_f, sub_f):
    title = _ar("📊 تقرير COBOT اليومي")
    sub = _ar(datetime.now(KSA_TZ).strftime("%Y-%m-%d %H:%M KSA"))
    draw.text((MARGIN, MARGIN), title, font=title_f, fill=(255, 255, 255))
    w, _ = _measure_text(draw, sub, sub_f)
    draw.text((CANVAS_W - MARGIN - w, MARGIN + 8), sub, font=sub_f, fill=(210, 218, 230))


def _draw_table(draw, rows, font):
    y = MARGIN + 100
    if not rows:
        draw.text((MARGIN, y), _ar("لا توجد تنبيهات اليوم"), font=font, fill=(240, 240, 240))
        return
    headers = [_ar("الرمز"), _ar("الإشارة"), _ar("السعر")]
    x_positions = [MARGIN, 600, 950]
    for i, h in enumerate(headers):
        draw.text((x_positions[i], y), h, font=font, fill=(180, 200, 255))
    y += 40
    for r in rows:
        sym = _ar(r.get("symbol", "-"))
        side = (r.get("side", "") or "").upper()
        price = r.get("price", "-")
        color = (36, 201, 105) if side == "CALL" else (235, 76, 66)
        draw.text((x_positions[0], y), sym, font=font, fill=(255, 255, 255))
        draw.text((x_positions[1], y), _ar(side or "-"), font=font, fill=color)
        draw.text((x_positions[2], y), str(price), font=font, fill=(235, 235, 235))
        y += 40


def _get_today_rows():
    path = "data/alerts.json"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _compose_image(rows):
    bg = _load_bg()
    draw = ImageDraw.Draw(bg)
    title_f = _load_font(44)
    sub_f = _load_font(28)
    cell_f = _load_font(32)
    _draw_header(draw, title_f, sub_f)
    _draw_table(draw, rows, cell_f)
    buf = io.BytesIO()
    bg.save(buf, format="PNG")
    buf.seek(0)
    return buf


async def _send_image_to_telegram(img_bytes: bytes, TG_API: str, CHAT_IDS: list[str]):
    """يرسل الصورة عبر sendPhoto حتى لو TG_API كان sendMessage"""
    if TG_API.endswith("/sendMessage"):
        send_photo_url = TG_API[:-len("/sendMessage")] + "/sendPhoto"
    elif TG_API.endswith("/sendPhoto"):
        send_photo_url = TG_API
    else:
        send_photo_url = TG_API.rstrip("/") + "/sendPhoto"

    results = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for cid in CHAT_IDS:
            files = {"photo": ("report.png", img_bytes, "image/png")}
            data = {"chat_id": cid.strip(), "caption": ""}
            try:
                r = await client.post(send_photo_url, data=data, files=files)
                ok = False
                try:
                    ok = bool(r.json().get("ok", False))
                except Exception:
                    ok = r.status_code == 200
                results.append([cid.strip(), ok, r.status_code])
            except Exception as e:
                results.append([cid.strip(), False, str(e)])
    return {"ok": all(x[1] for x in results), "results": results, "count": len(results)}


async def generate_daily_report(TG_API: str, CHAT_IDS):
    rows = _get_today_rows()
    img = _compose_image(rows)
    result = await _send_image_to_telegram(img.getvalue(), TG_API, CHAT_IDS)
    return {"status": "Report generated and sent", "result": result}
