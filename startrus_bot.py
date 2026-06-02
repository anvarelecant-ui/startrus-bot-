"""
StartRus Bot v2.0 — Telegram бот для продажи книги StartRus
Книга для изучения русского языка (уровень A2) для узбекоязычной аудитории

Двуязычный интерфейс: русский + узбекский

Возможности v2.0:
  • Постоянное хранение языка пользователей (SQLite)
  • Превью книги (отправка образцов страниц)
  • Процесс заказа с отслеживанием оплаты
  • Аналитика действий пользователей
  • Уведомления админу (новые пользователи, заказы, чеки)
  • Улучшенная обработка ошибок
  • Автоотправка PDF после подтверждения оплаты
  • Система промокодов / скидок
"""

import os
import sys
import sqlite3
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ─── Logging ───────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("StartRusBot")

# ─── Install dependencies if needed ───────────────────────
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, CallbackQueryHandler,
        MessageHandler, filters, ContextTypes,
    )
    from telegram.request import HTTPXRequest
    from telegram.error import TelegramError
except ImportError:
    logger.info("Installing python-telegram-bot...")
    import subprocess
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "python-telegram-bot>=21.0"]
    )
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, CallbackQueryHandler,
        MessageHandler, filters, ContextTypes,
    )
    from telegram.request import HTTPXRequest
    from telegram.error import TelegramError


# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / "Credentials.env"
    load_dotenv(dotenv_path=env_path)
except ImportError:
    logger.info("python-dotenv not installed, proceeding with os env vars.")

_token = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_TOKEN = _token.strip() if _token else None
if not BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN not set! "
        "Set it in Railway dashboard → Variables."
    )

admin_env = os.getenv("ADMIN_USER_ID", "0")
ADMIN_USER_ID = int(admin_env) if admin_env.strip() else 0
SELLER_CONTACT = os.getenv("SELLER_CONTACT", "https://t.me/callmeanv")
price_env = os.getenv("BOOK_PRICE", "59000")
BOOK_PRICE = int(price_env) if price_env.strip() else 59000
BOOK_PDF_PATH = os.getenv("BOOK_PDF_PATH", "")
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "")     # e.g. "8600 1234 5678 9012"
PAYMENT_METHOD = os.getenv("PAYMENT_METHOD", "")  # e.g. "Click / Payme / Перевод"
DB_PATH = os.getenv("DB_PATH", "startrus.db")


# ═══════════════════════════════════════════════════════════
#  DATABASE  (SQLite)
# ═══════════════════════════════════════════════════════════
def _conn() -> sqlite3.Connection:
    """Thread-safe DB connection."""
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    """Create tables on first run."""
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            lang         TEXT    DEFAULT 'ru',
            first_name   TEXT,
            username     TEXT,
            registered_at TEXT
        );
        CREATE TABLE IF NOT EXISTS orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            status          TEXT DEFAULT 'pending',
            promo_code      TEXT DEFAULT '',
            original_amount INTEGER DEFAULT 0,
            final_amount    INTEGER DEFAULT 0,
            receipt_file_id TEXT DEFAULT '',
            created_at      TEXT,
            confirmed_at    TEXT DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS analytics (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            action     TEXT,
            data       TEXT DEFAULT '',
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS promo_codes (
            code             TEXT PRIMARY KEY,
            discount_percent INTEGER,
            max_uses         INTEGER DEFAULT 0,
            used_count       INTEGER DEFAULT 0,
            active           INTEGER DEFAULT 1,
            created_at       TEXT
        );
        CREATE TABLE IF NOT EXISTS course_requests (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            format     TEXT,
            level      TEXT,
            name       TEXT,
            phone      TEXT,
            created_at TEXT
        );
    """)
    c.commit()
    c.close()
    logger.info("✅ БД инициализирована")


# ── helpers ────────────────────────────────────────────────
_now = lambda: datetime.now(timezone.utc).isoformat()


def db_save_user(uid: int, lang: str,
                 first_name: str = "", username: str = "") -> bool:
    """Save / update user.  Returns True if this is a *new* user."""
    c = _conn()
    exists = c.execute(
        "SELECT 1 FROM users WHERE user_id=?", (uid,)
    ).fetchone()
    c.execute(
        """INSERT INTO users (user_id,lang,first_name,username,registered_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(user_id)
           DO UPDATE SET lang=excluded.lang,
                         first_name=excluded.first_name,
                         username=excluded.username""",
        (uid, lang, first_name, username, _now()),
    )
    c.commit()
    c.close()
    return exists is None


def db_get_lang(uid: int) -> str:
    c = _conn()
    row = c.execute("SELECT lang FROM users WHERE user_id=?", (uid,)).fetchone()
    c.close()
    return row["lang"] if row else "ru"


def db_set_lang(uid: int, lang: str) -> None:
    c = _conn()
    c.execute(
        """INSERT INTO users (user_id,lang,registered_at) VALUES (?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET lang=?""",
        (uid, lang, _now(), lang),
    )
    c.commit()
    c.close()


def db_log(uid: int, action: str, data: str = "") -> None:
    c = _conn()
    c.execute(
        "INSERT INTO analytics (user_id,action,data,created_at) VALUES (?,?,?,?)",
        (uid, action, data, _now()),
    )
    c.commit()
    c.close()


# ── orders ─────────────────────────────────────────────────
def db_create_order(uid: int, promo: str = "",
                    orig: int = 0, final: int = 0) -> int:
    c = _conn()
    cur = c.execute(
        """INSERT INTO orders
           (user_id,status,promo_code,original_amount,final_amount,created_at)
           VALUES (?,'pending',?,?,?,?)""",
        (uid, promo, orig, final, _now()),
    )
    oid = cur.lastrowid
    c.commit()
    c.close()
    return oid


def db_set_receipt(oid: int, file_id: str) -> None:
    c = _conn()
    c.execute("UPDATE orders SET receipt_file_id=? WHERE id=?", (file_id, oid))
    c.commit()
    c.close()


def db_confirm_order(oid: int) -> dict | None:
    c = _conn()
    c.execute(
        "UPDATE orders SET status='confirmed',confirmed_at=? "
        "WHERE id=? AND status='pending'",
        (_now(), oid),
    )
    c.commit()
    row = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    c.close()
    return dict(row) if row else None


def db_reject_order(oid: int) -> dict | None:
    c = _conn()
    c.execute(
        "UPDATE orders SET status='rejected' WHERE id=? AND status='pending'",
        (oid,),
    )
    c.commit()
    row = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    c.close()
    return dict(row) if row else None


def db_pending_order(uid: int) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT * FROM orders WHERE user_id=? AND status='pending' "
        "ORDER BY id DESC LIMIT 1",
        (uid,),
    ).fetchone()
    c.close()
    return dict(row) if row else None


# ── promo ──────────────────────────────────────────────────
def db_get_promo(code: str) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT * FROM promo_codes WHERE code=? AND active=1",
        (code.upper().strip(),),
    ).fetchone()
    c.close()
    if row:
        r = dict(row)
        if r["max_uses"] > 0 and r["used_count"] >= r["max_uses"]:
            return None          # лимит исчерпан
        return r
    return None


def db_use_promo(code: str) -> None:
    c = _conn()
    c.execute(
        "UPDATE promo_codes SET used_count=used_count+1 WHERE code=?",
        (code.upper().strip(),),
    )
    c.commit()
    c.close()


def db_add_promo(code: str, discount: int, max_uses: int) -> None:
    c = _conn()
    c.execute(
        """INSERT OR REPLACE INTO promo_codes
           (code,discount_percent,max_uses,used_count,active,created_at)
           VALUES (?,?,?,0,1,?)""",
        (code.upper().strip(), discount, max_uses, _now()),
    )
    c.commit()
    c.close()


def db_list_promos() -> list[dict]:
    c = _conn()
    rows = c.execute("SELECT * FROM promo_codes WHERE active=1").fetchall()
    c.close()
    return [dict(r) for r in rows]


# ── courses ────────────────────────────────────────────────
def db_create_course_request(uid: int, format: str, level: str, name: str, phone: str) -> int:
    c = _conn()
    cur = c.execute(
        """INSERT INTO course_requests (user_id, format, level, name, phone, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (uid, format, level, name, phone, _now())
    )
    req_id = cur.lastrowid
    c.commit()
    c.close()
    return req_id


# ── stats ──────────────────────────────────────────────────
def db_stats() -> dict:
    c = _conn()
    s: dict = {}
    s["users"]     = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    s["orders"]    = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    s["pending"]   = c.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
    s["confirmed"] = c.execute("SELECT COUNT(*) FROM orders WHERE status='confirmed'").fetchone()[0]
    s["rejected"]  = c.execute("SELECT COUNT(*) FROM orders WHERE status='rejected'").fetchone()[0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    s["today_users"]  = c.execute(
        "SELECT COUNT(*) FROM users WHERE registered_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]
    s["today_orders"] = c.execute(
        "SELECT COUNT(*) FROM orders WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]
    top = c.execute(
        "SELECT action, COUNT(*) cnt FROM analytics "
        "GROUP BY action ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    s["top_actions"] = [(r["action"], r["cnt"]) for r in top]
    c.close()
    return s


# ═══════════════════════════════════════════════════════════
#  MARKDOWNV2  ESCAPE HELPER
# ═══════════════════════════════════════════════════════════
_MD2_SPECIAL = set(r"_*[]()~`>#+-=|{}.!")

def esc(text) -> str:
    """Escape any dynamic value for MarkdownV2."""
    return "".join(f"\\{ch}" if ch in _MD2_SPECIAL else ch for ch in str(text))


#  TRANSLATIONS   (RU + UZ)
# ═══════════════════════════════════════════════════════════
TEXTS = {
    "ru": {
        # ── main ───────────────────────────────────────────
        "welcome": (
            "📚 *Добро пожаловать в StartRus\\!*\n\n"
            "Я — бот книги *StartRus* для изучения русского языка\\.\n\n"
            "📖 Уровень: *A2 \\(начальный\\)*\n"
            "🎯 Аудитория: узбекоязычные студенты\n\n"
            "Выберите действие из меню ниже 👇"
        ),
        "choose_lang": "🌐 *Выберите язык / Tilni tanlang*",
        "lang_set": "✅ Язык установлен: *Русский* 🇷🇺",
        "book_info": (
            "📖 *StartRus — Учебник русского языка*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎯 *Уровень:* A2 \\(начальный\\)\n\n"
            "👥 *Для кого:* Узбекоязычные студенты, которые хотят "
            "выучить русский язык с нуля или укрепить базовые знания\\.\n\n"
            "📋 *Что внутри:*\n"
            "• Грамматика с объяснениями на русском языке\n"
            "• Практические диалоги и упражнения\n"
            "• Полезная лексика для повседневной жизни\n"
            "• Советы по произношению\n\n"
            "📄 *Формат:* PDF \\(электронная книга\\)\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔜 *Скоро:* Уровни B1, B2 и выше\\!"
        ),
        "price": (
            "💰 *Цена книги StartRus*\n\n"
            "📕 StartRus A2 — *{price} сўм*\n\n"
            "Для покупки нажмите «💳 Купить» 👇"
        ),
        "faq": (
            "❓ *Часто задаваемые вопросы*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*В: Какой формат книги?*\n"
            "О: PDF — электронная книга\\. Получите сразу после покупки\\.\n\n"
            "*В: Какой уровень?*\n"
            "О: A2 — начальный\\. Подходит для тех, кто знает алфавит "
            "и базовые фразы\\.\n\n"
            "*В: Есть объяснения на узбекском?*\n"
            "О: Да\\! В книге все правила и темы объясняются смешанно — и на русском, и на узбекском языках\\.\n\n"
            "*В: Будут другие уровни?*\n"
            "О: Да, планируются книги B1, B2 и выше\\.\n\n"
            "*В: Как купить?*\n"
            "О: Нажмите кнопку «💳 Купить» в главном меню\\."
        ),
        "contact": (
            "📞 *Связаться с нами*\n\n"
            "Для покупки книги или любых вопросов — "
            "напишите нам напрямую\\! 👇\n\n"
            "Вы также можете задать свой вопрос поддержке прямо здесь, нажав кнопку ниже 👇"
        ),
        "unknown": (
            "🤔 Я пока не понимаю это сообщение\\.\n\n"
            "Используйте кнопки меню или напишите /start"
        ),
        # ── preview ────────────────────────────────────────
        "preview": (
            "📖 *Демо-урок 1: Отдых и путешествия*\n\n"
            "В этом разделе вы можете ознакомиться с материалами первого урока книги\\.\n\n"
            "Выберите интересующий вас подраздел 👇"
        ),
        "prev_dialog": (
            "💬 *Диалог: Отдых и путешествия*\n\n"
            "🎙 *Нилуфар:* Анзор, ты хорошо отдохнул в отпуске?\n"
            "🎙 *Анзор:* Да, очень\\! Я ездил в Санкт\\-Петербург на поезде\\. Там потрясающе\\!\n"
            "🎙 *Нилуфар:* Что ты делал там?\n"
            "🎙 *Анзор:* Я ходил на экскурсии, смотрел достопримечательности и фотографировал\\. А ты?\n"
            "🎙 *Нилуфар:* Я никуда не ездила\\. Отдыхала дома — некогда было\\.\n"
            "🎙 *Анзор:* Жаль\\! В следующий раз поедем вместе\\!\n\n"
            "❓ *Вопрос:* Куда ездил Анзор и на чём? — Anzor qayerga va nima bilan bordi?"
        ),
        "prev_vocab": (
            "📖 *Новые слова (Лексика)*\n\n"
            "1\\. *путешествие* — sayohat\n"
            "2\\. *отдых* — dam olish\n"
            "3\\. *отпуск* — ta'til\n"
            "4\\. *пляж* — plyaj\n"
            "5\\. *горы* — togʻlar\n"
            "6\\. *море* — dengiz\n"
            "7\\. *гостиница* — mehmonxona\n"
            "8\\. *билет* — chipta\n"
            "9\\. *самолёт* — samolyot\n"
            "10\\. *поезд* — poezd\n"
            "11\\. *машина* — mashina\n"
            "12\\. *экскурсия* — ekskursiya\n"
            "13\\. *музей* — muzey\n"
            "14\\. *достопримечательность* — diqqatga sazovor joy\n"
            "15\\. *сувенир* — suvenir\n"
            "16\\. *фотография* — fotosurat\n"
            "17\\. *лето* — yoz\n"
            "18\\. *зима* — qish"
        ),
        "prev_grammar": (
            "📐 *Грамматика: Глаголы движения и падежи*\n\n"
            "1\\. *Глаголы движения \\(Настоящее время\\):*\n"
            "• *ехать* \\(поездом, машиной\\): я еду, ты едешь, он едет, мы едем, вы едете, они едут\\.\n"
            "• *лететь* \\(самолётом\\): я лечу, ты летишь, он летит, мы летим, вы летите, они летят\\.\n"
            "• *идти* \\(пешком\\): я иду, ты идёшь, он идёт, мы идём, вы идёте, они идут\\.\n\n"
            "2\\. *Куда\\? \\(Винительный падеж\\) vs Где\\? \\(Предложный падеж\\):*\n"
            "• в Россию \\(куда\\?\\) — в России \\(где\\?\\)\n"
            "• в Москву \\(куда\\?\\) — в Москве \\(где\\?\\)\n"
            "• на пляж \\(куда\\?\\) — на пляже \\(где\\?\\)\n"
            "• в гостиницу \\(куда\\?\\) — в гостинице \\(где\\?\\)\n"
            "• на экскурсию \\(куда\\?\\) — на экскурсии \\(где\\?\\)"
        ),
        "prev_test_start": (
            "🧠 *Мини-тест по Теме 1*\n\n"
            "Проверьте свои знания\\! Ответьте на 3 простых вопроса\\.\n\n"
            "Готовы начать?"
        ),
        "prev_test_q1": (
            "❓ *Вопрос 1 из 3:*\n\n"
            "Мы \\_\\_\\_ \\(лететь\\) в Дубай\\."
        ),
        "prev_test_q2": (
            "❓ *Вопрос 2 из 3:*\n\n"
            "Она едет в \\_\\_\\_ \\(Италия\\)\\."
        ),
        "prev_test_q3": (
            "❓ *Вопрос 3 из 3:*\n\n"
            "Я живу в \\_\\_\\_ \\(гостиница\\)\\."
        ),
        "prev_test_correct": "✅ *Правильно\\!*",
        "prev_test_wrong": "❌ *Неправильно\\. Попробуйте ещё раз\\!*",
        "prev_test_finish": (
            "🎉 *Поздравляем\\!*\n\n"
            "Вы успешно прошли мини-тест по первому уроку\\!\n\n"
            "Книга содержит *30 таких тем*, охватывающих всю необходимую грамматику и лексику уровня A2 для повседневного общения\\.\n\n"
            "Купите книгу StartRus A2 прямо сейчас всего за *{price} сўм* 👇"
        ),
        "support_intro": (
            "✏️ *Задать вопрос*\n\n"
            "Напишите ваш вопрос или сообщение для поддержки в одном сообщении 👇\n\n"
            "Мы ответим вам прямо в этот чат\\."
        ),
        "support_sent": "✅ *Ваш вопрос отправлен администратору\\!* Мы ответим вам в ближайшее время\\.",
        # ── buy / order flow ───────────────────────────────
        "buy_intro": (
            "💳 *Покупка StartRus A2*\n\n"
            "📕 Цена: *{price} сўм*\n\n"
            "У вас есть промокод?"
        ),
        "buy_intro_discounted": (
            "💳 *Покупка StartRus A2*\n\n"
            "📕 Цена: ~{old_price} сўм~ → *{new_price} сўм*\n"
            "🎉 Скидка: *{discount}%* \\(промокод `{code}`\\)\n\n"
        ),
        "buy_enter_promo": "✏️ Введите ваш промокод:",
        "buy_promo_applied": (
            "✅ Промокод *{code}* применён\\!\n"
            "Скидка: *{discount}%*\n\n"
            "💰 Новая цена: *{new_price} сўм*"
        ),
        "buy_promo_invalid": "❌ Промокод не найден или больше не действует\\.",
        "buy_payment_info": (
            "💳 *Инструкция по оплате*\n\n"
            "💰 Сумма к оплате: *{amount} сўм*\n\n"
            "📲 Переведите на карту:\n"
            "`{card}`\n\n"
            "📸 После оплаты отправьте *скриншот чека* "
            "прямо в этот чат 👇"
        ),
        "buy_payment_info_no_card": (
            "💳 *Инструкция по оплате*\n\n"
            "💰 Сумма к оплате: *{amount} сўм*\n\n"
            "📲 Свяжитесь с продавцом для получения "
            "реквизитов оплаты\\.\n\n"
            "📸 После оплаты отправьте *скриншот чека* "
            "прямо в этот чат 👇"
        ),
        "buy_receipt_ok": (
            "✅ Чек получен\\!\n\n"
            "📋 Заказ *\\#{order_id}*\n"
            "⏳ Ожидайте подтверждения от администратора\\.\n\n"
            "Обычно это занимает несколько минут\\."
        ),
        "buy_confirmed": (
            "🎉 *Оплата подтверждена\\!*\n\n"
            "Спасибо за покупку\\! Вот ваша книга 📚"
        ),
        "buy_confirmed_no_pdf": (
            "🎉 *Оплата подтверждена\\!*\n\n"
            "Спасибо за покупку\\! Свяжитесь с продавцом "
            "для получения книги 👇"
        ),
        "buy_rejected": (
            "❌ *К сожалению, оплата не подтверждена\\.*\n\n"
            "Если вы уверены, что оплатили — "
            "свяжитесь с нами напрямую 👇"
        ),
        "buy_cancelled": "🚫 Заказ отменён\\.",
        "buy_already_pending": (
            "⏳ У вас уже есть активный заказ *\\#{order_id}*\\.\n\n"
            "Дождитесь подтверждения или отмените текущий заказ\\."
        ),
        # ── materials & courses ────────────────────────────
        "materials_menu": "📚 *Учебные материалы*\n\nВыберите интересующий вас уровень:",
        "courses_menu": "🎓 *Записаться на курсы*\n\nВ каком формате вы хотели бы заниматься?",
        "course_ask_level": "Каким уровнем языка вы хотите заниматься?",
        "course_ask_name": "📝 *Как к вам обращаться?*\n\nПожалуйста, напишите ваше Имя и Фамилию\\.",
        "course_ask_phone": "📞 *Ваш номер телефона*\n\nНапишите ваш контактный номер \\(например: \\+998901234567\\)\\.",
        "course_success": "✅ *Ваша заявка успешно принята\\!*\n\nСпасибо\\! Мы скоро свяжемся с вами для уточнения деталей\\.",
        "mat_coming_soon": "⏳ *Уровень {lvl}*\n\nМатериалы для этого уровня сейчас находятся в разработке\\. Мы обязательно сообщим, когда они будут готовы\\!",
        # ── buttons ────────────────────────────────────────
        "btn_materials": "📚 Учебные материалы",
        "btn_courses": "🎓 Записаться на курсы",
        "btn_course_group": "👥 Групповые занятия",
        "btn_course_indiv": "👤 Индивидуальные занятия",
        "btn_book": "📖 О книге",
        "btn_price": "💰 Цена",
        "btn_buy": "💳 Купить",
        "btn_preview": "📄 Превью",
        "btn_faq": "❓ FAQ",
        "btn_contact": "📞 Связаться",
        "btn_lang": "🌐 Язык",
        "btn_back": "◀️ Назад",
        "btn_contact_link": "✉️ Написать продавцу",
        "btn_promo_yes": "🎟 Да, есть промокод",
        "btn_promo_no": "➡️ Нет, продолжить",
        "btn_cancel_order": "🚫 Отменить заказ",
        "btn_prev_dialog": "💬 Диалог",
        "btn_prev_vocab": "📖 Словарь",
        "btn_prev_grammar": "📐 Грамматика",
        "btn_prev_test": "🧠 Тест",
        "btn_prev_back": "◀️ К превью",
        "btn_test_start": "🚀 Начать тест",
        "btn_ask_support": "✉️ Задать вопрос",
    },

    "uz": {
        # ── main ───────────────────────────────────────────
        "welcome": (
            "📚 *StartRus ga xush kelibsiz\\!*\n\n"
            "Men — rus tilini o'rganish uchun *StartRus* kitob botiman\\.\n\n"
            "📖 Daraja: *A2 \\(boshlang'ich\\)*\n"
            "🎯 Auditoriya: o'zbekzabon talabalar\n\n"
            "Quyidagi menyudan tanlang 👇"
        ),
        "choose_lang": "🌐 *Tilni tanlang / Выберите язык*",
        "lang_set": "✅ Til tanlandi: *O'zbekcha* 🇺🇿",
        "book_info": (
            "📖 *StartRus — Rus tili darsligi*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎯 *Daraja:* A2 \\(boshlang'ich\\)\n\n"
            "👥 *Kim uchun:* Rus tilini noldan o'rganmoqchi yoki "
            "asosiy bilimlarini mustahkamlamoqchi bo'lgan o'zbekzabon talabalar\\.\n\n"
            "📋 *Ichida nima bor:*\n"
            "• Rus tilida grammatik tushuntirishlar\n"
            "• Amaliy dialoglar va mashqlar\n"
            "• Kundalik hayot uchun foydali so'zlar\n"
            "• Talaffuz bo'yicha maslahatlar\n\n"
            "📄 *Format:* PDF \\(elektron kitob\\)\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔜 *Tez kunda:* B1, B2 va undan yuqori darajalar\\!"
        ),
        "price": (
            "💰 *StartRus kitob narxi*\n\n"
            "📕 StartRus A2 — *{price} so'm*\n\n"
            "Sotib olish uchun «💳 Sotib olish» tugmasini bosing 👇"
        ),
        "faq": (
            "❓ *Ko'p beriladigan savollar*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*S: Kitob qanday formatda?*\n"
            "J: PDF — elektron kitob\\. Xarid qilgandan so'ng darhol olasiz\\.\n\n"
            "*S: Qaysi daraja?*\n"
            "J: A2 — boshlang'ich\\. Alifbo va oddiy iboralarni biladiganlar uchun\\.\n\n"
            "*S: O'zbekcha tushuntirishlar bormi?*\n"
            "J: Ha\\! Kitobdagi barcha qoida va mavzular aralash — ham rus, ham o'zbek tillarida tushuntirilgan\\.\n\n"
            "*S: Boshqa darajalar bo'ladimi?*\n"
            "J: Ha, B1, B2 va undan yuqori kitoblar rejalashtirilgan\\.\n\n"
            "*S: Qanday sotib olish mumkin?*\n"
            "J: Menyudagi «💳 Sotib olish» tugmasini bosing\\."
        ),
        "contact": (
            "📞 *Biz bilan bog'laning*\n\n"
            "Kitobni sotib olish yoki har qanday savol uchun — "
            "bizga yozing\\! 👇\n\n"
            "Shuningdek, pastdagi tugmani bosib qo'llab-quvvatlash xizmatiga savol yuborishingiz mumkin 👇"
        ),
        "unknown": (
            "🤔 Men bu xabarni tushunmadim\\.\n\n"
            "Menyu tugmalaridan foydalaning yoki /start yozing"
        ),
        # ── preview ────────────────────────────────────────
        "preview": (
            "📖 *1-dars: Dam olish va sayohat*\n\n"
            "Bu bo'limda kitobning birinchi darsi materiallari bilan tanishishingiz mumkin\\.\n\n"
            "Kerakli bo'limni tanlang 👇"
        ),
        "prev_dialog": (
            "💬 *Dialog: Dam olish va sayohat*\n\n"
            "🎙 *Nilufar:* Анзор, ты хорошо отдохнул в отпуске? (Anzor, ta'tilda yaxshi dam oldingmi?)\n"
            "🎙 *Anzor:* Да, очень\\! Я ездил в Санкт\\-Петербург на поезде\\. Там потрясающе\\! (Ha, juda ham! Poezdda Sankt-Peterburgga bordim. U yer ajoyib!)\n"
            "🎙 *Nilufar:* Что ты делал там? (U yerda nima qilding?)\n"
            "🎙 *Anzor:* Я ходил на экскурсии, смотрел достопримечательности и фотографировал\\. А ты? (Ekskursiyalarga bordim, diqqatga sazovor joylarni ko'rdim va rasmga oldim. Sen-chi?)\n"
            "🎙 *Nilufar:* Я никуда не ездила\\. Отдыхала дома — некогда было\\. (Hech qayerga bormadim. Uyda dam oldim — vaqt bo'lmadi.)\n"
            "🎙 *Anzor:* Жаль\\! В следующий раз поедем вместе\\! (Afsus! Keyingi safar birga boramiz!)\n\n"
            "❓ *Savol:* Anzor qayerga va nima bilan bordi?"
        ),
        "prev_vocab": (
            "📖 *Yangi so'zlar (Lug'at)*\n\n"
            "1\\. *путешествие* — sayohat\n"
            "2\\. *отдых* — dam olish\n"
            "3\\. *отпуск* — ta'til\n"
            "4\\. *пляж* — plyaj\n"
            "5\\. *горы* — togʻlar\n"
            "6\\. *море* — dengiz\n"
            "7\\. *гостиница* — mehmonxona\n"
            "8\\. *билет* — chipta\n"
            "9\\. *самолёт* — samolyot\n"
            "10\\. *поезд* — poezd\n"
            "11\\. *машина* — mashina\n"
            "12\\. *экскурсия* — ekskursiya\n"
            "13\\. *музей* — muzey\n"
            "14\\. *достопримечательность* — diqqatga sazovor joy\n"
            "15\\. *сувенир* — suvenir\n"
            "16\\. *фотография* — fotosurat\n"
            "17\\. *лето* — yoz\n"
            "18\\. *зима* — qish"
        ),
        "prev_grammar": (
            "📐 *Grammatika: Harakat fe'llari va kelishiklar*\n\n"
            "1\\. *Harakat fe'llari \\(Hozirgi zamon\\):*\n"
            "• *ехать* \\(transportda\\): я еду, ты едешь, он едет, мы едем, вы едете, они едут\\.\n"
            "• *лететь* \\(samolyotda\\): я лечу, ты летишь, он летит, мы летим, вы летите, они летят\\.\n"
            "• *идти* \\(piyoda\\): я иду, ты идёшь, он идёт, мы идём, вы идёте, они идут\\.\n\n"
            "2\\. *Куда\\? \\(Tushum kelishigi\\) vs Где\\? \\(O'rin-payt kelishigi\\):*\n"
            "• в Россию \\(qayerga\\?\\) — в России \\(qayerda\\?\\)\n"
            "• в Москву \\(qayerga\\?\\) — в Москве \\(qayerda\\?\\)\n"
            "• на пляж \\(qayerga\\?\\) — на пляже \\(qayerda\\?\\)\n"
            "• в гостиницу \\(qayerga\\?\\) — в гостинице \\(qayerda\\?\\)\n"
            "• на экскурсию \\(qayerga\\?\\) — на экскурсии \\(qayerda\\?\\)"
        ),
        "prev_test_start": (
            "🧠 *1-dars bo'yicha mini-test*\n\n"
            "Bilimingizni sinab ko'ring\\! 3 ta oddiy savolga javob bering\\.\n\n"
            "Boshlashga tayyormisiz?"
        ),
        "prev_test_q1": (
            "❓ *1-savol (3 tadan):*\n\n"
            "Мы \\_\\_\\_ \\(лететь\\) в Дубай\\."
        ),
        "prev_test_q2": (
            "❓ *1-savol (3 tadan):*\n\n"
            "Она едет в \\_\\_\\_ \\(Италия\\)\\."
        ),
        "prev_test_q3": (
            "❓ *3-savol (3 tadan):*\n\n"
            "Я живу в \\_\\_\\_ \\(гостиница\\)\\."
        ),
        "prev_test_correct": "✅ *To'g'ri\\!*",
        "prev_test_wrong": "❌ *Noto'g'ri\\. Yana bir bor urinib ko'ring\\!*",
        "prev_test_finish": (
            "🎉 *Tabriklaymiz\\!*\n\n"
            "Siz birinchi dars bo'yicha mini-testni muvaffaqiyatli topshirdingiz\\!\n\n"
            "Kitob kundalik muloqot uchun A2 darajasidagi barcha kerakli grammatika va lug'atni qamrab olgan *30 ta shunday mavzudan* iborat\\.\n\n"
            "StartRus A2 kitobini hozirning o'zidayoq *{price} so'm* evaziga sotib oling 👇"
        ),
        "support_intro": (
            "✏️ *Savol yuborish*\n\n"
            "Yordam xizmatiga savolingiz yoki xabaringizni bitta xabarda yozib yuboring 👇\n\n"
            "Biz sizга shu chatning o'zida javob beramiz\\."
        ),
        "support_sent": "✅ *Savolingiz administratorga yuborildi\\!* Tez orada javob qaytaramiz\\.",
        # ── buy / order flow ───────────────────────────────
        "buy_intro": (
            "💳 *StartRus A2 sotib olish*\n\n"
            "📕 Narxi: *{price} so'm*\n\n"
            "Promokodingiz bormi?"
        ),
        "buy_intro_discounted": (
            "💳 *StartRus A2 sotib olish*\n\n"
            "📕 Narxi: ~{old_price} so'm~ → *{new_price} so'm*\n"
            "🎉 Chegirma: *{discount}%* \\(promokod `{code}`\\)\n\n"
        ),
        "buy_enter_promo": "✏️ Promokodni kiriting:",
        "buy_promo_applied": (
            "✅ Promokod *{code}* qo'llanildi\\!\n"
            "Chegirma: *{discount}%*\n\n"
            "💰 Yangi narx: *{new_price} so'm*"
        ),
        "buy_promo_invalid": "❌ Promokod topilmadi yoki eskirgan\\.",
        "buy_payment_info": (
            "💳 *To'lov yo'riqnomasi*\n\n"
            "💰 To'lov summasi: *{amount} so'm*\n\n"
            "📲 Kartaga o'tkazing:\n"
            "`{card}`\n\n"
            "📸 To'lovdan so'ng *chek rasmini* shu chatga yuboring 👇"
        ),
        "buy_payment_info_no_card": (
            "💳 *To'lov yo'riqnomasi*\n\n"
            "💰 To'lov summasi: *{amount} so'm*\n\n"
            "📲 To'lov rekvizitlarini olish uchun "
            "sotuvchi bilan bog'laning\\.\n\n"
            "📸 To'lovdan so'ng *chek rasmini* shu chatga yuboring 👇"
        ),
        "buy_receipt_ok": (
            "✅ Chek qabul qilindi\\!\n\n"
            "📋 Buyurtma *\\#{order_id}*\n"
            "⏳ Administrator tasdiqlashini kuting\\.\n\n"
            "Odatda bir necha daqiqa oladi\\."
        ),
        "buy_confirmed": (
            "🎉 *To'lov tasdiqlandi\\!*\n\n"
            "Xaridingiz uchun rahmat\\! Mana kitobingiz 📚"
        ),
        "buy_confirmed_no_pdf": (
            "🎉 *To'lov tasdiqlandi\\!*\n\n"
            "Xaridingiz uchun rahmat\\! Kitobni olish uchun "
            "sotuvchi bilan bog'laning 👇"
        ),
        "buy_rejected": (
            "❌ *Afsuski, to'lov tasdiqlanmadi\\.*\n\n"
            "Agar to'lagan bo'lsangiz — "
            "biz bilan to'g'ridan\\-to'g'ri bog'laning 👇"
        ),
        "buy_cancelled": "🚫 Buyurtma bekor qilindi\\.",
        "buy_already_pending": (
            "⏳ Sizda allaqachon *\\#{order_id}* buyurtma mavjud\\.\n\n"
            "Tasdiqlashni kuting yoki joriy buyurtmani bekor qiling\\."
        ),
        # ── materials & courses ────────────────────────────
        "materials_menu": "📚 *O'quv materiallari*\n\nSizni qiziqtirgan darajani tanlang:",
        "courses_menu": "🎓 *Kurslarga yozilish*\n\nQaysi formatda o'qishni xohlaysiz?",
        "course_ask_level": "Qaysi daraja bo'yicha o'qishni xohlaysiz?",
        "course_ask_name": "📝 *Ismingiz nima?*\n\nIltimos, ism va familiyangizni yozing\\.",
        "course_ask_phone": "📞 *Telefon raqamingiz*\n\nAloqa raqamingizni yozing \\(masalan: \\+998901234567\\)\\.",
        "course_success": "✅ *Arizangiz muvaffaqiyatli qabul qilindi\\!*\n\nRahmat\\! Tez orada tafsilotlarni kelishish uchun siz bilan bog'lanamiz\\.",
        "mat_coming_soon": "⏳ *Daraja {lvl}*\n\nUshbu daraja uchun materiallar hozirda ishlab chiqilmoqda\\. Tayyor bo'lganda albatta xabar beramiz\\!",
        # ── buttons ────────────────────────────────────────
        "btn_materials": "📚 O'quv materiallari",
        "btn_courses": "🎓 Kurslarga yozilish",
        "btn_course_group": "👥 Guruh darslari",
        "btn_course_indiv": "👤 Yakkaterib darslar",
        "btn_book": "📖 Kitob haqida",
        "btn_price": "💰 Narxi",
        "btn_buy": "💳 Sotib olish",
        "btn_preview": "📄 Ko'rish",
        "btn_faq": "❓ FAQ",
        "btn_contact": "📞 Bog'lanish",
        "btn_lang": "🌐 Til",
        "btn_back": "◀️ Ortga",
        "btn_contact_link": "✉️ Sotuvchiga yozish",
        "btn_promo_yes": "🎟 Ha, promokod bor",
        "btn_promo_no": "➡️ Yo'q, davom etish",
        "btn_cancel_order": "🚫 Bekor qilish",
        "btn_prev_dialog": "💬 Dialog",
        "btn_prev_vocab": "📖 Lug'at",
        "btn_prev_grammar": "📐 Grammatika",
        "btn_prev_test": "🧠 Test",
        "btn_prev_back": "◀️ Ortga",
        "btn_test_start": "🚀 Testni boshlash",
        "btn_ask_support": "✉️ Savol yuborish",
    },
}


# ═══════════════════════════════════════════════════════════
#  TRANSLATION  HELPERS
# ═══════════════════════════════════════════════════════════
def t(uid: int, key: str, **fmt) -> str:
    """Get translated text. Use fmt for {placeholder} values (auto-escaped)."""
    lang = db_get_lang(uid)
    raw = TEXTS[lang].get(key, TEXTS["ru"].get(key, key))
    if fmt:
        safe = {k: esc(v) for k, v in fmt.items()}
        return raw.format(**safe)
    return raw


# ═══════════════════════════════════════════════════════════
#  KEYBOARDS
# ═══════════════════════════════════════════════════════════
def kb_main(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(uid, "btn_materials"), callback_data="menu_materials"),
        ],
        [
            InlineKeyboardButton(t(uid, "btn_courses"), callback_data="menu_courses"),
        ],
        [
            InlineKeyboardButton(t(uid, "btn_faq"), callback_data="faq"),
            InlineKeyboardButton(t(uid, "btn_contact"), url=SELLER_CONTACT),
        ],
        [
            InlineKeyboardButton(t(uid, "btn_lang"), callback_data="change_lang"),
        ],
    ])

def kb_materials(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟩 A1", callback_data="mat_other_A1"),
            InlineKeyboardButton("🟨 A2", callback_data="mat_a2"),
        ],
        [
            InlineKeyboardButton("🟦 B1", callback_data="mat_other_B1"),
            InlineKeyboardButton("🩵 B2", callback_data="mat_other_B2"),
        ],
        [
            InlineKeyboardButton("🟪 C1", callback_data="mat_other_C1"),
        ],
        [InlineKeyboardButton(t(uid, "btn_back"), callback_data="main_menu")],
    ])

def kb_course_format(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_course_group"), callback_data="course_fmt_group")],
        [InlineKeyboardButton(t(uid, "btn_course_indiv"), callback_data="course_fmt_indiv")],
        [InlineKeyboardButton(t(uid, "btn_back"), callback_data="main_menu")],
    ])

def kb_course_levels(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟩 A1", callback_data="course_lvl_A1"),
            InlineKeyboardButton("🟨 A2", callback_data="course_lvl_A2"),
        ],
        [
            InlineKeyboardButton("🟦 B1", callback_data="course_lvl_B1"),
            InlineKeyboardButton("🩵 B2", callback_data="course_lvl_B2"),
        ],
        [
            InlineKeyboardButton("🟪 C1", callback_data="course_lvl_C1"),
        ],
        [InlineKeyboardButton(t(uid, "btn_back"), callback_data="menu_courses")],
    ])

def kb_back(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_back"), callback_data="main_menu")],
    ])

def kb_contact(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_contact_link"), url=SELLER_CONTACT)],
        [InlineKeyboardButton(t(uid, "btn_back"), callback_data="main_menu")],
    ])

def kb_price(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_buy"), callback_data="buy")],
        [InlineKeyboardButton(t(uid, "btn_contact_link"), url=SELLER_CONTACT)],
        [InlineKeyboardButton(t(uid, "btn_back"), callback_data="menu_materials")],
    ])


def kb_lang() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇷🇺 Русский",   callback_data="set_lang_ru"),
            InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="set_lang_uz"),
        ],
    ])


def kb_promo(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_promo_yes"), callback_data="promo_yes")],
        [InlineKeyboardButton(t(uid, "btn_promo_no"),  callback_data="promo_no")],
        [InlineKeyboardButton(t(uid, "btn_back"),      callback_data="main_menu")],
    ])


def kb_cancel_order(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_cancel_order"), callback_data="cancel_order")],
        [InlineKeyboardButton(t(uid, "btn_contact_link"), url=SELLER_CONTACT)],
    ])


def kb_preview_contact(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_contact_link"), url=SELLER_CONTACT)],
        [InlineKeyboardButton(t(uid, "btn_buy"), callback_data="buy")],
        [InlineKeyboardButton(t(uid, "btn_back"), callback_data="main_menu")],
    ])


# ═══════════════════════════════════════════════════════════
#  ADMIN  HELPERS
# ═══════════════════════════════════════════════════════════
async def notify_admin(app, text: str) -> None:
    """Send a message to admin. Silently fails if ADMIN_USER_ID is not set."""
    if not ADMIN_USER_ID:
        logger.warning("ADMIN_USER_ID не задан — уведомление пропущено")
        return
    try:
        await app.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=text,
            parse_mode="MarkdownV2",
        )
    except TelegramError as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")


async def notify_admin_photo(app, photo_file_id: str, caption: str) -> None:
    """Send a photo to admin."""
    if not ADMIN_USER_ID:
        return
    try:
        await app.bot.send_photo(
            chat_id=ADMIN_USER_ID,
            photo=photo_file_id,
            caption=caption,
            parse_mode="MarkdownV2",
        )
    except TelegramError as e:
        logger.error(f"Не удалось отправить фото админу: {e}")


def is_admin(uid: int) -> bool:
    return ADMIN_USER_ID and uid == ADMIN_USER_ID


# ═══════════════════════════════════════════════════════════
#  PAYMENT  HELPERS
# ═══════════════════════════════════════════════════════════
def calc_price(promo_code: str = "") -> tuple[int, int, int, str]:
    """Returns (original, final, discount%, code) after applying promo."""
    original = BOOK_PRICE
    if promo_code:
        promo = db_get_promo(promo_code)
        if promo:
            disc = promo["discount_percent"]
            final = original - (original * disc // 100)
            return original, final, disc, promo["code"]
    return original, original, 0, ""


async def send_payment_instructions(
    uid: int, chat_id: int, amount: int, bot,
) -> None:
    """Send payment instruction message."""
    if PAYMENT_CARD:
        text = t(uid, "buy_payment_info",
                 amount=f"{amount:,}".replace(",", " "),
                 card=PAYMENT_CARD)
    else:
        text = t(uid, "buy_payment_info_no_card",
                 amount=f"{amount:,}".replace(",", " "))
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="MarkdownV2",
        reply_markup=kb_cancel_order(uid),
    )


async def deliver_book(uid: int, chat_id: int, bot) -> None:
    """Send the PDF book to user or fallback to contact link."""
    lang = db_get_lang(uid)
    if BOOK_PDF_PATH and Path(BOOK_PDF_PATH).is_file():
        await bot.send_message(
            chat_id=chat_id,
            text=t(uid, "buy_confirmed"),
            parse_mode="MarkdownV2",
        )
        with open(BOOK_PDF_PATH, "rb") as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                filename="StartRus_A2.pdf",
                caption="📚 StartRus A2",
            )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=t(uid, "buy_confirmed_no_pdf"),
            parse_mode="MarkdownV2",
            reply_markup=kb_contact(uid),
        )


# ═══════════════════════════════════════════════════════════
#  HANDLERS
# ═══════════════════════════════════════════════════════════

# ── /start ─────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"User {user.id} ({user.first_name}) started the bot")

    is_new = db_save_user(
        user.id, "ru", user.first_name or "", user.username or ""
    )
    db_log(user.id, "start")
    ctx.user_data.clear()

    if is_new and ADMIN_USER_ID:
        await notify_admin(
            ctx.application,
            f"🆕 Новый пользователь\\!\n"
            f"👤 {esc(user.first_name)} \\(@{esc(user.username or '—')}\\)\n"
            f"🆔 `{user.id}`",
        )

    await update.message.reply_text(
        TEXTS["ru"]["choose_lang"],
        parse_mode="MarkdownV2",
        reply_markup=kb_lang(),
    )


# ── /help ──────────────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    db_log(uid, "help")
    await update.message.reply_text(
        t(uid, "welcome"),
        parse_mode="MarkdownV2",
        reply_markup=kb_main(uid),
    )


# ── /cancel ────────────────────────────────────────────────
async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    ctx.user_data.clear()
    db_log(uid, "cancel")
    await update.message.reply_text(
        t(uid, "buy_cancelled"),
        parse_mode="MarkdownV2",
        reply_markup=kb_main(uid),
    )


# ── /stats  (admin) ───────────────────────────────────────
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    s = db_stats()
    top = "\n".join(
        f"  • `{esc(a)}` — {esc(c)}" for a, c in s["top_actions"]
    ) or "  нет данных"

    text = (
        f"📊 *Статистика StartRus Bot*\n\n"
        f"👥 Пользователей: *{esc(s['users'])}*\n"
        f"   ├ сегодня: {esc(s['today_users'])}\n\n"
        f"📦 Заказов: *{esc(s['orders'])}*\n"
        f"   ├ ⏳ ожидают: {esc(s['pending'])}\n"
        f"   ├ ✅ подтверждено: {esc(s['confirmed'])}\n"
        f"   ├ ❌ отклонено: {esc(s['rejected'])}\n"
        f"   ├ сегодня: {esc(s['today_orders'])}\n\n"
        f"🔝 *Популярные действия:*\n{top}"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


# ── /confirm <id>  (admin) ─────────────────────────────────
async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Использование: /confirm <order\\_id>",
                                        parse_mode="MarkdownV2")
        return
    try:
        oid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID заказа\\.",
                                        parse_mode="MarkdownV2")
        return

    order = db_confirm_order(oid)
    if not order:
        await update.message.reply_text(
            f"❌ Заказ \\#{esc(oid)} не найден или уже обработан\\.",
            parse_mode="MarkdownV2",
        )
        return

    customer_id = order["user_id"]
    db_log(customer_id, "order_confirmed", str(oid))
    if order.get("promo_code"):
        db_use_promo(order["promo_code"])

    # Deliver book to customer
    await deliver_book(customer_id, customer_id, ctx.bot)

    await update.message.reply_text(
        f"✅ Заказ \\#{esc(oid)} подтверждён\\. "
        f"Книга отправлена пользователю `{esc(customer_id)}`\\.",
        parse_mode="MarkdownV2",
    )


# ── /reject <id>  (admin) ──────────────────────────────────
async def cmd_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Использование: /reject <order\\_id>",
                                        parse_mode="MarkdownV2")
        return
    try:
        oid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID заказа\\.",
                                        parse_mode="MarkdownV2")
        return

    order = db_reject_order(oid)
    if not order:
        await update.message.reply_text(
            f"❌ Заказ \\#{esc(oid)} не найден или уже обработан\\.",
            parse_mode="MarkdownV2",
        )
        return

    customer_id = order["user_id"]
    db_log(customer_id, "order_rejected", str(oid))

    try:
        await ctx.bot.send_message(
            chat_id=customer_id,
            text=t(customer_id, "buy_rejected"),
            parse_mode="MarkdownV2",
            reply_markup=kb_contact(customer_id),
        )
    except TelegramError:
        pass

    await update.message.reply_text(
        f"❌ Заказ \\#{esc(oid)} отклонён\\.",
        parse_mode="MarkdownV2",
    )


# ── /addpromo CODE DISCOUNT% MAX_USES  (admin) ────────────
async def cmd_addpromo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = ctx.args
    if len(args) < 3:
        await update.message.reply_text(
            "Использование: /addpromo CODE DISCOUNT% MAX\\_USES\n"
            "Пример: `/addpromo SALE20 20 100`",
            parse_mode="MarkdownV2",
        )
        return
    code = args[0].upper()
    try:
        discount = int(args[1])
        max_uses = int(args[2])
    except ValueError:
        await update.message.reply_text("❌ Неверные параметры\\.",
                                        parse_mode="MarkdownV2")
        return

    db_add_promo(code, discount, max_uses)
    await update.message.reply_text(
        f"✅ Промокод `{esc(code)}` создан\\!\n"
        f"Скидка: *{esc(discount)}%*, лимит: *{esc(max_uses)}* использований",
        parse_mode="MarkdownV2",
    )


# ── /listpromos  (admin) ──────────────────────────────────
async def cmd_listpromos(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    promos = db_list_promos()
    if not promos:
        await update.message.reply_text("Нет активных промокодов\\.",
                                        parse_mode="MarkdownV2")
        return
    lines = ["🎟 *Активные промокоды:*\n"]
    for p in promos:
        lim = f"{p['used_count']}/{p['max_uses']}" if p["max_uses"] else f"{p['used_count']}/∞"
        lines.append(
            f"• `{esc(p['code'])}` — {esc(p['discount_percent'])}% "
            f"\\({esc(lim)}\\)"
        )
    await update.message.reply_text(
        "\n".join(lines), parse_mode="MarkdownV2"
    )


# ── Button handler ─────────────────────────────────────────
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    db_log(uid, "button", data)

    # ── language ───────────────────────────────────────────
    if data == "set_lang_ru":
        db_set_lang(uid, "ru")
        db_log(uid, "lang_change", "ru")
        await query.edit_message_text(
            t(uid, "lang_set"), parse_mode="MarkdownV2"
        )
        await query.message.reply_text(
            t(uid, "welcome"), parse_mode="MarkdownV2",
            reply_markup=kb_main(uid),
        )

    elif data == "set_lang_uz":
        db_set_lang(uid, "uz")
        db_log(uid, "lang_change", "uz")
        await query.edit_message_text(
            t(uid, "lang_set"), parse_mode="MarkdownV2"
        )
        await query.message.reply_text(
            t(uid, "welcome"), parse_mode="MarkdownV2",
            reply_markup=kb_main(uid),
        )

    elif data == "change_lang":
        ctx.user_data.clear()
        await query.edit_message_text(
            TEXTS["ru"]["choose_lang"], parse_mode="MarkdownV2",
            reply_markup=kb_lang(),
        )

    # ── navigation ─────────────────────────────────────────
    elif data == "main_menu":
        ctx.user_data.clear()
        await query.edit_message_text(
            t(uid, "welcome"), parse_mode="MarkdownV2",
            reply_markup=kb_main(uid),
        )

    elif data == "menu_materials":
        await query.edit_message_text(
            t(uid, "materials_menu"), parse_mode="MarkdownV2",
            reply_markup=kb_materials(uid),
        )

    elif data == "menu_courses":
        await query.edit_message_text(
            t(uid, "courses_menu"), parse_mode="MarkdownV2",
            reply_markup=kb_course_format(uid),
        )

    elif data.startswith("mat_other_"):
        lvl = data.split("_")[-1]
        await query.edit_message_text(
            t(uid, "mat_coming_soon", lvl=lvl), parse_mode="MarkdownV2",
            reply_markup=kb_materials(uid),
        )

    elif data == "mat_a2":
        await query.edit_message_text(
            t(uid, "book_info"), parse_mode="MarkdownV2",
            reply_markup=kb_price(uid),
        )

    elif data.startswith("course_fmt_"):
        fmt = data.split("_")[-1]
        ctx.user_data["course_format"] = fmt
        await query.edit_message_text(
            t(uid, "course_ask_level"), parse_mode="MarkdownV2",
            reply_markup=kb_course_levels(uid),
        )

    elif data.startswith("course_lvl_"):
        lvl = data.split("_")[-1]
        ctx.user_data["course_level"] = lvl
        ctx.user_data["order_state"] = "awaiting_name"
        await query.edit_message_text(
            t(uid, "course_ask_name"), parse_mode="MarkdownV2",
        )

    elif data == "price":
        price_str = f"{BOOK_PRICE:,}".replace(",", " ")
        await query.edit_message_text(
            t(uid, "price", price=price_str), parse_mode="MarkdownV2",
            reply_markup=kb_price(uid),
        )

    elif data == "faq":
        await query.edit_message_text(
            t(uid, "faq"), parse_mode="MarkdownV2",
            reply_markup=kb_back(uid),
        )


    # ── buy flow ───────────────────────────────────────────
    elif data == "buy":
        # Check for existing pending order
        pending = db_pending_order(uid)
        if pending:
            await query.edit_message_text(
                t(uid, "buy_already_pending", order_id=pending["id"]),
                parse_mode="MarkdownV2",
                reply_markup=kb_cancel_order(uid),
            )
            return

        price_str = f"{BOOK_PRICE:,}".replace(",", " ")
        await query.edit_message_text(
            t(uid, "buy_intro", price=price_str),
            parse_mode="MarkdownV2",
            reply_markup=kb_promo(uid),
        )
        db_log(uid, "buy_start")

    elif data == "promo_yes":
        ctx.user_data["order_state"] = "awaiting_promo"
        await query.edit_message_text(
            t(uid, "buy_enter_promo"), parse_mode="MarkdownV2",
        )

    elif data == "promo_no":
        # Create order without promo, show payment instructions
        oid = db_create_order(uid, "", BOOK_PRICE, BOOK_PRICE)
        ctx.user_data["order_state"] = "awaiting_receipt"
        ctx.user_data["order_id"] = oid
        db_log(uid, "order_created", str(oid))

        await query.edit_message_text(
            t(uid, "welcome"), parse_mode="MarkdownV2",
        )
        await send_payment_instructions(uid, query.message.chat_id,
                                        BOOK_PRICE, ctx.bot)

        await notify_admin(
            ctx.application,
            f"📦 *Новый заказ \\#{esc(oid)}*\n"
            f"👤 {esc(query.from_user.first_name)} "
            f"\\(@{esc(query.from_user.username or '—')}\\)\n"
            f"💰 {esc(f'{BOOK_PRICE:,}'.replace(',', ' '))} сўм\n"
            f"⏳ Ожидает скриншот чека",
        )

    elif data == "cancel_order":
        ctx.user_data.clear()
        db_log(uid, "order_cancelled")
        await query.edit_message_text(
            t(uid, "buy_cancelled"), parse_mode="MarkdownV2",
            reply_markup=kb_main(uid),
        )


# ── Text handler ───────────────────────────────────────────
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    text = update.message.text.strip()
    state = ctx.user_data.get("order_state")

    # ── Promo code input ───────────────────────────────────
    if state == "awaiting_promo":
        code = text.upper().strip()
        promo = db_get_promo(code)
        if promo:
            disc = promo["discount_percent"]
            orig = BOOK_PRICE
            final = orig - (orig * disc // 100)

            oid = db_create_order(uid, code, orig, final)
            ctx.user_data["order_state"] = "awaiting_receipt"
            ctx.user_data["order_id"] = oid
            db_log(uid, "promo_applied", code)
            db_log(uid, "order_created", str(oid))

            new_price_str = f"{final:,}".replace(",", " ")
            await update.message.reply_text(
                t(uid, "buy_promo_applied",
                  code=code, discount=str(disc), new_price=new_price_str),
                parse_mode="MarkdownV2",
            )
            await send_payment_instructions(uid, update.message.chat_id,
                                            final, ctx.bot)

            await notify_admin(
                ctx.application,
                f"📦 *Новый заказ \\#{esc(oid)}*\n"
                f"👤 {esc(update.effective_user.first_name)} "
                f"\\(@{esc(update.effective_user.username or '—')}\\)\n"
                f"💰 {esc(new_price_str)} сўм "
                f"\\(промо: `{esc(code)}`\\)\n"
                f"⏳ Ожидает скриншот чека",
            )
        else:
            db_log(uid, "promo_invalid", code)
            await update.message.reply_text(
                t(uid, "buy_promo_invalid"), parse_mode="MarkdownV2",
                reply_markup=kb_promo(uid),
            )
            ctx.user_data["order_state"] = None
        return

    # ── Course enrollment ──────────────────────────────────
    if state == "awaiting_name":
        ctx.user_data["course_name"] = text
        ctx.user_data["order_state"] = "awaiting_phone"
        await update.message.reply_text(
            t(uid, "course_ask_phone"), parse_mode="MarkdownV2"
        )
        return

    if state == "awaiting_phone":
        name = ctx.user_data.get("course_name", "—")
        phone = text
        fmt = ctx.user_data.get("course_format", "—")
        lvl = ctx.user_data.get("course_level", "—")

        # Save to DB
        db_create_course_request(uid, fmt, lvl, name, phone)
        db_log(uid, "course_requested", f"{fmt}_{lvl}")

        # Notify Admin
        await notify_admin(
            ctx.application,
            f"🎓 *Новая заявка на курсы\\!*\n\n"
            f"👤 Имя: {esc(name)}\n"
            f"📞 Телефон: `{esc(phone)}`\n"
            f"📊 Формат: {esc(fmt)}\n"
            f"📈 Уровень: {esc(lvl)}\n"
            f"🆔 Telegram ID: `{uid}`"
        )

        # Clear state
        ctx.user_data.clear()

        await update.message.reply_text(
            t(uid, "course_success"), parse_mode="MarkdownV2",
            reply_markup=kb_main(uid)
        )
        return

    # ── Greeting detection ─────────────────────────────────
    lower = text.lower()
    greetings_ru = ["привет", "здравствуйте", "хай", "хэй",
                    "салам", "добрый день"]
    greetings_uz = ["salom", "assalomu alaykum", "hayrli kun"]

    if any(g in lower for g in greetings_ru + greetings_uz):
        lang = db_get_lang(uid)
        if lang == "uz":
            greeting = "Salom\\! 👋 Men StartRus botiman\\."
        else:
            greeting = "Привет\\! 👋 Я бот StartRus\\."
        await update.message.reply_text(
            greeting, parse_mode="MarkdownV2",
            reply_markup=kb_main(uid),
        )
        db_log(uid, "greeting")
    else:
        await update.message.reply_text(
            t(uid, "unknown"), parse_mode="MarkdownV2",
            reply_markup=kb_main(uid),
        )
        db_log(uid, "unknown_text", text[:100])


# ── Photo handler (receipts) ──────────────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    state = ctx.user_data.get("order_state")

    if state != "awaiting_receipt":
        # Not expecting a photo — ignore or redirect
        await update.message.reply_text(
            t(uid, "unknown"), parse_mode="MarkdownV2",
            reply_markup=kb_main(uid),
        )
        return

    oid = ctx.user_data.get("order_id")
    if not oid:
        ctx.user_data.clear()
        return

    # Save receipt
    photo = update.message.photo[-1]  # highest resolution
    file_id = photo.file_id
    db_set_receipt(oid, file_id)
    db_log(uid, "receipt_sent", str(oid))
    ctx.user_data.clear()

    # Confirm to user
    await update.message.reply_text(
        t(uid, "buy_receipt_ok", order_id=str(oid)),
        parse_mode="MarkdownV2",
        reply_markup=kb_main(uid),
    )

    # Notify admin with photo
    user = update.effective_user
    await notify_admin_photo(
        ctx.application,
        file_id,
        f"📸 *Чек по заказу \\#{esc(oid)}*\n"
        f"👤 {esc(user.first_name)} \\(@{esc(user.username or '—')}\\)\n"
        f"🆔 `{user.id}`\n\n"
        f"Подтвердить: /confirm {oid}\n"
        f"Отклонить: /reject {oid}",
    )


# ═══════════════════════════════════════════════════════════
#  ERROR  HANDLER
# ═══════════════════════════════════════════════════════════
async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler — log and notify admin."""
    if "Message is not modified" in str(ctx.error):
        return
    
    logger.error("Exception while handling an update:", exc_info=ctx.error)
    tb = traceback.format_exception(None, ctx.error, ctx.error.__traceback__)
    tb_str = "".join(tb)[-1000:]  # last 1000 chars

    # Try to notify admin
    if ADMIN_USER_ID:
        try:
            await ctx.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=(
                    f"⚠️ *Ошибка в боте*\n\n"
                    f"```\n{esc(tb_str)}\n```"
                ),
                parse_mode="MarkdownV2",
            )
        except Exception:
            logger.error("Failed to send error notification to admin")

    # Try to respond to user gracefully
    if update and hasattr(update, "effective_user") and update.effective_user:
        uid = update.effective_user.id
        try:
            if hasattr(update, "message") and update.message:
                await update.message.reply_text(
                    "⚠️ Произошла ошибка\\. Попробуйте /start",
                    parse_mode="MarkdownV2",
                )
            elif hasattr(update, "callback_query") and update.callback_query:
                await update.callback_query.message.reply_text(
                    "⚠️ Произошла ошибка\\. Попробуйте /start",
                    parse_mode="MarkdownV2",
                )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════
def main() -> None:
    logger.info("🚀 Запуск StartRus Bot v2.0...")

    # Initialize database
    init_db()

    # Build application with increased timeouts
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .build()
    )

    # ── Register handlers ──────────────────────────────────
    # Commands
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("cancel",     cmd_cancel))
    app.add_handler(CommandHandler("stats",      cmd_stats))
    app.add_handler(CommandHandler("confirm",    cmd_confirm))
    app.add_handler(CommandHandler("reject",     cmd_reject))
    app.add_handler(CommandHandler("addpromo",   cmd_addpromo))
    app.add_handler(CommandHandler("listpromos", cmd_listpromos))

    # Buttons
    app.add_handler(CallbackQueryHandler(button_handler))

    # Photos (receipts)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Text messages
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text
    ))

    # Global error handler
    app.add_error_handler(error_handler)

    logger.info("✅ Бот запущен и готов к работе! v2.0")
    if ADMIN_USER_ID:
        logger.info(f"   Админ ID: {ADMIN_USER_ID}")
    else:
        logger.warning("   ⚠️ ADMIN_USER_ID не задан — уведомления отключены")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()
