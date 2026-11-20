"""SQLite-хранилище магазина цветов. Не зависит от мессенджера."""
import json
import sqlite3
import threading
from datetime import datetime, timedelta

import config as C

FMT = "%Y-%m-%d %H:%M"
_conn = None
_lock = threading.RLock()


def now_local():
    return datetime.now(C.TZ).replace(tzinfo=None)


def iso(dt):
    return dt.strftime(FMT)


def parse(s):
    return datetime.strptime(s, FMT)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, name TEXT, phone TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS fav(user_id INTEGER, key TEXT, PRIMARY KEY(user_id, key));
CREATE TABLE IF NOT EXISTS stop(key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS cart(
    user_id INTEGER, key TEXT, var INTEGER, qty INTEGER, PRIMARY KEY(user_id, key, var));
CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, created TEXT, status TEXT,
    mode TEXT, zone TEXT, address TEXT, who TEXT, rname TEXT, rphone TEXT, surprise INTEGER,
    date TEXT, slot TEXT, start_at TEXT, card TEXT, comment TEXT, pay TEXT,
    name TEXT, phone TEXT, subtotal INTEGER, discount INTEGER, fee INTEGER, total INTEGER, promo TEXT);
CREATE TABLE IF NOT EXISTS order_items(
    order_id INTEGER, key TEXT, var INTEGER, label TEXT, price INTEGER, qty INTEGER);
CREATE TABLE IF NOT EXISTS reviews(
    id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, user_id INTEGER,
    rating INTEGER, text TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS requests(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, phone TEXT,
    created TEXT, data TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS dates(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT,
    day INTEGER, month INTEGER, last_year INTEGER);
"""


def init_db(path=None, seed=True):
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = sqlite3.connect(path or C.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        if seed and not _one("SELECT 1 FROM reviews LIMIT 1"):
            for i, (rating, text) in enumerate(C.SEED_REVIEWS):
                _x(
                    "INSERT INTO reviews(order_id,user_id,rating,text,created) VALUES(0,0,?,?,?)",
                    (rating, text, iso(now_local() - timedelta(days=3 + i * 4))),
                )


def _q(sql, args=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def _one(sql, args=()):
    rows = _q(sql, args)
    return rows[0] if rows else None


def _x(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


# ------------------------------- пользователи -------------------------------
def upsert_user(uid, name):
    if _one("SELECT 1 FROM users WHERE id=?", (uid,)):
        if name:
            _x("UPDATE users SET name=? WHERE id=? AND (name IS NULL OR name='' OR name='Гость')", (name, uid))
    else:
        _x("INSERT INTO users(id,name,created) VALUES(?,?,?)", (uid, name, iso(now_local())))


def get_user(uid):
    return _one("SELECT * FROM users WHERE id=?", (uid,))


def set_phone(uid, phone):
    _x("UPDATE users SET phone=? WHERE id=?", (phone, uid))


def all_user_ids():
    return [r["id"] for r in _q("SELECT id FROM users WHERE id>0")]


# ----------------------------- избранное и стоп-лист ------------------------
def is_fav(uid, key):
    return bool(_one("SELECT 1 FROM fav WHERE user_id=? AND key=?", (uid, key)))


def toggle_fav(uid, key):
    if is_fav(uid, key):
        _x("DELETE FROM fav WHERE user_id=? AND key=?", (uid, key))
        return False
    _x("INSERT INTO fav(user_id,key) VALUES(?,?)", (uid, key))
    return True


def favs(uid):
    return [r["key"] for r in _q("SELECT key FROM fav WHERE user_id=?", (uid,))]


def is_stopped(key):
    return bool(_one("SELECT 1 FROM stop WHERE key=?", (key,)))


def toggle_stop(key):
    if is_stopped(key):
        _x("DELETE FROM stop WHERE key=?", (key,))
        return False
    _x("INSERT INTO stop(key) VALUES(?)", (key,))
    return True


# ---------------------------------- корзина ---------------------------------
def cart_get(uid):
    return _q("SELECT key,var,qty FROM cart WHERE user_id=? ORDER BY rowid", (uid,))


def cart_add(uid, key, var, qty=1):
    row = _one("SELECT qty FROM cart WHERE user_id=? AND key=? AND var=?", (uid, key, var))
    if row:
        _x("UPDATE cart SET qty=? WHERE user_id=? AND key=? AND var=?", (min(row["qty"] + qty, 20), uid, key, var))
    else:
        _x("INSERT INTO cart(user_id,key,var,qty) VALUES(?,?,?,?)", (uid, key, var, qty))


def cart_delta(uid, key, var, delta):
    row = _one("SELECT qty FROM cart WHERE user_id=? AND key=? AND var=?", (uid, key, var))
    if not row:
        return
    n = row["qty"] + delta
    if n <= 0:
        cart_remove(uid, key, var)
    else:
        _x("UPDATE cart SET qty=? WHERE user_id=? AND key=? AND var=?", (min(n, 20), uid, key, var))


def cart_remove(uid, key, var):
    _x("DELETE FROM cart WHERE user_id=? AND key=? AND var=?", (uid, key, var))


def cart_clear(uid):
    _x("DELETE FROM cart WHERE user_id=?", (uid,))


def cart_count(uid):
    row = _one("SELECT COALESCE(SUM(qty),0) AS n FROM cart WHERE user_id=?", (uid,))
    return row["n"] if row else 0


# ---------------------------------- заказы ----------------------------------
def has_orders(uid):
    return bool(_one("SELECT 1 FROM orders WHERE user_id=? AND status!='cancelled' LIMIT 1", (uid,)))


def slot_load(date_s, slot):
    row = _one(
        "SELECT COUNT(*) AS n FROM orders WHERE date=? AND slot=? AND mode='delivery' AND status!='cancelled'",
        (date_s, slot),
    )
    return row["n"] if row else 0


def create_order(uid, name, phone, co, calc, created=None, status="new"):
    """co: данные оформления, calc: результат расчёта корзины."""
    oid = _x(
        "INSERT INTO orders(user_id,created,status,mode,zone,address,who,rname,rphone,surprise,date,slot,start_at,"
        "card,comment,pay,name,phone,subtotal,discount,fee,total,promo) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            uid, created or iso(now_local()), status, co["mode"], co.get("zone"), co.get("addr"), co.get("who", "me"),
            co.get("rname"), co.get("rphone"), 1 if co.get("surprise") else 0, co["date"], co["slot"], co["start_at"],
            co.get("card") or "", co.get("comment") or "", co["pay"], name, phone,
            calc["items_sum"], calc["discount"], calc["fee"], calc["total"], calc.get("promo"),
        ),
    )
    for ln in calc["lines"]:
        _x(
            "INSERT INTO order_items(order_id,key,var,label,price,qty) VALUES(?,?,?,?,?,?)",
            (oid, ln["key"], ln["var"], ln["label"], ln["price"], ln["qty"]),
        )
    return oid


def get_order(oid):
    o = _one("SELECT * FROM orders WHERE id=?", (oid,))
    if o:
        o["items"] = _q("SELECT * FROM order_items WHERE order_id=?", (oid,))
    return o


def user_orders(uid, active):
    marks = "('new','confirmed','assembling','onway','ready')"
    cond = f"status IN {marks}" if active else f"status NOT IN {marks}"
    return _q(f"SELECT * FROM orders WHERE user_id=? AND {cond} ORDER BY id DESC LIMIT 15", (uid,))


def set_status(oid, status):
    _x("UPDATE orders SET status=? WHERE id=?", (status, oid))


def orders_by(kind):
    """kind: new | today | tomorrow | active"""
    today = now_local().date()
    if kind == "new":
        return _q("SELECT * FROM orders WHERE status='new' ORDER BY start_at")
    if kind in ("today", "tomorrow"):
        d = today + timedelta(days=0 if kind == "today" else 1)
        return _q("SELECT * FROM orders WHERE date=? AND status!='cancelled' ORDER BY start_at", (d.isoformat(),))
    return _q("SELECT * FROM orders WHERE status IN ('confirmed','assembling','onway','ready') ORDER BY start_at")


def count_new():
    return _one("SELECT COUNT(*) AS n FROM orders WHERE status='new'")["n"]


# ---------------------------------- отзывы ----------------------------------
def add_review(order_id, uid, rating, text):
    _x(
        "INSERT INTO reviews(order_id,user_id,rating,text,created) VALUES(?,?,?,?,?)",
        (order_id, uid, rating, text, iso(now_local())),
    )


def has_review(order_id):
    return bool(_one("SELECT 1 FROM reviews WHERE order_id=?", (order_id,)))


def shop_rating():
    row = _one("SELECT AVG(rating) AS a, COUNT(*) AS n FROM reviews")
    return (round(row["a"], 1), row["n"]) if row and row["n"] else (None, 0)


def last_reviews(n=5):
    return _q("SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (n,))


def product_rating(key):
    row = _one(
        "SELECT AVG(r.rating) AS a, COUNT(*) AS n FROM reviews r JOIN order_items i ON i.order_id=r.order_id "
        "WHERE i.key=?",
        (key,),
    )
    return (round(row["a"], 1), row["n"]) if row and row["n"] else (None, 0)


# ---------------------------- заявки на свой букет ---------------------------
def add_request(uid, name, phone, data):
    return _x(
        "INSERT INTO requests(user_id,name,phone,created,data,status) VALUES(?,?,?,?,?,'new')",
        (uid, name, phone, iso(now_local()), json.dumps(data, ensure_ascii=False)),
    )


def get_request(rid):
    r = _one("SELECT * FROM requests WHERE id=?", (rid,))
    if r:
        r["data"] = json.loads(r["data"])
    return r


def list_requests(status="new"):
    rows = _q("SELECT * FROM requests WHERE status=? ORDER BY id DESC LIMIT 10", (status,))
    for r in rows:
        r["data"] = json.loads(r["data"])
    return rows


def close_request(rid):
    _x("UPDATE requests SET status='done' WHERE id=?", (rid,))


def count_requests():
    return _one("SELECT COUNT(*) AS n FROM requests WHERE status='new'")["n"]


# ----------------------------- важные даты ----------------------------------
def date_add(uid, title, day, month):
    return _x("INSERT INTO dates(user_id,title,day,month,last_year) VALUES(?,?,?,?,0)", (uid, title, day, month))


def date_list(uid):
    return _q("SELECT * FROM dates WHERE user_id=? ORDER BY month, day", (uid,))


def date_del(uid, did):
    _x("DELETE FROM dates WHERE id=? AND user_id=?", (did, uid))


def dates_due(today=None):
    """Даты, до которых осталось ровно REMIND_DAYS_BEFORE дней и напоминание в этом году не отправлялось."""
    today = today or now_local().date()
    target = today + timedelta(days=C.REMIND_DAYS_BEFORE)
    return _q(
        "SELECT * FROM dates WHERE day=? AND month=? AND last_year!=?", (target.day, target.month, target.year)
    ), target


def date_mark(did, year):
    _x("UPDATE dates SET last_year=? WHERE id=?", (year, did))


# -------------------------------- статистика --------------------------------
def stats(days=30):
    since = iso(now_local() - timedelta(days=days))
    base = _one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS rev FROM orders WHERE created>=? AND status!='cancelled'",
        (since,),
    )
    canc = _one("SELECT COUNT(*) AS n FROM orders WHERE created>=? AND status='cancelled'", (since,))["n"]
    deliv = _one(
        "SELECT COUNT(*) AS n FROM orders WHERE created>=? AND status!='cancelled' AND mode='delivery'", (since,)
    )["n"]
    top = _q(
        "SELECT i.key AS key, SUM(i.qty) AS n FROM order_items i JOIN orders o ON o.id=i.order_id "
        "WHERE o.created>=? AND o.status!='cancelled' GROUP BY i.key ORDER BY n DESC LIMIT 5",
        (since,),
    )
    avg = round(base["rev"] / base["n"]) if base["n"] else 0
    return {"orders": base["n"], "revenue": base["rev"], "avg": avg, "cancelled": canc,
            "delivery": deliv, "pickup": base["n"] - deliv, "top": top, "rating": shop_rating()}
