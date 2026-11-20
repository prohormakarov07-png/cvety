"""Ядро бота цветочного магазина: вся логика экранов без привязки к мессенджеру.

Адаптеры (bot_tg.py для Telegram, bot_max.py для MAX) только:
  • передают сюда события: handle_start / handle_action / handle_text / handle_contact
  • показывают то, что вернулось: список Out(кому, Screen)
Кнопка описывается парой (текст, payload). Особые payload: "!contact" (запросить номер),
строка на http... (ссылка).
"""
import html
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

import config as C
import storage as S

ADMINS = set()


def configure(admin_ids):
    ADMINS.clear()
    ADMINS.update(admin_ids)


@dataclass
class Screen:
    text: str
    rows: list = field(default_factory=list)
    photo: str = None
    new: bool = False  # True: отправить новым сообщением, а не править прежнее
    contact: bool = False  # показать системную кнопку «Отправить номер»


@dataclass
class Out:
    to: int  # None: ответ тому, кто написал
    screen: Screen
    delay: float = 0.0


SESS = {}
HOME = [("🏠 Меню", "home")]


def sess(uid):
    return SESS.setdefault(uid, {})


def is_admin(uid):
    return uid in ADMINS


# =================================== хелперы ===================================
def esc(s):
    return html.escape(str(s or ""))


def money(n):
    return f"{int(n):,}".replace(",", " ") + " ₽"


def normalize_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return "+" + digits if 11 <= len(digits) <= 15 else None


WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def fmt_date(d):
    return f"{d.day:02d}.{d.month:02d}"


def day_label(d):
    today = S.now_local().date()
    if d == today:
        return f"Сегодня, {fmt_date(d)}"
    if d == today + timedelta(days=1):
        return f"Завтра, {fmt_date(d)}"
    return f"{WD[d.weekday()]}, {fmt_date(d)}"


def one(text, rows=None, **kw):
    return [Out(None, Screen(text, rows or [HOME], **kw))]


def photo_path(key):
    if not C.SHOW_PHOTOS:
        return None
    p = os.path.join(C.IMG_DIR, f"{key}.png")
    return p if os.path.exists(p) else None


def pmin(p):
    return min(v[1] for v in p["var"])


# ================================== меню =======================================
WELCOME = (
    "🌷 Привет, {name}!\n\n"
    "Это <b>{shop}</b>, {tag}. Здесь можно:\n"
    "• выбрать букет и оформить доставку за пару минут\n"
    "• заказать сюрприз и открытку с текстом\n"
    "• собрать букет под свой бюджет и пожелания\n"
    "• сохранить важные даты, мы напомним заранее\n\n"
    "Чтобы найти цветы, просто напишите название, например «пионы». Выберите раздел 👇"
)


def menu_rows(uid):
    n = S.cart_count(uid)
    rows = [
        [("💐 Каталог", "cat"), (f"🛒 Корзина{f' ({n})' if n else ''}", "cart")],
        [("🎨 Собрать букет на заказ", "cb")],
        [("📦 Мои заказы", "ord:act"), ("❤️ Избранное", "favs:1")],
        [("🔥 Акции", "promos"), ("🚚 Доставка и оплата", "deliv")],
        [("⭐ Отзывы", "reviews"), ("📍 Контакты", "contacts")],
        [("🔔 Важные даты", "dr"), ("❓ Вопросы", "faq")],
        [("✉️ Написать нам", "support")],
    ]
    if is_admin(uid):
        rows.append([("🛠 Админ-панель", "adm")])
    return rows


def home(uid, name, new=False):
    st = sess(uid)
    st.clear()
    first = esc((name or "гость").split()[0])
    return one(WELCOME.format(name=first, shop=C.SHOP["name"], tag=C.SHOP["tagline"]), menu_rows(uid), new=new)


# ================================== каталог ====================================
PAGE = 5
PRICE_RANGES = [(0, 2500), (2500, 4500), (4500, 7000), (7000, 10**6)]


def range_label(lo, hi):
    if lo == 0:
        return f"до {money(hi)}"
    if hi >= 10**6:
        return f"от {money(lo)}"
    return f"{money(lo)} – {money(hi)}"


def catalog_home():
    rows = [[(t, f"cat:{k}:1")] for k, t in C.CATEGORIES.items() if k != "gifts"]
    rows.append([("🔥 Хиты продаж", "hits:1"), ("🎯 По поводу", "occ")])
    rows.append([("💰 По бюджету", "pr"), ("🧸 Подарки к букету", "cat:gifts:1")])
    rows.append(HOME)
    return one("💐 <b>Каталог</b>\n\nВыберите раздел. Фото и состав внутри. Можно просто написать название цветов.", rows)


def product_btn(key):
    p = C.PRODUCTS[key]
    stop = "⛔ " if S.is_stopped(key) else ""
    label = f"{stop}{p['emoji']} {p['name']} · от {money(pmin(p))}"
    return [(label[:60], f"p:{key}")]


def list_screen(uid, title, keys, page, base, back="cat"):
    st = sess(uid)
    st["last"] = f"{base}:{page}"
    total = max(1, (len(keys) + PAGE - 1) // PAGE)
    page = min(max(page, 1), total)
    chunk = keys[(page - 1) * PAGE: page * PAGE]
    if not keys:
        return one(f"{title}\n\nПока ничего нет.", [[("💐 Каталог", "cat")], HOME])
    rows = [product_btn(k) for k in chunk]
    if total > 1:
        nav = []
        if page > 1:
            nav.append(("◀️", f"{base}:{page - 1}"))
        nav.append((f"{page}/{total}", f"{base}:{page}"))
        if page < total:
            nav.append(("▶️", f"{base}:{page + 1}"))
        rows.append(nav)
    rows.append([("◀️ Назад", back), ("🛒 Корзина", "cart")])
    rows.append(HOME)
    return one(f"{title}\n\nНайдено: {len(keys)}. Выберите, чтобы посмотреть фото и состав.", rows)


def product_card(uid, key, var=0):
    p = C.PRODUCTS[key]
    var = min(max(var, 0), len(p["var"]) - 1)
    stopped = S.is_stopped(key)
    avg, n = S.product_rating(key)
    lines = [f"{p['emoji']} <b>{esc(p['name'])}</b>", "", esc(p["desc"]), f"<i>Состав:</i> {esc(p['comp'])}"]
    if avg:
        lines.append(f"⭐ {avg} ({n} отзыв.)")
    if p["occ"]:
        lines.append("🎯 " + ", ".join(C.OCCASIONS[o].split(" ", 1)[1] for o in p["occ"][:3]))
    lines.append("")
    lines.append(f"💰 <b>{money(p['var'][var][1])}</b> ({esc(p['var'][var][0])})")
    if stopped:
        lines.append("⛔ Временно нет в наличии")
    rows = []
    if len(p["var"]) > 1:
        rows.append([(("● " if i == var else "") + f"{lab} · {money(pr)}", f"pv:{key}:{i}") for i, (lab, pr) in enumerate(p["var"])])
    if not stopped:
        rows.append([(f"🛒 В корзину · {money(p['var'][var][1])}", f"add:{key}:{var}")])
    fav = S.is_fav(uid, key)
    rows.append([("💔 Убрать из избранного" if fav else "❤️ В избранное", f"fav:{key}:{var}")])
    rows.append([("◀️ Назад", sess(uid).get("last", "cat:" + p["cat"] + ":1")), ("🛒 Корзина", "cart")])
    rows.append(HOME)
    return one("\n".join(lines), rows, photo=photo_path(key))


def search_keys(text):
    words = [w[:5].lower() for w in re.findall(r"[\wё]+", text.lower()) if len(w) >= 3]
    if not words:
        return []
    res = []
    for k, p in C.PRODUCTS.items():
        hay = (p["name"] + " " + p["comp"] + " " + p["desc"] + " " + " ".join(C.OCCASIONS[o] for o in p["occ"])).lower()
        if any(w in hay for w in words):
            res.append(k)
    return res


# =================================== корзина ===================================
def calc(uid, mode=None, zone=None, promo=None, exact=False):
    lines = []
    for r in S.cart_get(uid):
        p = C.PRODUCTS.get(r["key"])
        if not p:
            continue
        var = min(r["var"], len(p["var"]) - 1)
        label, price = p["var"][var]
        lines.append({"key": r["key"], "var": var, "qty": r["qty"], "name": p["name"], "label": label,
                      "price": price, "sum": price * r["qty"], "stopped": S.is_stopped(r["key"])})
    items_sum = sum(ln["sum"] for ln in lines)
    pct, dname, applied, perr = 0, None, None, None
    if promo:
        code = C.PROMOS.get(promo)
        if not code:
            perr = "Такого промокода нет"
        elif code[1] and S.has_orders(uid):
            perr = "Промокод действует только на первый заказ"
        else:
            pct, dname, applied = code[0], f"промокод {promo}", promo
    if mode == "pickup" and C.PICKUP_DISCOUNT > pct:
        pct, dname = C.PICKUP_DISCOUNT, "самовывоз"
    discount = round(items_sum * pct / 100)
    fee, free_note = 0, None
    if mode == "delivery" and zone:
        _, price, _, free = C.ZONES[zone]
        if free and items_sum >= free:
            fee, free_note = 0, "бесплатно"
        else:
            fee = price
    if exact:
        fee += C.EXACT_TIME_FEE
    return {"lines": lines, "items_sum": items_sum, "discount": discount, "disc_name": dname, "pct": pct,
            "fee": fee, "free_note": free_note, "total": items_sum - discount + fee, "promo": applied,
            "promo_err": perr}


def cart_screen(uid, note=None):
    st = sess(uid)
    c = calc(uid, promo=st.get("promo"))
    if not c["lines"]:
        return one("🛒 <b>Корзина пуста</b>\n\nДобавьте что-нибудь из каталога.", [[("💐 В каталог", "cat")], HOME])
    out = ["🛒 <b>Ваша корзина</b>", ""]
    rows = []
    for i, ln in enumerate(c["lines"], 1):
        warn = " ⛔ нет в наличии" if ln["stopped"] else ""
        out.append(f"{i}. {esc(ln['name'])} ({esc(ln['label'])}) × {ln['qty']} = <b>{money(ln['sum'])}</b>{warn}")
        k, v = ln["key"], ln["var"]
        rows.append([("➖", f"q:{k}:{v}:-"), (f"{ln['name'][:18]} ×{ln['qty']}", f"p:{k}"), ("➕", f"q:{k}:{v}:+"),
                     ("🗑", f"q:{k}:{v}:x")])
    out.append("")
    out.append(f"Товары: {money(c['items_sum'])}")
    if c["discount"]:
        out.append(f"Скидка ({c['disc_name']}): −{money(c['discount'])}")
    out.append(f"<b>Итого без доставки: {money(c['items_sum'] - c['discount'])}</b>")
    if c["items_sum"] < C.MIN_ORDER:
        out.append(f"\n⚠️ Минимальная сумма заказа {money(C.MIN_ORDER)}")
    if c["promo_err"]:
        out.append(f"\n⚠️ {c['promo_err']}")
    if note:
        out.append("\n" + note)
    if any(ln["stopped"] for ln in c["lines"]):
        out.append("\n⛔ Уберите позиции, которых нет в наличии.")
    rows.append([("🎁 Добавить подарок", "xtra"), (("🏷 Промокод" if not c["promo"] else "🏷 Убрать промокод"), "promo" if not c["promo"] else "promo:x")])
    rows.append([("✅ Оформить заказ", "co")])
    rows.append([("💐 Продолжить покупки", "cat"), ("🗑 Очистить", "cart:clear")])
    rows.append(HOME)
    return one("\n".join(out), rows)


def xtra_screen(uid, note=None):
    keys = [k for k, p in C.PRODUCTS.items() if p["cat"] == "gifts" and not S.is_stopped(k)]
    rows = [[(f"{C.PRODUCTS[k]['emoji']} {C.PRODUCTS[k]['name']} · {money(C.PRODUCTS[k]['var'][0][1])}", f"ax:{k}")] for k in keys]
    rows.append([("🛒 К корзине", "cart")])
    rows.append(HOME)
    text = "🎁 <b>Добавьте подарок к букету</b>\nЧасто берут вместе с цветами."
    if note:
        text = note + "\n\n" + text
    return one(text, rows)


# ================================ оформление ===================================
def valid_day_options(mode):
    res = []
    today = S.now_local().date()
    for off in range(C.ORDER_DAYS):
        d = today + timedelta(days=off)
        if slot_options(mode, d):
            res.append((off, d))
    return res


def slot_options(mode, d):
    """Список доступных окон: [(код, подпись, start_at datetime)]."""
    now = S.now_local()
    res = []
    if mode == "pickup":
        for h in C.PICKUP_HOURS:
            start = datetime.combine(d, time(h))
            if start - now >= timedelta(minutes=C.LEAD_PICKUP_MIN):
                res.append((f"h{h}", f"к {h}:00", start))
        return res
    if d == now.date() and C.OPEN_H * 60 <= now.hour * 60 + now.minute <= (C.CLOSE_H - 3) * 60:
        res.append(("a", "Срочно (~2 часа)", now + timedelta(minutes=120)))
    for i, (label, h1, _h2) in enumerate(C.DELIVERY_SLOTS):
        start = datetime.combine(d, time(h1))
        if start - now >= timedelta(minutes=C.LEAD_DELIVERY_MIN) and S.slot_load(d.isoformat(), label) < C.SLOT_CAPACITY:
            res.append((f"s{i}", label, start))
    return res


def co_calc(uid):
    st = sess(uid)
    co = st.get("co", {})
    return calc(uid, mode=co.get("mode"), zone=co.get("zone"), promo=st.get("promo"), exact=co.get("exact"))


def co_start(uid):
    st = sess(uid)
    c = calc(uid, promo=st.get("promo"))
    if not c["lines"]:
        return cart_screen(uid)
    if c["items_sum"] < C.MIN_ORDER:
        return cart_screen(uid, f"Добавьте товары ещё на {money(C.MIN_ORDER - c['items_sum'])}, чтобы оформить заказ.")
    if any(ln["stopped"] for ln in c["lines"]):
        return cart_screen(uid)
    st["co"] = {}
    st["mode"] = None
    return co_next(uid)


def co_next(uid, name=""):
    st = sess(uid)
    co = st.setdefault("co", {})
    st["mode"] = None
    if "mode" not in co:
        return one(
            "📦 <b>Как получить заказ?</b>",
            [[("🚚 Доставка курьером", "co:m:delivery")],
             [(f"🏪 Самовывоз (−{C.PICKUP_DISCOUNT}%)", "co:m:pickup")],
             [("◀️ В корзину", "cart")]],
        )
    if co["mode"] == "delivery":
        if "zone" not in co:
            rows = [[(f"{v[0]} · {money(v[1])}" + (f" (бесплатно от {money(v[3])})" if v[3] else ""), f"co:z:{k}")] for k, v in C.ZONES.items()]
            rows.append([("◀️ Назад", "co:ed:mode")])
            txt = "📍 <b>Куда доставить?</b>\n\n" + "\n".join(f"• <b>{v[0]}</b>: {v[2]}" for v in C.ZONES.values())
            return one(txt, rows)
        if "addr" not in co:
            st["mode"] = "co_addr"
            return one("🏠 Напишите адрес доставки одним сообщением: улица, дом, квартира, подъезд, этаж.",
                       [[("◀️ Назад", "co:ed:addr")]])
        if "who" not in co:
            return one("👤 <b>Кто получит цветы?</b>",
                       [[("Я сам(а)", "co:w:me")], [("Другой человек", "co:w:other")], [("◀️ Назад", "co:ed:addr")]])
        if co["who"] == "other":
            if "rname" not in co:
                st["mode"] = "co_rname"
                return one("Как зовут получателя? Напишите имя.", [[("◀️ Назад", "co:ed:rcp")]])
            if "rphone" not in co:
                st["mode"] = "co_rphone"
                return one("Телефон получателя (для курьера). Пример: +7 914 000-00-00", [[("◀️ Назад", "co:ed:rcp")]])
            if "surprise" not in co:
                return one(
                    "🤫 <b>Это сюрприз?</b>\nЕсли да, курьер не будет звонить получателю заранее.",
                    [[("Да, сюрприз", "co:s:1"), ("Нет, можно звонить", "co:s:0")]],
                )
    if "date" not in co:
        opts = valid_day_options(co["mode"])
        if not opts:
            return one("К сожалению, свободных окон на ближайшие дни нет. Напишите нам, подберём время.",
                       [[("✉️ Написать", "support")], HOME])
        rows, line = [], []
        for off, d in opts:
            line.append((day_label(d), f"co:d:{off}"))
            if len(line) == 2:
                rows.append(line)
                line = []
        if line:
            rows.append(line)
        rows.append([("◀️ Назад", "co:ed:addr" if co["mode"] == "delivery" else "co:ed:mode")])
        return one("📅 <b>На какой день?</b>", rows)
    if "slot" not in co:
        d = datetime.fromisoformat(co["date"]).date()
        opts = slot_options(co["mode"], d)
        if not opts:
            co.pop("date", None)
            return co_next(uid)
        rows, line = [], []
        for code, label, _ in opts:
            line.append((label, f"co:t:{code}"))
            if len(line) == 3:
                rows.append(line)
                line = []
        if line:
            rows.append(line)
        if co["mode"] == "delivery":
            rows.append([(f"🎯 К точному времени (+{money(C.EXACT_TIME_FEE)})", "co:t:e")])
        rows.append([("◀️ Другой день", "co:ed:time")])
        title = "🕒 <b>Выберите окно доставки</b>" if co["mode"] == "delivery" else "🕒 <b>К какому часу собрать?</b>"
        return one(f"{title}\n{day_label(d)}", rows)
    if "card" not in co:
        return one("💌 <b>Добавить открытку?</b>\nНапишем от руки ваш текст. Бесплатно.",
                   [[("Да, с текстом", "co:c:y")], [("Без открытки", "co:c:n")], [("◀️ Назад", "co:ed:time")]])
    if "comment" not in co:
        st["mode"] = "co_comment"
        return one("📝 Комментарий к заказу (цвет роз, пожелания флористу, домофон). Напишите или пропустите.",
                   [[("Пропустить", "co:cm:skip")], [("◀️ Назад", "co:ed:card")]])
    if "pay" not in co:
        rows = [[(v[0], f"co:p:{k}")] for k, v in C.PAYMENTS.items()]
        rows.append([("◀️ Назад", "co:ed:card")])
        return one("💳 <b>Как будете оплачивать?</b>", rows)
    user = S.get_user(uid)
    if not (user and user.get("phone")):
        st["mode"] = "phone"
        st["then"] = "co"
        return one("📱 Оставьте номер телефона для связи. Нажмите кнопку или напишите номер.",
                   [[("📱 Отправить мой номер", "!contact")], [("◀️ В корзину", "cart")]], contact=True)
    return co_confirm(uid)


def co_summary(uid, co, c, phone):
    d = datetime.fromisoformat(co["date"]).date()
    out = ["📋 <b>Проверьте заказ</b>", ""]
    for ln in c["lines"]:
        out.append(f"• {esc(ln['name'])} ({esc(ln['label'])}) × {ln['qty']} = {money(ln['sum'])}")
    out.append("")
    if co["mode"] == "delivery":
        out.append(f"🚚 Доставка: {esc(C.ZONES[co['zone']][0])}, {esc(co['addr'])}")
        if co.get("who") == "other":
            out.append(f"🎁 Получатель: {esc(co['rname'])}, {esc(co['rphone'])}" + (" 🤫 сюрприз" if co.get("surprise") else ""))
    else:
        out.append(f"🏪 Самовывоз: {esc(C.SHOP['address'])}")
    out.append(f"🕒 {day_label(d)}, {esc(co['slot'])}")
    if co.get("card"):
        out.append(f"💌 Открытка: «{esc(co['card'])}»")
    if co.get("comment"):
        out.append(f"📝 {esc(co['comment'])}")
    out.append(f"💳 {esc(C.PAYMENTS[co['pay']][0])}")
    out.append(f"📞 Ваш телефон: {esc(phone)}")
    out.append("")
    out.append(f"Товары: {money(c['items_sum'])}")
    if c["discount"]:
        out.append(f"Скидка ({c['disc_name']}): −{money(c['discount'])}")
    if co["mode"] == "delivery":
        out.append("Доставка: " + ("бесплатно" if c["fee"] == 0 else money(c["fee"])))
    out.append(f"<b>Итого к оплате: {money(c['total'])}</b>")
    return "\n".join(out)


def co_confirm(uid):
    st = sess(uid)
    co = st["co"]
    user = S.get_user(uid) or {}
    c = co_calc(uid)
    rows = [[("✅ Подтвердить заказ", "co:ok")],
            [("✏️ Получение", "co:ed:mode"), ("🕒 Время", "co:ed:time")],
            [("💌 Открытка", "co:ed:card"), ("💳 Оплата", "co:ed:pay")],
            [("🛒 Корзина", "cart"), ("🏠 Меню", "home")]]
    return one(co_summary(uid, co, c, user.get("phone") or ""), rows)


STATUS = {
    "new": "🆕 Ждёт подтверждения", "confirmed": "✅ Принят", "assembling": "💐 Собираем",
    "onway": "🚚 Курьер в пути", "ready": "🏪 Готов к выдаче", "done": "✔️ Выполнен", "cancelled": "❌ Отменён",
}


def order_card(o, admin=False):
    d = datetime.fromisoformat(o["date"]).date()
    out = [f"<b>Заказ №{o['id']}</b> · {STATUS[o['status']]}", ""]
    for it in o["items"]:
        out.append(f"• {esc(C.PRODUCTS.get(it['key'], {}).get('name', it['key']))} ({esc(it['label'])}) × {it['qty']}")
    out.append("")
    if o["mode"] == "delivery":
        out.append(f"🚚 {esc(C.ZONES[o['zone']][0])}, {esc(o['address'])}")
        if o["who"] == "other":
            out.append(f"🎁 Получатель: {esc(o['rname'])}, {esc(o['rphone'])}" + (" 🤫 СЮРПРИЗ, не звонить" if o["surprise"] else ""))
    else:
        out.append("🏪 Самовывоз")
    out.append(f"🕒 {day_label(d)}, {esc(o['slot'])}")
    if o["card"]:
        out.append(f"💌 Открытка: «{esc(o['card'])}»")
    if o["comment"]:
        out.append(f"📝 {esc(o['comment'])}")
    out.append(f"💳 {esc(C.PAYMENTS[o['pay']][0])}")
    if admin:
        out.append(f"👤 {esc(o['name'])}, {esc(o['phone'])}")
    out.append(f"<b>Итого: {money(o['total'])}</b>")
    return "\n".join(out)


def co_finish(uid, name):
    st = sess(uid)
    co = st.get("co")
    if not co:
        return home(uid, name)
    c = co_calc(uid)
    if not c["lines"] or any(ln["stopped"] for ln in c["lines"]):
        return cart_screen(uid, "Состав корзины изменился, проверьте её.")
    if c["items_sum"] < C.MIN_ORDER:
        return cart_screen(uid)
    d = datetime.fromisoformat(co["date"]).date()
    opt = next((x for x in slot_options(co["mode"], d) if x[1] == co["slot"]), None)
    if not opt and not co.get("exact"):
        for k in ("date", "slot", "start_at", "exact"):
            co.pop(k, None)
        res = co_next(uid)
        res[0].screen.text = "⚠️ Это окно только что заняли. Выберите другое.\n\n" + res[0].screen.text
        return res
    user = S.get_user(uid) or {}
    oid = S.create_order(uid, user.get("name") or name, user.get("phone"), co, c)
    S.cart_clear(uid)
    st.pop("co", None)
    st.pop("promo", None)
    o = S.get_order(oid)
    extra = ""
    if co["pay"] == "sbp":
        extra = "\n\n📲 Реквизиты для перевода по СБП пришлём после подтверждения."
    outs = one(
        f"🎉 <b>Заказ №{oid} оформлен!</b>\n\n{order_card(o)}\n\nМенеджер подтвердит заказ в течение 15 минут "
        f"в рабочее время ({C.SHOP['hours']}). Мы пришлём уведомление сюда.{extra}",
        [[("📦 Мои заказы", "ord:act")], [("💐 В каталог", "cat")], HOME],
    )
    for a in ADMINS:
        outs.append(Out(a, Screen(f"🔔 <b>Новый заказ</b>\n\n{order_card(o, admin=True)}", admin_order_rows(o))))
    return outs


# ================================ заказы клиента ===============================
def admin_order_rows(o):
    oid, s = o["id"], o["status"]
    rows = []
    nxt = {"new": ("confirmed", "✅ Принять"), "confirmed": ("assembling", "💐 Собираем"),
           "assembling": (("onway", "🚚 Курьер выехал") if o["mode"] == "delivery" else ("ready", "🏪 Готов к выдаче")),
           "onway": ("done", "✔️ Выполнен"), "ready": ("done", "✔️ Выполнен")}
    if s in nxt:
        rows.append([(nxt[s][1], f"adm:st:{oid}:{nxt[s][0]}")])
    if s not in ("done", "cancelled"):
        rows.append([("❌ Отменить", f"adm:st:{oid}:cancelled")])
    rows.append([("✉️ Написать клиенту", f"adm:reply:{o['user_id']}")] if o["user_id"] > 0 else [])
    rows = [r for r in rows if r]
    rows.append([("🛠 Панель", "adm")])
    return rows


def my_orders(uid, active):
    orders = S.user_orders(uid, active)
    title = "📦 <b>Активные заказы</b>" if active else "🕘 <b>История заказов</b>"
    rows = [[(f"№{o['id']} · {day_label(datetime.fromisoformat(o['date']).date())} · {money(o['total'])} · {STATUS[o['status']].split(' ', 1)[1]}", f"o:{o['id']}")] for o in orders]
    rows.append([("🕘 История", "ord:his")] if active else [("📦 Активные", "ord:act")])
    rows.append(HOME)
    if not orders:
        title += "\n\nПока пусто."
    return one(title, rows)


def order_screen(uid, oid):
    o = S.get_order(oid)
    if not o or o["user_id"] != uid:
        return home(uid, "")
    rows = []
    if o["status"] in ("new", "confirmed"):
        rows.append([("❌ Отменить заказ", f"ocx:{oid}")])
    if o["status"] == "done" and not S.has_review(oid):
        rows.append([("⭐ Оценить", f"rvs:{oid}")])
    rows.append([("🔁 Повторить заказ", f"orp:{oid}")])
    rows.append([("📦 Заказы", "ord:act")])
    rows.append(HOME)
    return one(order_card(o), rows)


def cancel_check(o):
    start = datetime.strptime(o["start_at"], S.FMT)
    return start - S.now_local() >= timedelta(hours=C.CANCEL_BEFORE_H)


def status_text(o):
    oid = o["id"]
    t = {
        "confirmed": f"✅ Заказ №{oid} принят. Скоро начнём собирать.",
        "assembling": f"💐 Флорист собирает ваш заказ №{oid}. Фото букета пришлём перед отправкой.",
        "onway": f"🚚 Курьер выехал с заказом №{oid}. Скоро будет у получателя.",
        "ready": f"🏪 Заказ №{oid} готов. Ждём вас: {C.SHOP['address']}.",
        "done": f"✔️ Заказ №{oid} выполнен. Спасибо, что выбрали нас! Оцените, как всё прошло:",
        "cancelled": f"❌ Заказ №{oid} отменён. Если это ошибка, напишите нам.",
    }[o["status"]]
    if o["status"] == "confirmed" and o["pay"] == "sbp":
        t += f"\n\n📲 Реквизиты для СБП: {C.SHOP['phone']} (демо), {C.SHOP['name']}. В комментарии укажите №{oid}."
    return t


# ================================= конструктор =================================
def cb_step(uid):
    st = sess(uid)
    cb = st.setdefault("cb", {})
    if "occ" not in cb:
        rows = [[(t, f"cb:o:{k}")] for k, t in C.OCCASIONS.items()]
        rows.append(HOME)
        return one("🎨 <b>Собрать букет на заказ</b>\nОтветьте на 4 вопроса, и флорист подготовит вариант с ценой.\n\n1/4. Какой повод?", rows)
    if "budget" not in cb:
        rows = [[(t, f"cb:b:{i}")] for i, (t, _) in enumerate(C.CB_BUDGET)]
        rows.append([("◀️ Сначала", "cb:reset")])
        return one("2/4. Какой бюджет?", rows)
    if "pal" not in cb:
        rows = [[(t, f"cb:c:{i}")] for i, (t, _) in enumerate(C.CB_PALETTE)]
        rows.append([("◀️ Сначала", "cb:reset")])
        return one("3/4. Какая цветовая гамма?", rows)
    if "pack" not in cb:
        rows = [[(t, f"cb:p:{i}")] for i, (t, _) in enumerate(C.CB_PACK)]
        rows.append([("◀️ Сначала", "cb:reset")])
        return one("4/4. Какая упаковка?", rows)
    st["mode"] = "cb_wish"
    return one("✍️ Напишите пожелания: любимые цветы, на какую дату и время, доставка или самовывоз, адрес. "
               "Можно коротко.", [[("Без пожеланий", "cb:skip")], [("◀️ Сначала", "cb:reset")]])


def cb_finish(uid, name):
    st = sess(uid)
    cb = st.get("cb", {})
    user = S.get_user(uid) or {}
    if not user.get("phone"):
        st["mode"] = "phone"
        st["then"] = "cb"
        return one("📱 Оставьте номер телефона, чтобы флорист мог связаться.",
                   [[("📱 Отправить мой номер", "!contact")], [("✖️ Отмена", "home")]], contact=True)
    st["mode"] = None
    rid = S.add_request(uid, user.get("name") or name, user["phone"], cb)
    st.pop("cb", None)
    outs = one(f"✅ Заявка №{rid} отправлена флористу. Ответим в течение 15 минут в рабочее время "
               f"({C.SHOP['hours']}). Ответ придёт сюда.", [HOME])
    for a in ADMINS:
        outs.append(Out(a, Screen(request_text(S.get_request(rid)),
                                  [[("✉️ Ответить клиенту", f"adm:reply:{uid}")], [("🛠 Панель", "adm")]])))
    return outs


def request_text(r):
    d = r["data"]
    return (f"🎨 <b>Заявка на букет №{r['id']}</b>\n\n👤 {esc(r['name'])}, {esc(r['phone'])}\n"
            f"Повод: {esc(C.OCCASIONS.get(d.get('occ'), d.get('occ')))}\nБюджет: {esc(d.get('budget'))}\n"
            f"Гамма: {esc(d.get('pal'))}\nУпаковка: {esc(d.get('pack'))}\nПожелания: {esc(d.get('wish') or '—')}")


# ================================ важные даты ==================================
DR_TITLES = ["Маме", "Любимой", "Жене", "Подруге", "Коллеге", "Другу"]


def dr_screen(uid):
    items = S.date_list(uid)
    out = ["🔔 <b>Важные даты</b>", "Добавьте день рождения или годовщину. Напомним за "
           f"{C.REMIND_DAYS_BEFORE} дня и предложим подобрать букет.", ""]
    rows = []
    for d in items:
        out.append(f"• {esc(d['title'])}: {d['day']:02d}.{d['month']:02d}")
        rows.append([(f"🗑 {d['title']} {d['day']:02d}.{d['month']:02d}", f"dr:del:{d['id']}")])
    if not items:
        out.append("Пока ничего не добавлено.")
    rows.append([("➕ Добавить дату", "dr:add")])
    rows.append(HOME)
    return one("\n".join(out), rows)


def parse_dm(text):
    m = re.match(r"^\s*(\d{1,2})[.\-/ ](\d{1,2})", text or "")
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    try:
        datetime(2024, mo, d)  # високосный год допускает 29.02
    except ValueError:
        return None
    return d, mo


def due_outs():
    """Для цикла напоминаний адаптера: важные даты."""
    outs = []
    rows, target = S.dates_due()
    for r in rows:
        S.date_mark(r["id"], target.year)
        outs.append(Out(r["user_id"], Screen(
            f"🔔 Через {C.REMIND_DAYS_BEFORE} дня ({target.day:02d}.{target.month:02d}) важная дата: <b>{esc(r['title'])}</b>.\n"
            "Давайте подберём букет, чтобы доставить вовремя.",
            [[("💐 Выбрать букет", "cat")], [("🔥 Хиты", "hits:1")], HOME])))
    return outs


# ================================== инфо =======================================
def reviews_screen():
    avg, n = S.shop_rating()
    out = [f"⭐ <b>Отзывы о «{esc(C.SHOP['name'])}»</b>"]
    out.append(f"Средняя оценка: {avg} из 5 ({n} отзывов)\n" if avg else "Пока нет отзывов.\n")
    for r in S.last_reviews(5):
        out.append("★" * r["rating"] + "☆" * (5 - r["rating"]) + (f"\n{esc(r['text'])}" if r["text"] else ""))
        out.append("")
    return one("\n".join(out), [[("💐 В каталог", "cat")], HOME])


def deliv_screen():
    z = "\n".join(f"• <b>{v[0]}</b>: {money(v[1])}" + (f", бесплатно от {money(v[3])}" if v[3] else "") + f"\n  {v[2]}" for v in C.ZONES.values())
    pay = "\n".join(f"• {v[0]}: {v[1]}" for v in C.PAYMENTS.values())
    return one(
        f"🚚 <b>Доставка</b>\n{z}\n\nОкна по 2 часа, доставка к точному времени +{money(C.EXACT_TIME_FEE)}. "
        f"Минимальная сумма заказа {money(C.MIN_ORDER)}. Заказ можно оформить на {C.ORDER_DAYS} дней вперёд.\n\n"
        f"🏪 {C.SHOP['pickup_note']}\n\n💳 <b>Оплата</b>\n{pay}", [[("💐 В каталог", "cat")], HOME])


def contacts_screen():
    s = C.SHOP
    ll = f"{s['lat']},{s['lon']}"
    rows = [[("🗺 Яндекс Карты", f"https://yandex.ru/maps/?pt={s['lon']},{s['lat']}&z=16&l=map"),
             ("🗺 2ГИС", f"https://2gis.ru/search/{s['address'].split(',')[0]}")], HOME]
    return one(f"📍 <b>{esc(s['name'])}</b>\n\n{esc(s['address'])}\n{esc(s['landmark'])}\n\n🕒 {esc(s['hours'])}\n"
               f"📞 {esc(s['phone'])}\n\nКоординаты: {ll}", rows)


# ================================== админка ====================================
def admin_home():
    n, rq = S.count_new(), S.count_requests()
    rows = [
        [(f"🆕 Новые ({n})", "adm:o:new"), ("🔄 В работе", "adm:o:active")],
        [("🚚 Сегодня", "adm:o:today"), ("📅 Завтра", "adm:o:tomorrow")],
        [(f"🎨 Заявки на букет ({rq})", "adm:rq")],
        [("📊 Статистика", "adm:stats"), ("⛔ Стоп-лист", "adm:stop:1")],
        [("📣 Рассылка", "adm:bc"), ("🧪 Демо-данные", "adm:demo")],
        HOME,
    ]
    return one("🛠 <b>Админ-панель</b>", rows)


def admin_orders(kind):
    titles = {"new": "🆕 Новые заказы", "active": "🔄 В работе", "today": "🚚 Заказы на сегодня", "tomorrow": "📅 Заказы на завтра"}
    orders = S.orders_by(kind)[:12]
    rows = [[(f"№{o['id']} · {o['slot']} · {money(o['total'])} · {STATUS[o['status']].split(' ', 1)[0]}", f"adm:ov:{o['id']}")] for o in orders]
    rows.append([("🛠 Панель", "adm")])
    return one(f"<b>{titles[kind]}</b>\n\n" + ("Список пуст." if not orders else f"Заказов: {len(orders)}"), rows)


def admin_stats():
    s = S.stats(30)
    avg, n = s["rating"]
    top = "\n".join(f"{i}. {esc(C.PRODUCTS.get(t['key'], {}).get('name', t['key']))}: {t['n']} шт." for i, t in enumerate(s["top"], 1)) or "—"
    return one(
        "📊 <b>Статистика за 30 дней</b>\n\n"
        f"Заказов: {s['orders']} (доставка {s['delivery']}, самовывоз {s['pickup']})\n"
        f"Выручка: {money(s['revenue'])}\nСредний чек: {money(s['avg'])}\nОтмен: {s['cancelled']}\n"
        f"Рейтинг: {avg if avg else '—'} ({n} отзывов)\n\n<b>Топ товаров</b>\n{top}",
        [[("🛠 Панель", "adm")]])


def admin_stop(page):
    keys = list(C.PRODUCTS)
    total = (len(keys) + 7) // 8
    page = min(max(page, 1), total)
    rows = [[(("⛔ " if S.is_stopped(k) else "✅ ") + C.PRODUCTS[k]["name"], f"adm:tg:{k}:{page}")] for k in keys[(page - 1) * 8: page * 8]]
    nav = []
    if page > 1:
        nav.append(("◀️", f"adm:stop:{page - 1}"))
    if page < total:
        nav.append(("▶️", f"adm:stop:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([("🛠 Панель", "adm")])
    return one("⛔ <b>Стоп-лист</b>\nНажмите на товар, чтобы убрать его из продажи или вернуть.", rows)


def seed_demo():
    import random
    rnd = random.Random(7)
    names = ["Анна", "Игорь", "Мария", "Олег", "Светлана"]
    today = S.now_local().date()
    made = 0
    keys = [k for k, p in C.PRODUCTS.items() if p["cat"] != "gifts"]
    for i in range(10):
        uid = -(i % 5) - 1
        S.upsert_user(uid, names[i % 5])
        k = rnd.choice(keys)
        p = C.PRODUCTS[k]
        var = rnd.randrange(len(p["var"]))
        label, price = p["var"][var]
        mode = "delivery" if i % 3 else "pickup"
        d = today + timedelta(days=(i % 3) - (1 if i > 6 else 0))
        slot_i = i % len(C.DELIVERY_SLOTS)
        slot = C.DELIVERY_SLOTS[slot_i][0] if mode == "delivery" else f"к {10 + i}:00"
        start = datetime.combine(d, time(C.DELIVERY_SLOTS[slot_i][1] if mode == "delivery" else 10 + i))
        co = {"mode": mode, "zone": rnd.choice(list(C.ZONES)) if mode == "delivery" else None,
              "addr": f"ул. Демонстрационная, {10 + i}, кв. {i + 3}" if mode == "delivery" else None,
              "who": "other" if i % 2 else "me", "rname": "Елена" if i % 2 else None,
              "rphone": "+79140000000" if i % 2 else None, "surprise": i % 4 == 1, "date": d.isoformat(), "slot": slot,
              "start_at": start.strftime(S.FMT), "card": "С днём рождения!" if i % 2 else "", "comment": "",
              "pay": rnd.choice(list(C.PAYMENTS))}
        fee = 0 if mode == "pickup" else C.ZONES[co["zone"]][1]
        c = {"items_sum": price, "discount": 0, "fee": fee, "total": price + fee, "promo": None,
             "lines": [{"key": k, "var": var, "label": label, "price": price, "qty": 1}]}
        status = "done" if d < today else rnd.choice(["new", "confirmed", "assembling"])
        created = S.iso(S.now_local() - timedelta(days=max(0, (today - d).days) + 1))
        oid = S.create_order(uid, names[i % 5], "+79140000000", co, c, created=created, status=status)
        if status == "done":
            S.add_review(oid, uid, rnd.choice([4, 5, 5]), "")
        made += 1
    return made


# ============================ точки входа для адаптеров ========================
def handle_start(uid, name):
    S.upsert_user(uid, name)
    return home(uid, name, new=True)


def handle_contact(uid, name, phone):
    S.upsert_user(uid, name)
    ph = normalize_phone(phone)
    if not ph:
        return one("Не похоже на номер телефона.", [[("📱 Отправить мой номер", "!contact")], HOME], contact=True)
    S.set_phone(uid, ph)
    st = sess(uid)
    then = st.pop("then", None)
    st["mode"] = None
    if then == "co":
        return co_next(uid, name)
    if then == "cb":
        return cb_finish(uid, name)
    return home(uid, name, new=True)


def handle_text(uid, name, text):
    S.upsert_user(uid, name)
    st = sess(uid)
    mode = st.get("mode")
    text = (text or "").strip()
    if not text:
        return one("Выберите раздел:", menu_rows(uid), new=True)
    co = st.get("co")
    if mode == "co_addr" and co is not None:
        co["addr"] = text[:200]
        return co_next(uid, name)
    if mode == "co_rname" and co is not None:
        co["rname"] = text[:60]
        return co_next(uid, name)
    if mode == "co_rphone" and co is not None:
        ph = normalize_phone(text)
        if not ph:
            return one("Не похоже на номер. Пример: +7 914 000-00-00", [[("◀️ Назад", "co:ed:rcp")]])
        co["rphone"] = ph
        return co_next(uid, name)
    if mode == "co_comment" and co is not None:
        co["comment"] = text[:300]
        return co_next(uid, name)
    if mode == "co_card" and co is not None:
        co["card"] = text[:250]
        return co_next(uid, name)
    if mode == "co_exact" and co is not None:
        m = re.match(r"^\s*(\d{1,2})[:.\- ](\d{2})\s*$", text)
        d = datetime.fromisoformat(co["date"]).date()
        if m and 0 <= int(m.group(1)) < 24 and 0 <= int(m.group(2)) < 60:
            start = datetime.combine(d, time(int(m.group(1)), int(m.group(2))))
            ok = C.OPEN_H * 60 + 60 <= start.hour * 60 + start.minute <= (C.CLOSE_H - 1) * 60 + 30
            if ok and start - S.now_local() >= timedelta(minutes=C.LEAD_DELIVERY_MIN):
                co.update(slot=f"к {start.strftime('%H:%M')}", start_at=start.strftime(S.FMT), exact=True)
                return co_next(uid, name)
        return one(f"Не получилось. Напишите время от {C.OPEN_H + 1}:00 до {C.CLOSE_H - 1}:30 в формате 14:30, "
                   f"не раньше чем через {C.LEAD_DELIVERY_MIN // 60} часа.", [[("◀️ Окна", "co:ed:slot")]])
    if mode == "promo":
        st["mode"] = None
        st["promo"] = text.upper().replace(" ", "")[:20]
        return cart_screen(uid)
    if mode == "phone":
        return handle_contact(uid, name, text)
    if mode == "cb_wish":
        st["cb"]["wish"] = text[:500]
        return cb_finish(uid, name)
    if mode == "review":
        S.add_review(st["rv_oid"], uid, st["rv_n"], text[:500])
        st["mode"] = None
        outs = one("Спасибо за отзыв! 💐", [[("💐 В каталог", "cat")], HOME])
        if st["rv_n"] <= 3:
            for a in ADMINS:
                outs.append(Out(a, Screen(f"⚠️ Низкая оценка ({st['rv_n']}★) по заказу №{st['rv_oid']}:\n{esc(text)}",
                                          [[("✉️ Написать клиенту", f"adm:reply:{uid}")]])))
        return outs
    if mode == "dr_title":
        st["dr_title"] = text[:40]
        st["mode"] = "dr_date"
        return one("Укажите дату в формате ДД.ММ, например 25.03", [[("✖️ Отмена", "dr")]])
    if mode == "dr_date":
        dm = parse_dm(text)
        if not dm:
            return one("Не получилось. Формат: 25.03", [[("✖️ Отмена", "dr")]])
        S.date_add(uid, st.pop("dr_title", "Дата"), dm[0], dm[1])
        st["mode"] = None
        return dr_screen(uid)
    if mode == "support":
        st["mode"] = None
        outs = one("Сообщение отправлено ✅ Ответим здесь.", [HOME])
        for a in ADMINS:
            outs.append(Out(a, Screen(f"✉️ <b>Сообщение от клиента</b> {esc(name)}:\n\n{esc(text)}",
                                      [[("✉️ Ответить", f"adm:reply:{uid}")]])))
        return outs
    if mode == "adm_reply" and is_admin(uid):
        to = st.pop("to")
        st["mode"] = None
        return [Out(None, Screen("Отправлено ✅", [[("🛠 Панель", "adm")]])),
                Out(to, Screen(f"💬 <b>Ответ от «{esc(C.SHOP['name'])}»:</b>\n\n{esc(text)}", [HOME]))]
    if mode == "broadcast" and is_admin(uid):
        st["bc_text"] = text
        st["mode"] = None
        return one(f"📣 <b>Предпросмотр рассылки</b>\n\n{esc(text)}\n\nПолучателей: {len(S.all_user_ids())}",
                   [[("✅ Отправить", "adm:bcgo")], [("✖️ Отмена", "adm")]])
    # поиск по каталогу
    keys = search_keys(text)
    if keys:
        st["srch"] = keys
        return list_screen(uid, f"🔎 <b>Поиск: «{esc(text[:30])}»</b>", keys, 1, "srch")
    return one("Не нашёл такого 🤔 Попробуйте другое слово или откройте каталог.",
               [[("💐 Каталог", "cat")], [("✉️ Спросить флориста", "support")], HOME], new=True)


def handle_action(uid, name, p):
    S.upsert_user(uid, name)
    st = sess(uid)
    parts = p.split(":")
    h = parts[0]
    st["mode"] = None  # режим ожидания текста включает только тот обработчик, которому он нужен

    if p == "home":
        return home(uid, name)
    # ---- каталог ----
    if p == "cat":
        return catalog_home()
    if h == "cat":
        key, page = parts[1], int(parts[2])
        keys = [k for k, pr in C.PRODUCTS.items() if pr["cat"] == key]
        return list_screen(uid, f"<b>{C.CATEGORIES[key]}</b>", keys, page, f"cat:{key}")
    if h == "hits":
        keys = [k for k, pr in C.PRODUCTS.items() if pr["hit"]]
        return list_screen(uid, "🔥 <b>Хиты продаж</b>", keys, int(parts[1]), "hits")
    if p == "occ":
        rows = [[(t, f"occ:{k}:1")] for k, t in C.OCCASIONS.items()]
        rows.append([("◀️ Каталог", "cat")])
        return one("🎯 <b>Выберите повод</b>", rows)
    if h == "occ":
        keys = [k for k, pr in C.PRODUCTS.items() if parts[1] in pr["occ"]]
        return list_screen(uid, f"<b>{C.OCCASIONS[parts[1]]}</b>", keys, int(parts[2]), f"occ:{parts[1]}", back="occ")
    if p == "pr":
        rows = [[(range_label(lo, hi), f"pr:{i}:1")] for i, (lo, hi) in enumerate(PRICE_RANGES)]
        rows.append([("◀️ Каталог", "cat")])
        return one("💰 <b>Какой бюджет?</b>", rows)
    if h == "pr":
        lo, hi = PRICE_RANGES[int(parts[1])]
        keys = [k for k, pr in C.PRODUCTS.items() if pr["cat"] != "gifts" and lo <= pmin(pr) < hi]
        return list_screen(uid, f"<b>💰 {range_label(lo, hi)}</b>", keys, int(parts[2]), f"pr:{parts[1]}", back="pr")
    if h == "srch":
        return list_screen(uid, "🔎 <b>Результаты поиска</b>", st.get("srch", []), int(parts[1]), "srch")
    if h == "favs":
        return list_screen(uid, "❤️ <b>Избранное</b>", [k for k in S.favs(uid) if k in C.PRODUCTS], int(parts[1]), "favs", back="home")
    if h == "p" and parts[1] in C.PRODUCTS:
        return product_card(uid, parts[1])
    if h == "pv" and parts[1] in C.PRODUCTS:
        return product_card(uid, parts[1], int(parts[2]))
    if h == "fav" and parts[1] in C.PRODUCTS:
        S.toggle_fav(uid, parts[1])
        return product_card(uid, parts[1], int(parts[2]))
    # ---- корзина ----
    if h == "add" and parts[1] in C.PRODUCTS and not S.is_stopped(parts[1]):
        S.cart_add(uid, parts[1], int(parts[2]))
        p_ = C.PRODUCTS[parts[1]]
        n = S.cart_count(uid)
        return one(f"✅ Добавлено: {esc(p_['name'])} ({esc(p_['var'][int(parts[2])][0])})\nВ корзине позиций: {n}",
                   [[("🛒 Оформить", "cart")], [("🎁 Добавить подарок", "xtra")],
                    [("💐 Продолжить покупки", st.get("last", "cat"))], HOME])
    if p == "cart":
        return cart_screen(uid)
    if p == "cart:clear":
        S.cart_clear(uid)
        st.pop("promo", None)
        return cart_screen(uid)
    if h == "q" and parts[1] in C.PRODUCTS:
        op = parts[3]
        if op == "x":
            S.cart_remove(uid, parts[1], int(parts[2]))
        else:
            S.cart_delta(uid, parts[1], int(parts[2]), 1 if op == "+" else -1)
        return cart_screen(uid)
    if p == "xtra":
        return xtra_screen(uid)
    if h == "ax" and parts[1] in C.PRODUCTS:
        S.cart_add(uid, parts[1], 0)
        return xtra_screen(uid, f"✅ Добавлено: {esc(C.PRODUCTS[parts[1]]['name'])}")
    if p == "promo":
        st["mode"] = "promo"
        return one("🏷 Введите промокод одним сообщением. Попробуйте FIRST10.", [[("◀️ В корзину", "cart")]])
    if p == "promo:x":
        st.pop("promo", None)
        return cart_screen(uid)
    # ---- оформление ----
    if p == "co":
        return co_start(uid)
    if h == "co":
        co = st.setdefault("co", {})
        sub = parts[1]
        if sub == "m":
            co.clear()
            co["mode"] = parts[2]
        elif sub == "z" and parts[2] in C.ZONES:
            co["zone"] = parts[2]
        elif sub == "w":
            co["who"] = parts[2]
            if parts[2] == "me":
                for k in ("rname", "rphone", "surprise"):
                    co.pop(k, None)
        elif sub == "s":
            co["surprise"] = parts[2] == "1"
        elif sub == "d":
            co["date"] = (S.now_local().date() + timedelta(days=int(parts[2]))).isoformat()
            for k in ("slot", "start_at", "exact"):
                co.pop(k, None)
        elif sub == "t":
            d = datetime.fromisoformat(co["date"]).date()
            if parts[2] == "e":
                st["mode"] = "co_exact"
                return one(f"🎯 Напишите точное время доставки, например 14:30 (с {C.OPEN_H + 1}:00 до {C.CLOSE_H - 1}:30). "
                           f"Доставка к точному времени +{money(C.EXACT_TIME_FEE)}.", [[("◀️ Окна", "co:ed:slot")]])
            opt = next((x for x in slot_options(co["mode"], d) if x[0] == parts[2]), None)
            if not opt:
                co.pop("slot", None)
                return co_next(uid, name)
            co.update(slot=opt[1], start_at=opt[2].strftime(S.FMT))
            co.pop("exact", None)
        elif sub == "c":
            if parts[2] == "y":
                st["mode"] = "co_card"
                return one("✍️ Напишите текст открытки одним сообщением.", [[("Без открытки", "co:c:n")]])
            co["card"] = ""
        elif sub == "cm":
            co["comment"] = ""
        elif sub == "p":
            co["pay"] = parts[2]
        elif sub == "ed":
            what = parts[2]
            drops = {"mode": ["mode", "zone", "addr", "who", "rname", "rphone", "surprise", "date", "slot", "start_at", "exact"],
                     "addr": ["zone", "addr"], "rcp": ["who", "rname", "rphone", "surprise"],
                     "time": ["date", "slot", "start_at", "exact"], "slot": ["slot", "start_at", "exact"],
                     "card": ["card", "comment"], "pay": ["pay"]}
            for k in drops.get(what, []):
                co.pop(k, None)
        elif sub == "ok":
            return co_finish(uid, name)
        return co_next(uid, name)
    # ---- заказы клиента ----
    if h == "ord":
        return my_orders(uid, parts[1] == "act")
    if h == "o":
        return order_screen(uid, int(parts[1]))
    if h == "ocx":
        o = S.get_order(int(parts[1]))
        if not o or o["user_id"] != uid:
            return home(uid, name)
        if o["status"] not in ("new", "confirmed") or not cancel_check(o):
            return one(f"Отменить онлайн уже нельзя: до доставки меньше {C.CANCEL_BEFORE_H} часов или заказ в работе. "
                       f"Позвоните: {C.SHOP['phone']}", [[("✉️ Написать нам", "support")], HOME])
        return one(f"Отменить заказ №{o['id']}?", [[("Да, отменить", f"ocxy:{o['id']}")], [("Нет", f"o:{o['id']}")]])
    if h == "ocxy":
        o = S.get_order(int(parts[1]))
        if o and o["user_id"] == uid and o["status"] in ("new", "confirmed") and cancel_check(o):
            S.set_status(o["id"], "cancelled")
            outs = one(f"❌ Заказ №{o['id']} отменён.", [[("💐 В каталог", "cat")], HOME])
            for a in ADMINS:
                outs.append(Out(a, Screen(f"❌ Клиент {esc(o['name'])} отменил заказ №{o['id']} ({money(o['total'])}).", [[("🛠 Панель", "adm")]])))
            return outs
        return home(uid, name)
    if h == "orp":
        o = S.get_order(int(parts[1]))
        if o and o["user_id"] == uid:
            S.cart_clear(uid)
            for it in o["items"]:
                if it["key"] in C.PRODUCTS:
                    S.cart_add(uid, it["key"], it["var"], it["qty"])
            return cart_screen(uid, "🔁 Состав прошлого заказа добавлен в корзину.")
        return home(uid, name)
    if h == "rvs":
        oid = int(parts[1])
        return one("Как всё прошло? Поставьте оценку:", [[(f"{i}⭐", f"rv:{oid}:{i}") for i in range(1, 6)], HOME])
    if h == "rv":
        oid, n = int(parts[1]), int(parts[2])
        o = S.get_order(oid)
        if not o or o["user_id"] != uid or S.has_review(oid):
            return home(uid, name)
        st["rv_oid"], st["rv_n"], st["mode"] = oid, n, "review"
        return one(f"Спасибо за оценку {n}⭐! Напишите пару слов о заказе или пропустите.", [[("Пропустить", "rvskip")]])
    if p == "rvskip":
        if st.get("rv_oid") and not S.has_review(st["rv_oid"]):
            S.add_review(st["rv_oid"], uid, st["rv_n"], "")
        return one("Спасибо за оценку! 💐", [[("💐 В каталог", "cat")], HOME])
    # ---- конструктор ----
    if p == "cb":
        st["cb"] = {}
        return cb_step(uid)
    if h == "cb":
        cb = st.setdefault("cb", {})
        sub = parts[1]
        if sub == "reset":
            st["cb"] = {}
        elif sub == "o" and parts[2] in C.OCCASIONS:
            cb["occ"] = parts[2]
        elif sub == "b":
            cb["budget"] = C.CB_BUDGET[int(parts[2])][1]
        elif sub == "c":
            cb["pal"] = C.CB_PALETTE[int(parts[2])][1]
        elif sub == "p":
            cb["pack"] = C.CB_PACK[int(parts[2])][1]
        elif sub == "skip":
            cb["wish"] = ""
            return cb_finish(uid, name)
        return cb_step(uid)
    # ---- важные даты ----
    if p == "dr":
        return dr_screen(uid)
    if p == "dr:add":
        rows = [[(t, f"dr:t:{i}") for i, t in enumerate(DR_TITLES[j:j + 3], j)] for j in (0, 3)]
        rows.append([("✍️ Другое", "dr:t:x")])
        rows.append([("◀️ Назад", "dr")])
        return one("Для кого напоминание?", rows)
    if h == "dr" and parts[1] == "t":
        if parts[2] == "x":
            st["mode"] = "dr_title"
            return one("Напишите, для кого (например, «Бабушке»).", [[("✖️ Отмена", "dr")]])
        st["dr_title"] = DR_TITLES[int(parts[2])]
        st["mode"] = "dr_date"
        return one(f"Дата для «{st['dr_title']}» в формате ДД.ММ, например 25.03", [[("✖️ Отмена", "dr")]])
    if h == "dr" and parts[1] == "del":
        S.date_del(uid, int(parts[2]))
        return dr_screen(uid)
    # ---- инфо ----
    if p == "promos":
        return one("🔥 <b>Акции</b>\n\n" + "\n\n".join(f"<b>{t}</b>\n{d}" for t, d in C.PROMO_TEXTS),
                   [[("🛒 Корзина", "cart")], [("💐 В каталог", "cat")], HOME])
    if p == "deliv":
        return deliv_screen()
    if p == "contacts":
        return contacts_screen()
    if p == "reviews":
        return reviews_screen()
    if p == "faq":
        rows = [[(q, f"faq:{i}")] for i, (q, _) in enumerate(C.FAQ)]
        rows.append(HOME)
        return one("❓ <b>Частые вопросы</b>", rows)
    if h == "faq":
        q, a = C.FAQ[int(parts[1])]
        return one(f"❓ <b>{esc(q)}</b>\n\n{esc(a)}", [[("◀️ Вопросы", "faq")], [("✉️ Написать нам", "support")], HOME])
    if p == "support":
        st["mode"] = "support"
        return one("✉️ Напишите сообщение одним текстом, администратор ответит здесь.", [[("✖️ Отмена", "home")]])
    # ---- админ ----
    if h == "adm" and is_admin(uid):
        sub = parts[1] if len(parts) > 1 else "home"
        if sub == "home":
            return admin_home()
        if sub == "o":
            return admin_orders(parts[2])
        if sub == "ov":
            o = S.get_order(int(parts[2]))
            return one(order_card(o, admin=True), admin_order_rows(o)) if o else admin_home()
        if sub == "st":
            oid, status = int(parts[2]), parts[3]
            o = S.get_order(oid)
            if not o or status not in STATUS or status == "new":
                return admin_home()
            S.set_status(oid, status)
            o = S.get_order(oid)
            outs = one(order_card(o, admin=True), admin_order_rows(o))
            if o["user_id"] > 0:
                rows = [[(f"{i}⭐", f"rv:{oid}:{i}") for i in range(1, 6)]] if status == "done" else [[("📦 Мои заказы", "ord:act")]]
                outs.append(Out(o["user_id"], Screen(status_text(o), rows + [HOME])))
            return outs
        if sub == "stats":
            return admin_stats()
        if sub == "stop":
            return admin_stop(int(parts[2]))
        if sub == "tg" and parts[2] in C.PRODUCTS:
            S.toggle_stop(parts[2])
            return admin_stop(int(parts[3]))
        if sub == "rq":
            reqs = S.list_requests()
            if not reqs:
                return one("Новых заявок нет.", [[("🛠 Панель", "adm")]])
            outs = []
            for r in reqs[:5]:
                outs.append(Out(None, Screen(request_text(r), [[("✉️ Ответить", f"adm:reply:{r['user_id']}"),
                                                                ("✅ Закрыть", f"adm:rqx:{r['id']}")]], new=True)))
            outs.append(Out(None, Screen("Заявки выше 👆", [[("🛠 Панель", "adm")]], new=True)))
            return outs
        if sub == "rqx":
            S.close_request(int(parts[2]))
            return one(f"Заявка №{parts[2]} закрыта ✅", [[("🎨 Заявки", "adm:rq")], [("🛠 Панель", "adm")]])
        if sub == "demo":
            return one(f"🧪 Создано демо-заказов: {seed_demo()}. Откройте «Сегодня» и «Статистика».", [[("🛠 Панель", "adm")]])
        if sub == "bc":
            st["mode"] = "broadcast"
            return one("📣 Отправьте текст рассылки одним сообщением.", [[("✖️ Отмена", "adm")]])
        if sub == "bcgo":
            text = st.pop("bc_text", None)
            if not text:
                return admin_home()
            ids = S.all_user_ids()
            outs = one(f"📣 Рассылка запущена, получателей: {len(ids)}.", [[("🛠 Панель", "adm")]])
            for u in ids:
                outs.append(Out(u, Screen(f"📣 <b>{esc(C.SHOP['name'])}</b>\n\n{esc(text)}", [[("💐 Каталог", "cat")], HOME], new=True), delay=0.08))
            return outs
        if sub == "reply":
            st["mode"], st["to"] = "adm_reply", int(parts[2])
            return one("Напишите ответ клиенту одним сообщением.", [[("✖️ Отмена", "adm")]])
    return home(uid, name)
