import os
import re
import logging
import asyncio
import sqlite3
from datetime import datetime
from aiogram import Bot, types, Dispatcher, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ContentType
from aiogram import Router
from aiogram.filters import Command

TOKEN = "7722867235:AAGT3hHQUrPeORDcQQrNBFROXiGJ5pT9l2E"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bot = Bot(token=TOKEN)
router = Router()

# Проверка и создание папки "data", если её нет
if not os.path.exists('data'):
    os.makedirs('data')

# Настройка базы данных в папке "data"
db_path = os.path.join('data', 'finance.db')
conn = sqlite3.connect(db_path, check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS global_balances
               (id INTEGER PRIMARY KEY DEFAULT 1,
                rub_balance REAL DEFAULT 0,
                usd_balance REAL DEFAULT 0)''')
conn.commit()

cursor.execute(''' 
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    currency TEXT,
    amount REAL,
    type TEXT
)
''')
conn.commit()


def safe_add_column(column_name, column_type):
    try:
        cursor.execute(f"ALTER TABLE global_balances ADD COLUMN {column_name} {column_type}")
        conn.commit()
    except sqlite3.OperationalError:
        pass


safe_add_column("rub_transactions", "INTEGER DEFAULT 0")
safe_add_column("usd_transactions", "INTEGER DEFAULT 0")

# Единая клавиатура — две кнопки: "Проверить баланс" и "Сбросить баланс"
keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Проверить баланс")],
        [KeyboardButton(text="Сбросить баланс")],
    ],
    resize_keyboard=True
)


def get_balances():
    cursor.execute(
        "SELECT rub_balance, usd_balance, rub_transactions, usd_transactions FROM global_balances WHERE id=1"
    )
    result = cursor.fetchone()
    if not result:
        cursor.execute("INSERT INTO global_balances (id) VALUES (1)")
        conn.commit()
        return 0.0, 0.0, 0, 0
    rub, usd, rub_tx, usd_tx = result
    return rub or 0.0, usd or 0.0, rub_tx or 0, usd_tx or 0


def log_transaction(currency, amount, tx_type):
    cursor.execute(''' 
        INSERT INTO transactions (timestamp, currency, amount, type) 
        VALUES (?, ?, ?, ?)
    ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), currency, amount, tx_type))
    conn.commit()


def update_balances(new_rub, new_usd, inc_rub=False, inc_usd=False, rub_diff=0.0, usd_diff=0.0, tx_type=None):
    cursor.execute("SELECT rub_transactions, usd_transactions FROM global_balances WHERE id=1")
    rub_tx, usd_tx = cursor.fetchone()
    if inc_rub:
        rub_tx += 1
        log_transaction("₽", rub_diff, tx_type if tx_type is not None else ("income" if rub_diff > 0 else "spend"))
    if inc_usd:
        usd_tx += 1
        log_transaction("$", usd_diff, tx_type if tx_type is not None else ("income" if usd_diff > 0 else "spend"))
    cursor.execute(
        "UPDATE global_balances SET rub_balance=?, usd_balance=?, rub_transactions=?, usd_transactions=? WHERE id=1",
        (new_rub, new_usd, rub_tx, usd_tx)
    )
    conn.commit()


def reset_balances():
    cursor.execute(
        "UPDATE global_balances SET rub_balance=0, usd_balance=0, rub_transactions=0, usd_transactions=0 WHERE id=1"
    )
    cursor.execute("DELETE FROM transactions")
    conn.commit()


def process_message(text, current_rub, current_usd):
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\b\d{1,2}[./]\d{1,2}\b', '', text)
    matches = re.findall(
        r'(\d+[\.,]?\d*)\s*([р₽$])|([р₽$])\s*(\d+[\.,]?\d*)',
        text,
        re.IGNORECASE
    )
    rub_change = 0.0
    usd_change = 0.0
    operation = -1 if any(word in text.lower() for word in ["принял", "компенсиро"]) else 1
    for match in matches:
        amount1, currency1, currency2, amount2 = match
        if amount1 and currency1:
            amount = amount1
            currency = currency1
        elif currency2 and amount2:
            amount = amount2
            currency = currency2
        else:
            continue
        try:
            value = float(amount.replace(',', '.'))
            value *= operation
            currency = currency.strip().lower()
            if currency in ['р', '₽']:
                rub_change += value
            elif currency == '$':
                usd_change += value
        except ValueError:
            continue
    return current_rub + rub_change, current_usd + usd_change


def format_amount(value):
    formatted = f"{round(value, 2):.2f}"
    return formatted[:-3] if formatted.endswith(".00") else formatted


def get_balance_status(value):
    return "Я тебе" if value > 0 else "Ты мне" if value < 0 else ""


def format_currency_line(current, diff, new, symbol):
    if diff == 0:
        return f"{get_balance_status(current)} {format_amount(current)}{symbol}".strip()

    action = "😎Оплатил" if diff > 0 else "❤️Принял"
    sign = "+" if diff > 0 else "-"
    return (
        f"{get_balance_status(new)} {format_amount(new)}{symbol} ← "
        f"{format_amount(current)}{symbol} ({action} {sign}{format_amount(abs(diff))}{symbol})"
    ).strip()



@router.message(Command('start'))
async def start(message: types.Message):
    get_balances()
    await message.answer(
        "💰 Финансовый трекер\n\n"
        "Правила:\n"
        "• 'Принял' или 'Компенсировал' – списание (компенсированные транзакции выводятся отдельно)\n"
        "• Без ключевых слов – зачисление\n"
        "• Форматы: 840₽, ₽840, 52.46$\n\n"
        "Баланс может быть отрицательным!",
        reply_markup=keyboard
    )


def generate_balance_report():
    rub, usd, _, _ = get_balances()
    balance_response = (
        f"🏦 Текущий баланс:\n"
        f"{get_balance_status(rub)} {format_amount(rub)}₽\n"
        f"{get_balance_status(usd)} {format_amount(usd)}$\n\n"
    )

    cursor.execute("SELECT timestamp, currency, amount, type FROM transactions ORDER BY id DESC")
    rows = cursor.fetchall()

    rub_income, rub_spend, usd_income, usd_spend = [], [], [], []
    rub_comp, usd_comp = [], []

    rub_income_sum = rub_spend_sum = 0.0
    usd_income_sum = usd_spend_sum = 0.0
    rub_comp_sum = usd_comp_sum = 0.0

    for row in rows:
        _, currency, amount, tx_type = row
        formatted = f"{format_amount(abs(amount))}{currency}"

        if currency == "₽":
            if tx_type == "income":
                rub_spend.append(f"-{formatted}")  # "Принял" → минус
                rub_spend_sum += abs(amount)
            elif tx_type == "spend":
                rub_income.append(f"+{formatted}")  # Обычные транзакции → плюс
                rub_income_sum += abs(amount)
            elif tx_type == "compensated":
                rub_comp.append(f"-{formatted}")  # Компенсация для рубля
                rub_comp_sum += abs(amount)
        elif currency == "$":
            if tx_type == "income":
                usd_spend.append(f"-{formatted}")
                usd_spend_sum += abs(amount)
            elif tx_type == "spend":
                usd_income.append(f"+{formatted}")
                usd_income_sum += abs(amount)
            elif tx_type == "compensated":
                usd_comp.append(f"-{formatted}")  # Компенсация для доллара
                usd_comp_sum += abs(amount)

    def format_block(title, items, total, symbol):
        if not items:
            return f"{title} 0{symbol} : (транз 0)"
        return f"{title} {format_amount(total)}{symbol} : (транз {len(items)})\n   " + " ".join(items)

    history_aggregated = (
        "История транзакций:\n\n" +
        format_block('❤️ Принял (₽)', rub_spend, rub_spend_sum, '₽') + "\n" +
        format_block('😎 Оплатил (₽)', rub_income, rub_income_sum, '₽') + "\n" +
        format_block('❤️ Принял ($)', usd_spend, usd_spend_sum, '$') + "\n" +
        format_block('😎 Оплатил ($)', usd_income, usd_income_sum, '$')
    )

    compensated_line = ""
    rub_comp_count = len(rub_comp)
    usd_comp_count = len(usd_comp)
    if rub_comp_count or usd_comp_count:
        compensated_parts = []
        if rub_comp_count:
            compensated_parts.append(f"{format_amount(rub_comp_sum)}₽ (транз {rub_comp_count})")
        if usd_comp_count:
            compensated_parts.append(f"{format_amount(usd_comp_sum)}$ (транз {usd_comp_count})")
        compensated_line = "\n\n❤️ Компенсировано " + " + ".join(compensated_parts)

    full_history_list = []
    for row in rows:
        _, currency, amount, _ = row
        sign = "+" if amount > 0 else "-"
        full_history_list.append(f"{sign}{format_amount(abs(amount))}{currency}")
    full_history = " ".join(full_history_list)

    return balance_response + history_aggregated + compensated_line + "\n\nПолная история транзакций:\n" + full_history





@router.message(F.text == "Проверить баланс")
async def check_balance(message: types.Message):
    report = generate_balance_report()
    await message.answer(report)


@router.message(F.text == "Сбросить баланс")
async def reset_balance_handler(message: types.Message):
    report = generate_balance_report()
    await message.answer(report + "\n\nБаланс будет сброшен.")
    reset_balances()


@router.message(lambda message: (message.text or message.caption) is not None)
async def handle_text(message: types.Message):
    try:
        input_text = message.text if message.text else message.caption
        if not input_text:
            return

        text_lower = input_text.lower()
        if "компенсиро" in text_lower:
            tx_type = "compensated"
        elif "принял" in text_lower:
            tx_type = "income"  # Исправлено: "Принял" → доход
        else:
            tx_type = "spend"  # Исправлено: обычные транзакции → расход

        text_clean = re.sub(r'\([^)]*\)', '', input_text)
        matches = re.findall(
            r'(\d+[\.,]?\d*)\s*([р₽$])|([р₽$])\s*(\d+[\.,]?\d*)',
            text_clean,
            re.IGNORECASE
        )
        if not matches:
            await message.answer("❌ Не обнаружено валют.")
            return
        found = sum(1 for match in matches if match[0] or match[2])
        if found > 1:
            raise ValueError("Обнаружено несколько валют в одном сообщении")
        current_rub, current_usd, _, _ = get_balances()
        new_rub, new_usd = process_message(input_text, current_rub, current_usd)
        if new_rub == current_rub and new_usd == current_usd:
            await message.answer("❌ Не удалось определить сумму.")
            return
        rub_line = format_currency_line(current_rub, new_rub - current_rub, new_rub, "₽")
        usd_line = format_currency_line(current_usd, new_usd - current_usd, new_usd, "$")
        update_balances(
            new_rub, new_usd,
            inc_rub=(new_rub != current_rub),
            inc_usd=(new_usd != current_usd),
            rub_diff=(new_rub - current_rub),
            usd_diff=(new_usd - current_usd),
            tx_type=tx_type
        )
        await message.answer(f"{rub_line}\n{usd_line}")
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    except Exception as e:
        logging.error(f"Text error: {e}")
        await message.answer("❌ Ошибка обработки")


async def main():
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        conn.close()
