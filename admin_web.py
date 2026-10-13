import os
import sqlite3
import json
import urllib.parse
import urllib.request
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string, flash, send_file, abort
from io import BytesIO

DB_FILE = os.getenv('DB_FILE', 'lunevia_orders.db')
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')
SECRET_KEY = os.getenv('ADMIN_SECRET_KEY', '') or os.getenv('BOT_TOKEN', 'change-this-secret-key')

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', '0') == '1')

STATUSES = {
    'awaiting_payment': 'Ожидает оплату',
    'payment_review': 'Проверка оплаты',
    'paid': 'Оплачено',
    'in_progress': 'В работе',
    'ready': 'Готово',
    'payment_rejected': 'Оплата отклонена',
    'cancelled': 'Отменён',
}

BASE_STYLE = '''
:root{color-scheme:dark;--bg:#090a12;--panel:#121421;--panel2:#191b2c;--line:#292c43;--text:#f4f5ff;--muted:#a2a7c2;--purple:#9b7bff;--blue:#62c8ff;--green:#58d6a3;--red:#ff7185}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top right,#1b1640 0,transparent 40%),var(--bg);color:var(--text);font:15px/1.5 Inter,Segoe UI,Arial,sans-serif}a{color:inherit;text-decoration:none}.shell{max-width:1440px;margin:auto;padding:26px}.top{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:26px}.brand{display:flex;gap:12px;align-items:center}.logo{width:44px;height:44px;border-radius:15px;background:linear-gradient(135deg,#a27bff,#48c7ff);display:grid;place-items:center;font-size:22px;color:#080914;font-weight:900}.brand h1{font-size:22px;margin:0}.muted{color:var(--muted)}.nav{display:flex;gap:10px;flex-wrap:wrap}.btn,button{border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:11px;padding:10px 14px;font:inherit;cursor:pointer}.btn.primary,button.primary{background:linear-gradient(135deg,#8c68f6,#5b9fff);border:0;color:white;font-weight:700}.btn:hover,button:hover{filter:brightness(1.13)}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.card{background:linear-gradient(145deg,rgba(25,27,44,.97),rgba(15,17,29,.97));border:1px solid var(--line);border-radius:18px;padding:20px;min-width:0;box-shadow:0 14px 38px #0002}.metric{font-size:30px;font-weight:800;margin-top:8px}.label{color:var(--muted);font-size:13px}.section{margin-top:20px}.section-head{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:14px}.section-head h2{font-size:18px;margin:0}.filters{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:14px}input,select,textarea{background:#0d0f1b;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:11px 12px;font:inherit;max-width:100%}input,select{min-height:42px}textarea{width:100%;min-height:115px;resize:vertical}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:13px 12px;border-bottom:1px solid var(--line);vertical-align:middle}th{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}tr:last-child td{border-bottom:0}.table-wrap{overflow:auto}.pill{display:inline-block;padding:5px 9px;border-radius:99px;background:#292541;color:#d2c6ff;font-size:12px;white-space:nowrap}.pill.green{background:#15372f;color:#80efc1}.pill.orange{background:#42301c;color:#ffd18a}.pill.red{background:#401f2a;color:#ff9eae}.two{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(300px,.8fr);gap:16px}.detail-list{display:grid;grid-template-columns:140px 1fr;gap:10px;margin:0}.detail-list dt{color:var(--muted)}.detail-list dd{margin:0;overflow-wrap:anywhere}.actions{display:flex;gap:8px;flex-wrap:wrap}.form-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.flash{padding:12px 15px;border:1px solid #53447f;background:#211a39;border-radius:12px;margin-bottom:14px}.login{max-width:440px;margin:10vh auto;padding:0 20px}.login .card{padding:28px}.login input{width:100%;margin:10px 0 14px}.empty{text-align:center;padding:40px;color:var(--muted)}.receipt{max-width:100%;border-radius:12px;border:1px solid var(--line)}.full{width:100%}.small{font-size:12px}.danger{color:#ff9eae}.success{color:#80efc1}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}.shell{padding:16px}.top{align-items:flex-start;flex-direction:column}.detail-list{grid-template-columns:115px 1fr}}@media(max-width:520px){.grid{grid-template-columns:1fr 1fr;gap:9px}.card{padding:14px}.metric{font-size:24px}th,td{padding:10px 8px}.brand h1{font-size:19px}}
'''

LOGIN = '''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lunevia · Вход</title><style>''' + BASE_STYLE + '''</style></head><body><div class="login"><div class="brand" style="margin-bottom:20px"><div class="logo">L</div><div><h1>Lunevia Admin</h1><div class="muted">Панель управления заказами</div></div></div><div class="card"><h2 style="margin-top:0">Вход администратора</h2><p class="muted">Введите пароль, заданный в настройках Render.</p>{% with messages = get_flashed_messages() %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}<form method="post"><label class="label" for="password">Пароль</label><input id="password" name="password" type="password" autocomplete="current-password" required autofocus><button class="primary full" type="submit">Войти в панель →</button></form></div><p class="muted small" style="text-align:center;margin-top:16px">Доступ только для администратора</p></div></body></html>'''

LAYOUT = '''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ title }} · Lunevia</title><style>''' + BASE_STYLE + '''</style></head><body><div class="shell"><header class="top"><a class="brand" href="{{ url_for('dashboard') }}"><div class="logo">L</div><div><h1>Lunevia <span style="color:var(--purple)">Admin</span></h1><div class="muted small">Заказы · Клиенты · Оплаты</div></div></a><nav class="nav"><a class="btn" href="{{ url_for('dashboard') }}">Обзор</a><a class="btn" href="{{ url_for('orders') }}">Заказы</a><a class="btn" href="{{ url_for('orders', status='payment_review') }}">Проверка оплат</a><a class="btn" href="{{ url_for('logout') }}">Выйти ↗</a></nav></header>{% with messages = get_flashed_messages() %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}{{ body|safe }}</div></body></html>'''


def db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
    return conn


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def telegram_api(method, data=None, raw=False):
    if not BOT_TOKEN:
        raise RuntimeError('На сервере не задан BOT_TOKEN')
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/{method}'
    payload = urllib.parse.urlencode(data or {}).encode()
    req = urllib.request.Request(url, data=payload, method='POST')
    with urllib.request.urlopen(req, timeout=25) as response:
        result = response.read()
    if raw:
        return result
    parsed = json.loads(result.decode('utf-8'))
    if not parsed.get('ok'):
        raise RuntimeError(parsed.get('description', 'Telegram API error'))
    return parsed.get('result')


def send_telegram_message(chat_id, text):
    return telegram_api('sendMessage', {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'})


def status_pill(status):
    cls = 'green' if status in ('paid','ready') else 'orange' if status in ('payment_review','awaiting_payment','in_progress') else 'red' if status in ('payment_rejected','cancelled') else ''
    return f'<span class="pill {cls}">{STATUSES.get(status, status or "—")}</span>'


def layout(title, body):
    return render_template_string(LAYOUT, title=title, body=body)


@app.route('/health')
def health():
    return 'Lunevia Admin is running', 200

@app.route('/login', methods=['GET','POST'])
def login():
    if not ADMIN_PASSWORD:
        return 'Ошибка настройки: добавь ADMIN_PASSWORD в переменные окружения Render.', 500
    if request.method == 'POST':
        if request.form.get('password', '') == ADMIN_PASSWORD:
            session.clear()
            session['admin_logged_in'] = True
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Неверный пароль.')
    return render_template_string(LOGIN)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    conn = db()
    total = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    review = conn.execute("SELECT COUNT(*) FROM orders WHERE status='payment_review'").fetchone()[0]
    progress = conn.execute("SELECT COUNT(*) FROM orders WHERE status='in_progress'").fetchone()[0]
    ready = conn.execute("SELECT COUNT(*) FROM orders WHERE status='ready'").fetchone()[0]
    revenue = conn.execute("SELECT COALESCE(SUM(price),0) FROM orders WHERE status IN ('paid','in_progress','ready')").fetchone()[0]
    recent = conn.execute('SELECT id,telegram_id,username,tariff,price,recipient_name,status,created_at FROM orders ORDER BY id DESC LIMIT 8').fetchall()
    conn.close()
    body = f'''<div class="section-head"><div><h2>Обзор</h2><div class="muted">Сводка по заказам Lunevia</div></div><a class="btn primary" href="{url_for('orders')}">Все заказы →</a></div>
    <div class="grid"><div class="card"><div class="label">Всего заказов</div><div class="metric">{total}</div><div class="muted small">За всё время</div></div><div class="card"><div class="label">Ожидают проверки</div><div class="metric" style="color:var(--blue)">{review}</div><div class="muted small">Проверь квитанции</div></div><div class="card"><div class="label">В работе</div><div class="metric">{progress}</div><div class="muted small">Создание сайтов</div></div><div class="card"><div class="label">Подтверждённая выручка</div><div class="metric" style="color:var(--green)">{revenue} ₴</div><div class="muted small">Оплачено, в работе и готово</div></div></div>
    <div class="section card"><div class="section-head"><h2>Последние заказы</h2><a class="btn" href="{url_for('orders')}">Открыть список</a></div>{orders_table(recent)}</div>
    <div class="section"><div class="grid"><a class="card" href="{url_for('orders',status='payment_review')}"><div class="label">Быстрое действие</div><h3>🟠 Проверить оплаты</h3><div class="muted">Открыть заказы с квитанциями</div></a><a class="card" href="{url_for('orders',status='in_progress')}"><div class="label">Быстрое действие</div><h3>🔵 Заказы в работе</h3><div class="muted">Управлять текущими проектами</div></a></div></div>'''
    return layout('Обзор', body)


def orders_table(rows):
    if not rows:
        return '<div class="empty">Заказов пока нет.</div>'
    out = ['<div class="table-wrap"><table><thead><tr><th>Заказ</th><th>Клиент</th><th>Тариф</th><th>Сумма</th><th>Статус</th><th></th></tr></thead><tbody>']
    for r in rows:
        user = ('@' + r['username']) if r['username'] else str(r['telegram_id'])
        out.append(f'<tr><td><b>#{r["id"]}</b><div class="muted small">{html_escape(r["created_at"] or "")}</div></td><td>{html_escape(user)}<div class="muted small">Для: {html_escape(r["recipient_name"] or "—")}</div></td><td>{html_escape(r["tariff"] or "—")}</td><td><b>{r["price"] or 0} ₴</b></td><td>{status_pill(r["status"])}</td><td><a class="btn" href="{url_for("order_detail", order_id=r["id"])}">Открыть →</a></td></tr>')
    out.append('</tbody></table></div>')
    return ''.join(out)


def html_escape(value):
    value = str(value if value is not None else '')
    return value.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;').replace("'",'&#x27;')

@app.route('/orders')
@login_required
def orders():
    status = request.args.get('status','')
    search = request.args.get('q','').strip()
    conn = db()
    query = 'SELECT id,telegram_id,username,tariff,price,recipient_name,status,created_at FROM orders WHERE 1=1'
    args = []
    if status in STATUSES:
        query += ' AND status=?'; args.append(status)
    if search:
        if search.startswith('#') and search[1:].isdigit():
            query += ' AND id=?'; args.append(int(search[1:]))
        elif search.isdigit():
            query += ' AND (id=? OR telegram_id=?)'; args.extend([int(search),int(search)])
        else:
            query += ' AND (username LIKE ? OR recipient_name LIKE ? OR custom_text LIKE ?)'; args.extend([f'%{search}%',f'%{search}%',f'%{search}%'])
    query += ' ORDER BY id DESC LIMIT 250'
    rows = conn.execute(query,args).fetchall(); conn.close()
    options = ''.join(f'<option value="{k}" {"selected" if status==k else ""}>{v}</option>' for k,v in STATUSES.items())
    body = f'''<div class="section-head"><div><h2>Заказы</h2><div class="muted">Найдено: {len(rows)} · максимум 250 в списке</div></div></div><div class="card"><form class="filters" method="get"><input name="q" value="{html_escape(search)}" placeholder="ID, username, имя или текст заказа" style="flex:1;min-width:210px"><select name="status"><option value="">Все статусы</option>{options}</select><button class="primary" type="submit">Найти</button><a class="btn" href="{url_for('orders')}">Сбросить</a></form>{orders_table(rows)}</div>'''
    return layout('Заказы', body)

@app.route('/orders/<int:order_id>', methods=['GET','POST'])
@login_required
def order_detail(order_id):
    conn = db()
    row = conn.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
    conn.close()
    if not row:
        flash('Заказ не найден.'); return redirect(url_for('orders'))
    if request.method == 'POST':
        action = request.form.get('action','')
        try:
            if action == 'status':
                new_status = request.form.get('status','')
                if new_status not in STATUSES: raise ValueError('Неизвестный статус')
                conn = db(); conn.execute('UPDATE orders SET status=? WHERE id=?',(new_status,order_id)); conn.commit(); conn.close()
                try:
                    send_telegram_message(row['telegram_id'], f'📌 <b>Статус заказа #{order_id} изменён</b>\n\nНовый статус: <b>{STATUSES[new_status]}</b>')
                    flash('Статус изменён, клиент уведомлён в Telegram.')
                except Exception as e:
                    flash(f'Статус изменён, но уведомление не отправлено: {e}')
            elif action == 'message':
                message = request.form.get('message','').strip()
                if not message: raise ValueError('Напиши текст сообщения')
                send_telegram_message(row['telegram_id'], f'💬 <b>Сообщение от Lunevia</b>\n\n{html_escape(message)}')
                flash('Сообщение отправлено клиенту в Telegram.')
            elif action == 'approve':
                conn = db(); conn.execute("UPDATE orders SET status='in_progress' WHERE id=?",(order_id,)); conn.commit(); conn.close()
                send_telegram_message(row['telegram_id'], f'🎉 <b>Оплата заказа #{order_id} подтверждена!</b>\n\nВаш сайт уже в процессе создания. 💙')
                flash('Оплата подтверждена, клиент уведомлён.')
            elif action == 'reject':
                conn = db(); conn.execute("UPDATE orders SET status='payment_rejected' WHERE id=?",(order_id,)); conn.commit(); conn.close()
                send_telegram_message(row['telegram_id'], f'❌ <b>Оплата заказа #{order_id} не подтверждена.</b>\n\nПроверьте квитанцию или свяжитесь с поддержкой.')
                flash('Оплата отклонена, клиент уведомлён.')
        except Exception as e:
            flash(f'Не удалось выполнить действие: {e}')
        return redirect(url_for('order_detail', order_id=order_id))
    conn = db(); row = conn.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone(); conn.close()
    username = '@'+row['username'] if row['username'] else 'без username'
    fields = [('Клиент',html_escape(username)),('Telegram ID',f'<code>{row["telegram_id"]}</code>'),('Тип сайта',html_escape(row['site_type'] or '—')),('Тариф',html_escape(row['tariff'] or '—')),('Цена',f'<b>{row["price"] or 0} грн</b>'),('Для кого',html_escape(row['recipient_name'] or '—')),('Дата события',html_escape(row['event_date'] or '—')),('Фотографий',str(row['photo_count'] or 0)),('Дизайн',html_escape(row['design'] or '—')),('Создан',html_escape(row['created_at'] or '—'))]
    detail = ''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k,v in fields)
    options = ''.join(f'<option value="{k}" {"selected" if row["status"]==k else ""}>{v}</option>' for k,v in STATUSES.items())
    receipt = f'<p><a class="btn" href="{url_for("receipt",order_id=order_id)}" target="_blank">Открыть квитанцию ↗</a></p>' if row['receipt_file_id'] else '<p class="muted">Квитанция не прикреплена к заказу.</p>'
    custom_text = html_escape(row['custom_text'] or '—').replace('\n','<br>')
    body = f'''<div class="section-head"><div><h2>Заказ #{order_id}</h2><div class="muted">Карточка клиента и управление заказом</div></div><a class="btn" href="{url_for('orders')}">← К списку</a></div><div class="two"><div class="card"><div class="section-head"><h2>Информация</h2>{status_pill(row['status'])}</div><dl class="detail-list">{detail}</dl><hr style="border:0;border-top:1px solid var(--line);margin:20px 0"><h3>Текст для сайта</h3><div style="overflow-wrap:anywhere">{custom_text}</div><div class="section"><h3>Квитанция оплаты</h3>{receipt}</div></div><div><div class="card"><h2 style="margin-top:0">Статус заказа</h2><form method="post"><input type="hidden" name="action" value="status"><select class="full" name="status">{options}</select><button class="primary full" style="margin-top:10px" type="submit">Сохранить статус</button></form><div class="actions section"><form method="post"><input type="hidden" name="action" value="approve"><button type="submit">✓ Подтвердить оплату</button></form><form method="post"><input type="hidden" name="action" value="reject"><button type="submit">✕ Отклонить оплату</button></form></div></div><div class="card section"><h2 style="margin-top:0">Написать клиенту</h2><p class="muted small">Сообщение отправится через Telegram-бота в чат клиента.</p><form method="post"><input type="hidden" name="action" value="message"><textarea name="message" required placeholder="Напиши клиенту..."></textarea><button class="primary full" style="margin-top:10px" type="submit">Отправить сообщение ↗</button></form></div></div></div>'''
    return layout(f'Заказ #{order_id}', body)

@app.route('/orders/<int:order_id>/receipt')
@login_required
def receipt(order_id):
    conn = db(); row = conn.execute('SELECT receipt_file_id FROM orders WHERE id=?',(order_id,)).fetchone(); conn.close()
    if not row or not row['receipt_file_id']:
        abort(404)
    try:
        file_info = telegram_api('getFile', {'file_id':row['receipt_file_id']})
        file_path = file_info.get('file_path')
        if not file_path: abort(404)
        url = f'https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
            content_type = resp.headers.get('Content-Type','image/jpeg')
        return send_file(BytesIO(data), mimetype=content_type, download_name=f'order-{order_id}-receipt')
    except Exception as e:
        return f'Не удалось загрузить квитанцию: {html_escape(e)}', 502

if __name__ == '__main__':
    if not ADMIN_PASSWORD:
        raise SystemExit('Задайте ADMIN_PASSWORD в переменных окружения')
    port = int(os.getenv('PORT','10000'))
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)


def run_admin_web():
    port = int(os.getenv('PORT', '10000'))
    print(f'🌐 Lunevia Admin запущена на порту {port}')
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
