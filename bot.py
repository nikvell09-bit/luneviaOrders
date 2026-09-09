import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PAYMENT_DETAILS = os.getenv("PAYMENT_DETAILS", "Реквизиты оплаты пока не указаны. Добавьте PAYMENT_DETAILS в .env")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@LuneviaSupport")
DB_FILE = "lunevia_orders.db"

PRICE_MINI = 299
PRICE_LOVE = 499
PRICE_PREMIUM = 899



# =========================================================
# БАЗА ЗАКАЗОВ
# =========================================================

def db_connect():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = db_connect()
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

    conn.commit()
    conn.close()


def create_order(user, data):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders (
            telegram_id, username, language, site_type, tariff, price,
            recipient_name, event_date, custom_text, photo_count, design,
            status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_payment', ?)
    """, (
        user.id,
        user.username or "",
        data.get("lang", "ru"),
        data.get("type", ""),
        data.get("tariff", ""),
        data.get("price", 0),
        data.get("recipient_name", ""),
        data.get("date", ""),
        data.get("custom_text", ""),
        data.get("photo_count", 0),
        data.get("design", ""),
        datetime.now().isoformat(timespec="seconds"),
    ))

    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id


def get_order(order_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_user_orders(telegram_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, tariff, price, status, created_at FROM orders "
        "WHERE telegram_id = ? ORDER BY id DESC",
        (telegram_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def set_receipt(order_id, file_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE orders SET receipt_file_id = ?, status = 'payment_review' WHERE id = ?",
        (file_id, order_id)
    )
    conn.commit()
    conn.close()


def set_status(order_id, status):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE orders SET status = ? WHERE id = ?",
        (status, order_id)
    )
    conn.commit()
    conn.close()


def status_text(context, status):
    if lang(context) == "uk":
        return {
            "awaiting_payment": "🟡 Очікує оплати",
            "payment_review": "🟠 Перевірка оплати",
            "paid": "🟢 Оплачено",
            "in_progress": "🔵 У процесі",
            "ready": "🟢 Готово",
            "payment_rejected": "🔴 Оплату не підтверджено",
            "cancelled": "⚫ Скасовано",
        }.get(status, status)
    return {
        "awaiting_payment": "🟡 Ожидает оплаты",
        "payment_review": "🟠 Проверка оплаты",
        "paid": "🟢 Оплачено",
        "in_progress": "🔵 В процессе",
        "ready": "🟢 Готово",
        "payment_rejected": "🔴 Оплата не подтверждена",
        "cancelled": "⚫ Отменено",
    }.get(status, status)


# =========================================================
# ЯЗЫКИ
# =========================================================

def lang(context):
    return context.user_data.get("lang", "ru")


def tr(context, ru, uk):
    return uk if lang(context) == "uk" else ru


def language_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
            InlineKeyboardButton("Русский", callback_data="lang_ru"),
        ]
    ])


async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["lang"] = "uk" if query.data == "lang_uk" else "ru"

    await show_main_menu(query, context)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Не стираем уже выбранный язык.
    selected_lang = context.user_data.get("lang")
    context.user_data.clear()

    if selected_lang:
        context.user_data["lang"] = selected_lang
        await update.message.reply_text(
            tr(
                context,
                "💙 <b>Добро пожаловать в Lunevia!</b>\n\n"
                "Создай особенный сайт для человека, который тебе дорог.\n\n"
                "✨ Персональный дизайн\n"
                "💌 Твой текст\n"
                "📸 Фотографии\n"
                "🎁 Интерактивные элементы\n"
                "❤️ Красивые анимации\n\n"
                "Выбери, что хочешь сделать:",
                "💙 <b>Ласкаво просимо до Lunevia!</b>\n\n"
                "Створи особливий сайт для людини, яка тобі дорога.\n\n"
                "✨ Персональний дизайн\n"
                "💌 Твій текст\n"
                "📸 Фотографії\n"
                "🎁 Інтерактивні елементи\n"
                "❤️ Красиві анімації\n\n"
                "Обери, що хочеш зробити:",
            ),
            parse_mode="HTML",
            reply_markup=main_menu(context),
        )
        return

    await update.message.reply_text(
        "🌐 <b>Выбери язык / Обери мову</b>",
        parse_mode="HTML",
        reply_markup=language_keyboard(),
    )


# =========================================================
# ГЛАВНОЕ МЕНЮ
# =========================================================

def main_menu(context):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            tr(context, "💌 Создать сайт", "💌 Створити сайт"),
            callback_data="create"
        )],
        [
            InlineKeyboardButton(
                tr(context, "👀 Примеры", "👀 Приклади"),
                callback_data="examples"
            ),
            InlineKeyboardButton(
                tr(context, "💰 Цены", "💰 Ціни"),
                callback_data="prices"
            ),
        ],
        [InlineKeyboardButton(
            tr(context, "📖 Подробное описание", "📖 Детальний опис"),
            callback_data="description"
        )],
        [InlineKeyboardButton(
            tr(context, "📦 Мои заказы", "📦 Мої замовлення"),
            callback_data="orders"
        )],
        [InlineKeyboardButton(
            tr(context, "🌐 Сменить язык", "🌐 Змінити мову"),
            callback_data="language"
        )],
    ])


async def show_main_menu(query, context):
    await query.edit_message_text(
        tr(
            context,
            "💙 <b>Добро пожаловать в Lunevia!</b>\n\n"
            "Создай особенный сайт для человека, который тебе дорог.\n\n"
            "✨ Персональный дизайн\n"
            "💌 Твой текст\n"
            "📸 Фотографии\n"
            "🎁 Интерактивные элементы\n"
            "❤️ Красивые анимации\n\n"
            "Выбери, что хочешь сделать:",
            "💙 <b>Ласкаво просимо до Lunevia!</b>\n\n"
            "Створи особливий сайт для людини, яка тобі дорога.\n\n"
            "✨ Персональний дизайн\n"
            "💌 Твій текст\n"
            "📸 Фотографії\n"
            "🎁 Інтерактивні елементи\n"
            "❤️ Красиві анімації\n\n"
            "Обери, що хочеш зробити:",
        ),
        parse_mode="HTML",
        reply_markup=main_menu(context),
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_lang = context.user_data.get("lang", "ru")
    context.user_data.clear()
    context.user_data["lang"] = current_lang

    await show_main_menu(query, context)


# =========================================================
# СОЗДАНИЕ САЙТА — ТИП
# =========================================================

async def start_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton(
            tr(context, "💙 Свидание", "💙 Побачення"),
            callback_data="type_date"
        )],
        [InlineKeyboardButton(
            tr(context, "🎂 День рождения", "🎂 День народження"),
            callback_data="type_birthday"
        )],
        [InlineKeyboardButton(
            tr(context, "💍 Предложение", "💍 Пропозиція"),
            callback_data="type_proposal"
        )],
        [InlineKeyboardButton(
            tr(context, "💌 Годовщина", "💌 Річниця"),
            callback_data="type_anniversary"
        )],
        [InlineKeyboardButton(
            tr(context, "🎁 Подарок", "🎁 Подарунок"),
            callback_data="type_gift"
        )],
        [InlineKeyboardButton(
            tr(context, "⬅️ Назад", "⬅️ Назад"),
            callback_data="menu"
        )],
    ]

    context.user_data["step"] = "type"

    await query.edit_message_text(
        tr(
            context,
            "💌 <b>Создание сайта</b>\n\n"
            "Для начала выбери, для какого события нужен сайт:",
            "💌 <b>Створення сайту</b>\n\n"
            "Для початку обери, для якої події потрібен сайт:",
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    types_ru = {
        "type_date": "💙 Свидание",
        "type_birthday": "🎂 День рождения",
        "type_proposal": "💍 Предложение",
        "type_anniversary": "💌 Годовщина",
        "type_gift": "🎁 Подарок",
    }

    types_uk = {
        "type_date": "💙 Побачення",
        "type_birthday": "🎂 День народження",
        "type_proposal": "💍 Пропозиція",
        "type_anniversary": "💌 Річниця",
        "type_gift": "🎁 Подарунок",
    }

    selected = (types_uk if lang(context) == "uk" else types_ru).get(query.data)
    context.user_data["type"] = selected

    await show_tariffs(query, context)


# =========================================================
# ТАРИФЫ
# =========================================================

async def show_tariffs(query, context):
    if lang(context) == "uk":
        text = (
            "💰 <b>Обери тариф</b>\n\n"
            f"🌙 <b>MINI — {PRICE_MINI} грн</b>\n"
            "• персональний текст\n"
            "• красивий дизайн\n"
            "• базові анімації\n"
            "• адаптація під телефон\n\n"
            f"💙 <b>LOVE — {PRICE_LOVE} грн</b>\n"
            "• усе з MINI\n"
            "• фотографії\n"
            "• інтерактивні кнопки\n"
            "• вибір ресторану або варіанта\n"
            "• додаткові анімації\n\n"
            f"👑 <b>PREMIUM — {PRICE_PREMIUM} грн</b>\n"
            "• усе з LOVE\n"
            "• індивідуальна структура\n"
            "• унікальний дизайн\n"
            "• більше інтерактивних елементів\n"
            "• додаткові функції\n\n"
            "💙 Кожен сайт створюється індивідуально."
        )
        back = "⬅️ Назад"
    else:
        text = (
            "💰 <b>Выбери тариф</b>\n\n"
            f"🌙 <b>MINI — {PRICE_MINI} грн</b>\n"
            "• персональный текст\n"
            "• красивый дизайн\n"
            "• базовые анимации\n"
            "• адаптация под телефон\n\n"
            f"💙 <b>LOVE — {PRICE_LOVE} грн</b>\n"
            "• всё из MINI\n"
            "• фотографии\n"
            "• интерактивные кнопки\n"
            "• выбор ресторана или варианта\n"
            "• дополнительные анимации\n\n"
            f"👑 <b>PREMIUM — {PRICE_PREMIUM} грн</b>\n"
            "• всё из LOVE\n"
            "• индивидуальная структура\n"
            "• уникальный дизайн\n"
            "• больше интерактивных элементов\n"
            "• дополнительные функции\n\n"
            "💙 Каждый сайт создаётся индивидуально."
        )
        back = "⬅️ Назад"

    keyboard = [
        [InlineKeyboardButton(f"🌙 MINI — {PRICE_MINI} грн", callback_data="tariff_mini")],
        [InlineKeyboardButton(f"💙 LOVE — {PRICE_LOVE} грн", callback_data="tariff_love")],
        [InlineKeyboardButton(f"👑 PREMIUM — {PRICE_PREMIUM} грн", callback_data="tariff_premium")],
        [InlineKeyboardButton(back, callback_data="back_type")],
    ]

    context.user_data["step"] = "tariff"

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def choose_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    tariffs = {
        "tariff_mini": ("🌙 MINI", PRICE_MINI),
        "tariff_love": ("💙 LOVE", PRICE_LOVE),
        "tariff_premium": ("👑 PREMIUM", PRICE_PREMIUM),
    }

    tariff_name, price = tariffs[query.data]
    context.user_data["tariff"] = tariff_name
    context.user_data["price"] = price
    context.user_data["step"] = "recipient_name"

    await query.edit_message_text(
        tr(
            context,
            f"✅ Выбран тариф: <b>{tariff_name}</b>\n"
            f"💰 Стоимость: <b>{price} грн</b>\n\n"
            "👤 <b>Для кого создаём сайт?</b>\n\n"
            "Напиши имя человека.\n\n"
            "Например:\n"
            "<i>Настя</i>",
            f"✅ Обрано тариф: <b>{tariff_name}</b>\n"
            f"💰 Вартість: <b>{price} грн</b>\n\n"
            "👤 <b>Для кого створюємо сайт?</b>\n\n"
            "Напиши ім'я людини.\n\n"
            "Наприклад:\n"
            "<i>Настя</i>",
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                tr(context, "⬅️ Назад", "⬅️ Назад"),
                callback_data="back_tariff"
            )]
        ]),
    )


# =========================================================
# ИМЯ → ДАТА
# =========================================================

async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["recipient_name"] = update.message.text.strip()
    context.user_data["step"] = "date"

    await update.message.reply_text(
        tr(
            context,
            "📅 <b>На какую дату создаём сайт?</b>\n\n"
            "Напиши дату.\n\n"
            "Например:\n"
            "<i>18 сентября</i>\n\n"
            "Если дата не важна — напиши:\n"
            "<i>Без даты</i>",
            "📅 <b>На яку дату створюємо сайт?</b>\n\n"
            "Напиши дату.\n\n"
            "Наприклад:\n"
            "<i>18 вересня</i>\n\n"
            "Якщо дата не важлива — напиши:\n"
            "<i>Без дати</i>",
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_name")]
        ]),
    )


# =========================================================
# ДАТА → ТЕКСТ
# =========================================================

async def ask_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text.strip()
    context.user_data["step"] = "text"

    await update.message.reply_text(
        tr(
            context,
            "💌 <b>Теперь самое важное — текст.</b>\n\n"
            "Напиши, что ты хочешь видеть на сайте.\n\n"
            "Это может быть:\n"
            "❤️ романтическое письмо\n"
            "🎂 поздравление\n"
            "💍 текст предложения\n"
            "💌 личное послание\n"
            "🎁 описание подарка\n\n"
            "Например:\n\n"
            "<i>«Настя, этот день я хочу провести только "
            "с тобой. Я подготовил для нас маленькое "
            "приключение ❤️»</i>",
            "💌 <b>Тепер найважливіше — текст.</b>\n\n"
            "Напиши, що ти хочеш бачити на сайті.\n\n"
            "Це може бути:\n"
            "❤️ романтичний лист\n"
            "🎂 привітання\n"
            "💍 текст пропозиції\n"
            "💌 особисте повідомлення\n"
            "🎁 опис подарунка\n\n"
            "Наприклад:\n\n"
            "<i>«Настя, цей день я хочу провести тільки "
            "з тобою. Я підготував для нас маленьку "
            "приключу ❤️»</i>",
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_date")]
        ]),
    )


# =========================================================
# ТЕКСТ → ФОТО
# =========================================================

async def ask_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["custom_text"] = update.message.text.strip()
    context.user_data["step"] = "photos"

    keyboard = [
        [InlineKeyboardButton(
            tr(context, "📸 Да, нужны фотографии", "📸 Так, потрібні фотографії"),
            callback_data="photos_yes"
        )],
        [InlineKeyboardButton(
            tr(context, "🚫 Нет фотографий", "🚫 Без фотографій"),
            callback_data="photos_no"
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_text")],
    ]

    await update.message.reply_text(
        tr(
            context,
            "📸 <b>Добавим фотографии?</b>\n\n"
            "Если выберешь «Да», сможешь отправить несколько фотографий.\n\n"
            "Их можно будет красиво разместить на сайте.",
            "📸 <b>Додамо фотографії?</b>\n\n"
            "Якщо обереш «Так», зможеш надіслати кілька фотографій.\n\n"
            "Їх можна буде красиво розмістити на сайті.",
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# ФОТО
# =========================================================

async def photos_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "photos_yes":
        context.user_data["photos"] = True
        context.user_data["photo_count"] = 0
        context.user_data["step"] = "upload_photos"

        await query.edit_message_text(
            tr(
                context,
                "📸 <b>Отправляй фотографии</b>\n\n"
                "Отправляй их по одной.\n\n"
                "Когда закончишь — напиши:\n"
                "<b>/done</b>\n\n"
                "Можно отправить несколько фотографий.",
                "📸 <b>Надсилай фотографії</b>\n\n"
                "Надсилай їх по одній.\n\n"
                "Коли закінчиш — напиши:\n"
                "<b>/done</b>\n\n"
                "Можна надіслати кілька фотографій.",
            ),
            parse_mode="HTML",
        )
    else:
        context.user_data["photos"] = False
        context.user_data["photo_count"] = 0
        await show_designs(query, context)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "upload_photos":
        context.user_data["photo_count"] = context.user_data.get("photo_count", 0) + 1
        count = context.user_data["photo_count"]

        await update.message.reply_text(
            tr(
                context,
                f"📸 Фото получено!\n\nЗагружено: <b>{count}</b>\n\n"
                "Можешь отправить ещё или написать <b>/done</b>.",
                f"📸 Фото отримано!\n\nЗавантажено: <b>{count}</b>\n\n"
                "Можеш надіслати ще або написати <b>/done</b>.",
            ),
            parse_mode="HTML",
        )
        return

    if step == "payment_receipt":
        order_id = context.user_data.get("order_id")

        if not order_id:
            await update.message.reply_text(
                tr(context, "Не найден текущий заказ. Открой /start.", "Не знайдено поточне замовлення. Відкрий /start.")
            )
            return

        photo = update.message.photo[-1]
        set_receipt(order_id, photo.file_id)
        context.user_data["step"] = "payment_review"

        await update.message.reply_text(
            tr(
                context,
                f"⏳ <b>Квитанция получена!</b>\n\n"
                f"Заказ #{order_id} отправлен на проверку.\n"
                "Ожидайте подтверждения оплаты в течение 15 минут.\n\n"
                "Мы проверим поступление средств и сообщим вам результат здесь. 💙",
                f"⏳ <b>Квитанцію отримано!</b>\n\n"
                f"Замовлення #{order_id} надіслано на перевірку.\n"
                "Очікуйте підтвердження оплати протягом 15 хвилин.\n\n"
                "Ми перевіримо надходження коштів і повідомимо вам результат тут. 💙",
            ),
            parse_mode="HTML",
        )

        row = get_order(order_id)
        if row and ADMIN_ID:
            username = f"@{row[2]}" if row[2] else "без username"
            admin_text = (
                f"🧾 <b>НОВАЯ КВИТАНЦИЯ — ЗАКАЗ #{order_id}</b>\n\n"
                f"👤 Клиент: {username}\n"
                f"🆔 Telegram ID: <code>{row[1]}</code>\n"
                f"🎯 Тип: {row[4]}\n"
                f"💎 Тариф: {row[5]}\n"
                f"💰 Сумма: {row[6]} грн\n"
                f"👤 Для кого: {row[7]}\n"
                f"📅 Дата: {row[8]}\n"
                f"📸 Фото на сайте: {row[10]}\n"
                f"🎨 Дизайн: {row[11]}\n\n"
                f"📌 Статус: 🟠 Проверка оплаты"
            )

            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo.file_id,
                caption=admin_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ Оплата подтверждена",
                            callback_data=f"pay_ok_{order_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Оплата не найдена",
                            callback_data=f"pay_no_{order_id}"
                        )
                    ],
                ]),
            )
        return


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") != "upload_photos":
        return

    count = context.user_data.get("photo_count", 0)

    if count == 0:
        await update.message.reply_text(
            tr(
                context,
                "📸 Ты ещё не отправил фотографии.\n\nОтправь хотя бы одну фотографию.",
                "📸 Ти ще не надіслав фотографій.\n\nНадішли хоча б одну фотографію.",
            )
        )
        return

    await update.message.reply_text(
        tr(
            context,
            f"✅ Отлично! Получено фотографий: {count}",
            f"✅ Чудово! Отримано фотографій: {count}",
        )
    )

    await show_designs_message(update, context)


# =========================================================
# ДИЗАЙНЫ
# =========================================================

def design_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💙 Love", callback_data="design_love")],
        [InlineKeyboardButton("💜 Purple", callback_data="design_purple")],
        [InlineKeyboardButton("🌹 Romantic", callback_data="design_romantic")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_photos")],
    ])


async def show_designs_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["step"] = "design"

    await update.message.reply_text(
        tr(
            context,
            "🎨 <b>Выбери дизайн сайта</b>\n\n"
            "💙 <b>Love</b> — нежный и романтичный\n"
            "💜 <b>Purple</b> — фиолетовый стиль\n"
            "🌹 <b>Romantic</b> — атмосферный дизайн",
            "🎨 <b>Обери дизайн сайту</b>\n\n"
            "💙 <b>Love</b> — ніжний і романтичний\n"
            "💜 <b>Purple</b> — фіолетовий стиль\n"
            "🌹 <b>Romantic</b> — атмосферний дизайн",
        ),
        parse_mode="HTML",
        reply_markup=design_keyboard(),
    )


async def show_designs(query, context):
    context.user_data["step"] = "design"

    await query.edit_message_text(
        tr(
            context,
            "🎨 <b>Выбери дизайн сайта</b>\n\n"
            "💙 <b>Love</b> — нежный и романтичный\n"
            "💜 <b>Purple</b> — фиолетовый стиль\n"
            "🌹 <b>Romantic</b> — атмосферный дизайн",
            "🎨 <b>Обери дизайн сайту</b>\n\n"
            "💙 <b>Love</b> — ніжний і романтичний\n"
            "💜 <b>Purple</b> — фіолетовий стиль\n"
            "🌹 <b>Romantic</b> — атмосферний дизайн",
        ),
        parse_mode="HTML",
        reply_markup=design_keyboard(),
    )


async def choose_design(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    designs_ru = {
        "design_love": "💙 Love",
        "design_purple": "💜 Purple",
        "design_romantic": "🌹 Romantic",
    }

    designs_uk = {
        "design_love": "💙 Love",
        "design_purple": "💜 Purple",
        "design_romantic": "🌹 Romantic",
    }

    context.user_data["design"] = (
        designs_uk if lang(context) == "uk" else designs_ru
    )[query.data]

    await show_summary(query, context)


# =========================================================
# ИТОГ
# =========================================================

async def show_summary(query, context):
    data = context.user_data
    photo_count = data.get("photo_count", 0)

    if lang(context) == "uk":
        text = (
            "📋 <b>Перевір своє замовлення</b>\n\n"
            f"🎯 Тип: <b>{data.get('type')}</b>\n"
            f"💎 Тариф: <b>{data.get('tariff')}</b>\n"
            f"💰 Ціна: <b>{data.get('price')} грн</b>\n\n"
            f"👤 Для кого: <b>{data.get('recipient_name')}</b>\n"
            f"📅 Дата: <b>{data.get('date')}</b>\n"
            f"📸 Фотографій: <b>{photo_count}</b>\n"
            f"🎨 Дизайн: <b>{data.get('design')}</b>\n\n"
            "💌 Текст додано.\n\n"
            "Якщо все правильно — натисни «Підтвердити замовлення»."
        )
        confirm = "✅ Підтвердити замовлення"
        cancel = "❌ Скасувати"
    else:
        text = (
            "📋 <b>Проверь свой заказ</b>\n\n"
            f"🎯 Тип: <b>{data.get('type')}</b>\n"
            f"💎 Тариф: <b>{data.get('tariff')}</b>\n"
            f"💰 Цена: <b>{data.get('price')} грн</b>\n\n"
            f"👤 Для кого: <b>{data.get('recipient_name')}</b>\n"
            f"📅 Дата: <b>{data.get('date')}</b>\n"
            f"📸 Фотографий: <b>{photo_count}</b>\n"
            f"🎨 Дизайн: <b>{data.get('design')}</b>\n\n"
            "💌 Текст добавлен.\n\n"
            "Если всё правильно — нажми «Подтвердить заказ»."
        )
        confirm = "✅ Подтвердить заказ"
        cancel = "❌ Отменить"

    keyboard = [
        [InlineKeyboardButton(confirm, callback_data="confirm_order")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_design")],
        [InlineKeyboardButton(cancel, callback_data="menu")],
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# ПОДТВЕРЖДЕНИЕ
# =========================================================

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = create_order(query.from_user, context.user_data)
    context.user_data["order_id"] = order_id
    context.user_data["step"] = "awaiting_payment"

    if lang(context) == "uk":
        text = (
            f"🎉 <b>Замовлення #{order_id} створено!</b>\n\n"
            f"💎 Тариф: <b>{context.user_data.get('tariff')}</b>\n"
            f"💰 До сплати: <b>{context.user_data.get('price')} грн</b>\n\n"
            "💳 <b>Реквізити для оплати:</b>\n"
            f"<code>{PAYMENT_DETAILS}</code>\n\n"
            "Після оплати натисни кнопку «Я оплатив(ла)».\n"
            "Потім бот попросить надіслати фото квитанції."
        )
        paid_btn = "💳 Я оплатив(ла)"
    else:
        text = (
            f"🎉 <b>Заказ #{order_id} создан!</b>\n\n"
            f"💎 Тариф: <b>{context.user_data.get('tariff')}</b>\n"
            f"💰 К оплате: <b>{context.user_data.get('price')} грн</b>\n\n"
            "💳 <b>Реквизиты для оплаты:</b>\n"
            f"<code>{PAYMENT_DETAILS}</code>\n\n"
            "После оплаты нажми кнопку «Я оплатил(а)».\n"
            "Затем бот попросит отправить фото квитанции."
        )
        paid_btn = "💳 Я оплатил(а)"

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(paid_btn, callback_data=f"paid_{order_id}")],
            [InlineKeyboardButton(
                tr(context, "📦 Мои заказы", "📦 Мої замовлення"),
                callback_data="orders"
            )],
        ]),
    )


# =========================================================
# ПРИМЕРЫ
# =========================================================

async def examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = tr(
        context,
        "👀 <b>Примеры сайтов Lunevia</b>\n\n"
        "💙 <b>Свидание</b>\n\n"
        "17:00 — прогулка\n"
        "18:00 — прогулка у реки\n"
        "19:00 — ужин\n"
        "20:30 — прогулка по центру\n\n"
        "После этого появляется:\n\n"
        "🍽️ <b>«Где ты хочешь поужинать?»</b>\n\n"
        "🔘 Rancho Grill\n"
        "🔘 The Italian Connection\n"
        "🔘 Tapas Lounge\n\n"
        "После выбора владелец сайта получает уведомление в Telegram. 💙\n\n"
        "Также можно сделать:\n"
        "🎂 поздравление\n"
        "💍 предложение\n"
        "💌 годовщину\n"
        "🎁 подарок\n"
        "📸 фотогалерею\n"
        "💬 вопросы и ответы\n"
        "❤️ интерактивные кнопки",
        "👀 <b>Приклади сайтів Lunevia</b>\n\n"
        "💙 <b>Побачення</b>\n\n"
        "17:00 — прогулянка\n"
        "18:00 — прогулянка біля річки\n"
        "19:00 — вечеря\n"
        "20:30 — прогулянка центром\n\n"
        "Після цього з'являється:\n\n"
        "🍽️ <b>«Де ти хочеш повечеряти?»</b>\n\n"
        "🔘 Rancho Grill\n"
        "🔘 The Italian Connection\n"
        "🔘 Tapas Lounge\n\n"
        "Після вибору власник сайту отримує сповіщення в Telegram. 💙\n\n"
        "Також можна зробити:\n"
        "🎂 привітання\n"
        "💍 пропозицію\n"
        "💌 річницю\n"
        "🎁 подарунок\n"
        "📸 фотогалерею\n"
        "💬 питання та відповіді\n"
        "❤️ інтерактивні кнопки",
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")]
        ]),
    )


# =========================================================
# ЦЕНЫ
# =========================================================

async def prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = tr(
        context,
        "💰 <b>Тарифы Lunevia</b>\n\n"
        f"🌙 <b>MINI — {PRICE_MINI} грн</b>\n"
        "Для простого красивого сайта.\n\n"
        "• персональный текст\n"
        "• базовый дизайн\n"
        "• анимации\n"
        "• адаптация под телефон\n\n"
        f"💙 <b>LOVE — {PRICE_LOVE} грн</b>\n"
        "Для полноценного романтического сайта.\n\n"
        "• всё из MINI\n"
        "• фотографии\n"
        "• интерактивные кнопки\n"
        "• выбор ресторана\n"
        "• дополнительные анимации\n\n"
        f"👑 <b>PREMIUM — {PRICE_PREMIUM} грн</b>\n"
        "Максимальная персонализация.\n\n"
        "• всё из LOVE\n"
        "• индивидуальная структура\n"
        "• уникальный дизайн\n"
        "• больше интерактивных элементов\n"
        "• дополнительные функции",
        "💰 <b>Тарифи Lunevia</b>\n\n"
        f"🌙 <b>MINI — {PRICE_MINI} грн</b>\n"
        "Для простого красивого сайту.\n\n"
        "• персональний текст\n"
        "• базовий дизайн\n"
        "• анімації\n"
        "• адаптація під телефон\n\n"
        f"💙 <b>LOVE — {PRICE_LOVE} грн</b>\n"
        "Для повноцінного романтичного сайту.\n\n"
        "• усе з MINI\n"
        "• фотографії\n"
        "• інтерактивні кнопки\n"
        "• вибір ресторану\n"
        "• додаткові анімації\n\n"
        f"👑 <b>PREMIUM — {PRICE_PREMIUM} грн</b>\n"
        "Максимальна персоналізація.\n\n"
        "• усе з LOVE\n"
        "• індивідуальна структура\n"
        "• унікальний дизайн\n"
        "• більше інтерактивних елементів\n"
        "• додаткові функції",
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                tr(context, "💌 Заказать сайт", "💌 Замовити сайт"),
                callback_data="create"
            )],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]),
    )


# =========================================================
# ПОДРОБНОЕ ОПИСАНИЕ
# =========================================================

async def description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = tr(
        context,
        "📖 <b>Что можно сделать на сайте?</b>\n\n"
        "Lunevia — это не просто страница с текстом. "
        "Мы создаём небольшой персональный сайт под конкретного человека и событие. 💙\n\n"
        "🌹 <b>Романтическая история</b>\n"
        "Ваш текст, фотографии, красивые переходы и атмосферный дизайн.\n\n"
        "📅 <b>План свидания</b>\n"
        "Можно показать вечер по времени.\n\n"
        "🍽️ <b>Выбор ресторана</b>\n"
        "Можно предложить несколько вариантов и дать человеку выбрать.\n\n"
        "🎁 <b>Выбор подарка</b>\n"
        "Можно предложить несколько вариантов и узнать, что человек хочет.\n\n"
        "💬 <b>Вопросы</b>\n"
        "Например: «Ты согласна провести этот вечер со мной?»\n\n"
        "📸 <b>Фотографии</b>\n"
        "Можно добавить ваши общие фотографии.\n\n"
        "🎵 <b>Музыка</b>\n"
        "Можно добавить атмосферное музыкальное сопровождение.\n\n"
        "✨ <b>Анимации</b>\n"
        "Плавные появления текста, фотографий и кнопок.\n\n"
        "📱 <b>Для телефона</b>\n"
        "Сайт адаптирован под смартфоны.\n\n"
        "💙 А в конце можно сделать специальное финальное послание.",
        "📖 <b>Що можна зробити на сайті?</b>\n\n"
        "Lunevia — це не просто сторінка з текстом. "
        "Ми створюємо невеликий персональний сайт під конкретну людину та подію. 💙\n\n"
        "🌹 <b>Романтична історія</b>\n"
        "Ваш текст, фотографії, красиві переходи та атмосферний дизайн.\n\n"
        "📅 <b>План побачення</b>\n"
        "Можна показати вечір за часом.\n\n"
        "🍽️ <b>Вибір ресторану</b>\n"
        "Можна запропонувати кілька варіантів і дати людині обрати.\n\n"
        "🎁 <b>Вибір подарунка</b>\n"
        "Можна запропонувати кілька варіантів і дізнатися, що людина хоче.\n\n"
        "💬 <b>Питання</b>\n"
        "Наприклад: «Ти згодна провести цей вечір зі мною?»\n\n"
        "📸 <b>Фотографії</b>\n"
        "Можна додати ваші спільні фотографії.\n\n"
        "🎵 <b>Музика</b>\n"
        "Можна додати атмосферний музичний супровід.\n\n"
        "✨ <b>Анімації</b>\n"
        "Плавна поява тексту, фотографій та кнопок.\n\n"
        "📱 <b>Для телефону</b>\n"
        "Сайт адаптований під смартфони.\n\n"
        "💙 А в кінці можна зробити спеціальне фінальне послання.",
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                tr(context, "💌 Создать сайт", "💌 Створити сайт"),
                callback_data="create"
            )],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]),
    )


# =========================================================
# МОИ ЗАКАЗЫ
# =========================================================

async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    rows = get_user_orders(query.from_user.id)

    if not rows:
        text = tr(
            context,
            "📦 <b>Мои заказы</b>\n\nУ тебя пока нет заказов.",
            "📦 <b>Мої замовлення</b>\n\nУ тебе поки немає замовлень.",
        )
        keyboard = [
            [InlineKeyboardButton(
                tr(context, "💌 Создать сайт", "💌 Створити сайт"),
                callback_data="create"
            )],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]
    else:
        lines = [tr(context, "📦 <b>МОИ ЗАКАЗЫ</b>\n", "📦 <b>МОЇ ЗАМОВЛЕННЯ</b>\n")]
        keyboard = []

        for order_id, tariff, price, status, created_at in rows:
            lines.append(
                f"#{order_id} — <b>{tariff}</b> — {price} грн\n"
                f"{status_text(context, status)}"
            )
            keyboard.append([
                InlineKeyboardButton(
                    tr(context, f"📄 Заказ #{order_id}", f"📄 Замовлення #{order_id}"),
                    callback_data=f"order_{order_id}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton("⬅️ Назад", callback_data="menu")
        ])
        text = "\n\n".join(lines)

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[1])
    row = get_order(order_id)

    if not row or row[1] != query.from_user.id:
        await query.answer(
            tr(context, "Заказ не найден.", "Замовлення не знайдено."),
            show_alert=True
        )
        return

    text = tr(
        context,
        f"📄 <b>Заказ #{row[0]}</b>\n\n"
        f"🎯 Тип: <b>{row[4]}</b>\n"
        f"💎 Тариф: <b>{row[5]}</b>\n"
        f"💰 Цена: <b>{row[6]} грн</b>\n"
        f"👤 Для кого: <b>{row[7]}</b>\n"
        f"📅 Дата: <b>{row[8]}</b>\n"
        f"📸 Фотографий: <b>{row[10]}</b>\n"
        f"🎨 Дизайн: <b>{row[11]}</b>\n\n"
        f"📌 Статус: <b>{status_text(context, row[12])}</b>",
        f"📄 <b>Замовлення #{row[0]}</b>\n\n"
        f"🎯 Тип: <b>{row[4]}</b>\n"
        f"💎 Тариф: <b>{row[5]}</b>\n"
        f"💰 Ціна: <b>{row[6]} грн</b>\n"
        f"👤 Для кого: <b>{row[7]}</b>\n"
        f"📅 Дата: <b>{row[8]}</b>\n"
        f"📸 Фотографій: <b>{row[10]}</b>\n"
        f"🎨 Дизайн: <b>{row[11]}</b>\n\n"
        f"📌 Статус: <b>{status_text(context, row[12])}</b>",
    )

    keyboard = []

    if row[12] in ("awaiting_payment", "payment_rejected"):
        keyboard.append([
            InlineKeyboardButton(
                "💳 Я оплатив(ла)",
                callback_data=f"paid_{order_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="orders")
    ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# НАЗАД
# =========================================================

async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "back_photos":
        await ask_photos_back(query, context)

    elif data == "back_design":
        await show_designs(query, context)

    elif data == "back_text":
        context.user_data["step"] = "text"
        await query.edit_message_text(
            tr(
                context,
                "💌 <b>Напиши текст для сайта</b>\n\n"
                "Можешь изменить свой текст и отправить его следующим сообщением.",
                "💌 <b>Напиши текст для сайту</b>\n\n"
                "Можеш змінити свій текст і надіслати його наступним повідомленням.",
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_date")]
            ]),
        )

    elif data == "back_date":
        context.user_data["step"] = "date"
        await query.edit_message_text(
            tr(
                context,
                "📅 <b>На какую дату создаём сайт?</b>\n\nНапиши дату.",
                "📅 <b>На яку дату створюємо сайт?</b>\n\nНапиши дату.",
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_name")]
            ]),
        )

    elif data == "back_name":
        context.user_data["step"] = "recipient_name"
        await query.edit_message_text(
            tr(
                context,
                "👤 <b>Для кого создаём сайт?</b>\n\nНапиши имя человека.",
                "👤 <b>Для кого створюємо сайт?</b>\n\nНапиши ім'я людини.",
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_tariff")]
            ]),
        )

    elif data == "back_tariff":
        await show_tariffs(query, context)

    elif data == "back_type":
        await start_order(update, context)


async def ask_photos_back(query, context):
    context.user_data["step"] = "photos"

    keyboard = [
        [InlineKeyboardButton(
            tr(context, "📸 Да, нужны фотографии", "📸 Так, потрібні фотографії"),
            callback_data="photos_yes"
        )],
        [InlineKeyboardButton(
            tr(context, "🚫 Нет фотографий", "🚫 Без фотографій"),
            callback_data="photos_no"
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_text")],
    ]

    await query.edit_message_text(
        tr(
            context,
            "📸 <b>Добавим фотографии?</b>",
            "📸 <b>Додамо фотографії?</b>",
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )



# =========================================================
# ОПЛАТА
# =========================================================

async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[1])
    row = get_order(order_id)

    if not row or row[1] != query.from_user.id:
        await query.answer(
            tr(context, "Заказ не найден.", "Замовлення не знайдено."),
            show_alert=True
        )
        return

    if row[12] not in ("awaiting_payment", "payment_rejected"):
        await query.edit_message_text(
            tr(
                context,
                f"📌 Заказ #{order_id} уже находится в статусе:\n<b>{status_text(context, row[12])}</b>",
                f"📌 Замовлення #{order_id} вже має статус:\n<b>{status_text(context, row[12])}</b>",
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="orders")]
            ]),
        )
        return

    context.user_data["order_id"] = order_id
    context.user_data["step"] = "payment_receipt"

    await query.edit_message_text(
        tr(
            context,
            f"📸 <b>Отправь фото квитанции</b>\n\n"
            f"Заказ: <b>#{order_id}</b>\n"
            "Отправь сюда скриншот или фото подтверждения оплаты.\n\n"
            "После этого мы проверим оплату вручную. 💙",
            f"📸 <b>Надішли фото квитанції</b>\n\n"
            f"Замовлення: <b>#{order_id}</b>\n"
            "Надішли сюди скриншот або фото підтвердження оплати.\n\n"
            "Після цього ми перевіримо оплату вручну. 💙",
        ),
        parse_mode="HTML",
    )


async def admin_payment_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return

    await query.answer()

    parts = query.data.split("_")
    action = parts[1]
    order_id = int(parts[2])

    row = get_order(order_id)
    if not row:
        await query.edit_message_caption(caption="❌ Заказ не найден.")
        return

    customer_id = row[1]

    if action == "ok":
        set_status(order_id, "in_progress")

        await context.bot.send_message(
            chat_id=customer_id,
            text=tr(
                context,
                f"🎉 <b>Оплата заказа #{order_id} прошла успешно!</b>\n\n"
                "Ваш сайт уже в процессе создания. 💙\n"
                "Мы сообщим вам здесь, когда он будет готов.",
                f"🎉 <b>Оплата замовлення #{order_id} пройшла успішно!</b>\n\n"
                "Ваш сайт уже в процесі створення. 💙\n"
                "Ми повідомимо вам тут, коли він буде готовий.",
            ),
            parse_mode="HTML",
        )

        await query.edit_message_caption(
            caption=f"✅ <b>Оплата заказа #{order_id} подтверждена.</b>\n\nСтатус: 🔵 В процессе",
            parse_mode="HTML",
        )

    else:
        set_status(order_id, "payment_rejected")

        await context.bot.send_message(
            chat_id=customer_id,
            text=tr(
                context,
                f"❌ <b>Оплата заказа #{order_id} не подтверждена.</b>\n\n"
                "Мы не смогли подтвердить поступление средств.\n"
                "Попробуйте оплатить ещё раз или свяжитесь с нами:\n"
                f"{SUPPORT_USERNAME}",
                f"❌ <b>Оплату замовлення #{order_id} не підтверджено.</b>\n\n"
                "Ми не змогли підтвердити надходження коштів.\n"
                "Спробуйте оплатити ще раз або зв'яжіться з нами:\n"
                f"{SUPPORT_USERNAME}",
            ),
            parse_mode="HTML",
        )

        await query.edit_message_caption(
            caption=f"❌ <b>Оплата заказа #{order_id} не найдена.</b>\n\nСтатус: 🔴 Оплата не подтверждена",
            parse_mode="HTML",
        )


# =========================================================
# CALLBACK
# =========================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "language":
        await query.answer()
        await query.edit_message_text(
            "🌐 <b>Выбери язык / Обери мову</b>",
            parse_mode="HTML",
            reply_markup=language_keyboard(),
        )

    elif data.startswith("lang_"):
        await choose_language(update, context)

    elif data == "menu":
        await menu(update, context)

    elif data == "create":
        await start_order(update, context)

    elif data.startswith("type_"):
        await choose_type(update, context)

    elif data.startswith("tariff_"):
        await choose_tariff(update, context)

    elif data in ["photos_yes", "photos_no"]:
        await photos_choice(update, context)

    elif data.startswith("design_"):
        await choose_design(update, context)

    elif data == "confirm_order":
        await confirm_order(update, context)

    elif data.startswith("paid_"):
        await paid(update, context)

    elif data.startswith("pay_ok_") or data.startswith("pay_no_"):
        await admin_payment_action(update, context)

    elif data.startswith("order_"):
        await show_order(update, context)

    elif data == "examples":
        await examples(update, context)

    elif data == "prices":
        await prices(update, context)

    elif data == "description":
        await description(update, context)

    elif data == "orders":
        await orders(update, context)

    elif data.startswith("back_"):
        await back_handler(update, context)


# =========================================================
# CANCEL
# =========================================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_lang = context.user_data.get("lang", "ru")
    context.user_data.clear()
    context.user_data["lang"] = current_lang

    await update.message.reply_text(
        tr(
            context,
            "❌ Создание заказа отменено.\n\nНажми /start, чтобы начать заново.",
            "❌ Створення замовлення скасовано.\n\nНатисни /start, щоб почати заново.",
        )
    )


# =========================================================
# ОБРАБОТКА ТЕКСТА
# =========================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "recipient_name":
        await ask_date(update, context)

    elif step == "date":
        await ask_text(update, context)

    elif step == "text":
        await ask_photos(update, context)

    else:
        await update.message.reply_text(
            tr(
                context,
                "Выбери действие через меню или нажми /start.",
                "Обери дію через меню або натисни /start.",
            )
        )


# =========================================================
# ЗАПУСК
# =========================================================

def main():
    init_db()

    if not BOT_TOKEN:
        print("❌ Не найден BOT_TOKEN в .env")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("done", done))

    application.add_handler(CallbackQueryHandler(button_handler))

    application.add_handler(
        MessageHandler(filters.PHOTO, handle_photo)
    )

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    print("💙 Lunevia Orders запущен!")
    application.run_polling()


if __name__ == "__main__":
    main()
