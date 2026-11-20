"""Генератор картинок для каталога: python gen_images.py
Рисует простые иллюстрации букетов по палитре из config.PRODUCTS (папка images/).
Для реального магазина замените файлы images/<ключ>.png настоящими фотографиями."""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

import config as C

W = 1600  # рисуем в 2 раза крупнее, потом уменьшаем (сглаживание)
OUT = 800


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def shade(c, t):
    return mix(c, (0, 0, 0), t) if t > 0 else mix(c, (255, 255, 255), -t)


def background(pal):
    base = mix(hexrgb(pal[0]), (255, 255, 255), 0.78)
    top = mix(base, (255, 255, 255), 0.5)
    img = Image.new("RGB", (W, W), top)
    px = ImageDraw.Draw(img)
    for y in range(W):
        px.line([(0, y), (W, y)], fill=mix(top, base, y / W))
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse([W * 0.12, W * 0.08, W * 0.88, W * 0.84], fill=mix(base, (255, 255, 255), 0.5) + (150,))
    return img


def leaf(d, x, y, ang, ln, wd, col):
    pts = []
    for i in range(0, 21):
        t = i / 20
        r = math.sin(math.pi * t) * wd
        pts.append((t * ln, r))
    for i in range(20, -1, -1):
        t = i / 20
        pts.append((t * ln, -math.sin(math.pi * t) * wd))
    ca, sa = math.cos(ang), math.sin(ang)
    d.polygon([(x + px * ca - py * sa, y + px * sa + py * ca) for px, py in pts], fill=col)


def rose(d, cx, cy, r, col):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=shade(col, 0.25))
    for i, k in enumerate([0.92, 0.74, 0.56, 0.38, 0.2]):
        rr = r * k
        off = r * 0.05 * (i % 2 * 2 - 1)
        c = shade(col, 0.12 - i * 0.06) if i % 2 == 0 else shade(col, 0.2 - i * 0.04)
        d.ellipse([cx - rr + off, cy - rr, cx + rr + off, cy + rr], fill=c, outline=shade(col, 0.3), width=max(2, int(r * 0.02)))
    d.arc([cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5], 200, 330, fill=shade(col, 0.35), width=max(2, int(r * 0.04)))


def daisy(d, cx, cy, r, col, center="#F4B400"):
    n = 12
    for i in range(n):
        a = i * 2 * math.pi / n
        pts = []
        for j in range(0, 13):
            t = j / 12
            pts.append((t * r, math.sin(math.pi * t) * r * 0.2))
        for j in range(12, -1, -1):
            t = j / 12
            pts.append((t * r, -math.sin(math.pi * t) * r * 0.2))
        ca, sa = math.cos(a), math.sin(a)
        d.polygon([(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts], fill=col, outline=shade(col, 0.15))
    d.ellipse([cx - r * 0.26, cy - r * 0.26, cx + r * 0.26, cy + r * 0.26], fill=hexrgb(center))


def tulip(d, cx, cy, w, h, col):
    body = [(cx - w / 2, cy), (cx - w * 0.55, cy - h * 0.55), (cx - w * 0.2, cy - h), (cx, cy - h * 0.7),
            (cx + w * 0.2, cy - h), (cx + w * 0.55, cy - h * 0.55), (cx + w / 2, cy)]
    d.polygon(body, fill=col)
    d.ellipse([cx - w / 2, cy - h * 0.45, cx + w / 2, cy + h * 0.1], fill=col)
    d.polygon([(cx - w * 0.1, cy + h * 0.05), (cx - w * 0.2, cy - h), (cx, cy - h * 0.72), (cx + w * 0.2, cy - h), (cx + w * 0.1, cy + h * 0.05)], fill=shade(col, 0.18))


def small_flower(d, cx, cy, r, col):
    for i in range(5):
        a = i * 2 * math.pi / 5
        x, y = cx + math.cos(a) * r * 0.6, cy + math.sin(a) * r * 0.6
        d.ellipse([x - r * 0.45, y - r * 0.45, x + r * 0.45, y + r * 0.45], fill=col, outline=shade(col, 0.12))
    d.ellipse([cx - r * 0.25, cy - r * 0.25, cx + r * 0.25, cy + r * 0.25], fill=(250, 220, 120))


GREEN = [(66, 122, 82), (90, 150, 100), (46, 100, 66)]


def paper(d, kraft=(214, 183, 140), ribbon=(190, 60, 100), y0=860):
    cone = [(W * 0.26, y0), (W * 0.74, y0), (W * 0.5, W * 0.93)]
    d.polygon(cone, fill=kraft)
    d.polygon([(W * 0.26, y0), (W * 0.5, y0 + 90), (W * 0.5, W * 0.93)], fill=shade(kraft, 0.1))
    d.line([(W * 0.26, y0), (W * 0.5, y0 + 90), (W * 0.74, y0)], fill=shade(kraft, 0.25), width=6)
    bx, by = W * 0.5, y0 + 150
    d.polygon([(bx, by), (bx - 120, by - 55), (bx - 120, by + 55)], fill=ribbon)
    d.polygon([(bx, by), (bx + 120, by - 55), (bx + 120, by + 55)], fill=ribbon)
    d.ellipse([bx - 30, by - 30, bx + 30, by + 30], fill=shade(ribbon, 0.2))


def bouquet(img, p, rnd):
    d = ImageDraw.Draw(img, "RGBA")
    pal = [hexrgb(c) for c in p["pal"]]
    style = p["style"]
    base = (W * 0.5, W * 0.78)
    n = {"roses": 11, "bush": 15, "mixed": 11, "tulips": 13, "daisy": 12}.get(style, 11)
    pts = []
    for i in range(n):
        ring = 0 if i == 0 else (1 if i < 6 else 2)
        a = rnd.uniform(0, 2 * math.pi) if ring == 0 else (i * 2 * math.pi / (5 if ring == 1 else n - 6) + rnd.uniform(-0.3, 0.3))
        rad = [0, 230, 400][ring]
        x = W * 0.5 + math.cos(a) * rad * 1.05
        y = W * 0.4 + math.sin(a) * rad * 0.72
        pts.append((x, y, [150, 125, 110][ring] * rnd.uniform(0.9, 1.1)))
    for i in range(14):  # зелень
        a = rnd.uniform(0, 2 * math.pi)
        x, y = W * 0.5 + math.cos(a) * 420, W * 0.42 + math.sin(a) * 330
        leaf(d, x, y, a + rnd.uniform(-0.3, 0.3), 260, 55, rnd.choice(GREEN))
    for x, y, r in pts:  # стебли
        d.line([(x, y), base], fill=(70, 130, 80), width=14)
    pts.sort(key=lambda t: t[1])
    for x, y, r in pts:
        c = rnd.choice(pal)
        if style in ("roses", "mixed") and (style == "roses" or rnd.random() < 0.55):
            rose(d, x, y, r, c)
        elif style == "bush":
            for k in range(7):
                small_flower(d, x + rnd.uniform(-90, 90), y + rnd.uniform(-90, 90), r * 0.48, rnd.choice(pal))
        elif style == "tulips":
            tulip(d, x, y + 90, r * 1.25, r * 2.1, c)
        elif style == "daisy":
            daisy(d, x, y, r * 0.9, c if style == "daisy" and sum(c) > 600 else shade(c, 0), center="#F4B400")
        else:
            small_flower(d, x, y, r * 0.8, c)
    kraft = rnd.choice([(214, 183, 140), (233, 224, 210), (241, 205, 205)])
    paper(d, kraft, ribbon=shade(pal[0], 0.2) if sum(pal[0]) < 600 else (190, 60, 100))


def orchid(img, p, rnd):
    d = ImageDraw.Draw(img, "RGBA")
    pal = [hexrgb(c) for c in p["pal"]]
    d.polygon([(W * 0.36, W * 0.72), (W * 0.64, W * 0.72), (W * 0.58, W * 0.92), (W * 0.42, W * 0.92)], fill=(240, 240, 235))
    for i in range(3):
        leaf(d, W * 0.5, W * 0.72, math.pi * (0.9 + i * 0.1) * (1 if i != 1 else 0.5) + 0.2, 380, 70, GREEN[i % 3])
    pts = [(W * 0.5 + math.sin(t / 5) * 120 + t * 14, W * 0.7 - t * 48) for t in range(0, 12)]
    d.line(pts, fill=(80, 130, 80), width=12)
    for i, (x, y) in enumerate(pts[3:], 3):
        r = 120 - i * 4
        for k in range(5):
            a = k * 2 * math.pi / 5 - math.pi / 2
            ex, ey = x + math.cos(a) * r * 0.55, y + math.sin(a) * r * 0.55
            d.ellipse([ex - r * 0.5, ey - r * 0.45, ex + r * 0.5, ey + r * 0.45], fill=pal[i % len(pal)], outline=shade(pal[i % len(pal)], 0.15))
        d.ellipse([x - r * 0.2, y - r * 0.2, x + r * 0.2, y + r * 0.2], fill=(250, 220, 140))


def succ(img, p, rnd):
    d = ImageDraw.Draw(img, "RGBA")
    pal = [hexrgb(c) for c in p["pal"]]
    for x, y, r in [(0.5, 0.52, 250), (0.33, 0.62, 170), (0.68, 0.6, 190), (0.46, 0.4, 130)]:
        cx, cy = W * x, W * y
        c = rnd.choice(pal)
        for ring, k in enumerate([1.0, 0.75, 0.5, 0.28]):
            n = 10 - ring * 2
            for i in range(n):
                a = i * 2 * math.pi / n + ring * 0.3
                leaf(d, cx, cy, a, r * k, r * k * 0.28, shade(c, 0.12 * ring - 0.1))
    d.polygon([(W * 0.26, W * 0.68), (W * 0.74, W * 0.68), (W * 0.66, W * 0.92), (W * 0.34, W * 0.92)], fill=(222, 210, 198))
    d.rectangle([W * 0.24, W * 0.66, W * 0.76, W * 0.7], fill=(205, 190, 176))


def gift(img, p, rnd):
    d = ImageDraw.Draw(img, "RGBA")
    pal = [hexrgb(c) for c in p["pal"]]
    c = pal[0]
    if p["name"].startswith("Гелиевые"):
        for i, col in enumerate(pal):
            x, y = W * (0.28 + i * 0.11), W * (0.3 + (i % 2) * 0.08)
            d.line([(x, y + 150), (W * 0.5, W * 0.88)], fill=(120, 120, 120), width=5)
            d.ellipse([x - 130, y - 160, x + 130, y + 160], fill=col)
            d.ellipse([x - 70, y - 110, x - 30, y - 60], fill=(255, 255, 255, 110))
        return
    d.rectangle([W * 0.28, W * 0.46, W * 0.72, W * 0.86], fill=c)
    d.rectangle([W * 0.25, W * 0.4, W * 0.75, W * 0.5], fill=shade(c, 0.12))
    d.rectangle([W * 0.47, W * 0.4, W * 0.53, W * 0.86], fill=pal[-1])
    d.ellipse([W * 0.38, W * 0.3, W * 0.5, W * 0.42], outline=pal[-1], width=22)
    d.ellipse([W * 0.5, W * 0.3, W * 0.62, W * 0.42], outline=pal[-1], width=22)


def render(key, p):
    rnd = random.Random(key)
    img = background(p["pal"])
    {"orchid": orchid, "succ": succ, "gift": gift}.get(p["style"], bouquet)(img, p, rnd)
    img = img.filter(ImageFilter.GaussianBlur(0.6)).resize((OUT, OUT), Image.LANCZOS)
    return img


def main():
    os.makedirs(C.IMG_DIR, exist_ok=True)
    for key, p in C.PRODUCTS.items():
        render(key, p).save(os.path.join(C.IMG_DIR, f"{key}.png"), optimize=True)
        print("ok", key)


if __name__ == "__main__":
    main()
