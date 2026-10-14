
import os
import sqlite3
import urllib.parse
import urllib.request
import json
import html
from io import BytesIO
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, flash, send_file, abort, jsonify
)

app = Flask(__name__)
app.secret_key = os.getenv("ADMIN_SECRET_KEY") or os.getenv("BOT_TOKEN") or "change-this-secret"

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_FILE = os.getenv("DB_FILE", "lunevia_orders.db")


def db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
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
    columns = {
        row["name"] for row in conn.execute(
            "PRAGMA table_info(chat_messages)"
        ).fetchall()
    }
    if "telegram_message_id" not in columns:
        conn.execute(
            "ALTER TABLE chat_messages ADD COLUMN telegram_message_id INTEGER"
        )
    conn.commit()
    conn.close()


def e(value):
    return html.escape(str(value or ""))


def telegram_api(method, data=None):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в Render Environment")

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


def save_message(telegram_id, direction, message_text, username=None,
                 telegram_message_id=None):
    conn = db()
    conn.execute("""
        INSERT INTO chat_messages
        (telegram_id, direction, message_text, username, telegram_message_id)
        VALUES (?, ?, ?, ?, ?)
    """, (
        telegram_id, direction, message_text,
        username, telegram_message_id
    ))
    conn.commit()
    conn.close()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Требуется вход"}), 401
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


STYLE = """
<style>
:root{color-scheme:dark;--bg:#0b0b0e;--panel:#141419;--panel2:#1b1b22;
--line:#292932;--gold:#e8bf75;--muted:#9696a5;--red:#ef6565}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:#f5f3ee;font:14px Inter,Arial,sans-serif}
a{color:var(--gold);text-decoration:none}a:hover{opacity:.8}
header{position:sticky;top:0;z-index:10;background:#111115ee;
backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:17px 24px}
.top{max-width:1400px;margin:auto;display:flex;justify-content:space-between;
align-items:center;gap:16px;flex-wrap:wrap}
.brand{font-size:22px;font-weight:800;letter-spacing:.4px;color:var(--gold)}
nav{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px}
nav a{color:#c7c4bc}
main{max-width:1400px;margin:26px auto;padding:0 18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;
padding:20px;margin-bottom:18px;min-width:0}
h1,h2,h3{margin-top:0}h2{font-size:21px}
.muted,small{color:var(--muted)}
input,textarea,select{width:100%;padding:12px 13px;background:#0d0d11;
border:1px solid #34343e;color:#fff;border-radius:10px;margin:7px 0 13px;
font:inherit;outline:none}
input:focus,textarea:focus,select:focus{border-color:var(--gold)}
textarea{min-height:100px;resize:vertical}
button,.btn{display:inline-flex;align-items:center;justify-content:center;
gap:7px;border:0;border-radius:10px;background:var(--gold);color:#17130c;
padding:11px 15px;font-weight:700;font-size:13px;cursor:pointer}
button:hover,.btn:hover{filter:brightness(1.08)}
.secondary{background:#292932;color:#fff}.danger{background:#55272b;color:#ffb3b3}
button:disabled{opacity:.5;cursor:wait}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.stat{background:linear-gradient(145deg,#1c1b20,#121216);border:1px solid var(--line);
border-radius:15px;padding:20px}.stat b{display:block;font-size:30px;margin-top:10px}
.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.7px;color:var(--muted)}
.flash{padding:13px;background:#282319;border:1px solid #54452b;border-radius:10px;margin-bottom:14px}
.layout{display:grid;grid-template-columns:310px minmax(0,1fr);gap:16px;align-items:start}
.chat-list{display:flex;flex-direction:column;gap:7px;margin-top:12px}
.chat-item{display:block;padding:14px;border:1px solid var(--line);border-radius:12px;
background:#111116;color:#fff}
.chat-item.active,.chat-item:hover{border-color:#8e7040;background:#211d17}
.chat-item b{color:var(--gold)}.chat-item small{display:block;margin-top:6px}
.chat-panel{padding:0;overflow:hidden}
.chat-head{padding:18px 20px;border-bottom:1px solid var(--line)}
.messages{height:min(58vh,650px);min-height:300px;overflow-y:auto;padding:18px;
display:flex;flex-direction:column;gap:12px;background:#0e0e12}
.message{max-width:82%;padding:12px 14px;border:1px solid var(--line);
border-radius:14px;background:#202027;overflow-wrap:anywhere;white-space:pre-wrap}
.message.outgoing{align-self:flex-end;background:#332a1c;border-color:#5c492b}
.message.incoming{align-self:flex-start}
.msg-meta{font-size:11px;color:var(--muted);margin-bottom:7px}
.msg-text{line-height:1.5}
.msg-actions{display:flex;gap:7px;margin-top:10px}
.mini{padding:6px 9px;font-size:11px;border-radius:7px}
.composer{padding:16px;border-top:1px solid var(--line)}
.composer textarea{min-height:75px;margin-bottom:10px}
.composer-row{display:flex;justify-content:space-between;align-items:center;gap:10px}
.empty{text-align:center;padding:45px 16px;color:var(--muted)}
.status{display:inline-block;border-radius:30px;background:#24242c;padding:5px 9px;font-size:11px}
@media(max-width:800px){.layout{grid-template-columns:1fr}.stats{grid-template-columns:1fr}
.messages{height:48vh}.message{max-width:94%}header{padding:14px}
main{padding:0 10px;margin:15px auto}.card{padding:14px}}
</style>
"""


def page(title, content, scripts=""):
    return render_template_string("""
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} · Lunevia</title>
""" + STYLE + """
</head>
<body>
<header><div class="top">
  <div class="brand">♡ LUNEVIA <span style="color:#888;font-size:12px">ADMIN</span></div>
  {% if logged_in %}<span class="status">Панель управления</span>{% endif %}
</div>
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
{% for message in messages %}<div class="flash">{{ message }}</div>{% endfor %}
{% endwith %}
""" + content + """
</main>
""" + scripts + """
</body></html>
""", title=title, logged_in=session.get("admin_logged_in", False))


@app.route("/")
def index():
    return redirect(url_for("dashboard") if session.get("admin_logged_in")
                    else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not ADMIN_PASSWORD:
        return "Ошибка: задай ADMIN_PASSWORD в Render Environment.", 500

    if request.method == "POST":
        if request.form.get("password", "") == ADMIN_PASSWORD:
            session.clear()
            session["admin_logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Неверный пароль")

    return page("Вход", """
<div class="card" style="max-width:420px;margin:55px auto">
  <h2>Вход в админку</h2>
  <p class="muted">Управление заказами и клиентскими чатами</p>
  <form method="post">
    <label>Пароль администратора</label>
    <input type="password" name="password" required autofocus>
    <button type="submit">Войти →</button>
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
        recent = conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT 8"
        ).fetchall()
    except sqlite3.Error as exc:
        conn.close()
        return page("Ошибка", f"<div class='card'>Ошибка базы: {e(exc)}</div>"), 500
    conn.close()

    rows = ""
    for order in recent:
        rows += f"""
        <tr><td>#{e(order['id'])}</td><td>{e(order['username'])}</td>
        <td>{e(order['tariff'])}</td><td>{e(order['status'])}</td>
        <td><a href="/order/{int(order['id'])}">Открыть →</a></td></tr>
        """

    return page("Главная", f"""
<div class="stats">
  <div class="stat"><span class="muted">Всего заказов</span><b>{orders_count}</b></div>
  <div class="stat"><span class="muted">Клиентов в чатах</span><b>{chats_count}</b></div>
  <div class="stat"><span class="muted">Сообщений в истории</span><b>{messages_count}</b></div>
</div>
<div class="card">
<h2>Последние заказы</h2><div class="tablewrap"><table>
<tr><th>ID</th><th>Клиент</th><th>Тариф</th><th>Статус</th><th></th></tr>
{rows}
</table></div><p><a href="/orders">Все заказы →</a></p>
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
                OR username LIKE ? OR recipient_name LIKE ?
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
        <tr><td>#{int(order['id'])}</td><td>{e(order['username'])}</td>
        <td>{e(order['site_type'])}</td><td>{e(order['tariff'])}</td>
        <td>{e(order['price'])} грн</td><td>{e(order['status'])}</td>
        <td><a href="/order/{int(order['id'])}">Открыть →</a></td></tr>
        """

    return page("Заказы", f"""
<div class="card"><h2>Заказы</h2>
<form method="get"><input name="q" value="{e(query)}"
placeholder="Поиск по ID, Telegram ID, username или имени">
<button>Найти</button></form>
<div class="tablewrap"><table>
<tr><th>ID</th><th>Клиент</th><th>Тип сайта</th><th>Тариф</th><th>Цена</th><th>Статус</th><th></th></tr>
{rows}</table></div></div>
""")


@app.route("/order/<int:order_id>", methods=["GET", "POST"])
@login_required
def order_detail(order_id):
    conn = db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        abort(404)

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "status":
            status = request.form.get("status", "").strip()
            allowed = {
                "awaiting_payment", "payment_review", "paid",
                "in_progress", "ready", "payment_rejected", "cancelled"
            }
            if status not in allowed:
                conn.close()
                abort(400)
            conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
            conn.commit()
            conn.close()
            flash("Статус обновлён")
            return redirect(url_for("order_detail", order_id=order_id))

        if action == "message":
            text = request.form.get("message", "").strip()
            telegram_id = order["telegram_id"]
            conn.close()
            if text:
                try:
                    sent = send_telegram_message(telegram_id, text)
                    save_message(
                        telegram_id, "outgoing", text, "admin",
                        sent.get("message_id") if sent else None
                    )
                    flash("Сообщение отправлено")
                except Exception as exc:
                    flash(f"Ошибка отправки: {exc}")
            return redirect(url_for("order_detail", order_id=order_id))

    columns = [row["name"] for row in conn.execute("PRAGMA table_info(orders)")]
    conn.close()
    fields = "".join(
        f"<tr><th>{e(col)}</th><td>{e(order[col])}</td></tr>"
        for col in columns if col in order.keys()
    )

    statuses = [
        "awaiting_payment", "payment_review", "paid", "in_progress",
        "ready", "payment_rejected", "cancelled"
    ]
    options = "".join(
        f'<option value="{s}" {"selected" if s == order["status"] else ""}>{s}</option>'
        for s in statuses
    )

    return page(f"Заказ #{order_id}", f"""
<div class="card"><h2>Заказ #{order_id}</h2>
<div class="tablewrap"><table>{fields}</table></div></div>
<div class="card"><h3>Статус заказа</h3>
<form method="post"><input type="hidden" name="action" value="status">
<select name="status">{options}</select><button>Сохранить</button></form></div>
<div class="card"><h3>Написать клиенту</h3>
<form method="post"><input type="hidden" name="action" value="message">
<textarea name="message" required placeholder="Сообщение клиенту"></textarea>
<button>Отправить в Telegram</button></form>
<p><a href="/chats/{int(order['telegram_id'])}">Открыть чат →</a></p></div>
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
                SELECT telegram_id, MAX(username) AS username,
                COUNT(*) AS message_count, MAX(created_at) AS last_message,
                MAX(id) AS last_id
                FROM chat_messages
                WHERE CAST(telegram_id AS TEXT) LIKE ? OR username LIKE ?
                GROUP BY telegram_id ORDER BY last_id DESC
            """, (like, like)).fetchall()
        else:
            rows = conn.execute("""
                SELECT telegram_id, MAX(username) AS username,
                COUNT(*) AS message_count, MAX(created_at) AS last_message,
                MAX(id) AS last_id
                FROM chat_messages GROUP BY telegram_id ORDER BY last_id DESC
            """).fetchall()
    except sqlite3.Error as exc:
        conn.close()
        return page("Чаты", f"<div class='card'>Ошибка: {e(exc)}</div>"), 500
    conn.close()

    items = ""
    for row in rows:
        username = row["username"] or "без username"
        items += f"""
<a class="chat-item" href="/chats/{int(row['telegram_id'])}">
<b>@{e(username)}</b><small>ID: {int(row['telegram_id'])}</small>
<small>Сообщений: {int(row['message_count'])}</small>
<small>{e(row['last_message'])}</small></a>
"""
    if not items:
        items = "<div class='empty'>История чатов пока пуста.</div>"

    return page("Чаты поддержки", f"""
<div class="card"><h2>Чаты поддержки</h2>
<form method="get"><input name="q" value="{e(query)}"
placeholder="Telegram ID или username"><button>Найти</button></form>
<div class="chat-list">{items}</div></div>
""")


@app.route("/chats/<int:telegram_id>")
@login_required
def chat_detail(telegram_id):
    conn = db()
    messages = conn.execute("""
        SELECT * FROM chat_messages WHERE telegram_id=? ORDER BY id ASC LIMIT 1000
    """, (telegram_id,)).fetchall()
    latest_id = messages[-1]["id"] if messages else 0
    conn.close()

    history = "".join(
        render_message(msg) for msg in messages
    ) or "<div class='empty'>Начни переписку с клиентом.</div>"

    scripts = """
<script>
const chatId = """ + str(telegram_id) + """;
let latestId = """ + str(latest_id) + """;
let busy = false;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));
}
function messageHtml(m) {
  const outgoing = m.direction === "outgoing";
  return `<div class="message ${outgoing ? "outgoing" : "incoming"}" id="msg-${m.id}">
    <div class="msg-meta">${outgoing ? "Администратор" : "Клиент"} · ${esc(m.created_at)}</div>
    <div class="msg-text">${esc(m.message_text)}</div>
    <div class="msg-actions">
      <button class="mini secondary" onclick="editMessage(${m.id}, ${JSON.stringify(m.message_text).replace(/</g, '\\\\u003c')})">Изменить</button>
      <button class="mini danger" onclick="deleteMessage(${m.id})">Удалить</button>
    </div></div>`;
}
async function refreshMessages() {
  if (busy || document.hidden) return;
  try {
    const r = await fetch(`/api/chats/${chatId}/messages?after=${latestId}`, {cache:"no-store"});
    if (!r.ok) return;
    const data = await r.json();
    if (!data.ok) return;
    const box = document.getElementById("messages");
    for (const m of data.messages) {
      const old = document.getElementById(`msg-${m.id}`);
      if (old) old.outerHTML = messageHtml(m);
      else {
        box.insertAdjacentHTML("beforeend", messageHtml(m));
        latestId = Math.max(latestId, Number(m.id));
      }
    }
    if (data.messages.length) box.scrollTop = box.scrollHeight;
  } catch (_) {}
}
async function sendMessage(event) {
  event.preventDefault();
  const input = document.getElementById("messageInput");
  const text = input.value.trim();
  if (!text || busy) return;
  busy = true;
  document.getElementById("sendBtn").disabled = true;
  try {
    const r = await fetch(`/api/chats/${chatId}/send`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({message:text})
    });
    const data = await r.json();
    if (!r.ok || !data.ok) { alert(data.error || "Не удалось отправить"); return; }
    input.value = "";
    await refreshMessages();
  } catch (_) { alert("Ошибка соединения"); }
  finally { busy = false; document.getElementById("sendBtn").disabled = false; }
}
async function editMessage(id, oldText) {
  const text = prompt("Измени сообщение:", oldText);
  if (text === null || text.trim() === "" || text === oldText) return;
  if (!confirm("Сохранить изменения?")) return;
  try {
    const r = await fetch(`/api/messages/${id}/edit`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({message:text.trim()})
    });
    const data = await r.json();
    if (!r.ok || !data.ok) { alert(data.error || "Не удалось изменить"); return; }
    await refreshMessages();
  } catch (_) { alert("Ошибка соединения"); }
}
async function deleteMessage(id) {
  if (!confirm("Удалить это сообщение из истории?")) return;
  try {
    const r = await fetch(`/api/messages/${id}/delete`, {method:"POST"});
    const data = await r.json();
    if (!r.ok || !data.ok) { alert(data.error || "Не удалось удалить"); return; }
    const el = document.getElementById(`msg-${id}`);
    if (el) el.remove();
  } catch (_) { alert("Ошибка соединения"); }
}
document.getElementById("composer").addEventListener("submit", sendMessage);
document.getElementById("messages").scrollTop = document.getElementById("messages").scrollHeight;
setInterval(refreshMessages, 2500);
</script>
"""

    return page("Чат", f"""
<div class="layout">
  <div class="card">
    <h3>Клиент</h3><p class="muted">Telegram ID</p>
    <div style="font-size:20px;color:var(--gold)">{telegram_id}</div>
    <p><a href="/chats">← Все чаты</a></p>
  </div>
  <div class="card chat-panel">
    <div class="chat-head"><h2 style="margin:0">Переписка</h2>
    <small>Обновление автоматически · примерно каждые 2,5 секунды</small></div>
    <div class="messages" id="messages">{history}</div>
    <form class="composer" id="composer">
      <textarea id="messageInput" required placeholder="Напиши клиенту..."></textarea>
      <div class="composer-row"><small>Enter — отправить не настроено, используй кнопку</small>
      <button id="sendBtn" type="submit">Отправить ↗</button></div>
    </form>
  </div>
</div>
""", scripts=scripts)


def render_message(msg):
    outgoing = msg["direction"] == "outgoing"
    css = "outgoing" if outgoing else "incoming"
    label = "Администратор" if outgoing else "Клиент"
    text = json.dumps(msg["message_text"] or "", ensure_ascii=False).replace("</", "<\\/")
    return f"""
<div class="message {css}" id="msg-{int(msg['id'])}">
<div class="msg-meta">{label} · {e(msg['created_at'])}</div>
<div class="msg-text">{e(msg['message_text'])}</div>
<div class="msg-actions">
<button class="mini secondary" onclick='editMessage({int(msg["id"])}, {text})'>Изменить</button>
<button class="mini danger" onclick="deleteMessage({int(msg['id'])})">Удалить</button>
</div></div>
"""


@app.route("/api/chats/<int:telegram_id>/messages")
@login_required
def api_chat_messages(telegram_id):
    after = request.args.get("after", "0")
    try:
        after = max(0, int(after))
    except ValueError:
        after = 0

    conn = db()
    rows = conn.execute("""
        SELECT * FROM chat_messages
        WHERE telegram_id=? AND id>?
        ORDER BY id ASC LIMIT 100
    """, (telegram_id, after)).fetchall()
    conn.close()

    return jsonify({
        "ok": True,
        "messages": [{
            "id": row["id"],
            "direction": row["direction"],
            "message_text": row["message_text"],
            "created_at": row["created_at"]
        } for row in rows]
    })


@app.route("/api/chats/<int:telegram_id>/send", methods=["POST"])
@login_required
def api_chat_send(telegram_id):
    data = request.get_json(silent=True) or {}
    text = str(data.get("message", "")).strip()
    if not text:
        return jsonify({"ok": False, "error": "Сообщение пустое"}), 400
    if len(text) > 4096:
        return jsonify({"ok": False, "error": "Максимум 4096 символов"}), 400

    try:
        sent = send_telegram_message(telegram_id, text)
        save_message(
            telegram_id, "outgoing", text, "admin",
            sent.get("message_id") if sent else None
        )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/messages/<int:message_id>/edit", methods=["POST"])
@login_required
def api_message_edit(message_id):
    data = request.get_json(silent=True) or {}
    text = str(data.get("message", "")).strip()
    if not text:
        return jsonify({"ok": False, "error": "Сообщение пустое"}), 400
    if len(text) > 4096:
        return jsonify({"ok": False, "error": "Максимум 4096 символов"}), 400

    conn = db()
    msg = conn.execute(
        "SELECT * FROM chat_messages WHERE id=?", (message_id,)
    ).fetchone()
    if not msg:
        conn.close()
        return jsonify({"ok": False, "error": "Сообщение не найдено"}), 404

    # Для сообщений администратора пытаемся изменить также сообщение в Telegram.
    if msg["direction"] == "outgoing" and msg["telegram_message_id"]:
        try:
            telegram_api("editMessageText", {
                "chat_id": msg["telegram_id"],
                "message_id": msg["telegram_message_id"],
                "text": text
            })
        except Exception as exc:
            conn.close()
            return jsonify({
                "ok": False,
                "error": "Telegram не разрешил редактирование: " + str(exc)
            }), 400

    conn.execute(
        "UPDATE chat_messages SET message_text=? WHERE id=?",
        (text, message_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/messages/<int:message_id>/delete", methods=["POST"])
@login_required
def api_message_delete(message_id):
    conn = db()
    msg = conn.execute(
        "SELECT * FROM chat_messages WHERE id=?", (message_id,)
    ).fetchone()
    if not msg:
        conn.close()
        return jsonify({"ok": False, "error": "Сообщение не найдено"}), 404

    # Telegram позволяет удалить только сообщение в пределах доступных ограничений.
    # Если Telegram отклонит удаление, запись в истории не удаляем.
    if msg["direction"] == "outgoing" and msg["telegram_message_id"]:
        try:
            telegram_api("deleteMessage", {
                "chat_id": msg["telegram_id"],
                "message_id": msg["telegram_message_id"]
            })
        except Exception as exc:
            conn.close()
            return jsonify({
                "ok": False,
                "error": "Telegram не разрешил удаление: " + str(exc)
            }), 400

    conn.execute("DELETE FROM chat_messages WHERE id=?", (message_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/receipt/<int:order_id>")
@login_required
def receipt(order_id):
    conn = db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id=?", (order_id,)
    ).fetchone()
    conn.close()

    if not order:
        abort(404)
    if not order["receipt_file_id"]:
        return "Чек не прикреплён", 404

    try:
        file_info = telegram_api("getFile", {"file_id": order["receipt_file_id"]})
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info['file_path']}"
        with urllib.request.urlopen(url, timeout=20) as response:
            file_data = response.read()
        return send_file(
            BytesIO(file_data), mimetype="application/octet-stream",
            as_attachment=False, download_name=f"receipt_{order_id}"
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
