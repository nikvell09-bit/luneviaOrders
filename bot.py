import os
import sqlite3
import asyncio
import threading
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, render_template_string, request,
    redirect, url_for, session, flash
)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")

PAYMENT_DETAILS = os.getenv(
    "PAYMENT_DETAILS",
    "Реквизиты оплаты пока не указаны."
)

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    "@LuneviaSupport"
)

DB_FILE = "lunevia_orders.db"
PORT = int(os.getenv("PORT", "10000"))

PRICE_MINI = 299
PRICE_LOVE = 499
PRICE_PREMIUM = 899


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            username TEXT,
            language TEXT NOT NULL,
            site_type TEXT,
            tariff TEXT,
            price INTEGER,
            recipient_name TEXT,
            event_date TEXT,
            custom_text TEXT,
            photo_count INTEGER DEFAULT 0,
            design TEXT,
            status TEXT NOT NULL DEFAULT 'awaiting_payment',
            receipt_file_id TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            language TEXT DEFAULT 'ru',
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            username TEXT,
            language TEXT,
            kind TEXT DEFAULT 'support',
            subject TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_type TEXT NOT NULL,
            sender_id TEXT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            title TEXT,
            body TEXT,
            order_id INTEGER,
            ticket_id INTEGER,
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def save_user(user):
    conn = db()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users
        (telegram_id, username, language, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id)
        DO UPDATE SET
            username=excluded.username,
            last_seen=excluded.last_seen
    """, (
        user.id,
        user.username,
        "ru",
        now(),
        now()
    ))

    conn.commit()
    conn.close()


def create_order(user, data):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders (
            telegram_id,
            username,
            language,
            site_type,
            tariff,
            price,
            recipient_name,
            event_date,
            custom_text,
            photo_count,
            design,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user.id,
        user.username,
        data.get("language", "ru"),
        data.get("site_type"),
        data.get("tariff"),
        data.get("price"),
        data.get("recipient_name"),
        data.get("event_date"),
        data.get("custom_text"),
        data.get("photo_count", 0),
        data.get("design"),
        "awaiting_payment",
        now()
    ))

    order_id = cur.lastrowid

    conn.commit()
    conn.close()

    return order_id


def get_order(order_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()
    conn.close()
    return row


def get_user_orders(telegram_id):
    conn = db()
    rows = conn.execute(
        """
        SELECT * FROM orders
        WHERE telegram_id=?
        ORDER BY id DESC
        """,
        (telegram_id,)
    ).fetchall()
    conn.close()
    return rows


def set_receipt(order_id, file_id):
    conn = db()

    conn.execute("""
        UPDATE orders
        SET receipt_file_id=?, status='payment_review'
        WHERE id=?
    """, (file_id, order_id))

    conn.commit()
    conn.close()

    order = get_order(order_id)

    add_notification(
        "payment",
        "Новая оплата",
        f"Заказ #{order_id} отправил чек",
        order_id=order_id
    )


def set_status(order_id, status):
    conn = db()

    conn.execute(
        "UPDATE orders SET status=? WHERE id=?",
        (status, order_id)
    )

    conn.commit()
    conn.close()


def add_notification(
    ntype,
    title,
    body,
    order_id=None,
    ticket_id=None
):
    conn = db()

    conn.execute("""
        INSERT INTO notifications
        (type, title, body, order_id, ticket_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        ntype,
        title,
        body,
        order_id,
        ticket_id,
        now()
    ))

    conn.commit()
    conn.close()


# =========================================================
# SUPPORT
# =========================================================

def create_ticket(
    telegram_id,
    username,
    language,
    text,
    kind="support"
):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO support_tickets
        (
            telegram_id,
            username,
            language,
            kind,
            subject,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
    """, (
        telegram_id,
        username,
        language,
        kind,
        text[:100],
        now(),
        now()
    ))

    ticket_id = cur.lastrowid

    cur.execute("""
        INSERT INTO support_messages
        (
            ticket_id,
            sender_type,
            sender_id,
            text,
            created_at
        )
        VALUES (?, 'user', ?, ?, ?)
    """, (
        ticket_id,
        str(telegram_id),
        text,
        now()
    ))

    conn.commit()
    conn.close()

    add_notification(
        "support",
        "Новое обращение",
        text,
        ticket_id=ticket_id
    )

    return ticket_id


def add_support_message(
    ticket_id,
    sender_type,
    sender_id,
    text
):
    conn = db()

    conn.execute("""
        INSERT INTO support_messages
        (
            ticket_id,
            sender_type,
            sender_id,
            text,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        ticket_id,
        sender_type,
        str(sender_id),
        text,
        now()
    ))

    conn.execute("""
        UPDATE support_tickets
        SET updated_at=?
        WHERE id=?
    """, (now(), ticket_id))

    conn.commit()
    conn.close()


def get_ticket(ticket_id):
    conn = db()

    ticket = conn.execute("""
        SELECT * FROM support_tickets
        WHERE id=?
    """, (ticket_id,)).fetchone()

    conn.close()

    return ticket


def get_ticket_messages(ticket_id):
    conn = db()

    rows = conn.execute("""
        SELECT * FROM support_messages
        WHERE ticket_id=?
        ORDER BY id ASC
    """, (ticket_id,)).fetchall()

    conn.close()

    return rows


# =========================================================
# TELEGRAM HELPERS
# =========================================================

async def send_telegram_message(chat_id, text):
    if not BOT_TOKEN:
        return

    try:
        async with Bot(BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=chat_id,
                text=text
            )
    except Exception as e:
        print("Telegram send error:", e)


async def notify_admin(text, keyboard=None):
    if not ADMIN_ID:
        return

    if not BOT_TOKEN:
        return

    try:
        async with Bot(BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=text,
                reply_markup=keyboard
            )
    except Exception as e:
        print("Admin notification error:", e)


# =========================================================
# TEXTS
# =========================================================

def status_text(status):
    return {
        "awaiting_payment": "💳 Ожидает оплаты",
        "payment_review": "🟠 Проверка оплаты",
        "paid": "💰 Оплачено",
        "in_progress": "🔵 В работе",
        "ready": "🟢 Готово",
        "payment_rejected": "🔴 Оплата отклонена",
        "cancelled": "⚫ Отменён",
    }.get(status, status)


# =========================================================
# TELEGRAM BOT
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🇺🇦 Українська",
                callback_data="lang_uk"
            )
        ],
        [
            InlineKeyboardButton(
                "Русский",
                callback_data="lang_ru"
            )
        ]
    ])

    await update.message.reply_text(
        "❤️ Добро пожаловать в Lunevia!\n\n"
        "Здесь мы создаём красивые персональные сайты "
        "для любимых людей, свиданий, годовщин и других событий.\n\n"
        "Выберите язык:",
        reply_markup=keyboard
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Действие отменено."
    )


def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💌 Создать сайт",
                callback_data="create_site"
            )
        ],
        [
            InlineKeyboardButton(
                "👀 Примеры",
                callback_data="examples"
            ),
            InlineKeyboardButton(
                "💰 Цены",
                callback_data="prices"
            )
        ],
        [
            InlineKeyboardButton(
                "📖 О нас",
                callback_data="about"
            )
        ],
        [
            InlineKeyboardButton(
                "📦 Мои заказы",
                callback_data="my_orders"
            )
        ],
        [
            InlineKeyboardButton(
                "💬 Поддержка",
                callback_data="support"
            )
        ]
    ])


async def show_menu(update, context):
    query = update.callback_query

    if query:
        await query.answer()
        await query.edit_message_text(
            "🏠 Главное меню",
            reply_markup=main_menu()
        )


# =========================================================
# ORDER CREATION
# =========================================================

async def create_site(update, context):
    query = update.callback_query
    await query.answer()

    context.user_data["order"] = {}

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💑 Романтический",
                callback_data="type_love"
            )
        ],
        [
            InlineKeyboardButton(
                "🎂 Праздник",
                callback_data="type_event"
            )
        ],
        [
            InlineKeyboardButton(
                "✨ Другое",
                callback_data="type_custom"
            )
        ]
    ])

    await query.edit_message_text(
        "💌 Какой сайт создаём?",
        reply_markup=keyboard
    )


async def choose_type(update, context):
    query = update.callback_query
    await query.answer()

    types = {
        "type_love": "Романтический",
        "type_event": "Праздник",
        "type_custom": "Другое"
    }

    context.user_data["order"]["site_type"] = types.get(
        query.data,
        "Другое"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🌙 Mini — 299 грн",
                callback_data="tariff_mini"
            )
        ],
        [
            InlineKeyboardButton(
                "❤️ Love — 499 грн",
                callback_data="tariff_love"
            )
        ],
        [
            InlineKeyboardButton(
                "👑 Premium — 899 грн",
                callback_data="tariff_premium"
            )
        ]
    ])

    await query.edit_message_text(
        "💰 Выберите тариф:",
        reply_markup=keyboard
    )


async def choose_tariff(update, context):
    query = update.callback_query
    await query.answer()

    tariffs = {
        "tariff_mini": ("Mini", PRICE_MINI),
        "tariff_love": ("Love", PRICE_LOVE),
        "tariff_premium": ("Premium", PRICE_PREMIUM)
    }

    tariff, price = tariffs[query.data]

    context.user_data["order"]["tariff"] = tariff
    context.user_data["order"]["price"] = price

    context.user_data["step"] = "recipient"

    await query.edit_message_text(
        "👤 Напиши имя человека, для которого создаём сайт:"
    )


async def handle_order_text(update, context):
    user = update.effective_user
    save_user(user)

    step = context.user_data.get("step")

    if step == "recipient":

        context.user_data["order"]["recipient_name"] = (
            update.message.text
        )

        context.user_data["step"] = "date"

        await update.message.reply_text(
            "📅 Напиши дату события.\n\n"
            "Например: 23.09.2026"
        )

        return

    if step == "date":

        context.user_data["order"]["event_date"] = (
            update.message.text
        )

        context.user_data["step"] = "text"

        await update.message.reply_text(
            "💌 Напиши текст, который хочешь разместить "
            "на сайте:"
        )

        return

    if step == "text":

        context.user_data["order"]["custom_text"] = (
            update.message.text
        )

        context.user_data["step"] = "photos"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📸 Да",
                    callback_data="photos_yes"
                ),
                InlineKeyboardButton(
                    "➡️ Нет",
                    callback_data="photos_no"
                )
            ]
        ])

        await update.message.reply_text(
            "📸 Хочешь добавить фотографии?",
            reply_markup=keyboard
        )

        return

    if step == "support":

        text = update.message.text

        ticket_id = create_ticket(
            user.id,
            user.username,
            "ru",
            text,
            "support"
        )

        await update.message.reply_text(
            f"✅ Обращение #{ticket_id} отправлено!\n\n"
            "Мы ответим тебе здесь."
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 Ответить",
                    callback_data=f"support_reply_{ticket_id}"
                )
            ]
        ])

        await notify_admin(
            f"💬 НОВОЕ ОБРАЩЕНИЕ #{ticket_id}\n\n"
            f"👤 @{user.username or user.id}\n\n"
            f"{text}",
            keyboard
        )

        context.user_data.clear()

        return


# =========================================================
# PHOTOS
# =========================================================

async def choose_photos(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "photos_yes":
        context.user_data["step"] = "upload_photos"
        context.user_data["photo_count"] = 0

        await query.edit_message_text(
            "📸 Отправляй фотографии по одной.\n\n"
            "Когда закончишь — напиши /done"
        )

    else:
        context.user_data["order"]["photo_count"] = 0

        await choose_design(query, context)


async def handle_photo(update, context):
    if context.user_data.get("step") != "upload_photos":
        return

    context.user_data["photo_count"] = (
        context.user_data.get("photo_count", 0) + 1
    )

    await update.message.reply_text(
        f"📸 Фото #{context.user_data['photo_count']} получено."
    )


async def done_photos(update, context):
    if context.user_data.get("step") != "upload_photos":
        return

    count = context.user_data.get("photo_count", 0)

    context.user_data["order"]["photo_count"] = count

    await choose_design(update.message, context)


async def choose_design(message, context):
    context.user_data["step"] = "design"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🌑 Dark",
                callback_data="design_dark"
            )
        ],
        [
            InlineKeyboardButton(
                "☀️ Light",
                callback_data="design_light"
            )
        ],
        [
            InlineKeyboardButton(
                "💜 Romantic",
                callback_data="design_romantic"
            )
        ]
    ])

    await message.reply_text(
        "🎨 Выбери дизайн:",
        reply_markup=keyboard
    )


async def select_design(update, context):
    query = update.callback_query
    await query.answer()

    designs = {
        "design_dark": "Dark",
        "design_light": "Light",
        "design_romantic": "Romantic"
    }

    context.user_data["order"]["design"] = designs[query.data]

    order = context.user_data["order"]

    text = (
        "📋 <b>Проверь заказ</b>\n\n"
        f"💌 Тип: {order.get('site_type')}\n"
        f"💎 Тариф: {order.get('tariff')}\n"
        f"💰 Цена: {order.get('price')} грн\n"
        f"👤 Имя: {order.get('recipient_name')}\n"
        f"📅 Дата: {order.get('event_date')}\n"
        f"📸 Фото: {order.get('photo_count', 0)}\n"
        f"🎨 Дизайн: {order.get('design')}\n\n"
        f"💬 Текст:\n{order.get('custom_text')}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Создать заказ",
                callback_data="confirm_order"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Отмена",
                callback_data="menu"
            )
        ]
    ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def confirm_order(update, context):
    query = update.callback_query
    await query.answer()

    user = update.effective_user

    order = context.user_data["order"]

    order_id = create_order(
        user,
        order
    )

    context.user_data["current_order_id"] = order_id

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💳 Я оплатил",
                callback_data=f"paid_{order_id}"
            )
        ]
    ])

    await query.edit_message_text(
        f"✅ Заказ #{order_id} создан!\n\n"
        f"💰 К оплате: {order['price']} грн\n\n"
        f"💳 {PAYMENT_DETAILS}\n\n"
        "После оплаты нажми кнопку ниже и отправь чек.",
        reply_markup=keyboard
    )

    await notify_admin(
        f"📦 НОВЫЙ ЗАКАЗ #{order_id}\n\n"
        f"👤 @{user.username or user.id}\n"
        f"💰 {order['price']} грн\n"
        f"💎 {order['tariff']}"
    )


# =========================================================
# RECEIPT
# =========================================================

async def paid_button(update, context):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[1])

    context.user_data["receipt_order"] = order_id
    context.user_data["step"] = "receipt"

    await query.message.reply_text(
        "📸 Отправь фото чека."
    )


async def handle_receipt(update, context):
    if context.user_data.get("step") != "receipt":
        return

    if not update.message.photo:
        await update.message.reply_text(
            "❌ Отправь именно фото чека."
        )
        return

    order_id = context.user_data["receipt_order"]

    file_id = update.message.photo[-1].file_id

    set_receipt(
        order_id,
        file_id
    )

    context.user_data.clear()

    await update.message.reply_text(
        f"✅ Чек по заказу #{order_id} отправлен "
        "на проверку.\n\n"
        "Ожидай подтверждения оплаты."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Оплатa подтверждена",
                callback_data=f"pay_ok_{order_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Отклонить",
                callback_data=f"pay_no_{order_id}"
            )
        ]
    ])

    order = get_order(order_id)

    await notify_admin(
        f"🧾 ЧЕК ПО ЗАКАЗУ #{order_id}\n\n"
        f"💰 {order['price']} грн",
        keyboard
    )


# =========================================================
# ADMIN TELEGRAM
# =========================================================

def admin_only(user_id):
    return user_id == ADMIN_ID


async def admin_command(update, context):
    if not admin_only(update.effective_user.id):
        return

    await update.message.reply_text(
        "🛠 Lunevia Admin",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📦 Заказы",
                    callback_data="admin_orders"
                )
            ],
            [
                InlineKeyboardButton(
                    "💬 Поддержка",
                    callback_data="admin_support"
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Статистика",
                    callback_data="admin_stats"
                )
            ]
        ])
    )


async def admin_orders_button(update, context):
    query = update.callback_query
    await query.answer()

    if not admin_only(query.from_user.id):
        return

    conn = db()

    rows = conn.execute("""
        SELECT * FROM orders
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()

    conn.close()

    if not rows:
        await query.edit_message_text(
            "📦 Заказов пока нет."
        )
        return

    buttons = []

    for row in rows:
        buttons.append([
            InlineKeyboardButton(
                f"#{row['id']} — {row['price']} грн",
                callback_data=f"admin_order_{row['id']}"
            )
        ])

    await query.edit_message_text(
        "📦 Последние заказы:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def admin_order_button(update, context):
    query = update.callback_query
    await query.answer()

    if not admin_only(query.from_user.id):
        return

    order_id = int(query.data.split("_")[-1])

    order = get_order(order_id)

    if not order:
        await query.edit_message_text(
            "❌ Заказ не найден."
        )
        return

    text = (
        f"📦 <b>Заказ #{order_id}</b>\n\n"
        f"👤 @{order['username'] or order['telegram_id']}\n"
        f"💌 {order['site_type']}\n"
        f"💎 {order['tariff']}\n"
        f"💰 {order['price']} грн\n"
        f"👤 Получатель: {order['recipient_name']}\n"
        f"📅 {order['event_date']}\n"
        f"📸 Фото: {order['photo_count']}\n"
        f"🎨 {order['design']}\n"
        f"📌 {status_text(order['status'])}\n\n"
        f"💬 {order['custom_text']}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💰 Оплачено",
                callback_data=f"status_paid_{order_id}"
            ),
            InlineKeyboardButton(
                "🔵 В работу",
                callback_data=f"status_progress_{order_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🟢 Готово",
                callback_data=f"status_ready_{order_id}"
            )
        ]
    ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def payment_action(update, context):
    query = update.callback_query
    await query.answer()

    if not admin_only(query.from_user.id):
        return

    parts = query.data.split("_")
    action = parts[1]
    order_id = int(parts[2])

    if action == "ok":
        set_status(order_id, "paid")

        order = get_order(order_id)

        await send_telegram_message(
            order["telegram_id"],
            f"✅ Оплата по заказу #{order_id} подтверждена!\n\n"
            "Теперь заказ передан в работу."
        )

        await query.edit_message_text(
            f"✅ Оплата заказа #{order_id} подтверждена."
        )

    else:
        set_status(order_id, "payment_rejected")

        order = get_order(order_id)

        await send_telegram_message(
            order["telegram_id"],
            f"❌ Оплата по заказу #{order_id} отклонена.\n\n"
            "Проверь чек и отправь его повторно."
        )

        await query.edit_message_text(
            f"❌ Оплата заказа #{order_id} отклонена."
        )


async def admin_status_button(update, context):
    query = update.callback_query
    await query.answer()

    if not admin_only(query.from_user.id):
        return

    parts = query.data.split("_")

    status_name = parts[1]
    order_id = int(parts[2])

    statuses = {
        "paid": "paid",
        "progress": "in_progress",
        "ready": "ready"
    }

    status = statuses.get(status_name)

    if not status:
        return

    set_status(
        order_id,
        status
    )

    order = get_order(order_id)

    await send_telegram_message(
        order["telegram_id"],
        f"📦 Статус заказа #{order_id} изменён:\n\n"
        f"{status_text(status)}"
    )

    await query.edit_message_text(
        f"✅ Заказ #{order_id}\n"
        f"Статус: {status_text(status)}"
    )


# =========================================================
# USER ORDERS
# =========================================================

async def my_orders(update, context):
    query = update.callback_query
    await query.answer()

    orders = get_user_orders(
        query.from_user.id
    )

    if not orders:
        await query.edit_message_text(
            "📦 У тебя пока нет заказов.",
            reply_markup=main_menu()
        )
        return

    buttons = []

    for order in orders:
        buttons.append([
            InlineKeyboardButton(
                f"#{order['id']} • {status_text(order['status'])}",
                callback_data=f"user_order_{order['id']}"
            )
        ])

    await query.edit_message_text(
        "📦 Твои заказы:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def user_order(update, context):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[-1])

    order = get_order(order_id)

    if not order or order["telegram_id"] != query.from_user.id:
        return

    await query.edit_message_text(
        f"📦 Заказ #{order_id}\n\n"
        f"💎 Тариф: {order['tariff']}\n"
        f"💰 Цена: {order['price']} грн\n"
        f"📌 Статус: {status_text(order['status'])}\n"
        f"📅 Дата: {order['event_date']}\n"
        f"🎨 Дизайн: {order['design']}",
        reply_markup=main_menu()
    )


# =========================================================
# SUPPORT
# =========================================================

async def support(update, context):
    query = update.callback_query
    await query.answer()

    context.user_data["step"] = "support"

    await query.edit_message_text(
        "💬 Поддержка\n\n"
        "Напиши свой вопрос одним сообщением.\n"
        "Администратор ответит тебе здесь."
    )


# =========================================================
# OTHER MENU
# =========================================================

async def prices(update, context):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💰 <b>Тарифы Lunevia</b>\n\n"
        "🌙 Mini — 299 грн\n"
        "❤️ Love — 499 грн\n"
        "👑 Premium — 899 грн",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


async def examples(update, context):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "👀 Примеры сайтов:\n\n"
        "Скоро здесь появится галерея готовых работ.",
        reply_markup=main_menu()
    )


async def about(update, context):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "❤️ <b>Lunevia</b>\n\n"
        "Создаём персональные сайты, которые "
        "можно подарить любимому человеку.\n\n"
        "Красиво. Персонально. С душой.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =========================================================
# WEB ADMIN
# =========================================================

app = Flask(__name__)
app.secret_key = SECRET_KEY


BASE_STYLE = """
<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #0b0d12;
    color: #f5f5f5;
    font-family: Arial, sans-serif;
}

a {
    color: inherit;
    text-decoration: none;
}

.nav {
    height: 64px;
    background: #11141b;
    border-bottom: 1px solid #242936;
    display: flex;
    align-items: center;
    padding: 0 24px;
    gap: 25px;
}

.logo {
    font-size: 22px;
    font-weight: 700;
}

.nav a {
    color: #aeb4c2;
}

.nav a:hover {
    color: white;
}

.container {
    max-width: 1250px;
    margin: 30px auto;
    padding: 0 20px;
}

.card {
    background: #11141b;
    border: 1px solid #242936;
    border-radius: 14px;
    padding: 20px;
    margin-bottom: 20px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px;
}

.stat {
    background: #161a22;
    border: 1px solid #272d39;
    border-radius: 14px;
    padding: 20px;
}

.stat b {
    display: block;
    font-size: 30px;
    margin-top: 8px;
}

table {
    width: 100%;
    border-collapse: collapse;
}

th, td {
    text-align: left;
    padding: 13px;
    border-bottom: 1px solid #272d39;
}

th {
    color: #858d9d;
}

.btn {
    display: inline-block;
    border: 0;
    border-radius: 9px;
    padding: 10px 14px;
    background: #252b38;
    color: white;
    cursor: pointer;
}

.btn:hover {
    background: #323a4a;
}

.btn-green {
    background: #176b45;
}

.btn-red {
    background: #8e2930;
}

.btn-blue {
    background: #24528c;
}

input, textarea, select {
    width: 100%;
    background: #0c0f15;
    border: 1px solid #303746;
    color: white;
    padding: 12px;
    border-radius: 8px;
    margin: 7px 0 15px;
}

.message {
    background: #181d27;
    padding: 13px;
    border-radius: 10px;
    margin: 10px 0;
}

.user-message {
    border-left: 3px solid #5574ff;
}

.admin-message {
    border-left: 3px solid #35b878;
}

.status {
    padding: 5px 9px;
    background: #222835;
    border-radius: 20px;
    font-size: 12px;
}

.login {
    max-width: 400px;
    margin: 100px auto;
}

@media(max-width:700px) {
    .nav {
        overflow-x: auto;
    }

    table {
        font-size: 13px;
    }

    th:nth-child(1),
    td:nth-child(1) {
        display: none;
    }
}
</style>
"""


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/admin/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        if (
            username == ADMIN_USERNAME
            and password == ADMIN_PASSWORD
        ):
            session["admin"] = True
            return redirect(url_for("dashboard"))

        flash("Неверный логин или пароль")

    return render_template_string(
        BASE_STYLE + """
        <div class="login card">
            <h1>🌙 Lunevia Admin</h1>

            <form method="POST">
                <label>Логин</label>
                <input name="username">

                <label>Пароль</label>
                <input name="password" type="password">

                <button class="btn btn-blue">
                    Войти
                </button>
            </form>
        </div>
        """
    )


@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@admin_required
def dashboard():

    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) FROM orders"
    ).fetchone()[0]

    review = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status='payment_review'"
    ).fetchone()[0]

    progress = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status='in_progress'"
    ).fetchone()[0]

    ready = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status='ready'"
    ).fetchone()[0]

    revenue = conn.execute(
        """
        SELECT COALESCE(SUM(price), 0)
        FROM orders
        WHERE status IN ('paid', 'in_progress', 'ready')
        """
    ).fetchone()[0]

    tickets = conn.execute(
        """
        SELECT COUNT(*)
        FROM support_tickets
        WHERE status='open'
        """
    ).fetchone()[0]

    conn.close()

    return render_template_string(
        BASE_STYLE + """
        <div class="nav">
            <div class="logo">🌙 Lunevia</div>
            <a href="/admin">Главная</a>
            <a href="/admin/orders">Заказы</a>
            <a href="/admin/support">Поддержка</a>
            <a href="/admin/notifications">Уведомления</a>
            <a href="/admin/logout">Выйти</a>
        </div>

        <div class="container">
            <h1>Панель управления</h1>

            <div class="grid">

                <div class="stat">
                    📦 Заказов
                    <b>{{ total }}</b>
                </div>

                <div class="stat">
                    🟠 Проверка оплаты
                    <b>{{ review }}</b>
                </div>

                <div class="stat">
                    🔵 В работе
                    <b>{{ progress }}</b>
                </div>

                <div class="stat">
                    🟢 Готовые
                    <b>{{ ready }}</b>
                </div>

                <div class="stat">
                    💰 Выручка
                    <b>{{ revenue }} грн</b>
                </div>

                <div class="stat">
                    💬 Открытые обращения
                    <b>{{ tickets }}</b>
                </div>

            </div>
        </div>
        """,
        total=total,
        review=review,
        progress=progress,
        ready=ready,
        revenue=revenue,
        tickets=tickets
    )


@app.route("/admin/orders")
@admin_required
def admin_orders_page():

    status = request.args.get("status")

    conn = db()

    if status:
        orders = conn.execute(
            """
            SELECT * FROM orders
            WHERE status=?
            ORDER BY id DESC
            """,
            (status,)
        ).fetchall()
    else:
        orders = conn.execute(
            """
            SELECT * FROM orders
            ORDER BY id DESC
            """
        ).fetchall()

    conn.close()

    return render_template_string(
        BASE_STYLE + """
        <div class="nav">
            <div class="logo">🌙 Lunevia</div>
            <a href="/admin">Главная</a>
            <a href="/admin/orders">Заказы</a>
            <a href="/admin/support">Поддержка</a>
            <a href="/admin/notifications">Уведомления</a>
            <a href="/admin/logout">Выйти</a>
        </div>

        <div class="container">

        <h1>📦 Заказы</h1>

        <div class="card">
            <a class="btn" href="/admin/orders">Все</a>
            <a class="btn" href="/admin/orders?status=payment_review">
                Проверка оплаты
            </a>
            <a class="btn" href="/admin/orders?status=in_progress">
                В работе
            </a>
            <a class="btn" href="/admin/orders?status=ready">
                Готовые
            </a>
        </div>

        <div class="card">
        <table>

        <tr>
            <th>ID</th>
            <th>Клиент</th>
            <th>Тариф</th>
            <th>Цена</th>
            <th>Статус</th>
            <th></th>
        </tr>

        {% for order in orders %}

        <tr>
            <td>#{{ order.id }}</td>
            <td>
                @{{ order.username or order.telegram_id }}
            </td>
            <td>{{ order.tariff }}</td>
            <td>{{ order.price }} грн</td>
            <td>
                <span class="status">
                    {{ status_text(order.status) }}
                </span>
            </td>
            <td>
                <a class="btn"
                   href="/admin/orders/{{ order.id }}">
                    Открыть
                </a>
            </td>
        </tr>

        {% endfor %}

        </table>
        </div>

        </div>
        """,
        orders=orders,
        status_text=status_text
    )


@app.route("/admin/orders/<int:order_id>")
@admin_required
def admin_order_page(order_id):

    order = get_order(order_id)

    if not order:
        return "Заказ не найден", 404

    return render_template_string(
        BASE_STYLE + """
        <div class="nav">
            <div class="logo">🌙 Lunevia</div>
            <a href="/admin">Главная</a>
            <a href="/admin/orders">Заказы</a>
            <a href="/admin/support">Поддержка</a>
            <a href="/admin/logout">Выйти</a>
        </div>

        <div class="container">

        <h1>📦 Заказ #{{ order.id }}</h1>

        <div class="card">

            <h2>Информация</h2>

            <p>👤 Клиент:
                @{{ order.username or order.telegram_id }}
            </p>

            <p>💌 Тип: {{ order.site_type }}</p>
            <p>💎 Тариф: {{ order.tariff }}</p>
            <p>💰 Цена: {{ order.price }} грн</p>
            <p>👤 Получатель: {{ order.recipient_name }}</p>
            <p>📅 Дата: {{ order.event_date }}</p>
            <p>📸 Фото: {{ order.photo_count }}</p>
            <p>🎨 Дизайн: {{ order.design }}</p>
            <p>📌 Статус:
                <b>{{ status_text(order.status) }}</b>
            </p>

            <hr>

            <h3>💬 Текст</h3>

            <div class="message">
                {{ order.custom_text }}
            </div>

        </div>

        {% if order.receipt_file_id %}

        <div class="card">

            <h2>🧾 Чек отправлен</h2>

            <p>
                Чек сохранён в Telegram.
                Открой Telegram-админку для просмотра
                изображения.
            </p>

        </div>

        {% endif %}

        <div class="card">

            <h2>Изменить статус</h2>

            <form method="POST"
                  action="/admin/orders/{{ order.id }}/status">

                <select name="status">

                    <option value="awaiting_payment">
                        Ожидает оплаты
                    </option>

                    <option value="payment_review">
                        Проверка оплаты
                    </option>

                    <option value="paid">
                        Оплачено
                    </option>

                    <option value="in_progress">
                        В работе
                    </option>

                    <option value="ready">
                        Готово
                    </option>

                    <option value="payment_rejected">
                        Оплата отклонена
                    </option>

                    <option value="cancelled">
                        Отменён
                    </option>

                </select>

                <button class="btn btn-blue">
                    Сохранить
                </button>

            </form>

        </div>

        </div>
        """,
        order=order,
        status_text=status_text
    )


@app.route(
    "/admin/orders/<int:order_id>/status",
    methods=["POST"]
)
@admin_required
def admin_change_status(order_id):

    status = request.form.get("status")

    allowed = {
        "awaiting_payment",
        "payment_review",
        "paid",
        "in_progress",
        "ready",
        "payment_rejected",
        "cancelled"
    }

    if status not in allowed:
        return redirect(
            url_for(
                "admin_order_page",
                order_id=order_id
            )
        )

    set_status(
        order_id,
        status
    )

    order = get_order(order_id)

    if order:
        # Flask работает в отдельном потоке,
        # поэтому запускаем отдельный asyncio loop.
        try:
            asyncio.run(
                send_telegram_message(
                    order["telegram_id"],
                    f"📦 Статус заказа #{order_id}:\n\n"
                    f"{status_text(status)}"
                )
            )
        except Exception as e:
            print(e)

    return redirect(
        url_for(
            "admin_order_page",
            order_id=order_id
        )
    )


@app.route("/admin/support")
@admin_required
def admin_support_page():

    conn = db()

    tickets = conn.execute("""
        SELECT * FROM support_tickets
        ORDER BY
            CASE WHEN status='open' THEN 0 ELSE 1 END,
            updated_at DESC
    """).fetchall()

    conn.close()

    return render_template_string(
        BASE_STYLE + """
        <div class="nav">
            <div class="logo">🌙 Lunevia</div>
            <a href="/admin">Главная</a>
            <a href="/admin/orders">Заказы</a>
            <a href="/admin/support">Поддержка</a>
            <a href="/admin/notifications">Уведомления</a>
            <a href="/admin/logout">Выйти</a>
        </div>

        <div class="container">

        <h1>💬 Поддержка</h1>

        {% for ticket in tickets %}

        <div class="card">

            <h3>
                #{{ ticket.id }}
                —
                {{ ticket.subject }}
            </h3>

            <p>
                👤 @{{ ticket.username or ticket.telegram_id }}
            </p>

            <p>
                📌 {{ ticket.status }}
            </p>

            <a class="btn btn-blue"
               href="/admin/support/{{ ticket.id }}">
                Открыть диалог
            </a>

        </div>

        {% endfor %}

        </div>
        """,
        tickets=tickets
    )


@app.route("/admin/support/<int:ticket_id>")
@admin_required
def admin_ticket_page(ticket_id):

    ticket = get_ticket(ticket_id)

    if not ticket:
        return "Обращение не найдено", 404

    messages = get_ticket_messages(ticket_id)

    return render_template_string(
        BASE_STYLE + """
        <div class="nav">
            <div class="logo">🌙 Lunevia</div>
            <a href="/admin">Главная</a>
            <a href="/admin/orders">Заказы</a>
            <a href="/admin/support">Поддержка</a>
            <a href="/admin/logout">Выйти</a>
        </div>

        <div class="container">

        <h1>💬 Обращение #{{ ticket.id }}</h1>

        <div class="card">

        {% for message in messages %}

            <div class="
                message
                {% if message.sender_type == 'user' %}
                    user-message
                {% else %}
                    admin-message
                {% endif %}
            ">

                <b>
                {% if message.sender_type == 'user' %}
                    👤 Клиент
                {% else %}
                    🛠 Администратор
                {% endif %}
                </b>

                <p>{{ message.text }}</p>

                <small>
                    {{ message.created_at }}
                </small>

            </div>

        {% endfor %}

        </div>

        {% if ticket.status == 'open' %}

        <div class="card">

            <form method="POST"
                  action="/admin/support/{{ ticket.id }}/reply">

                <textarea
                    name="text"
                    rows="5"
                    placeholder="Напиши ответ клиенту..."
                    required></textarea>

                <button class="btn btn-green">
                    💬 Отправить ответ
                </button>

            </form>

            <br>

            <form method="POST"
                  action="/admin/support/{{ ticket.id }}/close">

                <button class="btn btn-red">
                    Закрыть обращение
                </button>

            </form>

        </div>

        {% else %}

        <div class="card">
            ✅ Обращение закрыто
        </div>

        {% endif %}

        </div>
        """,
        ticket=ticket,
        messages=messages
    )


@app.route(
    "/admin/support/<int:ticket_id>/reply",
    methods=["POST"]
)
@admin_required
def admin_reply_ticket(ticket_id):

    text = request.form.get("text", "").strip()

    if not text:
        return redirect(
            url_for(
                "admin_ticket_page",
                ticket_id=ticket_id
            )
        )

    ticket = get_ticket(ticket_id)

    if not ticket:
        return "Not found", 404

    add_support_message(
        ticket_id,
        "admin",
        ADMIN_ID,
        text
    )

    try:
        asyncio.run(
            send_telegram_message(
                ticket["telegram_id"],
                f"💬 Ответ поддержки по обращению "
                f"#{ticket_id}:\n\n{text}"
            )
        )
    except Exception as e:
        print("Reply error:", e)

    return redirect(
        url_for(
            "admin_ticket_page",
            ticket_id=ticket_id
        )
    )


@app.route(
    "/admin/support/<int:ticket_id>/close",
    methods=["POST"]
)
@admin_required
def close_ticket(ticket_id):

    conn = db()

    ticket = conn.execute(
        "SELECT * FROM support_tickets WHERE id=?",
        (ticket_id,)
    ).fetchone()

    conn.execute("""
        UPDATE support_tickets
        SET status='closed', updated_at=?
        WHERE id=?
    """, (
        now(),
        ticket_id
    ))

    conn.commit()
    conn.close()

    if ticket:
        try:
            asyncio.run(
                send_telegram_message(
                    ticket["telegram_id"],
                    f"✅ Обращение #{ticket_id} закрыто."
                )
            )
        except Exception as e:
            print(e)

    return redirect(
        url_for(
            "admin_support_page"
        )
    )


@app.route("/admin/notifications")
@admin_required
def notifications_page():

    conn = db()

    rows = conn.execute("""
        SELECT * FROM notifications
        ORDER BY id DESC
        LIMIT 100
    """).fetchall()

    conn.execute("""
        UPDATE notifications
        SET is_read=1
        WHERE is_read=0
    """)

    conn.commit()
    conn.close()

    return render_template_string(
        BASE_STYLE + """
        <div class="nav">
            <div class="logo">🌙 Lunevia</div>
            <a href="/admin">Главная</a>
            <a href="/admin/orders">Заказы</a>
            <a href="/admin/support">Поддержка</a>
            <a href="/admin/notifications">Уведомления</a>
            <a href="/admin/logout">Выйти</a>
        </div>

        <div class="container">

        <h1>🔔 Уведомления</h1>

        {% for n in rows %}

        <div class="card">

            <h3>{{ n.title }}</h3>

            <p>{{ n.body }}</p>

            <small>
                {{ n.created_at }}
            </small>

        </div>

        {% endfor %}

        </div>
        """,
        rows=rows
    )


# =========================================================
# CALLBACK ROUTER
# =========================================================

async def button_handler(update, context):

    query = update.callback_query
    data = query.data

    if data == "lang_ru":
        await query.answer()

        save_user(query.from_user)

        await query.edit_message_text(
            "🇷🇺 Язык: Русский\n\n"
            "🏠 Главное меню",
            reply_markup=main_menu()
        )

    elif data == "lang_uk":
        await query.answer()

        save_user(query.from_user)

        await query.edit_message_text(
            "🇺🇦 Мова: Українська\n\n"
            "🏠 Головне меню",
            reply_markup=main_menu()
        )

    elif data == "menu":
        await show_menu(update, context)

    elif data == "create_site":
        await create_site(update, context)

    elif data.startswith("type_"):
        await choose_type(update, context)

    elif data.startswith("tariff_"):
        await choose_tariff(update, context)

    elif data.startswith("photos_"):
        await choose_photos(update, context)

    elif data.startswith("design_"):
        await select_design(update, context)

    elif data == "confirm_order":
        await confirm_order(update, context)

    elif data.startswith("paid_"):
        await paid_button(update, context)

    elif data.startswith("pay_ok_") or data.startswith("pay_no_"):
        await payment_action(update, context)

    elif data.startswith("status_"):
        await admin_status_button(update, context)

    elif data == "my_orders":
        await my_orders(update, context)

    elif data.startswith("user_order_"):
        await user_order(update, context)

    elif data == "support":
        await support(update, context)

    elif data == "prices":
        await prices(update, context)

    elif data == "examples":
        await examples(update, context)

    elif data == "about":
        await about(update, context)

    elif data == "admin_orders":
        await admin_orders_button(update, context)

    elif data.startswith("admin_order_"):
        await admin_order_button(update, context)


# =========================================================
# FLASK SERVER
# =========================================================

def run_web():
    print(
        f"🌐 Lunevia Admin запущен: порт {PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не указан в .env")
        return

    print("🤖 Lunevia Bot запускается...")

    threading.Thread(
        target=run_web,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel
        )
    )

    application.add_handler(
        CommandHandler(
            "done",
            done_photos
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_receipt
        ),
        group=1
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        ),
        group=2
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_order_text
        )
    )

    print("✅ Lunevia Bot запущен!")
    print(f"🌐 Admin: http://0.0.0.0:{PORT}/admin")

    application.run_polling()


if __name__ == "__main__":
    main()
