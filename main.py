# SalesRep AI Zambia v2.3 (report format, photo product detection, daily reminders)
# Android-first personal sales assistant for Pydroid 3 (Kivy). Single file.
#
# What's new in v2.0:
#   - Products and stock levels, low-stock alerts, restock entry
#   - Orders and quotations: create, confirm, mark delivered, cancel
#     (stock updates automatically)
#   - Customer messages: restock reminder, order confirmation, quotation,
#     follow-up. Open them in WhatsApp and send them yourself.
#   - Performance analytics: orders by shop, fastest-selling products,
#     visit-to-order conversion, weekly sales chart
#   - Offline AI Sales Coach with built-in guidance and a priority follow-up list
#   - Backups no longer include your API key
#
# Your v1.0 data (customers, visits, reports, settings) is kept. v2.0 uses
# the same database file.
#
# Requirements: Python 3 + Kivy. Offline features need no API key or internet.
# Optional online AI uses an OpenAI-compatible Chat Completions endpoint.

import os
import re
import json
import base64
import shutil
import sqlite3
import threading
import webbrowser
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, date, timedelta

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex

APP_NAME = "SalesRep AI Zambia"
VERSION = "2.3"
DB_NAME = "salesrep_ai_zambia.db"  # same file as v1.0, so existing data is kept
CURRENCY = "K"
ORDER_STATUSES = ["Quoted", "Confirmed", "Delivered", "Cancelled"]
TEMPLATES = ["Restock reminder", "Order confirmation", "Quotation", "Follow-up"]
DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"

NAVY = get_color_from_hex("#102A43")
BLUE = get_color_from_hex("#2878C8")
PALE = get_color_from_hex("#F2F6FA")
WHITE = get_color_from_hex("#FFFFFF")
DARK = get_color_from_hex("#243B53")
MUTED = get_color_from_hex("#627D98")
GREEN = get_color_from_hex("#238636")
RED = get_color_from_hex("#B42318")
DEEP = get_color_from_hex("#0A1B2C")
TAB = get_color_from_hex("#1B3A57")
TEAL = get_color_from_hex("#0E9F8E")
GOLD = get_color_from_hex("#B7791F")
SKY = get_color_from_hex("#9FC5E8")

Window.clearcolor = PALE


def paint_round(widget, color, radius=14):
    # Rounded background that follows the widget's position and size.
    with widget.canvas.before:
        fill = Color(*color)
        rect = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])

    def follow(*_):
        rect.pos = widget.pos
        rect.size = widget.size

    widget.bind(pos=follow, size=follow)
    return fill


class FlatButton(Button):
    # Rounded button that darkens slightly while pressed.

    def __init__(self, bg=BLUE, radius=14, **kwargs):
        super().__init__(background_normal="", background_down="",
                         background_color=(0, 0, 0, 0), color=WHITE, bold=True, **kwargs)
        self.bg = bg
        self._fill = paint_round(self, bg, radius)
        self.bind(state=self._on_state)

    def set_bg(self, color):
        self.bg = color
        self._on_state(self, self.state)

    def _on_state(self, _inst, state):
        k = 0.82 if state == "down" else 1.0
        self._fill.rgba = (self.bg[0] * k, self.bg[1] * k, self.bg[2] * k, 1)


def left_label(text, color=DARK, size="14sp", bold=False):
    lbl = Label(text=text, color=color, font_size=size, bold=bold,
                halign="left", valign="middle")
    lbl.bind(size=lambda inst, val: setattr(inst, "text_size", val))
    return lbl


def stat_card(title, value, accent):
    card = BoxLayout(orientation="vertical", padding=(dp(14), dp(10)), spacing=dp(2))
    paint_round(card, WHITE, 16)
    card.add_widget(left_label(value, accent, "22sp", True))
    card.add_widget(left_label(title, MUTED, "12sp"))
    return card


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today_iso():
    return date.today().isoformat()


def week_start(d):
    return d - timedelta(days=d.weekday())


def money(value):
    return f"{CURRENCY}{float(value or 0):,.2f}"


def to_float(text, default=0.0):
    try:
        return float(str(text).replace(",", "").strip())
    except ValueError:
        return default


def to_int(text, default=0):
    try:
        return int(float(str(text).strip()))
    except ValueError:
        return default


def valid_date(text):
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def parse_date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def normalize_phone(raw):
    """Turn a Zambian number like 0977 123 456 into 260977123456 for WhatsApp."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if digits.startswith("260"):
        return digits
    if digits.startswith("0"):
        return "260" + digits[1:]
    if len(digits) == 9:
        return "260" + digits
    return digits


def wrap_label(text, color=DARK, size=14, bold=False, halign="left"):
    """Label that wraps text and grows in height to fit."""
    lbl = Label(text=str(text), color=color, font_size=f"{size}sp", bold=bold,
                halign=halign, valign="top", size_hint_y=None)
    lbl.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
    lbl.bind(texture_size=lambda inst, ts: setattr(inst, "height", ts[1] + dp(6)))
    return lbl


def auto_box(spacing=4, padding=8):
    """Vertical box that grows to fit its children."""
    box = GridLayout(cols=1, spacing=dp(spacing), padding=dp(padding), size_hint_y=None)
    box.bind(minimum_height=box.setter("height"))
    return box


def popup_message(title, message):
    box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
    scroll = ScrollView()
    scroll.add_widget(wrap_label(message, DARK, 14))
    box.add_widget(scroll)
    close_btn = make_button("Close", None, BLUE)
    box.add_widget(close_btn)
    pop = Popup(title=title, title_color=NAVY, title_size="17sp", separator_color=BLUE,
                content=box, size_hint=(0.9, 0.55), auto_dismiss=True)
    close_btn.bind(on_release=pop.dismiss)
    pop.open()


def make_button(text, callback=None, color=BLUE, height=46, font_size="15sp"):
    btn = FlatButton(bg=color, text=text, size_hint_y=None, height=dp(height),
                     font_size=font_size)
    if callback:
        btn.bind(on_release=callback)
    return btn


def make_input(hint, multiline=False, text="", height=46):
    field = TextInput(
        hint_text=hint, text=text, multiline=multiline,
        size_hint_y=None, height=dp(height),
        padding=(dp(12), dp(12)), foreground_color=DARK,
        background_color=WHITE, cursor_color=BLUE,
        hint_text_color=MUTED, font_size="15sp"
    )
    return field


def make_spinner(values, text):
    return Spinner(text=text, values=values, size_hint_y=None, height=dp(46),
                   background_normal="", background_color=WHITE, color=DARK,
                   font_size="15sp")


def customer_label(c):
    return f"{c['shop'] or c['name']} (#{c['id']})"


def product_label(p):
    return f"{p['name']} • {money(p['unit_price'])} • stock {p['stock_qty']}"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.setup()

    def setup(self):
        with self.lock:
            c = self.conn.cursor()
            # v1.0 tables (kept as they were)
            c.execute("""CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, shop TEXT, phone TEXT, location TEXT,
                products TEXT, notes TEXT, created_at TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER, shop_name TEXT NOT NULL, visit_date TEXT,
                purpose TEXT, outcome TEXT, follow_up_date TEXT,
                status TEXT NOT NULL DEFAULT 'Planned', notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(customer_id) REFERENCES customers(id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, report_type TEXT, body TEXT NOT NULL,
                created_at TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT)""")
            # v2.0 tables
            c.execute("""CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, category TEXT, unit_price REAL NOT NULL DEFAULT 0,
                stock_qty INTEGER NOT NULL DEFAULT 0, reorder_level INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER, visit_id INTEGER, shop_name TEXT NOT NULL,
                order_date TEXT NOT NULL, status TEXT NOT NULL,
                total REAL NOT NULL DEFAULT 0, notes TEXT, created_at TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL, product_id INTEGER,
                product_name TEXT NOT NULL, qty INTEGER NOT NULL,
                unit_price REAL NOT NULL, line_total REAL NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS message_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER, shop_name TEXT, template TEXT,
                body TEXT NOT NULL, created_at TEXT NOT NULL)""")
            self.conn.commit()

    def all(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def run(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def get_setting(self, key, default=""):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row and row["value"] is not None else default

    def set_setting(self, key, value):
        self.run("INSERT INTO settings(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ---------------------------------------------------------------------------
# Business logic (no UI). Stock and order changes happen in one transaction.
# ---------------------------------------------------------------------------

def _check_stock(cur, items):
    for item in items:
        if item["product_id"] is None:
            continue
        row = cur.execute("SELECT name, stock_qty FROM products WHERE id=?",
                          (item["product_id"],)).fetchone()
        if row is not None and row["stock_qty"] < item["qty"]:
            raise ValueError(f"Not enough stock for {row['name']}: "
                             f"{row['stock_qty']} left, {item['qty']} needed.")


def _move_stock(cur, items, direction):
    """direction = -1 takes stock out, +1 puts it back."""
    for item in items:
        if item["product_id"] is None:
            continue
        cur.execute("UPDATE products SET stock_qty = stock_qty + ? WHERE id=?",
                    (direction * item["qty"], item["product_id"]))


def create_order(db, customer_id, shop, order_date, status, notes, visit_id, items):
    if not items:
        raise ValueError("Add at least one product to the order.")
    if status not in ("Quoted", "Confirmed"):
        raise ValueError("A new order can only be saved as a quotation or as confirmed.")
    total = sum(i["qty"] * i["unit_price"] for i in items)
    with db.lock:
        cur = db.conn.cursor()
        try:
            if status == "Confirmed":
                _check_stock(cur, items)
            cur.execute(
                "INSERT INTO orders(customer_id,visit_id,shop_name,order_date,status,total,notes,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (customer_id, visit_id, shop, order_date, status, total, notes, now_text()))
            order_id = cur.lastrowid
            for i in items:
                cur.execute(
                    "INSERT INTO order_items(order_id,product_id,product_name,qty,unit_price,line_total) "
                    "VALUES(?,?,?,?,?,?)",
                    (order_id, i["product_id"], i["product_name"], i["qty"],
                     i["unit_price"], i["qty"] * i["unit_price"]))
            if status == "Confirmed":
                _move_stock(cur, items, -1)
            db.conn.commit()
            return order_id
        except Exception:
            db.conn.rollback()
            raise


def change_order_status(db, order_id, new_status):
    with db.lock:
        cur = db.conn.cursor()
        try:
            order = cur.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
            if order is None:
                raise ValueError("Order not found.")
            old = order["status"]
            if old == new_status:
                return
            if old == "Cancelled":
                raise ValueError("A cancelled order cannot be reopened. Create a new order instead.")
            if new_status == "Quoted":
                raise ValueError("An order cannot go back to a quotation. Create a new quotation instead.")
            items = cur.execute("SELECT product_id, qty FROM order_items WHERE order_id=?",
                                (order_id,)).fetchall()
            if new_status == "Confirmed":
                if old != "Quoted":
                    raise ValueError("Only a quotation can be confirmed.")
                _check_stock(cur, items)
                _move_stock(cur, items, -1)
            elif new_status == "Delivered":
                if old != "Confirmed":
                    raise ValueError("Confirm the order before marking it delivered.")
            elif new_status == "Cancelled":
                if old in ("Confirmed", "Delivered"):
                    _move_stock(cur, items, +1)
            cur.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
            db.conn.commit()
        except Exception:
            db.conn.rollback()
            raise


def low_stock_products(db):
    return db.all("SELECT * FROM products WHERE stock_qty <= reorder_level "
                  "ORDER BY stock_qty ASC, name COLLATE NOCASE")


def order_items(db, order_id):
    return db.all("SELECT * FROM order_items WHERE order_id=? ORDER BY id", (order_id,))


def latest_order_for(db, customer_id):
    return db.one("SELECT * FROM orders WHERE customer_id=? ORDER BY order_date DESC, id DESC LIMIT 1",
                  (customer_id,))


def sales_by_week(db, weeks=8):
    start = week_start(date.today()) - timedelta(weeks=weeks - 1)
    rows = db.all("SELECT order_date, total FROM orders WHERE status!='Cancelled' AND order_date>=?",
                  (start.isoformat(),))
    buckets = {start + timedelta(weeks=i): [0.0, 0] for i in range(weeks)}
    for r in rows:
        d = parse_date(r["order_date"])
        if d is None:
            continue
        ws = week_start(d)
        if ws in buckets:
            buckets[ws][0] += r["total"] or 0
            buckets[ws][1] += 1
    return [(ws, v[0], v[1]) for ws, v in sorted(buckets.items())]


def follow_up_priorities(db):
    today = date.today()
    items = []  # (priority, shop, reason). Lower priority number = act first.
    overdue = db.all("SELECT shop_name, follow_up_date FROM visits "
                     "WHERE status!='Completed' AND follow_up_date!='' AND follow_up_date<=? "
                     "ORDER BY follow_up_date", (today.isoformat(),))
    for r in overdue:
        items.append((0, r["shop_name"], f"follow-up was due {r['follow_up_date']}"))
    last = {r["shop_name"]: r["last"] for r in db.all(
        "SELECT shop_name, MAX(order_date) AS last FROM orders WHERE status!='Cancelled' GROUP BY shop_name")}
    for c in db.all("SELECT shop, name FROM customers"):
        shop = c["shop"] or c["name"]
        d = parse_date(last.get(shop))
        if d is None:
            items.append((2, shop, "has never ordered"))
        else:
            days = (today - d).days
            if days > 30:
                items.append((1, shop, f"last order {days} days ago"))
    items.sort(key=lambda x: x[0])
    seen, result = set(), []
    for _, shop, reason in items:
        if shop in seen:
            continue
        seen.add(shop)
        result.append(f"{len(result) + 1}. {shop}: {reason}")
    return result[:10]


COACH_ANSWERS = {
    "accessories": (
        "Make it easy to say yes. Offer a small trial display of your best-selling accessories "
        "or a small starter order, and show the owner the margin they earn per item. "
        "Suggest a spot near the counter where customers pay. Come back in two weeks "
        "to check sales together and decide on the next order."),
    "competitor": (
        "Stay calm and never criticise the other supplier. Ask what the shop likes about "
        "their current supplier, then listen. Focus on what you can do better: faster restocking, "
        "reliable availability, flexible quantities, or help with display. Suggest a small trial "
        "order so the shop can compare your products with little risk."),
    "price": (
        "Avoid cutting price first. Explain the value: quality, warranty, faster sell-through, "
        "and how the margin works for them. If they push on price, offer a bundle or a bulk-quantity "
        "bonus instead of a straight discount, and only if your company allows it."),
    "restock": (
        "Start with the Products screen to see what is low in your stock. Then open Messages, "
        "choose the customer and send a Restock reminder. It lists what they last bought and asks "
        "for quantities. Reaching shops before they run out is the easiest way to get repeat orders."),
    "quotation": (
        "Send a clear quotation with items, quantities, unit prices, total and a validity period. "
        "State that availability is subject to stock at the time of order. Ask the shop to confirm, "
        "and offer to adjust quantities if that helps."),
    "close": (
        "When the shop shows interest, ask one direct, friendly question: 'Shall I prepare "
        "10 units for you today?' Offer two simple choices, such as two quantities or two delivery "
        "days, rather than an open question. If they hesitate, ask what would make the decision easier."),
    "default": (
        "I can help with accessories, competitors, pricing, restocking, quotations, closing a sale "
        "and follow-ups. Try asking one of those, or tap a question above."),
}

COACH_RULES = [
    (("accessor",), "accessories"),
    (("competit", "rival", "other supplier"), "competitor"),
    (("price", "expensive", "cheap", "discount"), "price"),
    (("restock", "low stock", "running out"), "restock"),
    (("quot",), "quotation"),
    (("close", "convince", "decide", "order"), "close"),
]

COACH_PRESETS = [
    "How can I convince a shop to stock our accessories?",
    "What should I say when a customer prefers a competitor?",
    "Which customers should I follow up with first?",
    "How should I handle price objections?",
    "How do I restock a shop?",
    "How do I close a sale?",
]


def coach_answer(db, question):
    q = question.lower()
    if "follow" in q:
        lines = follow_up_priorities(db)
        if lines:
            return ("Follow up in this order:\n" + "\n".join(lines) +
                    "\n\nStart with overdue follow-ups, then customers who have not ordered recently.")
        return ("No overdue follow-ups or lapsed customers right now. This is a good time to "
                "visit a shop that is not yet buying from you.")
    for keywords, key in COACH_RULES:
        if any(k in q for k in keywords):
            return COACH_ANSWERS[key]
    return COACH_ANSWERS["default"]


def build_message(db, template, customer, order, rep):
    """Return the message text, or None if the template needs an order that isn't chosen."""
    contact = customer["name"] or "there"
    shop = customer["shop"] or customer["name"]

    if template == "Restock reminder":
        last = order or latest_order_for(db, customer["id"])
        if last is None:
            return (f"Good day {contact}, this is {rep}. I hope business at {shop} is going well.\n\n"
                    "I would like to check whether you need a restock on our range. "
                    "Please let me know what you need and I will prepare it for you. "
                    "Thank you for your continued support.")
        lines = "\n".join(f"- {i['qty']} x {i['product_name']}" for i in order_items(db, last["id"]))
        days = (date.today() - (parse_date(last["order_date"]) or date.today())).days
        return (f"Good day {contact}, this is {rep}. I hope business at {shop} is going well.\n\n"
                f"Your last order with us was on {last['order_date']} ({days} days ago):\n{lines}\n\n"
                "If you are running low, please let me know the quantities you need and "
                "I will prepare the restock for you. Thank you for your continued support.")

    if template == "Order confirmation":
        if order is None:
            return None
        lines = "\n".join(f"- {i['qty']} x {i['product_name']} ({money(i['line_total'])})"
                          for i in order_items(db, order["id"]))
        return (f"Dear {contact}, thank you for your order with us.\n\n"
                f"Order #{order['id']} for {shop}, dated {order['order_date']}:\n{lines}\n\n"
                f"Total: {money(order['total'])}\nStatus: {order['status']}\n\n"
                "If anything needs changing, please let me know and I will be happy to help. "
                "Thank you for your business.")

    if template == "Quotation":
        if order is None:
            return None
        lines = "\n".join(f"- {i['qty']} x {i['product_name']} ({money(i['line_total'])})"
                          for i in order_items(db, order["id"]))
        return (f"Dear {contact}, thank you for the opportunity to quote for {shop}. "
                "Please find our quotation below:\n"
                f"{lines}\n\nTotal: {money(order['total'])}\n\n"
                f"This quotation is valid for 7 days from {order['order_date']} and is subject to "
                "stock availability at the time of order. Please reply to confirm or let me know "
                f"if you need changes.\n\nKind regards,\n{rep}")

    if template == "Follow-up":
        visit = db.one("SELECT purpose FROM visits WHERE shop_name=? ORDER BY visit_date DESC, id DESC LIMIT 1",
                       (shop,))
        detail = (f"When we last spoke, we discussed {visit['purpose']}."
                  if visit and visit["purpose"] else
                  "I would like to hear how things are going with your business.")
        return (f"Dear {contact}, I hope you are well. I am following up on our recent visit to {shop}. "
                f"{detail}\n\nPlease let me know a convenient time to talk, or whether there is "
                "anything I can help with. Thank you.")
    return None


def ask_online_ai(db, system_prompt, user_prompt, on_text, on_error, image_data_uri=None):
    """Call the configured OpenAI-compatible endpoint in a background thread."""
    api_key = db.get_setting("ai_api_key", "").strip()
    endpoint = db.get_setting("ai_endpoint", DEFAULT_ENDPOINT).strip()
    model = db.get_setting("ai_model", DEFAULT_MODEL).strip()

    def worker():
        try:
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": (user_prompt if not image_data_uri else [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": image_data_uri}}])}
                ],
                "temperature": 0.2
            }).encode("utf-8")
            req = urllib.request.Request(endpoint, data=payload, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key
            }, method="POST")
            with urllib.request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"].strip()
            Clock.schedule_once(lambda dt: on_text(text), 0)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:500]
            except Exception:
                pass
            msg = f"Online AI error (HTTP {e.code}). Check API key, model and endpoint.\n{detail}"
            Clock.schedule_once(lambda dt: on_error(msg), 0)
        except Exception as e:
            msg = f"Could not reach online AI: {e}\nThe offline version is still available."
            Clock.schedule_once(lambda dt: on_error(msg), 0)

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class BarChart(Widget):
    def __init__(self, values, **kwargs):
        super().__init__(**kwargs)
        self.values = values
        self.size_hint_y = None
        self.height = dp(150)
        self.bind(pos=self.redraw, size=self.redraw)

    def redraw(self, *_):
        self.canvas.clear()
        if not self.values or max(self.values) <= 0:
            return
        top = max(self.values)
        slot = self.width / len(self.values)
        bar_w = slot * 0.6
        base = self.y + dp(4)
        usable = self.height - dp(8)
        with self.canvas:
            Color(*BLUE)
            for i, v in enumerate(self.values):
                if v <= 0:
                    continue
                h = max(usable * v / top, dp(2))
                RoundedRectangle(pos=(self.x + i * slot + (slot - bar_w) / 2, base),
                                 size=(bar_w, h), radius=[dp(5)])


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

class BaseScreen(Screen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app
        self.root_box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        self.add_widget(self.root_box)

    def on_pre_enter(self, *args):
        self.rebuild()

    def title_text(self):
        return self.name.replace("_", " ").title()

    def rebuild(self):
        self.root_box.clear_widgets()
        header = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        title = Label(text=self.title_text(), color=NAVY, bold=True, font_size="22sp",
                      halign="left", valign="middle")
        title.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        header.add_widget(title)
        home = make_button("Home", lambda *_: self.app_ref.show_screen("dashboard"), NAVY, 38, "13sp")
        home.size_hint_x = None
        home.width = dp(84)
        header.add_widget(home)
        self.root_box.add_widget(header)
        accent = Widget(size_hint_y=None, height=dp(3))
        paint_round(accent, BLUE, 2)
        self.root_box.add_widget(accent)

        scroll = ScrollView()
        self.body = BoxLayout(orientation="vertical", spacing=dp(8), padding=(0, dp(2)),
                              size_hint_y=None)
        self.body.bind(minimum_height=self.body.setter("height"))
        scroll.add_widget(self.body)
        self.root_box.add_widget(scroll)
        self.build(self.body)

    def build(self, body):
        raise NotImplementedError

    def heading(self, text, color=NAVY):
        return wrap_label(text, color, 16, True)

    def note(self, text):
        return wrap_label(text, MUTED, 12)


class DashboardScreen(BaseScreen):
    def title_text(self):
        return "Home"

    def build(self, body):
        db = self.app_ref.db
        today = date.today()
        ws = week_start(today).isoformat()
        customers = db.one("SELECT COUNT(*) n FROM customers")["n"]
        week = db.one("SELECT COUNT(*) n, COALESCE(SUM(total),0) s FROM orders "
                      "WHERE status!='Cancelled' AND order_date>=?", (ws,))
        quotes = db.one("SELECT COUNT(*) n FROM orders WHERE status='Quoted'")["n"]
        due = db.one("SELECT COUNT(*) n FROM visits WHERE follow_up_date!='' AND follow_up_date<=? "
                     "AND status!='Completed'", (today.isoformat(),))["n"]
        low = len(low_stock_products(db))

        hour = datetime.now().hour
        greet = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
        rep_name = db.get_setting("rep_name", "").strip()
        hero = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(104),
                         padding=(dp(18), dp(12)), spacing=dp(2))
        paint_round(hero, NAVY, 18)
        hero.add_widget(left_label(f"{greet}, {rep_name}" if rep_name else greet, WHITE, "21sp", True))
        hero.add_widget(left_label(today.strftime("%A, %d %B %Y"), SKY, "13sp"))
        hero.add_widget(left_label(f"{week['n']} orders this week  •  {money(week['s'])} in sales",
                                   WHITE, "13sp"))
        body.add_widget(hero)

        rows = 3
        cards = GridLayout(cols=2, spacing=dp(10), size_hint_y=None,
                           height=dp(rows * 96 + (rows - 1) * 10))
        for title, value, accent in [
            ("Customers", str(customers), BLUE),
            ("Sales this week", money(week["s"]), GREEN),
            ("Orders this week", str(week["n"]), TEAL),
            ("Open quotations", str(quotes), GOLD),
            ("Follow-ups due", str(due), RED if due else MUTED),
            ("Low-stock products", str(low), RED if low else MUTED),
        ]:
            cards.add_widget(stat_card(title, value, accent))
        body.add_widget(cards)

        body.add_widget(self.heading("Quick actions"))
        app = self.app_ref
        body.add_widget(make_button("＋ New order or quotation", lambda *_: app.show_screen("orders")))
        body.add_widget(make_button("＋ Plan a shop visit", lambda *_: app.show_screen("visits")))
        body.add_widget(make_button("✉ Customer messages", lambda *_: app.show_screen("messages"), BLUE))
        body.add_widget(make_button("✎ Create sales visit report", lambda *_: app.show_screen("reports"), BLUE))
        body.add_widget(make_button("🔔 Today's reminders", lambda *_: app.run_reminders(manual=True), TEAL))
        body.add_widget(make_button("📈 Analytics", lambda *_: app.show_screen("analytics"), NAVY))
        body.add_widget(make_button("💬 Sales coach", lambda *_: app.show_screen("coach"), NAVY))
        body.add_widget(self.note("Offline mode is ready. Your records are saved on this phone."))


class CustomersScreen(BaseScreen):
    def title_text(self):
        return "Customers"

    def build(self, body):
        body.add_widget(self.heading("Add a customer or shop", BLUE))
        self.name_in = make_input("Contact person / owner name")
        self.shop_in = make_input("Shop / business name *")
        self.phone_in = make_input("Phone or WhatsApp number (e.g. 0977 123456)")
        self.location_in = make_input("Location / road / area")
        self.products_in = make_input("Products of interest (optional)")
        self.notes_in = make_input("Notes (optional)", multiline=True, height=70)
        for w in (self.name_in, self.shop_in, self.phone_in, self.location_in,
                  self.products_in, self.notes_in):
            body.add_widget(w)
        body.add_widget(make_button("Save customer", self.save_customer, GREEN))

        body.add_widget(self.heading("Saved customers"))
        rows = self.app_ref.db.all("SELECT * FROM customers ORDER BY shop COLLATE NOCASE")
        if not rows:
            body.add_widget(self.note("No customers yet. Add your first shop above."))
        for row in rows:
            body.add_widget(self.customer_card(row))

    def customer_card(self, row):
        card = auto_box()
        card.add_widget(wrap_label(row["shop"] or row["name"], NAVY, 15, True))
        card.add_widget(wrap_label(
            f"Contact: {row['name'] or '—'}  |  Phone: {row['phone'] or '—'}\n"
            f"Location: {row['location'] or '—'}", DARK, 12))
        actions = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
        actions.add_widget(make_button("Visit", lambda *_: self.go(row, "visits"), BLUE, 38, "12sp"))
        actions.add_widget(make_button("Order", lambda *_: self.go(row, "orders"), GREEN, 38, "12sp"))
        actions.add_widget(make_button("Message", lambda *_: self.go(row, "messages"), NAVY, 38, "12sp"))
        actions.add_widget(make_button("Delete", lambda *_: self.delete_customer(row), RED, 38, "12sp"))
        card.add_widget(actions)
        return card

    def save_customer(self, *_):
        shop = self.shop_in.text.strip()
        if not shop:
            popup_message("Missing shop name", "Please enter a shop or business name.")
            return
        self.app_ref.db.run(
            "INSERT INTO customers(name,shop,phone,location,products,notes,created_at) VALUES(?,?,?,?,?,?,?)",
            (self.name_in.text.strip(), shop, self.phone_in.text.strip(),
             self.location_in.text.strip(), self.products_in.text.strip(),
             self.notes_in.text.strip(), now_text()))
        self.rebuild()
        popup_message("Saved", f"{shop} has been saved on this phone.")

    def go(self, row, screen):
        self.app_ref.set_pending(customer_id=row["id"], shop=row["shop"] or row["name"])
        self.app_ref.show_screen(screen)

    def delete_customer(self, row):
        self.app_ref.db.run("DELETE FROM customers WHERE id=?", (row["id"],))
        self.rebuild()
        popup_message("Deleted", "Customer record deleted. Visit and order history is kept.")


class VisitsScreen(BaseScreen):
    def title_text(self):
        return "Visits"

    def build(self, body):
        app = self.app_ref
        body.add_widget(self.heading("Plan a shop visit", BLUE))
        self.shop_in = make_input("Shop name *", text=app.pending_shop)
        self.date_in = make_input("Visit date (YYYY-MM-DD)", text=today_iso())
        self.purpose_in = make_input("Purpose (e.g. introduce accessories / collect order)")
        self.outcome_in = make_input("Visit outcome / owner's response", multiline=True, height=70)
        self.follow_in = make_input("Follow-up date (YYYY-MM-DD, optional)")
        self.notes_in = make_input("Additional notes (optional)", multiline=True, height=60)
        for w in (self.shop_in, self.date_in, self.purpose_in, self.outcome_in,
                  self.follow_in, self.notes_in):
            body.add_widget(w)
        body.add_widget(make_button("Save visit", self.save_visit, GREEN))

        body.add_widget(self.heading("Visit plan and history"))
        rows = app.db.all("SELECT * FROM visits ORDER BY visit_date DESC, id DESC")
        if not rows:
            body.add_widget(self.note("No visits yet. Plan your first shop visit above."))
        for row in rows:
            body.add_widget(self.visit_card(row))

    def visit_card(self, row):
        card = auto_box()
        card.add_widget(wrap_label(f"{row['shop_name']}  •  {row['status']}", NAVY, 14, True))
        card.add_widget(wrap_label(
            f"Date: {row['visit_date'] or '—'} | Follow-up: {row['follow_up_date'] or '—'}\n"
            f"Purpose: {row['purpose'] or '—'}\nOutcome: {row['outcome'] or 'Not recorded'}", DARK, 12))
        actions = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
        if row["status"] != "Completed":
            actions.add_widget(make_button("Done", lambda *_: self.complete_visit(row), GREEN, 38, "12sp"))
        actions.add_widget(make_button("Order", lambda *_: self.order_from(row), BLUE, 38, "12sp"))
        actions.add_widget(make_button("Report", lambda *_: self.use_in_report(row), NAVY, 38, "12sp"))
        actions.add_widget(make_button("Delete", lambda *_: self.delete_visit(row), RED, 38, "12sp"))
        card.add_widget(actions)
        return card

    def save_visit(self, *_):
        app = self.app_ref
        shop = self.shop_in.text.strip()
        if not shop:
            popup_message("Missing shop name", "Enter the shop name for this visit.")
            return
        visit_date = self.date_in.text.strip()
        follow = self.follow_in.text.strip()
        for value, title in [(visit_date, "visit date"), (follow, "follow-up date")]:
            if value and not valid_date(value):
                popup_message("Date format", f"Please enter {title} as YYYY-MM-DD.")
                return
        app.db.run(
            "INSERT INTO visits(customer_id,shop_name,visit_date,purpose,outcome,follow_up_date,status,notes,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (app.pending_customer_id, shop, visit_date,
             self.purpose_in.text.strip(), self.outcome_in.text.strip(), follow,
             "Planned", self.notes_in.text.strip(), now_text()))
        app.set_pending()
        self.rebuild()
        popup_message("Visit saved", f"Visit for {shop} has been saved.")

    def complete_visit(self, row):
        self.app_ref.db.run("UPDATE visits SET status='Completed' WHERE id=?", (row["id"],))
        self.rebuild()

    def order_from(self, row):
        self.app_ref.set_pending(customer_id=row["customer_id"], shop=row["shop_name"], visit_id=row["id"])
        self.app_ref.show_screen("orders")

    def use_in_report(self, row):
        self.app_ref.report_visit = dict(row)
        self.app_ref.show_screen("reports")

    def delete_visit(self, row):
        self.app_ref.db.run("DELETE FROM visits WHERE id=?", (row["id"],))
        self.rebuild()


class OrdersScreen(BaseScreen):
    def title_text(self):
        return "Orders"

    def build(self, body):
        app = self.app_ref
        db = app.db
        customers = db.all("SELECT id, shop, name FROM customers ORDER BY shop COLLATE NOCASE")
        products = db.all("SELECT * FROM products ORDER BY name COLLATE NOCASE")

        body.add_widget(self.heading("New order or quotation", BLUE))
        if not customers or not products:
            body.add_widget(self.note("Add at least one customer (Customers) and one product (Products) "
                                      "before creating an order."))

        self.cust_map = {customer_label(c): c for c in customers}
        default_cust = next((l for l, c in self.cust_map.items()
                             if c["id"] == app.pending_customer_id), "Select customer")
        self.cust_spin = make_spinner(list(self.cust_map) or ["No customers yet"], default_cust)
        body.add_widget(self.cust_spin)

        self.prod_map = {product_label(p): p for p in products}
        self.prod_spin = make_spinner(list(self.prod_map) or ["No products yet"], "Select product")
        body.add_widget(self.prod_spin)
        self.qty_in = make_input("Quantity", text="1")
        self.qty_in.input_filter = "int"
        body.add_widget(self.qty_in)
        body.add_widget(make_button("Add item to order", self.add_item, BLUE))

        for idx, item in enumerate(app.draft_items):
            row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
            row.add_widget(wrap_label(
                f"{item['qty']} × {item['product_name']} = {money(item['qty'] * item['unit_price'])}",
                DARK, 13))
            row.add_widget(make_button("Remove", lambda _b, i=idx: self.remove_item(i), RED, 40, "12sp"))
            body.add_widget(row)
        draft_total = sum(i["qty"] * i["unit_price"] for i in app.draft_items)
        body.add_widget(wrap_label(f"Order total: {money(draft_total)}", NAVY, 15, True))

        self.date_in = make_input("Order date (YYYY-MM-DD)", text=today_iso())
        self.status_spin = make_spinner(["Quoted", "Confirmed"], "Quoted")
        self.notes_in = make_input("Notes, delivery or payment terms (optional)", multiline=True, height=60)
        for w in (self.date_in, self.status_spin, self.notes_in):
            body.add_widget(w)
        body.add_widget(make_button("Save order", self.save_order, GREEN))
        body.add_widget(self.note("Quotation: saved without touching stock. Confirmed: stock is taken out "
                                  "now. Save as Quoted and confirm later if you are not sure."))

        body.add_widget(self.heading("Orders"))
        orders = db.all("SELECT * FROM orders ORDER BY id DESC LIMIT 50")
        if not orders:
            body.add_widget(self.note("No orders yet."))
        for o in orders:
            body.add_widget(self.order_card(o))

    def order_card(self, o):
        db = self.app_ref.db
        card = auto_box()
        card.add_widget(wrap_label(f"#{o['id']} • {o['shop_name']} • {o['order_date']}", NAVY, 14, True))
        card.add_widget(wrap_label(f"Status: {o['status']} • Total: {money(o['total'])}", DARK, 12))
        items = order_items(db, o["id"])
        if items:
            card.add_widget(wrap_label("\n".join(f"• {i['qty']} × {i['product_name']}" for i in items),
                                       MUTED, 12))
        if o["notes"]:
            card.add_widget(wrap_label(f"Notes: {o['notes']}", MUTED, 12))

        status = o["status"]
        actions = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
        if status == "Quoted":
            actions.add_widget(make_button("Confirm", lambda _b, oid=o["id"]: self.set_status(oid, "Confirmed"),
                                           GREEN, 38, "12sp"))
        if status == "Confirmed":
            actions.add_widget(make_button("Delivered", lambda _b, oid=o["id"]: self.set_status(oid, "Delivered"),
                                           GREEN, 38, "12sp"))
        if status in ("Quoted", "Confirmed", "Delivered"):
            actions.add_widget(make_button("Cancel", lambda _b, oid=o["id"]: self.set_status(oid, "Cancelled"),
                                           RED, 38, "12sp"))
            actions.add_widget(make_button("Message", lambda _b, row=o: self.message_for(row), BLUE, 38, "12sp"))
        if actions.children:
            card.add_widget(actions)
        return card

    def add_item(self, *_):
        app = self.app_ref
        prod = self.prod_map.get(self.prod_spin.text)
        qty = to_int(self.qty_in.text, 0)
        if prod is None:
            popup_message("Choose a product", "Select a product from the list first.")
            return
        if qty <= 0:
            popup_message("Quantity", "Enter how many units the customer wants.")
            return
        app.draft_items.append({
            "product_id": prod["id"], "product_name": prod["name"],
            "qty": qty, "unit_price": prod["unit_price"],
        })
        self.rebuild()

    def remove_item(self, index):
        del self.app_ref.draft_items[index]
        self.rebuild()

    def save_order(self, *_):
        app = self.app_ref
        cust = self.cust_map.get(self.cust_spin.text)
        if cust is None:
            popup_message("Choose a customer", "Select a customer before saving the order.")
            return
        if not app.draft_items:
            popup_message("No items", "Add at least one product to the order.")
            return
        order_date = self.date_in.text.strip() or today_iso()
        if not valid_date(order_date):
            popup_message("Date format", "Please enter the order date as YYYY-MM-DD.")
            return
        visit_id = app.pending_visit_id if app.pending_customer_id == cust["id"] else None
        try:
            order_id = create_order(app.db, cust["id"], cust["shop"] or cust["name"], order_date,
                                    self.status_spin.text, self.notes_in.text.strip(), visit_id,
                                    app.draft_items)
        except ValueError as e:
            popup_message("Could not save order", str(e))
            return
        app.draft_items = []
        app.set_pending()
        app.pending_order_id = order_id
        self.rebuild()
        popup_message("Order saved",
                      f"Order #{order_id} saved as {self.status_spin.text}. "
                      "Open Messages to send the customer a confirmation or quotation.")

    def set_status(self, order_id, new_status):
        try:
            change_order_status(self.app_ref.db, order_id, new_status)
        except ValueError as e:
            popup_message("Cannot change order", str(e))
            return
        self.rebuild()

    def message_for(self, order_row):
        self.app_ref.set_pending(customer_id=order_row["customer_id"], shop=order_row["shop_name"])
        self.app_ref.pending_order_id = order_row["id"]
        self.app_ref.show_screen("messages")


class ProductsScreen(BaseScreen):
    def title_text(self):
        return "Products & Stock"

    def build(self, body):
        db = self.app_ref.db
        body.add_widget(self.heading("Add a product", BLUE))
        self.name_in = make_input("Product name *")
        self.category_in = make_input("Category (e.g. phone accessories)")
        self.price_in = make_input("Unit price (K)")
        self.price_in.input_filter = "float"
        self.stock_in = make_input("Stock on hand")
        self.stock_in.input_filter = "int"
        self.reorder_in = make_input("Reorder level (alert when at or below)")
        self.reorder_in.input_filter = "int"
        for w in (self.name_in, self.category_in, self.price_in, self.stock_in, self.reorder_in):
            body.add_widget(w)
        body.add_widget(make_button("Save product", self.save_product, GREEN))

        low = low_stock_products(db)
        if low:
            body.add_widget(wrap_label("Low stock: " + ", ".join(p["name"] for p in low), RED, 13, True))

        body.add_widget(self.heading("Products & stock"))
        rows = db.all("SELECT * FROM products ORDER BY name COLLATE NOCASE")
        if not rows:
            body.add_widget(self.note("No products yet. Add your first product above."))
        for p in rows:
            body.add_widget(self.product_card(p))

    def product_card(self, p):
        card = auto_box()
        is_low = p["stock_qty"] <= p["reorder_level"]
        title = p["name"] + ("  •  LOW STOCK" if is_low else "")
        card.add_widget(wrap_label(title, RED if is_low else NAVY, 14, True))
        card.add_widget(wrap_label(
            f"{p['category'] or 'General'} • Price {money(p['unit_price'])} • "
            f"Stock {p['stock_qty']} • Reorder at {p['reorder_level']}", DARK, 12))
        actions = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
        actions.add_widget(make_button("Restock", lambda *_: self.open_restock(p), GREEN, 38, "12sp"))
        actions.add_widget(make_button("Delete", lambda *_: self.delete_product(p), RED, 38, "12sp"))
        card.add_widget(actions)
        return card

    def save_product(self, *_):
        name = self.name_in.text.strip()
        if not name:
            popup_message("Missing name", "Enter the product name.")
            return
        self.app_ref.db.run(
            "INSERT INTO products(name,category,unit_price,stock_qty,reorder_level,created_at) VALUES(?,?,?,?,?,?)",
            (name, self.category_in.text.strip(), to_float(self.price_in.text),
             to_int(self.stock_in.text), to_int(self.reorder_in.text), now_text()))
        self.rebuild()
        popup_message("Saved", f"{name} has been added to your products.")

    def open_restock(self, row):
        app = self.app_ref
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        box.add_widget(wrap_label(f"Add stock for {row['name']}. Current stock: {row['stock_qty']}", DARK, 14))
        qty_in = make_input("Units received")
        qty_in.input_filter = "int"
        box.add_widget(qty_in)
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        cancel_btn = make_button("Cancel", None, MUTED)
        apply_btn = make_button("Add stock", None, GREEN)
        actions.add_widget(cancel_btn)
        actions.add_widget(apply_btn)
        box.add_widget(actions)
        pop = Popup(title="Restock", content=box, size_hint=(0.9, 0.5))

        def apply(*_):
            qty = to_int(qty_in.text, 0)
            if qty <= 0:
                popup_message("Quantity", "Enter the number of units received.")
                return
            app.db.run("UPDATE products SET stock_qty = stock_qty + ? WHERE id=?", (qty, row["id"]))
            pop.dismiss()
            self.rebuild()

        apply_btn.bind(on_release=apply)
        cancel_btn.bind(on_release=pop.dismiss)
        pop.open()

    def delete_product(self, row):
        self.app_ref.db.run("DELETE FROM products WHERE id=?", (row["id"],))
        self.rebuild()
        popup_message("Deleted", "Product removed. Past orders still show the product name.")


class MessagesScreen(BaseScreen):
    def title_text(self):
        return "Messages"

    def build(self, body):
        app = self.app_ref
        db = app.db
        customers = db.all("SELECT * FROM customers ORDER BY shop COLLATE NOCASE")
        self.cust_map = {customer_label(c): c for c in customers}

        body.add_widget(self.heading("Customer messages (WhatsApp)", BLUE))
        body.add_widget(self.note("Generate a message, edit it if you like, then open WhatsApp. "
                                  "You press send yourself."))
        default_cust = next((l for l, c in self.cust_map.items()
                             if c["id"] == app.pending_customer_id), "Select customer")
        self.cust_spin = make_spinner(list(self.cust_map) or ["No customers yet"], default_cust)
        self.cust_spin.bind(text=lambda *_: self.refresh_orders())
        body.add_widget(self.cust_spin)

        self.template_spin = make_spinner(TEMPLATES, TEMPLATES[0])
        body.add_widget(self.template_spin)

        self.order_spin = make_spinner(["Latest order"], "Latest order")
        body.add_widget(self.order_spin)
        self.phone_lbl = wrap_label("", MUTED, 12)
        body.add_widget(self.phone_lbl)

        body.add_widget(make_button("Generate message", self.generate, GREEN))
        self.preview = make_input("Your message will appear here. You can edit it before sending.",
                                  multiline=True, height=260)
        body.add_widget(self.preview)
        body.add_widget(make_button("Open in WhatsApp", self.open_whatsapp, GREEN))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        row.add_widget(make_button("Copy message", self.copy_message, NAVY, 44))
        row.add_widget(make_button("Log as sent", self.log_sent, BLUE, 44))
        body.add_widget(row)

        self.refresh_orders()

    def refresh_orders(self):
        db = self.app_ref.db
        cust = self.cust_map.get(self.cust_spin.text)
        self.order_map = {"Latest order": None}
        default = "Latest order"
        if cust is not None:
            for o in db.all("SELECT * FROM orders WHERE customer_id=? ORDER BY id DESC LIMIT 30", (cust["id"],)):
                label = f"#{o['id']} • {o['order_date']} • {o['status']}"
                self.order_map[label] = o
                if o["id"] == self.app_ref.pending_order_id:
                    default = label
            self.phone_lbl.text = (f"WhatsApp number: +{normalize_phone(cust['phone'])}"
                                   if normalize_phone(cust["phone"]) else
                                   "No phone number saved for this customer.")
        else:
            self.phone_lbl.text = ""
        self.order_spin.values = list(self.order_map)
        self.order_spin.text = default

    def generate(self, *_):
        app = self.app_ref
        cust = self.cust_map.get(self.cust_spin.text)
        if cust is None:
            popup_message("Choose a customer", "Select a customer first.")
            return
        order = self.order_map.get(self.order_spin.text)
        text = build_message(app.db, self.template_spin.text, cust, order,
                             app.db.get_setting("rep_name", "") or "your sales representative")
        if text is None:
            popup_message("Choose an order",
                          f"'{self.template_spin.text}' needs an order. Create one in Orders first.")
            return
        self.preview.text = text

    def open_whatsapp(self, *_):
        text = self.preview.text.strip()
        cust = self.cust_map.get(self.cust_spin.text)
        if not text or cust is None:
            popup_message("Nothing to send", "Generate a message first.")
            return
        phone = normalize_phone(cust["phone"])
        if not phone:
            popup_message("No phone number",
                          "This customer has no phone number. Edit the customer, or tap Copy message "
                          "and paste it into WhatsApp yourself.")
            return
        url = "https://wa.me/" + phone + "?text=" + urllib.parse.quote(text)
        try:
            webbrowser.open(url)
        except Exception:
            Clipboard.copy(text)
            popup_message("Could not open WhatsApp",
                          "The message has been copied. Open WhatsApp and paste it.")

    def copy_message(self, *_):
        text = self.preview.text.strip()
        if not text:
            popup_message("Nothing to copy", "Generate a message first.")
            return
        Clipboard.copy(text)
        popup_message("Copied", "Message copied. Paste it into WhatsApp.")

    def log_sent(self, *_):
        text = self.preview.text.strip()
        cust = self.cust_map.get(self.cust_spin.text)
        if not text or cust is None:
            popup_message("Nothing to log", "Generate a message first.")
            return
        self.app_ref.db.run(
            "INSERT INTO message_log(customer_id,shop_name,template,body,created_at) VALUES(?,?,?,?,?)",
            (cust["id"], cust["shop"] or cust["name"], self.template_spin.text, text, now_text()))
        popup_message("Logged", "Message recorded as sent for this customer.")


class AnalyticsScreen(BaseScreen):
    def title_text(self):
        return "Analytics"

    def build(self, body):
        db = self.app_ref.db
        body.add_widget(self.heading("Orders by shop", BLUE))
        shops = db.all("SELECT shop_name, COUNT(*) n, COALESCE(SUM(total),0) s FROM orders "
                       "WHERE status!='Cancelled' GROUP BY shop_name ORDER BY n DESC, s DESC LIMIT 10")
        if not shops:
            body.add_widget(self.note("No orders yet."))
        for r in shops:
            body.add_widget(wrap_label(f"{r['shop_name']}: {r['n']} order(s), {money(r['s'])}", DARK, 13))

        body.add_widget(self.heading("Fastest-selling products (last 30 days)"))
        since = (date.today() - timedelta(days=30)).isoformat()
        products = db.all(
            "SELECT oi.product_name, SUM(oi.qty) units, SUM(oi.line_total) revenue "
            "FROM order_items oi JOIN orders o ON o.id=oi.order_id "
            "WHERE o.status!='Cancelled' AND o.order_date>=? "
            "GROUP BY oi.product_name ORDER BY units DESC LIMIT 10", (since,))
        if not products:
            body.add_widget(self.note("No sales in the last 30 days."))
        for r in products:
            body.add_widget(wrap_label(f"{r['product_name']}: {r['units']} units, {money(r['revenue'])}", DARK, 13))

        body.add_widget(self.heading("Visits that led to an order"))
        total_visits = db.one("SELECT COUNT(*) n FROM visits")["n"]
        visits_with_orders = db.one("SELECT COUNT(DISTINCT visit_id) n FROM orders "
                                    "WHERE visit_id IS NOT NULL AND status!='Cancelled'")["n"]
        rate = (visits_with_orders / total_visits * 100) if total_visits else 0
        body.add_widget(wrap_label(
            f"{visits_with_orders} of {total_visits} visits led to an order ({rate:.0f}%).", DARK, 13))

        body.add_widget(self.heading("Weekly sales (last 8 weeks)"))
        weeks = sales_by_week(db, 8)
        chart = BarChart([w[1] for w in weeks])
        body.add_widget(chart)
        labels = GridLayout(cols=len(weeks), size_hint_y=None, height=dp(40))
        for ws, total, count in weeks:
            labels.add_widget(Label(text=f"{ws.strftime('%d %b')}\n{CURRENCY}{total:,.0f}\n{count} ord.",
                                    color=DARK, font_size="10sp", halign="center"))
        body.add_widget(labels)
        body.add_widget(self.note("Week-over-week change compares each week with the one before it."))
        if len(weeks) >= 2 and weeks[-2][1] > 0:
            change = (weeks[-1][1] - weeks[-2][1]) / weeks[-2][1] * 100
            body.add_widget(wrap_label(f"This week vs last week: {change:+.0f}%", NAVY, 14, True))


class CoachScreen(BaseScreen):
    def title_text(self):
        return "Sales Coach"

    def build(self, body):
        body.add_widget(self.note("Built-in guidance works offline. Tap a question or type your own."))
        for q in COACH_PRESETS:
            body.add_widget(make_button(q, lambda _b, q=q: self.ask(q), NAVY, 44, "12sp"))
        self.question_in = make_input("Type your sales question...")
        body.add_widget(self.question_in)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        row.add_widget(make_button("Ask", lambda *_: self.ask(self.question_in.text.strip()), GREEN, 44))
        if self.app_ref.db.get_setting("ai_api_key", "").strip():
            row.add_widget(make_button("Ask online AI", lambda *_: self.ask_online(), BLUE, 44))
        body.add_widget(row)
        self.answer = wrap_label("Ask a question to see advice here.", DARK, 14)
        body.add_widget(self.answer)

    def ask(self, question):
        if not question:
            popup_message("Ask a question", "Type a question or tap one of the questions above.")
            return
        self.last_question = question
        self.answer.text = coach_answer(self.app_ref.db, question)

    def ask_online(self):
        question = self.question_in.text.strip() or getattr(self, "last_question", "")
        if not question:
            popup_message("Ask a question", "Type a question first.")
            return
        self.answer.text = "Asking online AI..."
        ask_online_ai(
            self.app_ref.db,
            "You are a practical sales coach for small shops in Zambia. Give short, concrete, "
            "respectful advice. Do not invent facts or numbers.",
            question,
            on_text=lambda text: setattr(self.answer, "text", text),
            on_error=lambda msg: popup_message("Online AI", msg))


REPORT_OUTCOMES = {
    "Follow-up Pending": "Awaiting Feedback",
    "Quotation Requested": "Quotation In Progress",
    "Order Placed": "Order Received",
    "Not Interested": "Closed",
    "Visit Completed": "Completed",
}


def report_date(text):
    """Show dates the way reps write them: DD/MM/YYYY."""
    if not text:
        return date.today().strftime("%d/%m/%Y")
    d = parse_date(text)
    if d is None:
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                d = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                pass
    return d.strftime("%d/%m/%Y") if d else text


class ReportsScreen(BaseScreen):
    def title_text(self):
        return "Sales Visit Report"

    def build(self, body):
        app = self.app_ref
        rv = getattr(app, "report_visit", None) or {}
        body.add_widget(self.heading("Professional sales visit report", BLUE))
        self.shop_in = make_input("Shop name", text=rv.get("shop_name", ""))
        self.date_in = make_input("Visit date (DD/MM/YYYY)", text=report_date(rv.get("visit_date")))
        self.rep_in = make_input("Sales representative name", text=app.db.get_setting("rep_name", ""))
        self.outcome_type = make_spinner(list(REPORT_OUTCOMES.keys()),
                                         rv.get("outcome_type") or "Follow-up Pending")
        self.products_in = make_input("Products promoted (e.g. itel accessories)",
                                      text=rv.get("purpose", "") or "")
        for w in (self.shop_in, self.date_in, self.rep_in, self.outcome_type, self.products_in):
            body.add_widget(w)
        body.add_widget(make_button("Detect products from a photo", self.pick_photo, NAVY))
        self.photo_status = self.note("Choose a product photo to list the items in it. "
                                      "Needs internet and an online AI key in Settings.")
        body.add_widget(self.photo_status)
        self.outcome_in = make_input("What happened during the visit (what the customer said)",
                                     multiline=True, height=90, text=rv.get("outcome", "") or "")
        self.next_in = make_input("Next action (e.g. I will follow up tomorrow to get feedback)")
        self.extra_in = make_input("Additional details (optional)", multiline=True, height=65,
                                   text=rv.get("notes", "") or "")
        for w in (self.outcome_in, self.next_in, self.extra_in):
            body.add_widget(w)
        body.add_widget(make_button("Generate report (offline)", self.generate_offline, GREEN))
        body.add_widget(make_button("Polish with online AI (optional)", self.generate_online, BLUE))
        body.add_widget(self.heading("Generated report"))
        self.output = make_input("Your report will appear here...", multiline=True, height=260)
        body.add_widget(self.output)
        body.add_widget(make_button("Copy report", self.copy_report, NAVY))
        body.add_widget(make_button("Save report to history", self.save_report, GREEN))
        body.add_widget(make_button("View saved reports", self.show_saved_reports, MUTED))

    def collect(self):
        return {
            "shop": self.shop_in.text.strip(),
            "date": report_date(self.date_in.text.strip()),
            "rep": self.rep_in.text.strip() or "Sales Representative",
            "outcome_type": self.outcome_type.text,
            "products": self.products_in.text.strip(),
            "outcome": self.outcome_in.text.strip(),
            "next": self.next_in.text.strip(),
            "extra": self.extra_in.text.strip(),
        }

    def build_report(self, d):
        if d["products"]:
            opening = f"I visited {d['shop']} to introduce and promote {d['products']}."
        else:
            opening = f"I visited {d['shop']} to follow up on our business relationship."
        story = d["outcome"] or "No response from the customer was recorded during this visit."
        next_action = d["next"] or "I will follow up with the customer to confirm their decision and any possible order."
        status = REPORT_OUTCOMES.get(d["outcome_type"], "Recorded")
        lines = [
            "SALES VISIT REPORT",
            "",
            f"Shop Name: {d['shop']}",
            f"Sales Representative: {d['rep']}",
            f"Date: {d['date']}",
            f"Visit Outcome: {d['outcome_type']}",
            "",
            f"{opening} {story}",
            "",
            f"Next Action: {next_action}",
            "",
            f"Status: {status}.",
        ]
        if d["extra"]:
            lines += ["", "Additional Notes: " + d["extra"]]
        return "\n".join(lines)

    def generate_offline(self, *_):
        d = self.collect()
        if not d["shop"]:
            popup_message("Missing shop name", "Enter the shop or customer name first.")
            return
        self.output.text = self.build_report(d)

    def generate_online(self, *_):
        d = self.collect()
        if not d["shop"]:
            popup_message("Missing shop name", "Enter the shop or customer name first.")
            return
        if not self.app_ref.db.get_setting("ai_api_key", "").strip():
            popup_message("Online AI not configured",
                          "Generate the offline report now. To enable online AI, open Settings and add your "
                          "AI provider API key. API usage may cost money.")
            return
        report = self.build_report(d)
        self.output.text = report + "\n\nPolishing with online AI..."
        prompt = ("Rewrite the following sales visit report in concise, professional business English. "
                  "Keep exactly this layout and these labels. Do not invent facts, numbers, orders, promises, "
                  "or dates. Return only the finished report.\n\n" + report)
        ask_online_ai(self.app_ref.db, "You are a careful sales reporting assistant. Never invent facts.",
                      prompt,
                      on_text=lambda text: setattr(self.output, "text", text),
                      on_error=lambda msg: popup_message("Online AI error", msg))

    def pick_photo(self, *_):
        if not self.app_ref.db.get_setting("ai_api_key", "").strip():
            popup_message("Online AI not configured",
                          "Photo detection uses online AI. Add your AI provider API key in Settings first. "
                          "You can still type the products by hand.")
            return
        start = "/storage/emulated/0" if os.path.isdir("/storage/emulated/0") else os.path.expanduser("~")
        chooser = FileChooserListView(path=start,
                                      filters=["*.jpg", "*.jpeg", "*.png", "*.webp",
                                               "*.JPG", "*.JPEG", "*.PNG", "*.WEBP"])
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        box.add_widget(chooser)
        use_btn = make_button("Detect products in this photo", None, GREEN)
        box.add_widget(use_btn)
        pop = Popup(title="Choose a product photo", title_color=NAVY, title_size="17sp",
                    separator_color=BLUE, content=box, size_hint=(0.95, 0.9))

        def use(*_):
            if not chooser.selection:
                popup_message("No photo selected", "Tap a photo file first.")
                return
            path = chooser.selection[0]
            pop.dismiss()
            self.detect_products(path)

        use_btn.bind(on_release=use)
        pop.open()

    def detect_products(self, path):
        try:
            if os.path.getsize(path) > 4 * 1024 * 1024:
                popup_message("Photo too large",
                              "Choose a photo under 4 MB. Tip: take the photo at a lower resolution.")
                return
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            popup_message("Could not open photo", str(e))
            return
        ext = os.path.splitext(path)[1].lower()
        mime = {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
        uri = f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
        self.photo_status.text = "Looking at the photo. This can take a moment..."
        ask_online_ai(
            self.app_ref.db,
            "You identify products in photos for a small sales representative in Zambia. "
            "Only list products you can actually see. Never invent brands or models. "
            "Reply with only a JSON array of short product names, for example "
            "['itel earphones', 'phone chargers']. If no products can be identified, reply with [].",
            "List the products visible in this photo.",
            on_text=self.on_products_detected,
            on_error=self.on_detect_error,
            image_data_uri=uri)

    def on_products_detected(self, text):
        raw = re.sub(r"```json|```", "", text or "").strip()
        try:
            items = json.loads(raw)
            if not isinstance(items, list):
                raise ValueError("not a list")
            names = [str(i).strip() for i in items if str(i).strip()]
        except ValueError:
            names = [s.strip(" -*'\"") for s in re.split(r"[\n,]", raw) if s.strip(" -*'\"")]
        existing = [p.strip() for p in self.products_in.text.split(",") if p.strip()]
        known = {p.lower() for p in existing}
        for name in names:
            if name.lower() not in known:
                existing.append(name)
                known.add(name.lower())
        self.products_in.text = ", ".join(existing)
        if names:
            self.photo_status.text = (f"Found {len(names)} product(s) in the photo and added them to "
                                      "Products promoted. Check the list and edit if needed.")
        else:
            self.photo_status.text = "No products could be identified. Type them in by hand."

    def on_detect_error(self, msg):
        self.photo_status.text = "Photo detection failed. You can type the products by hand."
        popup_message("Photo detection error", msg)

    def copy_report(self, *_):
        if not self.output.text.strip():
            popup_message("Nothing to copy", "Generate a report first.")
            return
        Clipboard.copy(self.output.text)
        popup_message("Copied", "Report copied. You can paste it into WhatsApp or your work group.")

    def save_report(self, *_):
        body = self.output.text.strip()
        if not body:
            popup_message("Nothing to save", "Generate a report first.")
            return
        title = self.shop_in.text.strip() or "Sales visit report"
        self.app_ref.db.run("INSERT INTO reports(title,report_type,body,created_at) VALUES(?,?,?,?)",
                            (title, "Sales Visit", body, now_text()))
        popup_message("Saved", "Report saved in local history.")

    def show_saved_reports(self, *_):
        rows = self.app_ref.db.all("SELECT * FROM reports ORDER BY id DESC LIMIT 30")
        if not rows:
            popup_message("Report history", "No saved reports yet.")
            return
        msg = "\n\n".join(f"{r['created_at']} — {r['title']}\n{r['body'][:240]}" for r in rows)
        popup_message("Saved reports (latest 30)", msg)


class SettingsScreen(BaseScreen):
    def title_text(self):
        return "Settings"

    def build(self, body):
        db = self.app_ref.db
        body.add_widget(self.heading("Personal settings", BLUE))
        self.rep_in = make_input("Your name for messages and reports", text=db.get_setting("rep_name", ""))
        body.add_widget(self.rep_in)

        body.add_widget(self.heading("Optional online AI configuration", NAVY))
        body.add_widget(self.note("The offline features work without these fields. Your API key is stored "
                                  "in this app's database on this phone. Keep your phone locked."))
        self.endpoint_in = make_input("API endpoint", text=db.get_setting("ai_endpoint", DEFAULT_ENDPOINT))
        self.model_in = make_input("Model name", text=db.get_setting("ai_model", DEFAULT_MODEL))
        self.key_in = make_input("API key (stored locally)", text=db.get_setting("ai_api_key", ""))
        self.key_in.password = True
        for w in (self.endpoint_in, self.model_in, self.key_in):
            body.add_widget(w)
        body.add_widget(make_button("Save settings", self.save_settings, GREEN))

        body.add_widget(self.heading("Reminders", TEAL))
        body.add_widget(self.note("The app checks once a day while it is open or running in the background "
                                  "and sends phone notifications about visits, follow-ups, quotations and "
                                  "restocks. Turn on 'Ignore battery optimisation' for Pydroid 3 so Android "
                                  "does not stop it."))
        self.reminders_spin = make_spinner(["On", "Off"], db.get_setting("reminders_on", "On"))
        self.time_in = make_input("Daily reminder time (HH:MM, 24-hour)",
                                  text=db.get_setting("reminder_time", "08:00"))
        body.add_widget(self.reminders_spin)
        body.add_widget(self.time_in)
        body.add_widget(make_button("Send reminders now", lambda *_: self.app_ref.run_reminders(manual=True), TEAL))

        body.add_widget(self.heading("Data & privacy", NAVY))
        body.add_widget(self.note("Customers, visits, orders and messages stay on this phone unless you share "
                                  "them yourself or use online AI. Online AI sends the text you ask about to "
                                  "the provider you set up. Do not include confidential customer details "
                                  "unless you are allowed to."))
        body.add_widget(make_button("Export database backup", self.export_backup, BLUE))
        body.add_widget(self.note("Backups are created without your API key, so a copied file cannot "
                                  "expose it. You will need to enter the key again after restoring."))
        body.add_widget(self.note(f"App version: {VERSION} • Built for Android / Pydroid 3"))

    def save_settings(self, *_):
        db = self.app_ref.db
        db.set_setting("rep_name", self.rep_in.text.strip())
        db.set_setting("ai_endpoint", self.endpoint_in.text.strip() or DEFAULT_ENDPOINT)
        db.set_setting("ai_model", self.model_in.text.strip() or DEFAULT_MODEL)
        db.set_setting("ai_api_key", self.key_in.text.strip())
        db.set_setting("reminders_on", self.reminders_spin.text)
        t = self.time_in.text.strip()
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", t)
        if not m:
            popup_message("Check reminder time", "Use 24-hour format, for example 08:00 or 17:30.")
            return
        db.set_setting("reminder_time", f"{int(m.group(1)):02d}:{m.group(2)}")
        popup_message("Settings saved", "Your settings have been saved locally.")

    def export_backup(self, *_):
        app = self.app_ref
        try:
            app.db.conn.commit()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = os.path.join(app.user_data_dir, f"salesrep_ai_backup_{stamp}.db")
            shutil.copy2(app.db.path, backup)
            # Remove the API key from the copy only; the live database is untouched.
            copy_conn = sqlite3.connect(backup)
            copy_conn.execute("DELETE FROM settings WHERE key='ai_api_key'")
            copy_conn.commit()
            copy_conn.close()
            popup_message("Backup created",
                          f"Backup created at:\n{backup}\n\nIt does not include your API key. "
                          "Use your file manager to copy it somewhere safe.")
        except Exception as e:
            popup_message("Backup failed", str(e))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def reminder_sections(db):
    """Return (title, lines) groups for today's reminders. Uses the same rules as the Coach."""
    today = date.today()
    sections = []
    visits = db.all("SELECT shop_name FROM visits WHERE visit_date=? AND status!='Completed' ORDER BY id",
                    (today.isoformat(),))
    if visits:
        sections.append(("Visits today", [f"Visit {r['shop_name']}" for r in visits]))

    follow = []
    for entry in follow_up_priorities(db)[:6]:
        follow.append(entry.split(". ", 1)[1] if ". " in entry else entry)
    quotes = db.all("SELECT shop_name, order_date FROM orders WHERE status='Quoted' ORDER BY order_date")
    for q in quotes:
        d = parse_date(q["order_date"])
        days = (today - d).days if d else 0
        if days >= 3:
            follow.append(f"{q['shop_name']}: quotation {days} days old, ask for the order")
    if follow:
        sections.append(("Follow up and order", follow[:8]))

    low = low_stock_products(db)
    if low:
        sections.append(("Restock needed",
                         [f"{p['name']} (stock {p['stock_qty']})" for p in low[:8]]))
    return sections


def send_notification(title, message):
    """Show a phone notification. Returns False if the phone bridge is not available."""
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name=APP_NAME, timeout=12)
        return True
    except Exception:
        return False


class SalesRepAIApp(App):
    title = APP_NAME

    def build(self):
        # Kivy provides user_data_dir as a property; do not assign to it.
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.db = Database(os.path.join(self.user_data_dir, DB_NAME))

        # Cross-screen state
        self.pending_customer_id = None
        self.pending_shop = ""
        self.pending_visit_id = None
        self.pending_order_id = None
        self.draft_items = []
        self.report_visit = None

        outer = BoxLayout(orientation="vertical", spacing=0)
        top = BoxLayout(size_hint_y=None, height=dp(58), padding=(dp(12), dp(5)), spacing=dp(8))
        with top.canvas.before:
            Color(*NAVY)
            self.top_rect = Rectangle(pos=top.pos, size=top.size)
        top.bind(pos=self._update_top_rect, size=self._update_top_rect)
        brand = BoxLayout(orientation="vertical", spacing=0)
        brand.add_widget(Label(text=APP_NAME, color=WHITE, bold=True, font_size="18sp", halign="left"))
        brand.add_widget(Label(text=f"Personal Sales Assistant • v{VERSION}",
                               color=get_color_from_hex("#D9EAF7"), font_size="11sp", halign="left"))
        top.add_widget(brand)
        outer.add_widget(top)

        self.sm = ScreenManager()
        self.screens = {
            "dashboard": DashboardScreen(self, name="dashboard"),
            "customers": CustomersScreen(self, name="customers"),
            "visits": VisitsScreen(self, name="visits"),
            "orders": OrdersScreen(self, name="orders"),
            "products": ProductsScreen(self, name="products"),
            "messages": MessagesScreen(self, name="messages"),
            "analytics": AnalyticsScreen(self, name="analytics"),
            "coach": CoachScreen(self, name="coach"),
            "reports": ReportsScreen(self, name="reports"),
            "settings": SettingsScreen(self, name="settings"),
        }
        for screen in self.screens.values():
            self.sm.add_widget(screen)
        outer.add_widget(self.sm)

        nav = GridLayout(cols=5, size_hint_y=None, height=dp(66), spacing=dp(6), padding=(dp(8), dp(8)))
        paint_round(nav, DEEP, 0)
        self.nav_buttons = {}
        for text, name in [("Home", "dashboard"), ("Customers", "customers"),
                           ("Orders", "orders"), ("Visits", "visits"), ("More", "more")]:
            btn = FlatButton(bg=TAB, text=text, font_size="12sp", radius=12)
            btn.bind(on_release=lambda inst, target=name: self.nav_tap(target))
            nav.add_widget(btn)
            self.nav_buttons[name] = btn
        outer.add_widget(nav)
        Clock.schedule_interval(self._check_daily_reminder, 60)
        self.show_screen("dashboard")
        return outer

    def run_reminders(self, manual=False):
        sections = reminder_sections(self.db)
        if not sections:
            if manual:
                popup_message("All clear", "No visits, follow-ups or restocks need attention right now.")
            return
        any_sent = False
        for title, lines in sections:
            msg = "\n".join("• " + l for l in lines[:5])
            if send_notification(f"SalesRep: {title}", msg):
                any_sent = True
        if manual or not any_sent:
            text = "\n\n".join(f"{t}\n" + "\n".join("• " + l for l in lines) for t, lines in sections)
            title = "Today's reminders" if manual else "Reminders (phone notifications unavailable)"
            popup_message(title, text)

    def _check_daily_reminder(self, _dt):
        db = self.db
        if db.get_setting("reminders_on", "On") != "On":
            return
        try:
            hh, mm = map(int, db.get_setting("reminder_time", "08:00").split(":"))
        except ValueError:
            hh, mm = 8, 0
        due = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
        if datetime.now() >= due and db.get_setting("last_reminder_date", "") != today_iso():
            db.set_setting("last_reminder_date", today_iso())
            self.run_reminders(manual=False)

    def _update_top_rect(self, widget, value):
        self.top_rect.pos = widget.pos
        self.top_rect.size = widget.size

    def nav_tap(self, target):
        if target == "more":
            self.open_more()
        else:
            self.show_screen(target)

    def open_more(self):
        box = GridLayout(cols=2, spacing=dp(8), padding=dp(12))
        pop = Popup(title="More", title_color=NAVY, title_size="17sp", separator_color=BLUE,
                    content=box, size_hint=(0.92, 0.6))
        for text, name in [("Products & Stock", "products"), ("Messages", "messages"),
                           ("Analytics", "analytics"), ("Sales Coach", "coach"),
                           ("Reports", "reports"), ("Settings", "settings")]:
            box.add_widget(make_button(text, lambda _b, n=name: (pop.dismiss(), self.show_screen(n)),
                                       BLUE, 60))
        pop.open()

    def set_pending(self, customer_id=None, shop="", visit_id=None):
        self.pending_customer_id = customer_id
        self.pending_shop = shop
        self.pending_visit_id = visit_id

    def show_screen(self, name):
        if name not in self.screens:
            return
        if self.sm.current == name:
            self.screens[name].rebuild()
        else:
            self.sm.current = name  # on_pre_enter rebuilds the screen
        active = name if name in self.nav_buttons else "more"
        for key, btn in self.nav_buttons.items():
            btn.set_bg(BLUE if key == active else TAB)

    def on_stop(self):
        try:
            self.db.conn.commit()
            self.db.conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    # If startup fails, write the traceback to a text file beside this script.
    try:
        SalesRepAIApp().run()
    except Exception:
        import traceback
        error_text = traceback.format_exc()
        try:
            error_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "SalesRep_AI_startup_error.txt")
            with open(error_path, "w", encoding="utf-8") as error_file:
                error_file.write(error_text)
        except Exception:
            pass
        raise
