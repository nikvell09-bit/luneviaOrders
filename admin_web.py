
import os
import sqlite3
import urllib.parse
import urllib.request
import json
import html
from functools import wraps
from io import BytesIO

from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, flash, send_file, abort
)

app = Flask(__name__)
app.secret_key = os.getenv("ADMIN_SECRET_KEY") or os.getenv("BOT_TOKEN") or "change-this-secret"

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_FILE = os.getenv("DB_FILE", "lunevia_orders.db")


def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_chat_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            direction TEXT NOT NULL,
            message_text TEXT NOT NULL,
            username TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def e(value):
    return html.escape(str(value or ""))


def telegram_api(method, data=None):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в переменных окружения Render")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    payload = urllib.parse.urlencode(data or {}).encode("utf-8")

    req = urllib.request.Request(url, data=payload)

    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Ошибка Telegram API"))

    return result.get("result")


def send_telegram_message(chat_id, text):
    return telegram_api("sendMessage", {
        "chat_id": chat_id,
        "text": text
    })


def save_message(telegram_id, direction, message_text, username=None):
    conn = db()
    conn.execute("""
        INSERT INTO chat_messages
        (telegram_id, direction, message_text, username)
        VALUES (?, ?, ?, ?)
    """, (telegram_id, direction, message_text, username))
    conn.commit()
    conn.close()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


BASE_STYLE = """
<style>
*{box-sizing:border-box}
body{margin:0;background:#101010;color:#eee;font-family:Arial,sans-serif}
header{background:#191919;padding:18px 24px;border-bottom:1px solid #333}
header h2{margin:0;color:#e8bd69}
nav{display:flex;gap:16px;flex-wrap:wrap;margin-top:14px}
a{color:#e8bd69;text-decoration:none}
a:hover{text-decoration:underline}
main{max-width:1200px;margin:24px auto;padding:0 16px}
.card{background:#191919;border:1px solid #333;border-radius:12px;padding:18px;margin-bottom:16px}
input,textarea,select{width:100%;padding:11px;background:#101010;border:1px solid #444;color:#fff;border-radius:7px;margin:6px 0 12px}
textarea{min-height:110px;resize:vertical}
button,.btn{display:inline-block;border:0;border-radius:7px;background:#d9ad5b;color:#111;padding:10px 15px;font-weight:bold;cursor:pointer}
.btn-secondary{background:#333;color:#fff}
.btn-danger{background:#7e3030;color:#fff}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:11px;border-bottom:1px solid #333;vertical-align:top}
small,.muted{color:#aaa}
.message{padding:12px;border-radius:9px;margin:10px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.incoming{background:#252525;margin-right:12%}
.outgoing{background:#493b25;margin-left:12%}
.layout{display:grid;grid-template-columns:minmax(220px,320px) 1fr;gap:16px}
.chat-list a{display:block;padding:12px;border-bottom:1px solid #333}
.flash{padding:12px;background:#332b1c;border-radius:8px;margin-bottom:12px}
@media(max-width:700px){.layout{grid-template-columns:1fr}table{font-size:13px}th,td{padding:7px}}
</style>
"""


def page(title, content):
    return render_template_string("""
    <!doctype html>
    <html lang="ru">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>{{ title }} — Lunevia</title>
      """ + BASE_STYLE + """
    </head>
    <body>
      <header>
        <h2>♡ Lunevia Admin</h2>
        {% if logged_in %}
        <nav>
          <a href="{{ url_for('dashboard') }}">Главная</a>
          <a href="{{ url_for('orders') }}">Заказы</a>
          <a href="{{ url_for('chats') }}">Чаты поддержки</a>
          <a href="{{ url_for('logout') }}">Выйти</a>
        </nav>
        {% endif %}
      </header>
      <main>
        {% with messages = get_flashed_messages() %}
          {% for message in messages %}
            <div class="flash">{{ message }}</div>
          {% endfor %}
        {% endwith %}
        """ + content + """
      </main>
    </body>
    </html>
    """, title=title, logged_in=session.get("admin_logged_in", False))


@app.route("/", methods=["GET"])
def index():
    if session.get("admin_logged_in"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not ADMIN_PASSWORD:
        return "Ошибка настройки: задай ADMIN_PASSWORD в Render Environment.", 500

    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session.clear()
            session["admin_logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Неверный пароль")

    return page("Вход", """
      <div class="card" style="max-width:420px;margin:40px auto">
        <h2>Вход в админку</h2>
        <form method="post">
          <label>Пароль администратора</label>
          <input type="password" name="password" required autofocus>
          <button type="submit">Войти</button>
        </form>
      </div>
    """)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = db()

    try:
        orders_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        chats_count = conn.execute(
            "SELECT COUNT(DISTINCT telegram_id) FROM chat_messages"
        ).fetchone()[0]
        messages_count = conn.execute(
            "SELECT COUNT(*) FROM chat_messages"
        ).fetchone()[0]
        recent_orders = conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT 8"
        ).fetchall()
    except sqlite3.Error as exc:
        conn.close()
        return page("Ошибка базы", f"""
          <div class="card">
            <h3>Не удалось прочитать базу данных</h3>
            <p>{e(exc)}</p>
            <p>Проверь DB_FILE и существующую базу заказов.</p>
          </div>
        """), 500

    conn.close()

    rows = ""
    for order in recent_orders:
        rows += f"""
        <tr>
          <td>#{e(order['id'])}</td>
          <td>{e(order['username'])}</td>
          <td>{e(order['tariff'])}</td>
          <td>{e(order['status'])}</td>
          <td><a href="/order/{e(order['id'])}">Открыть</a></td>
        </tr>
        """

    return page("Главная", f"""
      <div class="layout">
        <div class="card"><h3>Заказов</h3><h1>{orders_count}</h1></div>
        <div class="card"><h3>Клиентов в чатах</h3><h1>{chats_count}</h1></div>
      </div>
      <div class="card">
        <h3>Сообщений в истории</h3><h1>{messages_count}</h1>
      </div>
      <div class="card">
        <h2>Последние заказы</h2>
        <table>
          <tr><th>ID</th><th>Клиент</th><th>Тариф</th><th>Статус</th><th></th></tr>
          {rows}
        </table>
        <p><a href="/orders">Все заказы →</a></p>
      </div>
    """)


@app.route("/orders")
@login_required
def orders():
    query = request.args.get("q", "").strip()
    conn = db()

    try:
        if query:
            like = f"%{query}%"
            data = conn.execute("""
                SELECT * FROM orders
                WHERE CAST(id AS TEXT) LIKE ?
                   OR CAST(telegram_id AS TEXT) LIKE ?
                   OR username LIKE ?
                   OR recipient_name LIKE ?
                ORDER BY id DESC
            """, (like, like, like, like)).fetchall()
        else:
            data = conn.execute(
                "SELECT * FROM orders ORDER BY id DESC LIMIT 300"
            ).fetchall()
    except sqlite3.Error as exc:
        conn.close()
        return page("Заказы", f"<div class='card'>Ошибка: {e(exc)}</div>"), 500

    conn.close()

    rows = ""
    for order in data:
        rows += f"""
        <tr>
          <td>#{e(order['id'])}</td>
          <td>{e(order['username'])}</td>
          <td>{e(order['site_type'])}</td>
          <td>{e(order['tariff'])}</td>
          <td>{e(order['price'])} грн</td>
          <td>{e(order['status'])}</td>
          <td><a href="/order/{e(order['id'])}">Открыть</a></td>
        </tr>
        """

    return page("Заказы", f"""
      <div class="card">
        <h2>Заказы</h2>
        <form method="get">
          <input name="q" value="{e(query)}" placeholder="ID, Telegram ID, username или имя">
          <button>Найти</button>
        </form>
        <div style="overflow-x:auto">
        <table>
          <tr><th>ID</th><th>Клиент</th><th>Тип сайта</th><th>Тариф</th><th>Цена</th><th>Статус</th><th></th></tr>
          {rows}
        </table>
        </div>
      </div>
    """)


@app.route("/order/<int:order_id>", methods=["GET", "POST"])
@login_required
def order_detail(order_id):
    conn = db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id = ?", (order_id,)
    ).fetchone()

    if not order:
        conn.close()
        abort(404)

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "status":
            status = request.form.get("status", "").strip()
            try:
                conn.execute(
                    "UPDATE orders SET status = ? WHERE id = ?",
                    (status, order_id)
                )
                conn.commit()
                flash("Статус обновлён")
            except sqlite3.Error as exc:
                flash(f"Ошибка обновления статуса: {exc}")
            conn.close()
            return redirect(url_for("order_detail", order_id=order_id))

        if action == "message":
            text = request.form.get("message", "").strip()
            telegram_id = order["telegram_id"]
            conn.close()

            if text:
                try:
                    send_telegram_message(telegram_id, text)
                    save_message(telegram_id, "outgoing", text, "admin")
                    flash("Сообщение отправлено клиенту")
                except Exception as exc:
                    flash(f"Не удалось отправить: {exc}")

            return redirect(url_for("order_detail", order_id=order_id))

    columns = [row["name"] for row in conn.execute(
        "PRAGMA table_info(orders)"
    ).fetchall()]
    conn.close()

    fields = ""
    for col in columns:
        if col in order.keys():
            fields += f"<tr><th>{e(col)}</th><td>{e(order[col])}</td></tr>"

    return page(f"Заказ #{order_id}", f"""
      <div class="card">
        <h2>Заказ #{order_id}</h2>
        <div style="overflow-x:auto"><table>{fields}</table></div>
      </div>
      <div class="card">
        <h3>Изменить статус</h3>
        <form method="post">
          <input type="hidden" name="action" value="status">
          <select name="status">
            {''.join(
                f'<option value="{e(s)}" {"selected" if s == order["status"] else ""}>{e(s)}</option>'
                for s in [
                    "awaiting_payment", "payment_review", "paid",
                    "in_progress", "ready", "payment_rejected", "cancelled"
                ]
            )}
          </select>
          <button>Сохранить статус</button>
        </form>
      </div>
      <div class="card">
        <h3>Написать клиенту</h3>
        <form method="post">
          <input type="hidden" name="action" value="message">
          <textarea name="message" required placeholder="Текст сообщения"></textarea>
          <button>Отправить в Telegram</button>
        </form>
        <p><a href="/chats/{e(order['telegram_id'])}">Открыть чат клиента →</a></p>
      </div>
    """)


@app.route("/chats")
@login_required
def chats():
    query = request.args.get("q", "").strip()
    conn = db()

    try:
        if query:
            like = f"%{query}%"
            rows = conn.execute("""
                SELECT telegram_id,
                       MAX(username) AS username,
                       COUNT(*) AS message_count,
                       MAX(created_at) AS last_message
                FROM chat_messages
                WHERE CAST(telegram_id AS TEXT) LIKE ?
                   OR username LIKE ?
                GROUP BY telegram_id
                ORDER BY MAX(id) DESC
            """, (like, like)).fetchall()
        else:
            rows = conn.execute("""
                SELECT telegram_id,
                       MAX(username) AS username,
                       COUNT(*) AS message_count,
                       MAX(created_at) AS last_message
                FROM chat_messages
                GROUP BY telegram_id
                ORDER BY MAX(id) DESC
            """).fetchall()
    except sqlite3.Error as exc:
        conn.close()
        return page("Чаты", f"<div class='card'>Ошибка базы: {e(exc)}</div>"), 500

    conn.close()

    items = ""
    for row in rows:
        username = row["username"] or "без username"
        items += f"""
        <a href="/chats/{e(row['telegram_id'])}">
          <b>@{e(username)}</b><br>
          <small>ID: {e(row['telegram_id'])}</small><br>
          <small>Сообщений: {e(row['message_count'])}</small><br>
          <small>{e(row['last_message'])}</small>
        </a>
        """

    if not items:
        items = "<p class='muted'>Пока сообщений нет. Они появятся, когда бот начнёт сохранять переписку.</p>"

    return page("Чаты", f"""
      <div class="card">
        <h2>Чаты поддержки</h2>
        <form method="get">
          <input name="q" value="{e(query)}" placeholder="Telegram ID или username">
          <button>Найти</button>
        </form>
        <div class="chat-list">{items}</div>
      </div>
    """)


@app.route("/chats/<int:telegram_id>", methods=["GET", "POST"])
@login_required
def chat_detail(telegram_id):
    if request.method == "POST":
        text = request.form.get("message", "").strip()

        if text:
            try:
                send_telegram_message(telegram_id, text)
                save_message(telegram_id, "outgoing", text, "admin")
                flash("Сообщение отправлено")
            except Exception as exc:
                flash(f"Ошибка отправки: {exc}")

        return redirect(url_for("chat_detail", telegram_id=telegram_id))

    conn = db()
    messages = conn.execute("""
        SELECT * FROM chat_messages
        WHERE telegram_id = ?
        ORDER BY id ASC
        LIMIT 1000
    """, (telegram_id,)).fetchall()
    conn.close()

    history = ""
    for msg in messages:
        direction = msg["direction"]
        css_class = "incoming" if direction == "incoming" else "outgoing"
        label = "Клиент" if direction == "incoming" else "Администратор"
        history += f"""
        <div class="message {css_class}">
          <small>{label} · {e(msg['created_at'])}</small>
          <div>{e(msg['message_text'])}</div>
        </div>
        """

    if not history:
        history = "<p class='muted'>История пока пустая.</p>"

    return page("Чат", f"""
      <div class="card">
        <h2>Чат с клиентом</h2>
        <p class="muted">Telegram ID: {telegram_id}</p>
        <a href="/chats">← Все чаты</a>
        <hr>
        {history}
        <form method="post">
          <textarea name="message" required placeholder="Напиши клиенту..."></textarea>
          <button>Отправить сообщение</button>
        </form>
      </div>
    """)


@app.route("/receipt/<int:order_id>")
@login_required
def receipt(order_id):
    conn = db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id = ?", (order_id,)
    ).fetchone()
    conn.close()

    if not order:
        abort(404)

    if not order["receipt_file_id"]:
        return "Чек не прикреплён", 404

    try:
        file_info = telegram_api("getFile", {"file_id": order["receipt_file_id"]})
        file_path = file_info["file_path"]
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

        with urllib.request.urlopen(url, timeout=20) as response:
            file_data = response.read()

        return send_file(
            BytesIO(file_data),
            mimetype="application/octet-stream",
            as_attachment=False,
            download_name=f"receipt_{order_id}"
        )
    except Exception as exc:
        return f"Не удалось получить чек: {e(exc)}", 500


def run_admin_web():
    init_chat_db()

    if not ADMIN_PASSWORD:
        print("WARNING: ADMIN_PASSWORD не задан в Render Environment")

    port = int(os.getenv("PORT", "10000"))
    print(f"Lunevia admin web starts on port {port}")
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run_admin_web()
