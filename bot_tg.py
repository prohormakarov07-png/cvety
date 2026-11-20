"""Telegram-версия бота цветочного магазина (aiogram 3). Запуск: python bot_tg.py
Вся логика в core.py, здесь только показ экранов и приём событий."""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

import config as C
import core
import storage as S

log = logging.getLogger("flowers-tg")
router = Router()
PHOTO_IDS = {}  # путь файла -> file_id (чтобы не загружать картинку каждый раз)
CANCEL_TEXT = "✖️ Отмена"


def ikb(rows):
    out = []
    for row in rows:
        btns = []
        for text, data in row:
            if data == "!contact":
                continue  # в Telegram номер запрашивается системной кнопкой снизу
            if data.startswith("http"):
                btns.append(InlineKeyboardButton(text=text, url=data))
            else:
                btns.append(InlineKeyboardButton(text=text, callback_data=data))
        if btns:
            out.append(btns)
    return InlineKeyboardMarkup(inline_keyboard=out)


def contact_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)], [KeyboardButton(text=CANCEL_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def send_screen(bot, chat_id, scr):
    """Отправить экран новым сообщением."""
    if scr.contact:
        return await bot.send_message(chat_id, scr.text, reply_markup=contact_kb())
    if scr.photo and len(scr.text) <= 1000:
        try:
            src = PHOTO_IDS.get(scr.photo) or FSInputFile(scr.photo)
            m = await bot.send_photo(chat_id, src, caption=scr.text, reply_markup=ikb(scr.rows))
            if m.photo:
                PHOTO_IDS[scr.photo] = m.photo[-1].file_id
            return m
        except Exception as e:  # noqa: BLE001  не вышло с фото: покажем текстом
            log.info("фото не отправилось: %s", e)
            PHOTO_IDS.pop(scr.photo, None)
    return await bot.send_message(chat_id, scr.text, reply_markup=ikb(scr.rows))


async def safe_send(bot, chat_id, scr):
    try:
        await send_screen(bot, chat_id, scr)
        return True
    except Exception as e:  # noqa: BLE001  клиент мог заблокировать бота или это демо-пользователь
        log.info("не удалось отправить %s: %s", chat_id, e)
        return False


async def edit_or_send(bot, msg, chat_id, scr):
    """Для кнопки: правим сообщение, при невозможности удаляем и отправляем заново."""
    if scr.photo and getattr(msg, "photo", None) and not scr.new and len(scr.text) <= 1000:
        try:  # карточка товара уже на экране: меняем только подпись и кнопки, без новой загрузки фото
            await msg.edit_caption(caption=scr.text, reply_markup=ikb(scr.rows))
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return
        except Exception:  # noqa: BLE001
            pass
    if scr.photo or scr.contact or scr.new:
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001
            pass
        return await send_screen(bot, chat_id, scr)
    try:
        await msg.edit_text(scr.text, reply_markup=ikb(scr.rows))
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            return
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001
            pass
        await send_screen(bot, chat_id, scr)


async def dispatch(bot, uid, chat_id, outs, msg=None):
    first = True
    for out in outs:
        if out.delay:
            await asyncio.sleep(out.delay)
        if out.to is not None and out.to != uid:
            await safe_send(bot, out.to, out.screen)
            continue
        if msg is not None and first:
            await edit_or_send(bot, msg, chat_id, out.screen)
        else:
            await send_screen(bot, chat_id, out.screen)
        first = False


def who(user):
    return user.full_name if user else "Гость"


@router.message(Command("id"))
async def cmd_id(m: Message):
    await m.answer(f"Ваш Telegram ID: {m.from_user.id}")


@router.message(Command("start", "menu", "cancel"))
async def cmd_start(m: Message):
    uid = m.from_user.id
    await dispatch(m.bot, uid, m.chat.id, core.handle_start(uid, who(m.from_user)))


@router.message(Command("admin"))
async def cmd_admin(m: Message):
    uid = m.from_user.id
    if not core.is_admin(uid):
        return await m.answer(f"Админ-панель доступна только администратору. Ваш ID: {uid}. Добавьте его в ADMIN_IDS в .env.")
    await dispatch(m.bot, uid, m.chat.id, core.handle_action(uid, who(m.from_user), "adm"))


@router.callback_query()
async def on_callback(cb: CallbackQuery):
    uid = cb.from_user.id
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    try:
        outs = core.handle_action(uid, who(cb.from_user), cb.data or "")
        await dispatch(cb.bot, uid, cb.message.chat.id, outs, msg=cb.message)
    except Exception:  # noqa: BLE001  один сбой не должен ронять бота
        log.exception("ошибка в обработчике кнопки %r", cb.data)


@router.message(F.contact)
async def on_contact(m: Message):
    uid = m.from_user.id
    await m.answer("📱 Номер получен, спасибо!", reply_markup=ReplyKeyboardRemove())
    await dispatch(m.bot, uid, m.chat.id, core.handle_contact(uid, who(m.from_user), m.contact.phone_number))


@router.message(F.text)
async def on_text(m: Message):
    uid = m.from_user.id
    try:
        if m.text == CANCEL_TEXT:
            await m.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
            outs = core.handle_start(uid, who(m.from_user))
        else:
            outs = core.handle_text(uid, who(m.from_user), m.text)
        await dispatch(m.bot, uid, m.chat.id, outs)
    except Exception:  # noqa: BLE001
        log.exception("ошибка в обработчике сообщения")


@router.message()
async def on_other(m: Message):
    await m.answer("Я понимаю текст и кнопки 🙂 Откройте /menu.")


async def reminder_loop(bot):
    while True:
        try:
            for out in core.due_outs():
                await safe_send(bot, out.to, out.screen)
        except Exception:  # noqa: BLE001
            log.exception("ошибка в цикле напоминаний")
        await asyncio.sleep(600)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not C.BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен.")
    S.init_db(C.DB_PATH)
    core.configure(C.ADMIN_IDS)
    session = AiohttpSession(proxy=C.PROXY) if C.PROXY else None
    bot = Bot(C.BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    me = await bot.get_me()
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="menu", description="Показать меню"),
            BotCommand(command="cancel", description="Отменить действие"),
            BotCommand(command="id", description="Узнать свой Telegram ID"),
            BotCommand(command="admin", description="Админ-панель"),
        ]
    )
    reminders = asyncio.create_task(reminder_loop(bot))
    log.info("Бот @%s запущен", me.username)
    try:
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
