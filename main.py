# -*- coding: utf-8 -*-
"""
🐼 پاندا پوینت - ربات بازی/اقتصادی برای سروش‌پلاس
====================================================
این نسخه بازنویسی‌شده‌ی کامل رباته. تغییرات اصلی نسبت به نسخه قبلی:

  1) باگ اصلی که باعث می‌شد ربات "کار نکنه": در نسخه قبلی فقط دستورهای
     /start و راهنما پردازش می‌شدن و همه‌ی بقیه دستورها (بازی‌ها، اقتصاد،
     کلن، ماموریت و ...) با `pass` نادیده گرفته می‌شدن. الان همه‌شون
     پیاده‌سازی شدن.
  2) پیام‌ها با parse_mode="MarkdownV2" فرستاده می‌شدن بدون escape کردن
     کاراکترهای خاص - همین باعث می‌شد سروش پیام رو رد کنه یا ارسال با خطا
     مواجه بشه. الان پیام‌ها ساده (plain text) فرستاده می‌شن؛ مطمئن‌تره.
  3) دسترسی به ستون‌های دیتابیس با ایندکس عددی (user[18]، user[16] و ...)
     باگ‌زا بود (مثلاً دستاورد "games" در واقع به ستون اشتباهی نگاه می‌کرد).
     الان از sqlite3.Row استفاده می‌شه و همه‌جا با اسم ستون کار می‌کنیم.
  4) پنل مدیریت به‌جای کپی‌پیست کردن یک بلوک CSS/سایدبار در هر route،
     از یک قالب مشترک استفاده می‌کنه؛ همچنین چارت واقعی، جستجوی کاربر،
     بن/آنبن و ویرایش امتیاز از داخل پنل اضافه شده.
  5) ایده‌های جدید به ربات اضافه شده: چرخ‌شانس، کوییز، کد هدیه، کارت
     پروفایل با نوار پیشرفت، پیدا کردن کاربر با @username برای جنگ/انتقال.

نکته: اگه از نسخه قبلی یک فایل panda_bot.db روی دیسک داری، بهتره قبل از
اجرا حذفش کنی تا جدول‌ها با ستون‌های جدید از اول ساخته بشن (یک مهاجرت
خودکار هم برای ستون‌های جدید گذاشته شده، ولی حذف فایل قدیمی مطمئن‌تره).
"""
import requests
import sqlite3
import random
import time
import threading
import json
import hashlib
import secrets as secrets_lib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect, url_for, session
from functools import wraps
import os

# ------------------------------------------------------------
# 🔐 تنظیمات اصلی (ترجیحاً با متغیر محیطی ست کن، ولی مقدار پیش‌فرض هم هست)
# ------------------------------------------------------------
BOT_TOKEN = os.environ.get("PANDA_BOT_TOKEN", "69669213:7vV7TpLn1_YMuPOe271FW7Pw5ZhpfCsO5q8")
BASE_URL = f"https://api.splus.ir/bot{BOT_TOKEN}"
ADMIN_PASSWORD = os.environ.get("PANDA_ADMIN_PASSWORD", "123456")
DB_PATH = os.environ.get("PANDA_DB_PATH", "panda_bot.db")

app = Flask(__name__)
app.secret_key = os.environ.get("PANDA_SECRET_KEY", "panda_super_secret_key_2026")

PET_COOLDOWN_SEC = 30
FEED_COOLDOWN_SEC = 30
DAILY_COOLDOWN_HOURS = 24
WHEEL_COST = 30
QUIZ_TIMEOUT_SEC = 60
QUIZ_REWARD = 25

# در حافظه: کوییزهایی که منتظر جواب کاربر هستن {user_id: {...}}
pending_quiz = {}


# ------------------------------------------------------------
# 🗄️ دیتابیس
# ------------------------------------------------------------
class Database:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self._create_all_tables()
        self._migrate()

    def _create_all_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            points INTEGER DEFAULT 100,
            level INTEGER DEFAULT 1,
            panda_name TEXT DEFAULT 'پاندای من',
            panda_hunger INTEGER DEFAULT 100,
            panda_happiness INTEGER DEFAULT 100,
            panda_love INTEGER DEFAULT 0,
            bank_balance INTEGER DEFAULT 0,
            last_daily TEXT,
            last_pet TEXT,
            last_feed TEXT,
            last_quiz TEXT,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_games INTEGER DEFAULT 0,
            is_banned BOOLEAN DEFAULT 0,
            invite_code TEXT,
            invited_by INTEGER DEFAULT 0,
            clan TEXT DEFAULT NULL,
            join_date TEXT DEFAULT CURRENT_TIMESTAMP,
            xp INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            last_streak_date TEXT,
            pet_count INTEGER DEFAULT 0,
            feed_count INTEGER DEFAULT 0
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            item TEXT,
            quantity INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item)
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS shop (
            item TEXT PRIMARY KEY,
            price INTEGER,
            description TEXT,
            emoji TEXT,
            stock INTEGER DEFAULT -1,
            category TEXT DEFAULT 'general'
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            requirement_type TEXT,
            requirement_value INTEGER,
            reward INTEGER,
            cooldown_hours INTEGER DEFAULT 24
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS user_missions (
            user_id INTEGER,
            mission_id INTEGER,
            progress INTEGER DEFAULT 0,
            completed BOOLEAN DEFAULT 0,
            last_claim TEXT,
            PRIMARY KEY (user_id, mission_id)
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            icon TEXT,
            requirement_type TEXT,
            requirement_value INTEGER
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS user_achievements (
            user_id INTEGER,
            achievement_id INTEGER,
            unlocked_at TEXT,
            PRIMARY KEY (user_id, achievement_id)
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS clans (
            name TEXT PRIMARY KEY,
            owner_id INTEGER,
            member_count INTEGER DEFAULT 1,
            total_points INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            description TEXT DEFAULT ''
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS gift_codes (
            code TEXT PRIMARY KEY,
            reward INTEGER,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS gift_code_redemptions (
            code TEXT,
            user_id INTEGER,
            redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (code, user_id)
        )''')

        default_items = [
            ('🍫 شکلات', 50, 'به پاندا غذا می‌ده و شادیش رو زیاد می‌کنه', '🍫', -1, 'general'),
            ('🎁 جعبه هدیه', 100, 'یک هدیه تصادفی', '🎁', -1, 'general'),
            ('⭐ ستاره', 200, 'افزایش ۲۰۰ امتیاز', '⭐', -1, 'general'),
            ('💎 الماس', 500, 'افزایش ۵۰۰ امتیاز', '💎', -1, 'general'),
            ('🛡️ سپر', 150, 'محافظت در جنگ', '🛡️', -1, 'battle'),
            ('⚡ رعد', 300, 'حمله قوی در جنگ', '⚡', -1, 'battle'),
            ('🎨 رنگ پاندا', 400, 'تغییر رنگ پاندا', '🎨', -1, 'cosmetic'),
            ('👑 تاج', 1000, 'تاج سلطنتی', '👑', -1, 'cosmetic'),
            ('🚀 راکت', 800, 'پرواز با پاندا!', '🚀', -1, 'special'),
            ('🌈 رنگین‌کمان', 600, 'رنگین‌کمان پاندا', '🌈', -1, 'cosmetic'),
        ]
        for item in default_items:
            self.cursor.execute(
                "INSERT OR IGNORE INTO shop (item, price, description, emoji, stock, category) VALUES (?, ?, ?, ?, ?, ?)",
                item)

        default_achievements = [
            ('تازه‌کار', '۱۰۰ امتیاز جمع کن', '🌟', 'points', 100),
            ('حرفه‌ای', '۵۰۰ امتیاز جمع کن', '🏆', 'points', 500),
            ('افسانه', '۱۰۰۰ امتیاز جمع کن', '👑', 'points', 1000),
            ('جنگ‌جو', '۱۰ برد در جنگ', '⚔️', 'wins', 10),
            ('بازی‌ساز', '۵۰ بازی انجام بده', '🎮', 'games', 50),
            ('دوست پاندا', '۵۰ بار نوازش', '🐼', 'pet', 50),
            ('پادشاه', 'به سطح ۱۰ برس', '👑', 'level', 10),
        ]
        for name, desc, icon, req_type, req_val in default_achievements:
            self.cursor.execute(
                "INSERT OR IGNORE INTO achievements (name, description, icon, requirement_type, requirement_value) VALUES (?, ?, ?, ?, ?)",
                (name, desc, icon, req_type, req_val))

        default_missions = [
            ('جمع‌آوری امتیاز', '۱۰۰ امتیاز جمع کن', 'points', 100, 30, 24),
            ('پادشاه بازی‌ها', '۲۰ بازی انجام بده', 'games', 20, 40, 24),
            ('جنگ‌جوی حرفه‌ای', '۵ برد در جنگ', 'wins', 5, 50, 24),
            ('پاندا دوست', '۱۰ بار نوازش کن', 'pet', 10, 20, 24),
        ]
        for name, desc, req_type, req_val, reward, cd in default_missions:
            self.cursor.execute(
                "INSERT OR IGNORE INTO missions (name, description, requirement_type, requirement_value, reward, cooldown_hours) VALUES (?, ?, ?, ?, ?, ?)",
                (name, desc, req_type, req_val, reward, cd))

        self.conn.commit()

    def _migrate(self):
        """اضافه کردن ستون‌های جدید به دیتابیس‌های قدیمی، بدون نیاز به حذف فایل."""
        for col_def in ["pet_count INTEGER DEFAULT 0", "feed_count INTEGER DEFAULT 0"]:
            col_name = col_def.split()[0]
            try:
                self.cursor.execute(f"ALTER TABLE users ADD COLUMN {col_def}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # ستون از قبل وجود داره

    # ===== کاربر =====
    def get_user(self, user_id, username="", first_name="", last_name=""):
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = self.cursor.fetchone()
        if not user:
            invite_code = hashlib.md5(str(user_id).encode()).hexdigest()[:8]
            self.cursor.execute('''INSERT INTO users (user_id, username, first_name, last_name, invite_code)
                VALUES (?, ?, ?, ?, ?)''', (user_id, username, first_name, last_name, invite_code))
            self.conn.commit()
            self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = self.cursor.fetchone()
        elif username or first_name:
            # اگه یوزرنیم/اسم تغییر کرده، آپدیت کن
            self.cursor.execute(
                "UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE user_id = ?",
                (username or user['username'], first_name or user['first_name'], last_name or user['last_name'], user_id))
            self.conn.commit()
            self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = self.cursor.fetchone()
        return user

    def get_user_by_username(self, username):
        username = username.lstrip('@')
        self.cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        return self.cursor.fetchone()

    def update_user(self, user_id, **kwargs):
        for key, value in kwargs.items():
            self.cursor.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))
        self.conn.commit()

    def add_points(self, user_id, points, reason=""):
        self.cursor.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        self.conn.commit()
        self.cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
        pts = self.cursor.fetchone()['points']
        level = max(1, 1 + pts // 100)
        self.cursor.execute("UPDATE users SET level = ? WHERE user_id = ?", (level, user_id))
        self.conn.commit()
        self.log_action(user_id, "add_points", f"{points} points | {reason}")
        return self.check_achievements(user_id)

    def add_xp(self, user_id, xp):
        self.cursor.execute("UPDATE users SET xp = xp + ? WHERE user_id = ?", (xp, user_id))
        self.conn.commit()

    def get_inventory(self, user_id):
        self.cursor.execute("SELECT item, quantity FROM inventory WHERE user_id = ? AND quantity > 0", (user_id,))
        return self.cursor.fetchall()

    def get_item_qty(self, user_id, item):
        self.cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item = ?", (user_id, item))
        row = self.cursor.fetchone()
        return row['quantity'] if row else 0

    def add_item(self, user_id, item, quantity=1):
        self.cursor.execute(
            "INSERT INTO inventory (user_id, item, quantity) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, item) DO UPDATE SET quantity = quantity + ?",
            (user_id, item, quantity, quantity))
        self.conn.commit()

    def use_item(self, user_id, item):
        if self.get_item_qty(user_id, item) <= 0:
            return False
        self.cursor.execute("UPDATE inventory SET quantity = quantity - 1 WHERE user_id = ? AND item = ?",
                             (user_id, item))
        self.conn.commit()
        return True

    def get_shop_items(self):
        self.cursor.execute("SELECT * FROM shop")
        return self.cursor.fetchall()

    def get_shop_item(self, item):
        self.cursor.execute("SELECT * FROM shop WHERE item = ?", (item,))
        return self.cursor.fetchone()

    def add_shop_item(self, item, price, description, emoji, stock=-1, category='general'):
        self.cursor.execute(
            "INSERT OR REPLACE INTO shop (item, price, description, emoji, stock, category) VALUES (?, ?, ?, ?, ?, ?)",
            (item, price, description, emoji, stock, category))
        self.conn.commit()

    def delete_shop_item(self, item):
        self.cursor.execute("DELETE FROM shop WHERE item = ?", (item,))
        self.conn.commit()

    def get_leaderboard(self, limit=10, by='points'):
        col = by if by in ('points', 'wins', 'level') else 'points'
        self.cursor.execute(f"SELECT user_id, username, first_name, points, level, wins FROM users ORDER BY {col} DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()

    def get_all_users(self, search=None, limit=200):
        if search:
            like = f"%{search}%"
            self.cursor.execute(
                "SELECT * FROM users WHERE username LIKE ? OR first_name LIKE ? OR CAST(user_id AS TEXT) LIKE ? "
                "ORDER BY points DESC LIMIT ?", (like, like, like, limit))
        else:
            self.cursor.execute("SELECT * FROM users ORDER BY points DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()

    def toggle_ban(self, user_id):
        self.cursor.execute("UPDATE users SET is_banned = NOT is_banned WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def set_points(self, user_id, points):
        self.cursor.execute("UPDATE users SET points = ? WHERE user_id = ?", (points, user_id))
        self.conn.commit()

    # ===== کلن‌ها =====
    def get_clans(self):
        self.cursor.execute("SELECT * FROM clans ORDER BY total_points DESC")
        return self.cursor.fetchall()

    def get_clan(self, name):
        self.cursor.execute("SELECT * FROM clans WHERE name = ?", (name,))
        return self.cursor.fetchone()

    def create_or_join_clan(self, user_id, name):
        clan = self.get_clan(name)
        user = self.get_user(user_id)
        old_clan = user['clan']
        if old_clan == name:
            return "already"
        if old_clan:
            self.cursor.execute("UPDATE clans SET member_count = member_count - 1 WHERE name = ?", (old_clan,))
        if clan:
            self.cursor.execute("UPDATE clans SET member_count = member_count + 1 WHERE name = ?", (name,))
            result = "joined"
        else:
            self.cursor.execute("INSERT INTO clans (name, owner_id) VALUES (?, ?)", (name, user_id))
            result = "created"
        self.cursor.execute("UPDATE users SET clan = ? WHERE user_id = ?", (name, user_id))
        self.conn.commit()
        return result

    # ===== ماموریت‌ها =====
    def get_missions(self):
        self.cursor.execute("SELECT * FROM missions")
        return self.cursor.fetchall()

    def get_user_mission_state(self, user_id, mission_id):
        self.cursor.execute("SELECT * FROM user_missions WHERE user_id = ? AND mission_id = ?", (user_id, mission_id))
        return self.cursor.fetchone()

    def claim_mission(self, user_id, mission):
        user = self.get_user(user_id)
        stat_map = {'points': user['points'], 'games': user['total_games'],
                    'wins': user['wins'], 'pet': user['pet_count'], 'level': user['level']}
        current = stat_map.get(mission['requirement_type'], 0)
        if current < mission['requirement_value']:
            return "not_ready", current
        state = self.get_user_mission_state(user_id, mission['id'])
        now = datetime.now()
        if state and state['last_claim']:
            last = datetime.fromisoformat(state['last_claim'])
            if now - last < timedelta(hours=mission['cooldown_hours']):
                remain = timedelta(hours=mission['cooldown_hours']) - (now - last)
                return "cooldown", remain
        self.cursor.execute(
            "INSERT INTO user_missions (user_id, mission_id, completed, last_claim) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(user_id, mission_id) DO UPDATE SET completed=1, last_claim=?",
            (user_id, mission['id'], now.isoformat(), now.isoformat()))
        self.conn.commit()
        self.add_points(user_id, mission['reward'], f"ماموریت: {mission['name']}")
        return "claimed", mission['reward']

    # ===== دستاوردها =====
    def get_achievements(self):
        self.cursor.execute("SELECT * FROM achievements")
        return self.cursor.fetchall()

    def get_user_achievements(self, user_id):
        self.cursor.execute("SELECT achievement_id FROM user_achievements WHERE user_id = ?", (user_id,))
        return [row['achievement_id'] for row in self.cursor.fetchall()]

    def check_achievements(self, user_id):
        user = self.get_user(user_id)
        unlocked_ids = self.get_user_achievements(user_id)
        stat_map = {'points': user['points'], 'wins': user['wins'],
                    'games': user['total_games'], 'pet': user['pet_count'], 'level': user['level']}
        newly_unlocked = []
        for ach in self.get_achievements():
            if ach['id'] in unlocked_ids:
                continue
            current = stat_map.get(ach['requirement_type'], 0)
            if current >= ach['requirement_value']:
                self.cursor.execute(
                    "INSERT INTO user_achievements (user_id, achievement_id, unlocked_at) VALUES (?, ?, ?)",
                    (user_id, ach['id'], datetime.now().isoformat()))
                self.conn.commit()
                newly_unlocked.append(ach)
        return newly_unlocked

    # ===== کد هدیه =====
    def create_gift_code(self, reward, max_uses=1, code=None):
        code = code or secrets_lib.token_hex(4).upper()
        self.cursor.execute("INSERT INTO gift_codes (code, reward, max_uses) VALUES (?, ?, ?)",
                             (code, reward, max_uses))
        self.conn.commit()
        return code

    def get_gift_codes(self):
        self.cursor.execute("SELECT * FROM gift_codes ORDER BY created_at DESC")
        return self.cursor.fetchall()

    def redeem_gift_code(self, user_id, code):
        self.cursor.execute("SELECT * FROM gift_codes WHERE code = ?", (code,))
        gc = self.cursor.fetchone()
        if not gc:
            return "not_found", 0
        if gc['used_count'] >= gc['max_uses']:
            return "exhausted", 0
        self.cursor.execute("SELECT 1 FROM gift_code_redemptions WHERE code = ? AND user_id = ?", (code, user_id))
        if self.cursor.fetchone():
            return "already_used", 0
        self.cursor.execute("INSERT INTO gift_code_redemptions (code, user_id) VALUES (?, ?)", (code, user_id))
        self.cursor.execute("UPDATE gift_codes SET used_count = used_count + 1 WHERE code = ?", (code,))
        self.conn.commit()
        self.add_points(user_id, gc['reward'], f"کد هدیه {code}")
        return "ok", gc['reward']

    # ===== لاگ و آمار =====
    def log_action(self, user_id, action, details=""):
        self.cursor.execute("INSERT INTO logs (user_id, action, details) VALUES (?, ?, ?)",
                             (user_id, action, details))
        self.conn.commit()

    def get_logs(self, limit=100):
        self.cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()

    def get_stats(self):
        return {
            'total_users': self.cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            'total_points': self.cursor.execute("SELECT SUM(points) FROM users").fetchone()[0] or 0,
            'total_games': self.cursor.execute("SELECT SUM(total_games) FROM users").fetchone()[0] or 0,
            'total_clans': self.cursor.execute("SELECT COUNT(*) FROM clans").fetchone()[0],
            'total_missions': self.cursor.execute("SELECT COUNT(*) FROM missions").fetchone()[0],
            'total_achievements': self.cursor.execute("SELECT COUNT(*) FROM achievements").fetchone()[0],
            'active_users': self.cursor.execute(
                "SELECT COUNT(*) FROM users WHERE last_daily IS NOT NULL AND datetime(last_daily) > datetime('now', '-7 days')"
            ).fetchone()[0],
            'banned_users': self.cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1").fetchone()[0],
        }


db = Database()

# ------------------------------------------------------------
# 📨 ارسال پیام به سروش‌پلاس (بدون parse_mode، برای جلوگیری از خطای ارسال)
# ------------------------------------------------------------
def send_message(chat_id, text, reply_markup=None):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print(f"⚠️ ارسال پیام ناموفق ({r.status_code}): {r.text[:200]}")
    except Exception as e:
        print(f"❌ خطا در ارسال پیام: {e}")


def create_reply_keyboard(buttons, resize=True):
    return {"keyboard": [[{"text": t} for t in row] for row in buttons], "resize_keyboard": resize}


MAIN_KEYBOARD = create_reply_keyboard([
    ["🐼 پاندا", "🤗 نوازش", "🍎 غذا"],
    ["🎁 گل", "🏆 لیست", "📖 راهنما"],
    ["🏦 بانک", "🛒 فروشگاه", "📋 ماموریت‌ها"],
    ["🎡 چرخ", "❓ کوییز", "👥 کلن‌ها"],
])


def progress_bar(value, maximum, length=10):
    value = max(0, min(value, maximum))
    filled = int(length * value / maximum) if maximum else 0
    return "█" * filled + "░" * (length - filled)


def now_iso():
    return datetime.now().isoformat()


def seconds_since(ts):
    if not ts:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
    except ValueError:
        return None


# ------------------------------------------------------------
# 🎮 بازی‌ها
# ------------------------------------------------------------
def roll_dice():
    return random.randint(1, 6)


def play_dart():
    return random.randint(1, 10)


def rps(player_choice):
    choices = ["سنگ", "کاغذ", "قیچی"]
    bot = random.choice(choices)
    if player_choice == bot:
        return "مساوی", bot
    wins_against = {"سنگ": "قیچی", "کاغذ": "سنگ", "قیچی": "کاغذ"}
    if wins_against[player_choice] == bot:
        return "برنده", bot
    return "بازنده", bot


def blackjack_sim():
    deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4
    random.shuffle(deck)
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    def value(hand):
        v = sum(hand)
        aces = hand.count(11)
        while v > 21 and aces:
            v -= 10
            aces -= 1
        return v

    while value(player) < 17:
        player.append(deck.pop())
    while value(dealer) < 17:
        dealer.append(deck.pop())
    pv, dv = value(player), value(dealer)
    if pv > 21:
        return "بازنده", pv, dv
    if dv > 21:
        return "برنده", pv, dv
    if pv > dv:
        return "برنده", pv, dv
    if pv < dv:
        return "بازنده", pv, dv
    return "مساوی", pv, dv


def fight(user1_id, user2_id):
    u1 = db.get_user(user1_id)
    u2 = db.get_user(user2_id)
    power1 = random.randint(1, 20) + (u1['points'] // 50)
    power2 = random.randint(1, 20) + (u2['points'] // 50)
    inv1 = {row['item'] for row in db.get_inventory(user1_id)}
    inv2 = {row['item'] for row in db.get_inventory(user2_id)}
    if '🛡️ سپر' in inv1:
        power1 += 5
        db.use_item(user1_id, '🛡️ سپر')
    if '🛡️ سپر' in inv2:
        power2 += 5
        db.use_item(user2_id, '🛡️ سپر')
    if '⚡ رعد' in inv1:
        power1 += 10
        db.use_item(user1_id, '⚡ رعد')
    if '⚡ رعد' in inv2:
        power2 += 10
        db.use_item(user2_id, '⚡ رعد')

    db.update_user(user1_id, total_games=u1['total_games'] + 1)
    db.update_user(user2_id, total_games=u2['total_games'] + 1)

    if power1 > power2:
        db.update_user(user1_id, wins=u1['wins'] + 1)
        db.update_user(user2_id, losses=u2['losses'] + 1)
        db.add_points(user1_id, 20, "برد در جنگ")
        return user1_id, power1, power2
    elif power2 > power1:
        db.update_user(user2_id, wins=u2['wins'] + 1)
        db.update_user(user1_id, losses=u1['losses'] + 1)
        db.add_points(user2_id, 20, "برد در جنگ")
        return user2_id, power1, power2
    return None, power1, power2


QUIZ_BANK = [
    ("پایتخت ایران کجاست؟", ["تهران", "اصفهان", "شیراز", "مشهد"], 0),
    ("۲ + ۲ × ۲ چند می‌شه؟", ["۶", "۸", "۴", "۲"], 0),
    ("بزرگ‌ترین سیاره منظومه شمسی کدومه؟", ["مریخ", "زمین", "مشتری", "زحل"], 2),
    ("پاندا معمولاً چی می‌خوره؟", ["گوشت", "بامبو", "ماهی", "میوه"], 1),
    ("سریع‌ترین حیوان خشکی کدومه؟", ["شیر", "یوزپلنگ", "اسب", "گورخر"], 1),
    ("آب از چند اتم تشکیل شده؟", ["۲", "۳", "۴", "۱"], 1),
]


# ------------------------------------------------------------
# 📋 هندلرهای دستورات
# ------------------------------------------------------------
def handle_start(chat_id, user_id, username, first_name, last_name):
    db.get_user(user_id, username, first_name, last_name)
    text = f"""🐼 به ربات پاندا پوینت خوش اومدید! 🐼

سلام {first_name or 'کاربر'}!
💎 امتیاز اولیه: ۱۰۰

از دکمه‌های پایین استفاده کن یا "راهنما" رو بفرست تا همه دستورها رو ببینی."""
    send_message(chat_id, text, MAIN_KEYBOARD)


def handle_help(chat_id):
    text = """🐼 راهنمای کامل پاندا پوینت

🐾 پایه:
• پاندا - کارت پروفایل و وضعیت پاندا
• نوازش - نوازش پاندا (هر ۳۰ ثانیه)
• غذا - غذا دادن به پاندا (هر ۳۰ ثانیه)
• تغییر اسم [نام] - تغییر اسم پاندا
• گل - جایزه روزانه
• لیست - ۱۰ نفر برتر
• آمار - آمار کامل خودت

🎮 بازی‌ها:
• تاس / دارت
• سنگ یا کاغذ یا قیچی
• بلک‌جک
• جنگ @username (یا ریپلای کن و بنویس جنگ)

💰 اقتصاد:
• بانک
• واریز [مقدار]
• برداشت [مقدار]
• انتقال [مقدار] @username
• فروشگاه
• خرید [نام آیتم]

👥 اجتماعی:
• کلن [نام]
• کلن‌ها
• دعوت

🏆 پیشرفت:
• ماموریت‌ها
• دستاوردها

✨ امکانات ویژه:
• چرخ - چرخ‌شانس (هزینه ۳۰ امتیاز)
• کوییز - یک سوال با جایزه امتیاز
• کد [کد هدیه] - فعال‌سازی کد هدیه"""
    send_message(chat_id, text)


def handle_profile(chat_id, user_id):
    u = db.get_user(user_id)
    xp_in_level = u['points'] % 100
    text = f"""🐼 کارت {u['panda_name']}

👤 {u['first_name'] or 'کاربر'} | سطح {u['level']}
💎 امتیاز: {u['points']}
📊 پیشرفت سطح: {progress_bar(xp_in_level, 100)} ({xp_in_level}/100)

🍖 گرسنگی: {progress_bar(u['panda_hunger'], 100)} {u['panda_hunger']}%
😊 شادی: {progress_bar(u['panda_happiness'], 100)} {u['panda_happiness']}%
❤️ عشق: {u['panda_love']}

🏦 موجودی بانک: {u['bank_balance']}
⚔️ برد/باخت: {u['wins']}/{u['losses']}
🎮 تعداد بازی‌ها: {u['total_games']}
🏰 کلن: {u['clan'] or 'ندارد'}
🔥 استریک روزانه: {u['streak']}"""
    send_message(chat_id, text)


def handle_rename_panda(chat_id, user_id, new_name):
    new_name = new_name.strip()[:30]
    if not new_name:
        send_message(chat_id, "❗ اسم جدید رو بعد از دستور بنویس. مثال: تغییر اسم بامبو")
        return
    db.update_user(user_id, panda_name=new_name)
    send_message(chat_id, f"✅ اسم پاندات شد: {new_name}")


def handle_pet(chat_id, user_id):
    u = db.get_user(user_id)
    elapsed = seconds_since(u['last_pet'])
    if elapsed is not None and elapsed < PET_COOLDOWN_SEC:
        send_message(chat_id, f"⏳ {int(PET_COOLDOWN_SEC - elapsed)} ثانیه دیگه صبر کن تا دوباره نوازش کنی.")
        return
    gained = random.randint(1, 5)
    new_happiness = min(100, u['panda_happiness'] + random.randint(3, 8))
    db.update_user(user_id, last_pet=now_iso(), panda_happiness=new_happiness,
                    panda_love=u['panda_love'] + 1, pet_count=u['pet_count'] + 1)
    db.add_points(user_id, gained, "نوازش")
    send_message(chat_id, f"🤗 {u['panda_name']} رو نوازش کردی! +{gained} امتیاز | 😊 شادی: {new_happiness}%")


def handle_feed(chat_id, user_id):
    u = db.get_user(user_id)
    elapsed = seconds_since(u['last_feed'])
    if elapsed is not None and elapsed < FEED_COOLDOWN_SEC:
        send_message(chat_id, f"⏳ {int(FEED_COOLDOWN_SEC - elapsed)} ثانیه دیگه صبر کن تا دوباره غذا بدی.")
        return
    gained = random.randint(1, 5)
    new_hunger = min(100, u['panda_hunger'] + random.randint(5, 15))
    db.update_user(user_id, last_feed=now_iso(), panda_hunger=new_hunger, feed_count=u['feed_count'] + 1)
    db.add_points(user_id, gained, "غذا دادن")
    send_message(chat_id, f"🍎 به {u['panda_name']} غذا دادی! +{gained} امتیاز | 🍖 گرسنگی: {new_hunger}%")


def handle_daily(chat_id, user_id):
    u = db.get_user(user_id)
    elapsed = seconds_since(u['last_daily'])
    if elapsed is not None and elapsed < DAILY_COOLDOWN_HOURS * 3600:
        remain = DAILY_COOLDOWN_HOURS * 3600 - elapsed
        h, m = int(remain // 3600), int((remain % 3600) // 60)
        send_message(chat_id, f"⏳ جایزه روزانه رو قبلاً گرفتی. {h} ساعت و {m} دقیقه دیگه دوباره سر بزن.")
        return
    # استریک: اگه فاصله بین دو گرفتن جایزه کمتر از ۴۸ ساعت باشه، استریک ادامه پیدا می‌کنه
    streak = u['streak'] + 1 if (elapsed is not None and elapsed < 48 * 3600) else 1
    reward = random.randint(10, 25) + min(streak * 2, 50)
    db.update_user(user_id, last_daily=now_iso(), streak=streak)
    db.add_points(user_id, reward, "جایزه روزانه")
    send_message(chat_id, f"🎁 جایزه روزانه: +{reward} امتیاز!\n🔥 استریک: {streak} روز")


def handle_leaderboard(chat_id):
    rows = db.get_leaderboard(10)
    lines = ["🏆 ۱۰ نفر برتر:\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = r['first_name'] or r['username'] or str(r['user_id'])
        lines.append(f"{medal} {name} - {r['points']} امتیاز (سطح {r['level']})")
    send_message(chat_id, "\n".join(lines))


def handle_stats(chat_id, user_id):
    u = db.get_user(user_id)
    unlocked = len(db.get_user_achievements(user_id))
    total_ach = len(db.get_achievements())
    text = f"""📊 آمار کامل شما

💎 امتیاز: {u['points']} | سطح {u['level']}
🏦 بانک: {u['bank_balance']}
⚔️ برد: {u['wins']} | باخت: {u['losses']} | کل بازی‌ها: {u['total_games']}
🐼 نوازش‌ها: {u['pet_count']} | غذاها: {u['feed_count']}
🏰 کلن: {u['clan'] or 'ندارد'}
🏆 دستاوردها: {unlocked}/{total_ach}
📨 کد دعوت شما: {u['invite_code']}"""
    send_message(chat_id, text)


def handle_dice(chat_id, user_id):
    result = roll_dice()
    u = db.get_user(user_id)
    db.update_user(user_id, total_games=u['total_games'] + 1)
    db.add_points(user_id, result, "تاس")
    send_message(chat_id, f"🎲 تاس انداختی و عدد {result} اومد! +{result} امتیاز")


def handle_dart(chat_id, user_id):
    result = play_dart()
    u = db.get_user(user_id)
    db.update_user(user_id, total_games=u['total_games'] + 1)
    db.add_points(user_id, result, "دارت")
    send_message(chat_id, f"🎯 دارت زدی و {result} آوردی! +{result} امتیاز")


def handle_rps(chat_id, user_id, choice):
    outcome, bot_choice = rps(choice)
    u = db.get_user(user_id)
    db.update_user(user_id, total_games=u['total_games'] + 1)
    if outcome == "برنده":
        db.update_user(user_id, wins=u['wins'] + 1)
        db.add_points(user_id, 15, "سنگ‌کاغذقیچی")
        send_message(chat_id, f"✊✋✌️ تو {choice} گذاشتی، ربات {bot_choice} گذاشت. بردی! +۱۵ امتیاز")
    elif outcome == "بازنده":
        db.update_user(user_id, losses=u['losses'] + 1)
        send_message(chat_id, f"✊✋✌️ تو {choice} گذاشتی، ربات {bot_choice} گذاشت. باختی!")
    else:
        send_message(chat_id, f"✊✋✌️ تو {choice} گذاشتی، ربات هم {bot_choice} گذاشت. مساوی شد!")


def handle_blackjack(chat_id, user_id):
    outcome, pv, dv = blackjack_sim()
    u = db.get_user(user_id)
    db.update_user(user_id, total_games=u['total_games'] + 1)
    if outcome == "برنده":
        db.update_user(user_id, wins=u['wins'] + 1)
        db.add_points(user_id, 20, "بلک‌جک")
        send_message(chat_id, f"🃏 تو: {pv} | دیلر: {dv}\n🎉 بردی! +۲۰ امتیاز")
    elif outcome == "بازنده":
        db.update_user(user_id, losses=u['losses'] + 1)
        db.add_points(user_id, -10, "بلک‌جک")
        send_message(chat_id, f"🃏 تو: {pv} | دیلر: {dv}\n😢 باختی! -۱۰ امتیاز")
    else:
        send_message(chat_id, f"🃏 تو: {pv} | دیلر: {dv}\n🤝 مساوی شد!")


def handle_fight(chat_id, user_id, target_id):
    if target_id == user_id:
        send_message(chat_id, "❗ نمی‌تونی با خودت بجنگی!")
        return
    winner, p1, p2 = fight(user_id, target_id)
    target = db.get_user(target_id)
    target_name = target['first_name'] or target['username'] or str(target_id)
    if winner is None:
        send_message(chat_id, f"⚔️ جنگ با {target_name}: قدرت {p1} در برابر {p2} — مساوی شد!")
    elif winner == user_id:
        send_message(chat_id, f"⚔️ جنگ با {target_name}: قدرت {p1} در برابر {p2}\n🎉 بردی! +۲۰ امتیاز")
    else:
        send_message(chat_id, f"⚔️ جنگ با {target_name}: قدرت {p1} در برابر {p2}\n😢 باختی!")


def handle_bank_status(chat_id, user_id):
    u = db.get_user(user_id)
    send_message(chat_id, f"🏦 موجودی بانک: {u['bank_balance']}\n💎 امتیاز نقدی: {u['points']}")


def handle_deposit(chat_id, user_id, amount):
    u = db.get_user(user_id)
    if amount <= 0:
        send_message(chat_id, "❗ مقدار باید بزرگ‌تر از صفر باشه.")
        return
    if u['points'] < amount:
        send_message(chat_id, "❗ امتیاز کافی نداری.")
        return
    db.update_user(user_id, points=u['points'] - amount, bank_balance=u['bank_balance'] + amount)
    send_message(chat_id, f"🏦 {amount} امتیاز واریز شد. موجودی بانک: {u['bank_balance'] + amount}")


def handle_withdraw(chat_id, user_id, amount):
    u = db.get_user(user_id)
    if amount <= 0:
        send_message(chat_id, "❗ مقدار باید بزرگ‌تر از صفر باشه.")
        return
    if u['bank_balance'] < amount:
        send_message(chat_id, "❗ موجودی بانک کافی نیست.")
        return
    db.update_user(user_id, points=u['points'] + amount, bank_balance=u['bank_balance'] - amount)
    send_message(chat_id, f"💵 {amount} امتیاز برداشت شد. امتیاز فعلی: {u['points'] + amount}")


def handle_transfer(chat_id, user_id, amount, target_username):
    if amount <= 0:
        send_message(chat_id, "❗ مقدار باید بزرگ‌تر از صفر باشه.")
        return
    target = db.get_user_by_username(target_username)
    if not target:
        send_message(chat_id, "❗ کاربری با این یوزرنیم پیدا نشد.")
        return
    u = db.get_user(user_id)
    if u['points'] < amount:
        send_message(chat_id, "❗ امتیاز کافی نداری.")
        return
    if target['user_id'] == user_id:
        send_message(chat_id, "❗ نمی‌تونی به خودت انتقال بدی.")
        return
    db.update_user(user_id, points=u['points'] - amount)
    db.add_points(target['user_id'], amount, f"انتقال از {user_id}")
    send_message(chat_id, f"✅ {amount} امتیاز به @{target_username} منتقل شد.")
    send_message(target['user_id'], f"💌 {amount} امتیاز از طرف یک کاربر برات اومد!")


def handle_shop(chat_id):
    items = db.get_shop_items()
    lines = ["🛒 فروشگاه پاندا:\n"]
    for it in items:
        stock = "نامحدود" if it['stock'] == -1 else it['stock']
        lines.append(f"{it['emoji']} {it['item']} - {it['price']} امتیاز | {it['description']} (موجودی: {stock})")
    lines.append("\nبرای خرید بنویس: خرید [نام آیتم]")
    send_message(chat_id, "\n".join(lines))


def handle_buy(chat_id, user_id, item_query):
    item = db.get_shop_item(item_query.strip())
    if not item:
        # جستجوی نرم‌تر: شاید ایموجی رو ننوشته
        for it in db.get_shop_items():
            if item_query.strip() in it['item']:
                item = it
                break
    if not item:
        send_message(chat_id, "❗ این آیتم تو فروشگاه پیدا نشد. برای دیدن لیست بنویس: فروشگاه")
        return
    if item['stock'] == 0:
        send_message(chat_id, "❗ این آیتم موجود نیست.")
        return
    u = db.get_user(user_id)
    if u['points'] < item['price']:
        send_message(chat_id, "❗ امتیاز کافی نداری.")
        return
    db.update_user(user_id, points=u['points'] - item['price'])
    db.add_item(user_id, item['item'])
    if item['stock'] > 0:
        db.cursor.execute("UPDATE shop SET stock = stock - 1 WHERE item = ?", (item['item'],))
        db.conn.commit()
    send_message(chat_id, f"✅ {item['item']} خریداری شد!")


def handle_clan_join(chat_id, user_id, name):
    name = name.strip()[:30]
    if not name:
        send_message(chat_id, "❗ اسم کلن رو بعد از دستور بنویس. مثال: کلن پاندا‌ها")
        return
    result = db.create_or_join_clan(user_id, name)
    if result == "already":
        send_message(chat_id, f"شما از قبل عضو کلن «{name}» هستید.")
    elif result == "created":
        send_message(chat_id, f"🏰 کلن «{name}» ساخته شد و شما رهبرش هستید!")
    else:
        send_message(chat_id, f"✅ به کلن «{name}» پیوستید!")


def handle_clans_list(chat_id):
    clans = db.get_clans()
    if not clans:
        send_message(chat_id, "هنوز هیچ کلنی ساخته نشده. با «کلن [نام]» یکی بساز!")
        return
    lines = ["🏰 لیست کلن‌ها:\n"]
    for c in clans:
        lines.append(f"• {c['name']} - {c['member_count']} عضو")
    send_message(chat_id, "\n".join(lines))


def handle_invite(chat_id, user_id):
    u = db.get_user(user_id)
    send_message(chat_id, f"📨 کد دعوت شما: {u['invite_code']}\nاین کد رو به دوستات بده!")


def handle_missions(chat_id, user_id):
    lines = ["📋 ماموریت‌ها:\n"]
    for m in db.get_missions():
        status, info = db.claim_mission(user_id, m)
        if status == "claimed":
            lines.append(f"✅ {m['name']} - انجام شد! +{info} امتیاز")
        elif status == "cooldown":
            h = int(info.total_seconds() // 3600)
            mnt = int((info.total_seconds() % 3600) // 60)
            lines.append(f"⏳ {m['name']} - قبلاً گرفتی، {h}h {mnt}m دیگه صبر کن")
        else:
            lines.append(f"🔒 {m['name']} - {m['description']} (پاداش: {m['reward']})")
    send_message(chat_id, "\n".join(lines))


def handle_achievements(chat_id, user_id):
    unlocked_ids = set(db.get_user_achievements(user_id))
    lines = ["🏆 دستاوردها:\n"]
    for a in db.get_achievements():
        mark = "✅" if a['id'] in unlocked_ids else "🔒"
        lines.append(f"{mark} {a['icon']} {a['name']} - {a['description']}")
    send_message(chat_id, "\n".join(lines))


def handle_wheel(chat_id, user_id):
    u = db.get_user(user_id)
    if u['points'] < WHEEL_COST:
        send_message(chat_id, f"❗ برای چرخوندن چرخ‌شانس حداقل {WHEEL_COST} امتیاز لازمه.")
        return
    prizes = [0, 10, 20, 30, 50, 80, 100, 150]
    weights = [25, 20, 20, 15, 10, 5, 3, 2]
    prize = random.choices(prizes, weights=weights, k=1)[0]
    net = prize - WHEEL_COST
    db.update_user(user_id, points=u['points'] - WHEEL_COST)
    db.add_points(user_id, prize, "چرخ‌شانس")
    emoji = "🎉" if net > 0 else ("😐" if net == 0 else "😢")
    send_message(chat_id, f"🎡 چرخ چرخید... جایزه: {prize} امتیاز {emoji}\n(هزینه چرخوندن: {WHEEL_COST})")


def handle_quiz(chat_id, user_id):
    if user_id in pending_quiz and time.time() < pending_quiz[user_id]['expires']:
        send_message(chat_id, "❗ یک سوال قبلی هنوز بازه، اول بهش جواب بده (عدد ۱ تا ۴).")
        return
    q, options, correct = random.choice(QUIZ_BANK)
    pending_quiz[user_id] = {'correct': correct, 'expires': time.time() + QUIZ_TIMEOUT_SEC, 'chat_id': chat_id}
    opts_text = "\n".join([f"{i+1}. {o}" for i, o in enumerate(options)])
    send_message(chat_id, f"❓ {q}\n\n{opts_text}\n\nجواب رو با عدد بفرست (تا {QUIZ_TIMEOUT_SEC} ثانیه فرصت داری).")


def try_handle_quiz_answer(chat_id, user_id, text):
    pending = pending_quiz.get(user_id)
    if not pending:
        return False
    if time.time() > pending['expires']:
        del pending_quiz[user_id]
        return False
    if text.strip() not in ("1", "2", "3", "4", "۱", "۲", "۳", "۴"):
        return False
    digit_map = {"۱": "1", "۲": "2", "۳": "3", "۴": "4"}
    normalized = digit_map.get(text.strip(), text.strip())
    answer_idx = int(normalized) - 1
    del pending_quiz[user_id]
    if answer_idx == pending['correct']:
        db.add_points(user_id, QUIZ_REWARD, "کوییز")
        send_message(chat_id, f"✅ درست بود! +{QUIZ_REWARD} امتیاز")
    else:
        send_message(chat_id, "❌ جواب اشتباه بود. دوباره امتحان کن: کوییز")
    return True


def handle_redeem_code(chat_id, user_id, code):
    code = code.strip().upper()
    status, reward = db.redeem_gift_code(user_id, code)
    if status == "ok":
        send_message(chat_id, f"🎁 کد فعال شد! +{reward} امتیاز")
    elif status == "not_found":
        send_message(chat_id, "❗ این کد معتبر نیست.")
    elif status == "exhausted":
        send_message(chat_id, "❗ ظرفیت این کد تموم شده.")
    else:
        send_message(chat_id, "❗ قبلاً از این کد استفاده کردی.")


# ------------------------------------------------------------
# 🔀 مسیریابی پیام‌ها
# ------------------------------------------------------------
def normalize(text):
    # حذف ایموجی‌های تزئینی روی دکمه‌ها تا با متن ساده هم کار کنه
    for junk in ["🐼 ", "🤗 ", "🍎 ", "🎁 ", "🏆 ", "📖 ", "🏦 ", "🛒 ", "📋 ", "🎡 ", "❓ ", "👥 "]:
        text = text.replace(junk, "")
    return text.strip()


def process_update(update):
    if 'message' not in update:
        return
    msg = update['message']
    chat_id = msg['chat']['id']
    user_id = msg['from']['id']
    username = msg['from'].get('username', '')
    first_name = msg['from'].get('first_name', '')
    last_name = msg['from'].get('last_name', '')
    raw_text = msg.get('text', '')
    if not raw_text:
        return
    text = normalize(raw_text)

    user = db.get_user(user_id, username, first_name, last_name)
    if user['is_banned']:
        send_message(chat_id, "⛔ شما مسدود شده‌اید.")
        return

    # اول ببین منتظر جواب کوییز هست یا نه
    if try_handle_quiz_answer(chat_id, user_id, text):
        return

    if text in ('/start', 'شروع'):
        handle_start(chat_id, user_id, username, first_name, last_name)
    elif text in ('راهنما', '/help'):
        handle_help(chat_id)
    elif text == 'پاندا':
        handle_profile(chat_id, user_id)
    elif text == 'نوازش':
        handle_pet(chat_id, user_id)
    elif text == 'غذا':
        handle_feed(chat_id, user_id)
    elif text == 'گل':
        handle_daily(chat_id, user_id)
    elif text == 'لیست':
        handle_leaderboard(chat_id)
    elif text == 'آمار':
        handle_stats(chat_id, user_id)
    elif text == 'تاس':
        handle_dice(chat_id, user_id)
    elif text == 'دارت':
        handle_dart(chat_id, user_id)
    elif text in ('سنگ', 'کاغذ', 'قیچی'):
        handle_rps(chat_id, user_id, text)
    elif text in ('بلک‌جک', 'بلک جک'):
        handle_blackjack(chat_id, user_id)
    elif text == 'بانک':
        handle_bank_status(chat_id, user_id)
    elif text == 'فروشگاه':
        handle_shop(chat_id)
    elif text == 'کلن‌ها':
        handle_clans_list(chat_id)
    elif text == 'دعوت':
        handle_invite(chat_id, user_id)
    elif text == 'ماموریت‌ها':
        handle_missions(chat_id, user_id)
    elif text == 'دستاوردها':
        handle_achievements(chat_id, user_id)
    elif text == 'چرخ':
        handle_wheel(chat_id, user_id)
    elif text == 'کوییز':
        handle_quiz(chat_id, user_id)
    elif text.startswith('جنگ'):
        rest = text[len('جنگ'):].strip()
        target_id = None
        if rest.startswith('@'):
            target = db.get_user_by_username(rest)
            if target:
                target_id = target['user_id']
        elif msg.get('reply_to_message'):
            target_id = msg['reply_to_message'].get('from', {}).get('id')
        if target_id:
            handle_fight(chat_id, user_id, target_id)
        else:
            send_message(chat_id, "❗ بنویس: جنگ @username یا روی پیام کسی ریپلای کن و بنویس جنگ")
    elif text.startswith('واریز'):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            handle_deposit(chat_id, user_id, int(parts[1]))
        else:
            send_message(chat_id, "❗ مثال درست: واریز 100")
    elif text.startswith('برداشت'):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            handle_withdraw(chat_id, user_id, int(parts[1]))
        else:
            send_message(chat_id, "❗ مثال درست: برداشت 100")
    elif text.startswith('انتقال'):
        parts = text.split()
        if len(parts) >= 3 and parts[1].isdigit() and parts[2].startswith('@'):
            handle_transfer(chat_id, user_id, int(parts[1]), parts[2])
        else:
            send_message(chat_id, "❗ مثال درست: انتقال 50 @username")
    elif text.startswith('خرید'):
        rest = text.split(' ', 1)
        if len(rest) == 2:
            handle_buy(chat_id, user_id, rest[1])
        else:
            send_message(chat_id, "❗ مثال درست: خرید 🍫 شکلات")
    elif text.startswith('کلن '):
        handle_clan_join(chat_id, user_id, text[len('کلن'):])
    elif text.startswith('تغییر اسم'):
        handle_rename_panda(chat_id, user_id, text[len('تغییر اسم'):])
    elif text.startswith('کد '):
        handle_redeem_code(chat_id, user_id, text[len('کد'):])
    else:
        send_message(chat_id, "متوجه نشدم 🤔 برای دیدن دستورها بنویس: راهنما")


def run_polling():
    print("🔄 شروع Polling...")
    last_update_id = 0
    while True:
        try:
            url = f"{BASE_URL}/getUpdates?offset={last_update_id + 1}&timeout=30"
            resp = requests.get(url, timeout=35)
            data = resp.json()
            if data.get('ok') and data.get('result'):
                for update in data['result']:
                    last_update_id = update['update_id']
                    try:
                        process_update(update)
                    except Exception as e:
                        print(f"❌ خطا در پردازش پیام: {e}")
        except Exception as e:
            print(f"❌ خطا در polling: {e}")
        time.sleep(1)


# ==============================================================
# 🌐 پنل مدیریت (Glassmorphism) - قالب مشترک برای همه صفحات
# ==============================================================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


NAV_ITEMS = [
    ('dashboard', '/dashboard', 'bi-grid', 'داشبورد'),
    ('users', '/users', 'bi-people', 'کاربران'),
    ('shop', '/shop_panel', 'bi-cart', 'فروشگاه'),
    ('missions', '/missions_panel', 'bi-list-check', 'ماموریت‌ها'),
    ('gifts', '/gift_codes', 'bi-gift', 'کدهای هدیه'),
    ('logs', '/logs', 'bi-clock-history', 'لاگ‌ها'),
    ('settings', '/settings', 'bi-gear', 'تنظیمات'),
]

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__ - پنل پاندا</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;700;800&display=swap');
* { margin:0; padding:0; box-sizing:border-box; font-family:'Vazirmatn',sans-serif; }
body { background: radial-gradient(circle at top left, #1b1730, #0a0a0f 60%); color:#fff; min-height:100vh; }
.sidebar { background: rgba(255,255,255,0.03); backdrop-filter: blur(20px); min-height:100vh; padding:25px 15px;
  border-left:1px solid rgba(255,255,255,0.06); position:sticky; top:0; }
.sidebar .brand { color:#a29bfe; font-size:1.6rem; font-weight:800; margin-bottom:30px; text-align:center;
  text-shadow: 0 0 25px rgba(162,155,254,0.5); }
.sidebar .brand span { color:#fff; }
.sidebar a { color:rgba(255,255,255,0.55); text-decoration:none; display:flex; align-items:center; gap:12px;
  padding:12px 18px; border-radius:14px; margin:5px 0; transition:0.25s; font-size:0.95rem; }
.sidebar a:hover { background:rgba(108,92,231,0.15); color:#fff; transform:translateX(-3px); }
.sidebar a.active { background:linear-gradient(135deg, rgba(108,92,231,0.35), rgba(162,155,254,0.12));
  color:#fff; border:1px solid rgba(108,92,231,0.3); box-shadow:0 0 20px rgba(108,92,231,0.15); }
.sidebar a i { font-size:1.2rem; width:24px; }
.main-content { padding:30px; }
.glass { background:rgba(255,255,255,0.03); backdrop-filter:blur(20px); border:1px solid rgba(255,255,255,0.06);
  border-radius:24px; padding:25px; margin-bottom:20px; }
.stat-card { background:linear-gradient(135deg, rgba(108,92,231,0.18), rgba(255,255,255,0.02));
  border:1px solid rgba(108,92,231,0.25); border-radius:20px; padding:20px; text-align:center; transition:0.3s; }
.stat-card:hover { transform:translateY(-4px); box-shadow:0 15px 30px rgba(108,92,231,0.2); }
.stat-card .num { font-size:2rem; font-weight:800; color:#a29bfe; }
.stat-card .label { color:rgba(255,255,255,0.55); font-size:0.9rem; margin-top:5px; }
table { color:#fff; }
.table td, .table th { border-color: rgba(255,255,255,0.06); padding:12px 15px; vertical-align:middle; }
.table thead th { border-bottom: 2px solid rgba(108,92,231,0.3); color: rgba(255,255,255,0.6); font-weight:400; }
.page-title { font-size:1.8rem; font-weight:700; margin-bottom:25px; }
.page-title i { color:#6c5ce7; margin-left:10px; }
.btn-glass { background:linear-gradient(135deg, #6c5ce7, #a29bfe); border:none; border-radius:14px;
  padding:10px 25px; color:#fff; font-weight:600; transition:0.3s; }
.btn-glass:hover { transform:scale(1.03); color:#fff; box-shadow:0 8px 20px rgba(108,92,231,0.35); }
.btn-danger-glass { background:rgba(214,48,49,0.2); border:1px solid rgba(214,48,49,0.4); border-radius:10px;
  padding:6px 14px; color:#ff7675; font-size:0.85rem; }
.btn-ok-glass { background:rgba(0,184,148,0.2); border:1px solid rgba(0,184,148,0.4); border-radius:10px;
  padding:6px 14px; color:#55efc4; font-size:0.85rem; }
.form-control, .form-select { background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.12);
  color:#fff; border-radius:12px; }
.form-control:focus, .form-select:focus { background:rgba(255,255,255,0.1); color:#fff; border-color:#6c5ce7;
  box-shadow:0 0 0 0.2rem rgba(108,92,231,0.2); }
.badge-soft { background:rgba(108,92,231,0.25); color:#a29bfe; padding:4px 10px; border-radius:8px; font-size:0.8rem; }
</style>
</head>
<body>
<div class="container-fluid"><div class="row">
  <div class="col-md-2 sidebar">
    <div class="brand">🐼 <span>پنل پاندا</span></div>
    __NAV__
  </div>
  <div class="col-md-10 main-content">
    <div class="page-title"><i class="__ICON__"></i> __TITLE__</div>
    __BODY__
  </div>
</div></div>
</body></html>
"""


def render_page(active, title, icon, body):
    nav_html = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}"><i class="bi {ic}"></i> {label}</a>'
        for key, href, ic, label in NAV_ITEMS
    ) + '<a href="/logout"><i class="bi bi-box-arrow-right"></i> خروج</a>'
    return (PAGE_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__ICON__", f"bi {icon}")
            .replace("__NAV__", nav_html)
            .replace("__BODY__", body))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = ""
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        error = '<p style="color:#ff7675;text-align:center;margin-top:15px;">رمز اشتباهه، دوباره امتحان کن.</p>'
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ورود - پنل پاندا</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;700&display=swap');
* {{ margin:0; padding:0; box-sizing:border-box; font-family:'Vazirmatn',sans-serif; }}
body {{ min-height:100vh; display:flex; align-items:center; justify-content:center;
  background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); background-size:400% 400%;
  animation: gradientBG 15s ease infinite; }}
@keyframes gradientBG {{ 0%{{background-position:0% 50%;}} 50%{{background-position:100% 50%;}} 100%{{background-position:0% 50%;}} }}
.glass-card {{ background:rgba(255,255,255,0.05); backdrop-filter:blur(20px); border:1px solid rgba(255,255,255,0.1);
  border-radius:30px; padding:50px 40px; max-width:420px; width:100%; box-shadow:0 30px 80px rgba(0,0,0,0.6); }}
.glass-card h2 {{ color:#fff; text-align:center; font-weight:300; margin-bottom:35px; }}
.glass-card h2 span {{ color:#6c5ce7; }}
.glass-card .form-control {{ background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.15);
  border-radius:16px; padding:16px 20px; color:#fff; }}
.glass-card .btn {{ background:linear-gradient(135deg, #6c5ce7, #a29bfe); border:none; border-radius:16px;
  padding:16px; color:#fff; font-weight:600; width:100%; font-size:1.1rem; }}
</style>
</head>
<body>
<div class="glass-card">
<h2>🐼 پنل <span>پاندا</span></h2>
<form method="POST">
<input type="password" name="password" class="form-control mb-3" placeholder="رمز عبور" required autofocus>
<button type="submit" class="btn">ورود</button>
</form>
{error}
</div>
</body></html>"""


@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    stats = db.get_stats()
    top = db.get_leaderboard(8)
    cards = "".join(f'''
    <div class="col-md-3 col-6 mb-3"><div class="stat-card">
      <div class="num">{v}</div><div class="label">{label}</div>
    </div></div>''' for label, v in [
        ("کل کاربران", stats['total_users']), ("کاربران فعال (۷ روز)", stats['active_users']),
        ("مجموع امتیازها", stats['total_points']), ("کل بازی‌ها", stats['total_games']),
        ("کلن‌ها", stats['total_clans']), ("ماموریت‌ها", stats['total_missions']),
        ("دستاوردها", stats['total_achievements']), ("کاربران بن‌شده", stats['banned_users']),
    ])
    labels = json.dumps([r['first_name'] or r['username'] or str(r['user_id']) for r in top], ensure_ascii=False)
    points = json.dumps([r['points'] for r in top])
    body = f'''
    <div class="row">{cards}</div>
    <div class="glass">
      <h5 class="mb-3"><i class="bi bi-bar-chart" style="color:#6c5ce7;"></i> ۸ کاربر برتر بر اساس امتیاز</h5>
      <canvas id="topChart" height="90"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('topChart'), {{
      type: 'bar',
      data: {{ labels: {labels}, datasets: [{{ label:'امتیاز', data: {points},
        backgroundColor:'rgba(108,92,231,0.55)', borderColor:'#a29bfe', borderWidth:1, borderRadius:8 }}] }},
      options: {{ scales: {{ x:{{ ticks:{{color:'#ccc'}}, grid:{{color:'rgba(255,255,255,0.05)'}} }},
                             y:{{ ticks:{{color:'#ccc'}}, grid:{{color:'rgba(255,255,255,0.05)'}} }} }},
                  plugins: {{ legend:{{ labels:{{color:'#ccc'}} }} }} }}
    }});
    </script>
    '''
    return render_page('dashboard', 'داشبورد', 'bi-grid', body)


@app.route('/users')
@login_required
def users_page():
    search = request.args.get('q', '').strip()
    users = db.get_all_users(search or None)
    rows = "".join(f'''<tr>
      <td>{u['user_id']}</td><td>{u['username'] or '-'}</td><td>{u['first_name'] or '-'}</td>
      <td>{u['points']}</td><td>{u['level']}</td>
      <td>{'<span class="badge-soft" style="color:#ff7675;background:rgba(214,48,49,0.2);">مسدود</span>' if u['is_banned'] else '<span class="badge-soft">فعال</span>'}</td>
      <td>
        <button class="btn-danger-glass" onclick="toggleBan({u['user_id']})">{'آنبن' if u['is_banned'] else 'بن'}</button>
        <button class="btn-ok-glass" onclick="editPoints({u['user_id']}, {u['points']})">ویرایش امتیاز</button>
      </td>
    </tr>''' for u in users)
    body = f'''
    <div class="glass mb-3">
      <form class="d-flex gap-2" method="GET">
        <input class="form-control" type="text" name="q" value="{search}" placeholder="جستجو بر اساس یوزرنیم، نام یا آیدی">
        <button class="btn-glass" type="submit">جستجو</button>
      </form>
    </div>
    <div class="glass"><table class="table"><thead><tr>
      <th>شناسه</th><th>یوزرنیم</th><th>نام</th><th>امتیاز</th><th>سطح</th><th>وضعیت</th><th>عملیات</th>
    </tr></thead><tbody>{rows}</tbody></table></div>
    <script>
    function toggleBan(uid) {{
      fetch('/api/users/' + uid + '/toggle_ban', {{method:'POST'}}).then(() => location.reload());
    }}
    function editPoints(uid, current) {{
      const val = prompt('امتیاز جدید:', current);
      if (val === null) return;
      const n = parseInt(val);
      if (isNaN(n)) return alert('عدد معتبر وارد کن.');
      fetch('/api/users/' + uid + '/set_points', {{
        method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{points:n}})
      }}).then(() => location.reload());
    }}
    </script>
    '''
    return render_page('users', 'مدیریت کاربران', 'bi-people', body)


@app.route('/api/users/<int:user_id>/toggle_ban', methods=['POST'])
@login_required
def api_toggle_ban(user_id):
    db.toggle_ban(user_id)
    return jsonify({"ok": True})


@app.route('/api/users/<int:user_id>/set_points', methods=['POST'])
@login_required
def api_set_points(user_id):
    data = request.get_json(force=True, silent=True) or {}
    points = int(data.get('points', 0))
    db.set_points(user_id, points)
    return jsonify({"ok": True})


@app.route('/shop_panel', methods=['GET', 'POST'])
@login_required
def shop_panel():
    if request.method == 'POST':
        db.add_shop_item(
            request.form.get('item', '').strip(),
            int(request.form.get('price', 0) or 0),
            request.form.get('description', '').strip(),
            request.form.get('emoji', '🎁').strip(),
            int(request.form.get('stock', -1) or -1),
            request.form.get('category', 'general').strip(),
        )
        return redirect(url_for('shop_panel'))
    items = db.get_shop_items()
    rows = "".join(f'''<tr>
      <td>{i['emoji']} {i['item']}</td><td>{i['price']}</td><td>{i['description']}</td>
      <td>{"نامحدود" if i['stock']==-1 else i['stock']}</td>
      <td><form method="POST" action="/shop_panel/delete" style="display:inline;">
        <input type="hidden" name="item" value="{i['item']}">
        <button class="btn-danger-glass" type="submit">حذف</button></form></td>
    </tr>''' for i in items)
    body = f'''
    <div class="glass mb-3">
      <h5 class="mb-3">افزودن آیتم جدید</h5>
      <form method="POST" class="row g-2">
        <div class="col-md-2"><input class="form-control" name="emoji" placeholder="ایموجی" value="🎁"></div>
        <div class="col-md-3"><input class="form-control" name="item" placeholder="نام آیتم" required></div>
        <div class="col-md-2"><input class="form-control" name="price" type="number" placeholder="قیمت" required></div>
        <div class="col-md-3"><input class="form-control" name="description" placeholder="توضیحات"></div>
        <div class="col-md-1"><input class="form-control" name="stock" type="number" placeholder="موجودی (-1=نامحدود)" value="-1"></div>
        <div class="col-md-1"><button class="btn-glass w-100" type="submit">افزودن</button></div>
      </form>
    </div>
    <div class="glass"><table class="table"><thead><tr>
      <th>آیتم</th><th>قیمت</th><th>توضیحات</th><th>موجودی</th><th></th>
    </tr></thead><tbody>{rows}</tbody></table></div>
    '''
    return render_page('shop', 'مدیریت فروشگاه', 'bi-cart', body)


@app.route('/shop_panel/delete', methods=['POST'])
@login_required
def shop_panel_delete():
    db.delete_shop_item(request.form.get('item', ''))
    return redirect(url_for('shop_panel'))


@app.route('/missions_panel')
@login_required
def missions_panel():
    missions = db.get_missions()
    rows = "".join(f'''<tr>
      <td>{m['name']}</td><td>{m['description']}</td>
      <td>{m['requirement_type']} ≥ {m['requirement_value']}</td>
      <td>{m['reward']}</td><td>{m['cooldown_hours']}h</td>
    </tr>''' for m in missions)
    body = f'''<div class="glass"><table class="table"><thead><tr>
      <th>ماموریت</th><th>توضیحات</th><th>شرط</th><th>پاداش</th><th>کول‌داون</th>
    </tr></thead><tbody>{rows}</tbody></table></div>'''
    return render_page('missions', 'مدیریت ماموریت‌ها', 'bi-list-check', body)


@app.route('/gift_codes', methods=['GET', 'POST'])
@login_required
def gift_codes_page():
    if request.method == 'POST':
        db.create_gift_code(
            int(request.form.get('reward', 0) or 0),
            int(request.form.get('max_uses', 1) or 1),
        )
        return redirect(url_for('gift_codes_page'))
    codes = db.get_gift_codes()
    rows = "".join(f'''<tr>
      <td><code>{c['code']}</code></td><td>{c['reward']}</td>
      <td>{c['used_count']}/{c['max_uses']}</td><td>{c['created_at']}</td>
    </tr>''' for c in codes)
    body = f'''
    <div class="glass mb-3">
      <h5 class="mb-3">ساخت کد هدیه جدید</h5>
      <form method="POST" class="row g-2">
        <div class="col-md-4"><input class="form-control" name="reward" type="number" placeholder="مقدار جایزه" required></div>
        <div class="col-md-4"><input class="form-control" name="max_uses" type="number" placeholder="تعداد دفعات استفاده" value="1"></div>
        <div class="col-md-4"><button class="btn-glass w-100" type="submit">ساخت کد</button></div>
      </form>
    </div>
    <div class="glass"><table class="table"><thead><tr>
      <th>کد</th><th>جایزه</th><th>استفاده‌شده</th><th>تاریخ ساخت</th>
    </tr></thead><tbody>{rows}</tbody></table></div>
    '''
    return render_page('gifts', 'کدهای هدیه', 'bi-gift', body)


@app.route('/logs')
@login_required
def logs_page():
    logs = db.get_logs(150)
    rows = "".join(
        f'<tr><td>{l["timestamp"]}</td><td>{l["user_id"]}</td>'
        f'<td><span class="badge-soft">{l["action"]}</span></td><td>{l["details"]}</td></tr>'
        for l in logs)
    body = f'''<div class="glass"><table class="table"><thead><tr>
      <th>زمان</th><th>کاربر</th><th>عمل</th><th>جزئیات</th>
    </tr></thead><tbody>{rows}</tbody></table></div>'''
    return render_page('logs', 'لاگ‌ها', 'bi-clock-history', body)


@app.route('/settings')
@login_required
def settings_page():
    masked_token = BOT_TOKEN[:6] + "..." + BOT_TOKEN[-4:]
    body = f'''
    <div class="glass">
      <h5 class="mb-3"><i class="bi bi-info-circle" style="color:#6c5ce7;"></i> وضعیت پیکربندی</h5>
      <p>🔑 توکن ربات: <code>{masked_token}</code> (بهتره از متغیر محیطی PANDA_BOT_TOKEN ست بشه)</p>
      <p>🗄️ مسیر دیتابیس: <code>{DB_PATH}</code></p>
      <p>🌐 آدرس API سروش: <code>{BASE_URL.split(BOT_TOKEN)[0]}...</code></p>
      <p class="mt-3" style="color:rgba(255,255,255,0.5);">برای تغییر رمز پنل، متغیر محیطی PANDA_ADMIN_PASSWORD رو ست کن.</p>
    </div>
    '''
    return render_page('settings', 'تنظیمات', 'bi-gear', body)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


# ------------------------------------------------------------
# 🚀 اجرا
# ------------------------------------------------------------
if __name__ == "__main__":
    print("🔹 حذف وب‌هوک...")
    try:
        requests.get(f"{BASE_URL}/deleteWebhook", timeout=10)
    except Exception as e:
        print(f"⚠️ حذف وب‌هوک ناموفق بود (مشکلی نیست، با polling کار می‌کنیم): {e}")
    threading.Thread(target=run_polling, daemon=True).start()
    print("🚀 ربات و پنل مدیریت راه‌اندازی شدند...")
    print("🔹 پنل: http://localhost:5000")
    print(f"🔹 رمز پنل: {ADMIN_PASSWORD}")
    print("🔹 ربات با Polling کار می‌کند (بدون ngrok)")
    app.run(host="0.0.0.0", port=5000, debug=False)
