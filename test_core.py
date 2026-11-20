"""Тесты логики ядра: python -m unittest -v"""
import os
import tempfile
import unittest
from datetime import timedelta

import config as C
import core
import storage as S

ADMIN, U = 1, 100


def texts(outs):
    return "\n".join(o.screen.text for o in outs)


def payloads(outs):
    res = []
    for o in outs:
        for row in o.screen.rows:
            for _, data in row:
                res.append(data)
    return res


def act(uid, p):
    return core.handle_action(uid, f"user{uid}", p)


def say(uid, t):
    return core.handle_text(uid, f"user{uid}", t)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        S.init_db(os.path.join(self.tmp, "t.db"))
        core.SESS.clear()
        core.configure({ADMIN})

    def order_flow(self, uid=U, day=1, slot="s2", mode="delivery", pay="cash", promo=None):
        act(uid, "add:r_red:0")
        if promo:
            act(uid, "promo")
            say(uid, promo)
        act(uid, "co")
        act(uid, f"co:m:{mode}")
        if mode == "delivery":
            act(uid, "co:z:center")
            say(uid, "ул. Ленина, 1, кв. 2")
            act(uid, "co:w:other")
            say(uid, "Елена")
            say(uid, "8 914 000 00 00")
            act(uid, "co:s:1")
        act(uid, f"co:d:{day}")
        act(uid, f"co:t:{slot}")
        act(uid, "co:c:y")
        say(uid, "С днём рождения!")
        say(uid, "Позвонить за 10 минут")
        act(uid, f"co:p:{pay}")
        out = core.handle_contact(uid, "Покупатель", "+7 914 111-22-33")
        return out


class TestCalc(Base):
    def test_totals_and_delivery(self):
        S.cart_add(U, "r_red", 0)  # 3200
        c = core.calc(U, mode="delivery", zone="center")
        self.assertEqual((c["items_sum"], c["fee"], c["total"]), (3200, 250, 3450))
        S.cart_add(U, "r_red", 1)  # +7000 -> 10200: бесплатно
        c = core.calc(U, mode="delivery", zone="center")
        self.assertEqual(c["fee"], 0)
        c = core.calc(U, mode="delivery", zone="out")  # пригород платный всегда
        self.assertEqual(c["fee"], 700)

    def test_pickup_discount_and_promo(self):
        S.cart_add(U, "r_red", 0)
        c = core.calc(U, mode="pickup")
        self.assertEqual((c["discount"], c["total"]), (160, 3040))
        c = core.calc(U, mode="delivery", zone="center", promo="FIRST10")
        self.assertEqual((c["discount"], c["promo"]), (320, "FIRST10"))
        # самовывоз -5% меньше промокода -10%: действует большая скидка
        c = core.calc(U, mode="pickup", promo="FIRST10")
        self.assertEqual(c["discount"], 320)
        self.assertIsNotNone(core.calc(U, promo="NOPE")["promo_err"])

    def test_promo_first_order_only(self):
        self.order_flow(promo="FIRST10")
        act(U, "co:ok")  # первый заказ оформлен
        S.cart_add(U, "r_red", 0)
        self.assertIn("первый", core.calc(U, promo="FIRST10")["promo_err"])

    def test_exact_fee(self):
        S.cart_add(U, "r_red", 0)
        self.assertEqual(core.calc(U, mode="delivery", zone="city", exact=True)["fee"], 350 + C.EXACT_TIME_FEE)


class TestFlow(Base):
    def test_full_delivery_order_and_statuses(self):
        outs = self.order_flow(promo="FIRST10")
        self.assertIn("Проверьте заказ", texts(outs))
        self.assertIn("−320", texts(outs).replace("−", "−"))
        outs = act(U, "co:ok")
        self.assertIn("Заказ №1 оформлен", texts(outs))
        admin_outs = [o for o in outs if o.to == ADMIN]
        self.assertEqual(len(admin_outs), 1)
        self.assertIn("СЮРПРИЗ", admin_outs[0].screen.text)
        self.assertIn("С днём рождения!", admin_outs[0].screen.text)
        self.assertEqual(S.cart_count(U), 0)
        o = S.get_order(1)
        self.assertEqual((o["total"], o["status"], o["mode"]), (3200 - 320 + 250, "new", "delivery"))
        # админ ведёт заказ по статусам
        for st in ("confirmed", "assembling", "onway", "done"):
            outs = act(ADMIN, f"adm:st:1:{st}")
            to_client = [x for x in outs if x.to == U]
            self.assertEqual(len(to_client), 1, st)
        self.assertEqual(S.get_order(1)["status"], "done")
        self.assertIn("rv:1:5", payloads(to_client))
        act(U, "rv:1:5")
        outs = say(U, "Всё супер")
        self.assertIn("Спасибо", texts(outs))
        self.assertTrue(S.has_review(1))
        self.assertEqual(S.product_rating("r_red")[1], 1)

    def test_pickup_order(self):
        self.order_flow(mode="pickup", day=1, slot="h12", pay="sbp")
        outs = act(U, "co:ok")
        self.assertIn("Самовывоз", texts(outs))
        self.assertIn("СБП", texts(outs))
        o = S.get_order(1)
        self.assertEqual((o["mode"], o["slot"]), ("pickup", "к 12:00"))
        outs = act(ADMIN, "adm:st:1:confirmed")
        self.assertIn("Реквизиты", [x for x in outs if x.to == U][0].screen.text)
        outs = act(ADMIN, "adm:st:1:assembling")
        self.assertIn("adm:st:1:ready", payloads(outs))

    def test_min_order(self):
        act(U, "add:g_vase:0")  # 700 < 1500
        outs = act(U, "co")
        self.assertIn("Минимальная", texts(outs))
        self.assertNotIn("co:m:delivery", payloads(outs))

    def test_stoplist_blocks(self):
        act(ADMIN, "adm:tg:r_red:1")
        outs = act(U, "p:r_red")
        self.assertIn("нет в наличии", texts(outs))
        act(U, "add:r_red:0")
        self.assertEqual(S.cart_count(U), 0)
        act(ADMIN, "adm:tg:r_red:1")
        act(U, "add:r_red:0")
        self.assertEqual(S.cart_count(U), 1)

    def test_cart_edit(self):
        act(U, "add:r_red:0")
        act(U, "q:r_red:0:+")
        self.assertEqual(S.cart_get(U)[0]["qty"], 2)
        act(U, "q:r_red:0:-")
        act(U, "q:r_red:0:-")
        self.assertEqual(S.cart_count(U), 0)
        self.assertIn("пуста", texts(act(U, "cart")))

    def test_cancel_rules(self):
        self.order_flow(day=3)
        act(U, "co:ok")
        self.assertIn("ocxy:1", payloads(act(U, "ocx:1")))
        outs = act(U, "ocxy:1")
        self.assertEqual(S.get_order(1)["status"], "cancelled")
        self.assertTrue(any(o.to == ADMIN for o in outs))

    def test_slot_capacity(self):
        d = (S.now_local().date() + timedelta(days=2)).isoformat()
        for i in range(C.SLOT_CAPACITY):
            S._x("INSERT INTO orders(user_id,created,status,mode,date,slot) VALUES(5,'x','new','delivery',?,?)", (d, "12:00-14:00"))
        opts = core.slot_options("delivery", S.now_local().date() + timedelta(days=2))
        self.assertNotIn("12:00-14:00", [o[1] for o in opts])

    def test_repeat_order(self):
        self.order_flow(day=2)
        act(U, "co:ok")
        outs = act(U, "orp:1")
        self.assertIn("прошлого заказа", texts(outs))
        self.assertEqual(S.cart_count(U), 1)

    def test_exact_time(self):
        act(U, "add:r_red:0")
        act(U, "co")
        act(U, "co:m:delivery")
        act(U, "co:z:center")
        say(U, "Адрес 1")
        act(U, "co:w:me")
        act(U, "co:d:2")
        act(U, "co:t:e")
        outs = say(U, "14:30")
        self.assertIn("открытк", texts(outs))
        self.assertTrue(core.sess(U)["co"]["exact"])
        self.assertEqual(core.co_calc(U)["fee"], 250 + C.EXACT_TIME_FEE)


class TestExtras(Base):
    def test_constructor_and_reply(self):
        act(U, "cb")
        for p in ("cb:o:mom", "cb:b:1", "cb:c:0", "cb:p:2"):
            outs = act(U, p)
        self.assertIn("пожелания", texts(outs).lower())
        outs = say(U, "К субботе, самовывоз")
        self.assertEqual(core.sess(U)["mode"], "phone")
        outs = core.handle_contact(U, "Аня", "89141112233")
        self.assertIn("Заявка №1", texts(outs))
        self.assertTrue(any(o.to == ADMIN and "Маме" in o.screen.text for o in outs))
        act(ADMIN, "adm:reply:100")
        outs = say(ADMIN, "Есть вариант за 4500")
        self.assertTrue(any(o.to == U for o in outs))

    def test_date_reminders(self):
        act(U, "dr:add")
        act(U, "dr:t:0")
        say(U, "01.01")
        self.assertEqual(len(S.date_list(U)), 1)
        target = S.now_local().date() + timedelta(days=C.REMIND_DAYS_BEFORE)
        S._x("UPDATE dates SET day=?, month=?", (target.day, target.month))
        outs = core.due_outs()
        self.assertEqual(len(outs), 1)
        self.assertEqual(core.due_outs(), [])  # второй раз не шлём
        self.assertIsNone(core.parse_dm("31.02"))

    def test_search_and_favs(self):
        outs = say(U, "пионы")
        self.assertIn("p:b_peony", payloads(outs))
        act(U, "fav:b_peony:0")
        self.assertIn("p:b_peony", payloads(act(U, "favs:1")))
        self.assertIn("Не нашёл", texts(say(U, "самолёт")))

    def test_admin_only_and_demo(self):
        self.assertNotIn("Админ-панель</b>", texts(act(U, "adm")))
        self.assertIn("Админ-панель", texts(act(ADMIN, "adm")))
        outs = act(ADMIN, "adm:demo")
        self.assertIn("Создано демо-заказов", texts(outs))
        self.assertIn("Выручка", texts(act(ADMIN, "adm:stats")))
        for k in ("new", "active", "today", "tomorrow"):
            act(ADMIN, f"adm:o:{k}")

    def test_broadcast(self):
        say(U, "привет")  # создаёт пользователя
        act(ADMIN, "adm:bc")
        say(ADMIN, "Скидка выходного дня")
        outs = act(ADMIN, "adm:bcgo")
        self.assertTrue(any(o.to == U for o in outs))

    def test_support_flow(self):
        act(U, "support")
        outs = say(U, "Вопрос про доставку")
        self.assertTrue(any(o.to == ADMIN for o in outs))


class TestCrawler(Base):
    def test_every_button_works(self):
        """Обходит все кнопки, достижимые из меню (клиент и админ): ни одна не падает, callback ≤ 64 байт."""
        S.cart_add(U, "r_red", 0)
        S.cart_add(U, "b_tender", 1)
        act(ADMIN, "adm:demo")
        for uid in (U, ADMIN):
            seen = set()
            queue = [o for o in core.handle_start(uid, "x")]
            todo = payloads(queue)
            skip_prefix = ("adm:st:", "co:ok", "ocxy", "adm:bcgo", "cart:clear")
            while todo:
                p = todo.pop()
                if p in seen or p.startswith("http") or p == "!contact":
                    continue
                seen.add(p)
                self.assertLessEqual(len(p.encode()), 64, p)
                if p.startswith(skip_prefix):
                    continue
                outs = act(uid, p)
                for o in outs:
                    self.assertTrue(o.screen.text.strip(), p)
                    self.assertLessEqual(len(o.screen.text), 3900, p)
                    if o.screen.photo:
                        self.assertLessEqual(len(o.screen.text), 1000, p)
                        self.assertTrue(os.path.exists(o.screen.photo), p)
                todo.extend(payloads(outs))
            self.assertGreater(len(seen), 40 if uid == U else 60, f"{uid}: {len(seen)}")


if __name__ == "__main__":
    unittest.main()
