import os
import logging
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
import sqlite3
import re
import atexit
import requests
import schedule
import time
import threading
from liqpay import LiqPay
import base64
import json
import hashlib
import uuid

# Initialize the bot
bot = telebot.TeleBot('ВАШ_ТОКЕН_ТЕЛЕГРАМ_БОТА')
admin_ids = [ВАШ_АЙДИ_ТЕЛЕГРАМА]

# Налаштування для LiqPay
TEST_PUBLIC_KEY = 'ВАШ_ПУБЛІЧНИЙ_ТОКЕН_ОПЛАТИ'
TEST_PRIVATE_KEY = 'ВАШ_ПРИВАТНИЙ_ТОКЕН_ОПЛАТИ'

# SQLite database connection
conn = sqlite3.connect('shop_db.sqlite', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    city TEXT,
    subscribed INTEGER DEFAULT 0
)''')
conn.commit()


cursor.execute('''
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    full_name TEXT,
    item_name TEXT,
    item_price REAL,
    address TEXT,
    order_id TEXT,  -- Додаємо колонку order_id
    status TEXT DEFAULT "обробляється"
)
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS cart (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    item_name TEXT,
    item_price REAL,
    quantity INTEGER DEFAULT 1
)
''')
conn.commit()


cursor.execute('''CREATE TABLE IF NOT EXISTS catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,
    name TEXT,
    description TEXT,
    price TEXT,
    photo_url TEXT
)''')
conn.commit()

# Отримати поточну директорію
current_directory = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(current_directory, 'bot.log')

# Налаштування логування з вказівкою кодування UTF-8
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),  # Вказуємо кодування
        logging.StreamHandler()  # Додатково виведе логи в консоль
    ]
)

# Функція для логування подій
def log_event(event, user_id=None, username=None):
    if user_id and username:
        logging.info(f"{event} - Користувач ID: {user_id}, Username: @{username}")
    else:
        logging.info(event)


@atexit.register
def close_db():
    conn.close()

# Adding items to the catalog table (only once)
def add_items_to_catalog():
    items = [
        ("smartphones", "Смартфон A", "Смартфон з потужним акумулятором", "10,000 грн",
         "https://bomba.if.ua/upload/resize_cache/webp/iblock/6bd/m0b811yhj5dwiqr1m71qlp7hu88bea84.webp"),
        ("smartphones", "Смартфон B", "Смартфон середнього рівня", "15,000 грн",
         "https://www.rbc.ua/static/ckef2/img/66_1500.jpg"),
        ("smartphones", "Смартфон C", "Бюджетного смартфону", "5,000 грн",
         "https://files.foxtrot.com.ua/PhotoNew/1_638126582647337668.jpg"),
        ("laptops", "Ноутбук A", "Легкий та потужний ноутбук", "20,000 грн",
         "https://scdn.comfy.ua/89fc351a-22e7-41ee-8321-f8a9356ca351/https://cdn.comfy.ua/media/catalog/product/0/2/02_ideapad_1_hero_front_facing_jd.jpg/w_600"),
        ("laptops", "Ноутбук B", "Високопродуктивний ноутбук", "30,000 грн",
         "https://www.ixbt.com/img/r30/00/02/58/65/IMG3013.jpg"),
        ("headphones", "Навушники A", "Безпровідні навушники з шумозаглушенням", "2,500 грн",
         "https://i.moyo.ua/img/news/1677/ua_74_400x400x_1699964475.jpg"),
        ("headphones", "Навушники B", "Класичні навушники", "1,500 грн",
         "https://cdn.vogue.ua/i/image_720x/uploads/article-inline/0d6/254/b97/5b97b972540d6.jpeg.webp")
    ]
    cursor.executemany("INSERT INTO catalog (category, name, description, price, photo_url) VALUES (?, ?, ?, ?, ?)",
                       items)
    conn.commit()

# Add items if the catalog table is empty
cursor.execute("SELECT COUNT(*) FROM catalog")
if cursor.fetchone()[0] == 0:
    add_items_to_catalog()

# Function to get items by category
def get_items_by_category(category):
    cursor.execute("SELECT id, name, description, price, photo_url FROM catalog WHERE category = ?", (category,))
    return cursor.fetchall()

# Validate name
def is_valid_name(name):
    return bool(re.match(r"^[А-ЯІЇЄҐ][а-яіїєґ]+\s[А-ЯІЇЄҐ][а-яіїєґ]+\s[А-ЯІЇЄҐ][а-яіїєґ]+$", name))

# Validate address
def is_valid_address(address):
    return len(address) > 5


@bot.message_handler(commands=['start'])
def welcome_message(message):
    # Створюємо клавіатуру з командами
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)

    # Додаємо кнопки з короткими описами для всіх користувачів
    keyboard.add(
        KeyboardButton("🚀 Старт бота"),
        KeyboardButton("❓ Всі команди")
    )
    keyboard.add(
        KeyboardButton("ℹ️ Інформація про магазин"),
        KeyboardButton("📦 Каталог товарів"),
        KeyboardButton("📦 Мої замовлення"),
        KeyboardButton("🛒 Моя корзина")
    )
    keyboard.add(
        KeyboardButton("🌤️ Прогноз погоди"),
        KeyboardButton("📬 Підписка на погоду"),
        KeyboardButton("🚫 Відписка від погоди")
    )
    keyboard.add(KeyboardButton("✉️ Залишити відгук"))

    # Перевірка, чи є користувач адміністратором, і додавання відповідних кнопок
    if message.from_user.id in admin_ids:
        keyboard.add(
            KeyboardButton("➕ Додати товар"),
            KeyboardButton("🗑️ Видалити товар"),
            KeyboardButton("📋 Список замовлень"),
            KeyboardButton("🔄 Оновити статус замовлення")
        )

    # Відправляємо повідомлення з постійною клавіатурою
    bot.send_message(
        message.chat.id,
        "👋 Вітаємо вас у офіційному боті магазину Техносова!\n\n"
        "🛒 У нашому магазині ви знайдете широкий асортимент електроніки: смартфони, ноутбуки, навушники та багато іншого. "
        "Наша місія - надавати якісну техніку за доступними цінами та забезпечувати високий рівень обслуговування для кожного клієнта.\n\n"
        "ℹ️ За допомогою цього бота ви можете:\n"
        "• Переглядати каталог товарів\n"
        "• Отримувати щоденний прогноз погоди для вашого міста\n"
        "• Залишати відгуки та пропозиції\n"
        "• Отримувати оперативну інформацію про наші товари та послуги\n\n"
        "❓ Для перегляду всіх команд натисніть кнопку \"Всі команди\" або введіть команду /help.\n\n"
        "Дякуємо, що обрали нас! 💼",
        reply_markup=keyboard
    )
    log_event("Команда /start виконана", message.from_user.id, message.from_user.username)


@bot.message_handler(func=lambda message: message.text == "🚀 Старт бота")
def handle_start_button(message):
    welcome_message(message)

@bot.message_handler(func=lambda message: message.text == "❓ Всі команди")
def handle_help_button(message):
    help_command(message)

@bot.message_handler(func=lambda message: message.text == "ℹ️ Інформація про магазин")
def handle_info_button(message):
    info_command(message)

@bot.message_handler(func=lambda message: message.text == "📦 Каталог товарів")
def handle_catalog_button(message):
    show_catalog(message)

@bot.message_handler(func=lambda message: message.text == "📦 Мої замовлення")
def handle_catalog_button(message):
    user_view_orders(message)

@bot.message_handler(func=lambda message: message.text == "🛒 Моя корзина")
def handle_catalog_button(message):
    view_cart(message)

@bot.message_handler(func=lambda message: message.text == "🌤️ Прогноз погоди")
def handle_weather_button(message):
    weather_command(message)

@bot.message_handler(func=lambda message: message.text == "📬 Підписка на погоду")
def handle_subscribe_weather_button(message):
    subscribe_weather(message)

@bot.message_handler(func=lambda message: message.text == "🚫 Відписка від погоди")
def handle_unsubscribe_weather_button(message):
    unsubscribe_weather(message)

@bot.message_handler(func=lambda message: message.text == "✉️ Залишити відгук")
def handle_feedback_button(message):
    feedback_command(message)

# Обробники команд для адміністратора
@bot.message_handler(func=lambda message: message.text == "➕ Додати товар" and message.from_user.id in admin_ids)
def handle_add_item_button(message):
    add_item(message)

@bot.message_handler(func=lambda message: message.text == "🗑️ Видалити товар" and message.from_user.id in admin_ids)
def handle_delete_item_button(message):
    delete_item(message)

@bot.message_handler(func=lambda message: message.text == "📋 Список замовлень" and message.from_user.id in admin_ids)
def handle_view_orders_button(message):
    admin_view_orders(message)

@bot.message_handler(func=lambda message: message.text == "🔄 Оновити статус замовлення" and message.from_user.id in admin_ids)
def handle_update_order_status_button(message):
    update_order_status(message)




# Display the main catalog with subcategories
@bot.message_handler(commands=['catalog'])
def show_catalog(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📱Смартфони", callback_data="category_smartphones"),
        InlineKeyboardButton("💻Ноутбуки", callback_data="category_laptops"),
        InlineKeyboardButton("🎧Навушники", callback_data="category_headphones")
    )
    bot.send_message(message.chat.id, "Виберіть категорію:", reply_markup=markup)

@bot.message_handler(commands=['add_item'])
def add_item(message):
    if message.from_user.id in admin_ids:
        bot.send_message(message.chat.id, "✏️Введіть категорію товару:")
        bot.register_next_step_handler(message, process_category_step)
    else:
        bot.send_message(message.chat.id, "🔒Ця команда доступна лише адміністраторам.🔒")


# Process category step
def process_category_step(message):
    chat_id = message.chat.id
    category = message.text
    bot.send_message(chat_id, "📃Введіть назву товару:")
    bot.register_next_step_handler(message, process_name_step, category)


def process_name_step(message, category):
    chat_id = message.chat.id
    name = message.text
    bot.send_message(chat_id, "📒Введіть опис товару:")
    bot.register_next_step_handler(message, process_description_step, category, name)


def process_description_step(message, category, name):
    chat_id = message.chat.id
    description = message.text
    bot.send_message(chat_id, "💵Введіть ціну товару:")
    bot.register_next_step_handler(message, process_price_step, category, name, description)


def process_price_step(message, category, name, description):
    chat_id = message.chat.id
    price = message.text
    bot.send_message(chat_id, "🔗Введіть URL зображення товару:")
    bot.register_next_step_handler(message, process_photo_url_step, category, name, description, price)


def process_photo_url_step(message, category, name, description, price):
    chat_id = message.chat.id
    photo_url = message.text

    # Insert the item into the database
    cursor.execute("INSERT INTO catalog (category, name, description, price, photo_url) VALUES (?, ?, ?, ?, ?)",
                   (category, name, description, price, photo_url))
    conn.commit()

    bot.send_message(chat_id, f"Товар '{name}' успішно додано до каталогу.")

@bot.message_handler(commands=['weather'])
def weather_command(message):
    bot.send_message(message.chat.id, "Будь ласка, введіть назву міста для отримання прогнозу погоди:")
    bot.register_next_step_handler(message, process_city_step)

def process_city_step(message):
    city_name = message.text
    api_key = '07280fec99f37dca4efeb9abd36d85ef'  # Замініть на ваш реальний API-ключ
    weather_data = get_weather(city_name, api_key)
    if weather_data:
        bot.send_message(message.chat.id, weather_data)
    else:
        bot.send_message(message.chat.id, "Не вдалося отримати дані про погоду. Перевірте назву міста та спробуйте ще раз.")

def get_weather(city_name, api_key):
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        'q': city_name,
        'appid': api_key,
        'units': 'metric',
        'lang': 'uk'
    }
    try:
        response = requests.get(base_url, params=params)
        data = response.json()
        if data.get('cod') == 200:
            city = data['name']
            country = data['sys']['country']
            temp = data['main']['temp']
            description = data['weather'][0]['description']
            humidity = data['main']['humidity']
            wind_speed = data['wind']['speed']
            return (f"🌤️Погода в {city}, {country}:\n"
                    f"🌡️Температура: {temp}°C\n"
                    f"📝Опис: {description.capitalize()}\n"
                    f"💧Вологість: {humidity}%\n"
                    f"🌬️Швидкість вітру: {wind_speed} м/с")
        else:
            return None
    except Exception as e:
        print(f"Помилка при отриманні даних: {e}")
        return None

def send_daily_weather():
    # Отримуємо список підписників з містами
    cursor.execute("SELECT user_id, city FROM users WHERE subscribed = 1")
    users = cursor.fetchall()

    for user_id, city in users:
        weather_data = get_weather(city, '07280fec99f37dca4efeb9abd36d85ef')
        if weather_data:
            bot.send_message(user_id, f"🗓️Щоденний прогноз погоди для міста {city}:\n\n{weather_data}")
        else:
            bot.send_message(user_id, f"Не вдалося отримати погоду для міста {city}. Перевірте налаштування.")

# Розклад щоденної розсилки на 8:00 ранку
def run_scheduler():
    schedule.every().day.at("08:00").do(send_daily_weather)

    while True:
        schedule.run_pending()
        time.sleep(60)

# Запускаємо планувальник у фоновому потоці
scheduler_thread = threading.Thread(target=run_scheduler)
scheduler_thread.start()


@bot.message_handler(commands=['subscribe_weather'])
def subscribe_weather(message):
    user_id = message.from_user.id
    # Перевірка, чи користувач уже підписаний
    cursor.execute("SELECT subscribed FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    if result and result[0] == 1:
        bot.send_message(message.chat.id, "Ви вже підписані на щоденну розсилку погоди.")
    else:
        bot.send_message(message.chat.id, "Введіть назву вашого міста для щоденної розсилки погоди:")
        bot.register_next_step_handler(message, process_weather_subscription)


def process_weather_subscription(message):
    city_name = message.text
    user_id = message.from_user.id
    # Додаємо користувача до бази даних або оновлюємо його місто і статус підписки
    cursor.execute("INSERT OR REPLACE INTO users (user_id, city, subscribed) VALUES (?, ?, 1)", (user_id, city_name))
    conn.commit()
    bot.send_message(message.chat.id, f"Ви підписані на щоденну розсилку погоди для міста {city_name}.")
    log_event(f"Користувач {message.from_user.username} підписався на розсилку погоди  /subscribe_weather виконана",message.from_user.id)


@bot.message_handler(commands=['unsubscribe_weather'])
def unsubscribe_weather(message):
    user_id = message.from_user.id
    # Перевірка, чи користувач підписаний
    cursor.execute("SELECT subscribed FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    if result and result[0] == 1:
        # Оновлюємо статус підписки на 0 (відписка)
        cursor.execute("UPDATE users SET subscribed = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.send_message(message.chat.id, "Ви успішно відписалися від щоденної розсилки погоди.")
        log_event(f"Користувач {message.from_user.username} відпписався на розсилку погоди  /subscribe_weather виконана",message.from_user.id)
    else:
        bot.send_message(message.chat.id, "Ви ще не підписані на щоденну розсилку погоди.")

# Command to delete an item from the catalog (only for admins)
@bot.message_handler(commands=['delete_item'])
def delete_item(message):
    if message.from_user.id in admin_ids:
        bot.send_message(message.chat.id, "Введіть ID товару, який потрібно видалити:")
        bot.register_next_step_handler(message, process_delete_step)
    else:
        bot.send_message(message.chat.id, "🔒Ця команда доступна лише адміністраторам.🔒")


def process_delete_step(message):
    item_id = message.text
    cursor.execute("SELECT * FROM catalog WHERE id = ?", (item_id,))
    item = cursor.fetchone()

    if item:
        cursor.execute("DELETE FROM catalog WHERE id = ?", (item_id,))
        conn.commit()
        bot.send_message(message.chat.id, f"Товар із ID {item_id} успішно видалено з каталогу.")
    else:
        bot.send_message(message.chat.id, "Товар із таким ID не знайдено.")


# Get all orders from the database
def get_all_orders():
    cursor.execute("SELECT * FROM orders")
    return cursor.fetchall()

# View orders by the admin
@bot.message_handler(commands=['view_orders'])
def admin_view_orders(message):
    user_id = message.from_user.id
    if user_id in admin_ids:
        orders_list = get_all_orders()
        if orders_list:
            send_order_details(message, orders_list, 0)
        else:
            bot.send_message(message.chat.id, "Немає жодного замовлення.")
    else:
        bot.send_message(message.chat.id, "🔒Ця команда доступна лише адміністраторам.🔒")

# Функція для відображення деталей замовлення з навігацією
def send_order_details(message, orders, index, message_id=None):
    order = orders[index]
    order_id = order[0]
    username = order[2] or "N/A"
    full_name = order[3] or "N/A"
    item_name = order[4] or "N/A"
    item_price = order[5] if order[5] is not None else "N/A"
    address = order[6] or "N/A"
    buy_id = order[7] or "N/A"
    status = order[8] or "N/A"

    # Формуємо текст повідомлення з деталями замовлення
    order_text = (
        f"📦 **Замовлення {order_id}**\n\n"
        f"Username: @{username}\n"
        f"ПІБ: {full_name}\n"
        f"Товар: {item_name}\n"
        f"Ціна: {item_price} грн\n"
        f"Адреса: {address}\n"
        f"ID Оплати: {buy_id}\n\n"
        f"Статус: {status}"
    )

    # Кнопки для управління статусом замовлення
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📦 Відправлено", callback_data=f"set_status_Відправлено_{order_id}"),
        InlineKeyboardButton("⏳ Обробляється", callback_data=f"set_status_Обробляється_{order_id}"),
        InlineKeyboardButton("❌ Скасувати", callback_data=f"set_status_cancelled_{order_id}"),
        InlineKeyboardButton("🗑️ Видалити замовлення", callback_data=f"delete_order_{order_id}")
    )

    # Кнопки для навігації між замовленнями
    navigation_buttons = []
    if index > 0:
        navigation_buttons.append(InlineKeyboardButton("⬅️ Попереднє", callback_data=f"order_navigate_{index - 1}"))
    if index < len(orders) - 1:
        navigation_buttons.append(InlineKeyboardButton("Наступне ➡️", callback_data=f"order_navigate_{index + 1}"))
    if navigation_buttons:
        markup.row(*navigation_buttons)

    # Кнопка для відкриття списку замовлень
    markup.add(InlineKeyboardButton("📋 Показати всі замовлення", callback_data="show_order_list"))

    # Оновлення повідомлення, якщо message_id передано, інакше надсилаємо нове повідомлення
    if message_id:
        bot.edit_message_text(
            order_text, chat_id=message.chat.id, message_id=message_id,
            reply_markup=markup, parse_mode="Markdown"
        )
    else:
        bot.send_message(message.chat.id, order_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "show_order_list")
def show_order_list(call):
    orders = get_all_orders()
    if orders:
        markup = InlineKeyboardMarkup()
        for i, order in enumerate(orders):
            order_id = order[0]
            markup.add(InlineKeyboardButton(f"Замовлення {order_id}", callback_data=f"select_order_{i}"))
        bot.edit_message_text("Оберіть замовлення зі списку:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "Немає доступних замовлень.", show_alert=True)


# Get all orders from the database
def get_all_orders():
    cursor.execute("SELECT * FROM orders")
    return cursor.fetchall()

@bot.message_handler(commands=['my_orders'])
def user_view_orders(message):
    user_id = message.from_user.id
    orders = get_user_orders(user_id)
    if orders:
        send_user_order_details(message, orders, 0)
    else:
        bot.send_message(message.chat.id, "У вас немає жодного замовлення.")

# Отримати всі замовлення користувача
def get_user_orders(user_id):
    cursor.execute("SELECT * FROM orders WHERE user_id = ?", (user_id,))
    return cursor.fetchall()

# Відображення деталей замовлення для користувача
def send_user_order_details(message, orders, index, message_id=None):
    order = orders[index]
    order_id = order[0]
    item_name = order[4] or "N/A"
    item_price = order[5] if order[5] is not None else "N/A"
    address = order[6] or "N/A"
    status = order[8] or "N/A"

    # Формуємо текст повідомлення з деталями замовлення
    order_text = (
        f"📦 **Ваше замовлення {order_id}**\n\n"
        f"Товар: {item_name}\n"
        f"Ціна: {item_price} грн\n"
        f"Адреса: {address}\n"
        f"Статус: {status}"
    )

    # Кнопки для навігації між замовленнями
    markup = InlineKeyboardMarkup()
    navigation_buttons = []
    if index > 0:
        navigation_buttons.append(
            InlineKeyboardButton("⬅️ Попереднє", callback_data=f"user_order_navigate_{index - 1}"))
    if index < len(orders) - 1:
        navigation_buttons.append(InlineKeyboardButton("Наступне ➡️", callback_data=f"user_order_navigate_{index + 1}"))
    if navigation_buttons:
        markup.row(*navigation_buttons)

    # Кнопка "Отримано", активна тільки при статусі "Відправлено"
    if status == "Відправлено":
        markup.add(InlineKeyboardButton("✅ Отримано", callback_data=f"confirm_received_{order_id}"))

    # Оновлення повідомлення, якщо message_id передано, інакше надсилаємо нове повідомлення
    if message_id:
        bot.edit_message_text(order_text, chat_id=message.chat.id, message_id=message_id, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, order_text, reply_markup=markup, parse_mode="Markdown")

# Навігація по замовленнях користувача
@bot.callback_query_handler(func=lambda call: call.data.startswith("user_order_navigate_"))
def navigate_user_orders(call):
    try:

        # Розбиття на частини
        parts = call.data.split("_")

        # Перевірка, що parts містить саме чотири елементи, як очікується для формату 'user_order_navigate_<index>'
        if len(parts) != 4:
            raise ValueError("Incorrect callback format. Expected format: 'user_order_navigate_<index>'")

        # Отримання індексу з останньої частини
        index = int(parts[3])

        user_id = call.from_user.id
        orders = get_user_orders(user_id)

        # Перевірка на правильний індекс
        if 0 <= index < len(orders):
            send_user_order_details(call.message, orders, index, message_id=call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "Немає доступних замовлень або індекс виходить за межі списку.")
    except ValueError as ve:
        logging.error(f"ValueError in navigating user orders with callback data: {call.data} - {ve}")
        bot.answer_callback_query(call.id, "Невірні дані для навігації.")
    except IndexError as ie:
        logging.error(f"IndexError in navigating user orders with callback data: {call.data} - {ie}")
        bot.answer_callback_query(call.id, "Невірні дані для навігації.")

# Підтвердження отримання замовлення
@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_received_"))
def confirm_order_received(call):
    order_id = int(call.data.split("_")[2])
    cursor.execute("UPDATE orders SET status = 'Отримано' WHERE id = ?", (order_id,))
    conn.commit()
    bot.answer_callback_query(call.id, "Замовлення підтверджено як отримане.")
    bot.send_message(call.message.chat.id, f"Ваше замовлення {order_id} підтверджено як отримане.")
    logging.info(f"Користувач {call.from_user.username} (ID: {call.from_user.id}) підтвердив отримання замовлення ID: {order_id}.")

# Handle subcategory selection
@bot.callback_query_handler(func=lambda call: call.data.startswith("category_"))
def show_subcategory(call):
    category = call.data.split("_")[1]
    items = get_items_by_category(category)
    if items:
        show_item_details(call.message, items, 0)
    else:
        bot.send_message(call.message.chat.id, "Ця категорія зараз порожня.")

# Display item details from a category
def show_item_details(message, items, index):
    item = items[index]
    message_text = f"**{item[1]}**\n\n{item[2]}\nЦіна: {item[3]}"

    markup = InlineKeyboardMarkup()
    navigation_buttons = []
    if index > 0:
        navigation_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"catalog_navigate_{index - 1}_{item[0]}"))
    if index < len(items) - 1:
        navigation_buttons.append(InlineKeyboardButton("Далі ➡️", callback_data=f"catalog_navigate_{index + 1}_{item[0]}"))

    if navigation_buttons:
        markup.row(*navigation_buttons)

    catalog_button = InlineKeyboardButton("🗃️Каталог товарів", callback_data="back_to_catalog")
    order_button = InlineKeyboardButton("📬Замовити", callback_data=f"confirm_order_{item[0]}")
    add_cart = InlineKeyboardButton("🛒Додати в корзину", callback_data=f"add_to_cart_{item[0]}")
    markup.add(order_button, catalog_button,add_cart)

    bot.send_photo(chat_id=message.chat.id, photo=item[4], caption=message_text, reply_markup=markup, parse_mode='Markdown')

def add_to_cart(user_id, item_name, item_price):
    cursor.execute("SELECT * FROM cart WHERE user_id = ? AND item_name = ?", (user_id, item_name))
    item = cursor.fetchone()

    if item:
        cursor.execute("UPDATE cart SET quantity = quantity + 1 WHERE user_id = ? AND item_name = ?", (user_id, item_name))
    else:
        cursor.execute("INSERT INTO cart (user_id, item_name, item_price) VALUES (?, ?, ?)", (user_id, item_name, item_price))
    conn.commit()

def remove_from_cart(user_id, item_name):
    cursor.execute("DELETE FROM cart WHERE user_id = ? AND item_name = ?", (user_id, item_name))
    conn.commit()

def get_cart(user_id):
    cursor.execute("SELECT item_name, item_price, quantity FROM cart WHERE user_id = ?", (user_id,))
    return cursor.fetchall()


@bot.callback_query_handler(func=lambda call: call.data.startswith("add_to_cart_"))
def handle_add_to_cart(call):
    # Логування значення call.data для діагностики
    logging.info(f"Received call.data: {call.data}")

    try:
        # Розбиття рядка та перевірка, що четвертий елемент є числом
        data_parts = call.data.split("_")
        logging.info(f"Parsed data_parts: {data_parts}")

        # Перевірка, що `data_parts` має чотири частини, а остання частина - числове значення
        if len(data_parts) == 4 and data_parts[3].isdigit():
            item_id = int(data_parts[3])
            logging.info(f"Extracted item_id: {item_id}")

            cursor.execute("SELECT name, price FROM catalog WHERE id = ?", (item_id,))
            item = cursor.fetchone()

            if item:
                item_name, item_price = item
                add_to_cart(call.from_user.id, item_name,
                            float(item_price.replace(",", "").replace(" грн", "").strip()))
                bot.answer_callback_query(call.id, "Товар додано в корзину!")
            else:
                bot.answer_callback_query(call.id, "Товар не знайдено.")
        else:
            raise ValueError("Невірний формат item_id - можливо, item_id відсутній або некоректний.")
    except (IndexError, ValueError) as e:
        # Логування конкретної помилки при розподілі чи форматуванні
        logging.error(f"Invalid format for call.data: {call.data} - Error: {e}")
        bot.answer_callback_query(call.id, "Невірний формат даних для додавання в корзину.")


@bot.message_handler(commands=['view_cart'])
def view_cart(message):
    cart_items = get_cart(message.from_user.id)
    if cart_items:
        cart_text = "🛒 Ваша корзина:\n\n"
        total = 0
        for item_name, item_price, quantity in cart_items:
            cart_text += f"{item_name} - {item_price} грн x {quantity}\n"
            total += item_price * quantity
        cart_text += f"\n💰 Загальна сума: {total} грн"

        # Кнопки для керування товарами та оформлення замовлення
        markup = InlineKeyboardMarkup()
        for item_name, item_price, quantity in cart_items:
            markup.add(
                InlineKeyboardButton(f"➕ {item_name}", callback_data=f"add_cart_item_{item_name}"),
                InlineKeyboardButton(f"➖ {item_name}", callback_data=f"remove_cart_item_{item_name}")
            )
        markup.add(InlineKeyboardButton("🛍️ Оформити замовлення", callback_data="checkout_cart"))
        markup.add(InlineKeyboardButton("🧹Очисти корзину", callback_data="checkout_cart"))
        bot.send_message(message.chat.id, cart_text, reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "Ваша корзина порожня.")

# Обробка додавання одиниці товару в корзину
@bot.callback_query_handler(func=lambda call: call.data.startswith("add_cart_item_"))
def handle_add_cart_item(call):
    item_name = call.data.split("_")[3]
    cursor.execute("UPDATE cart SET quantity = quantity + 1 WHERE user_id = ? AND item_name = ?", (call.from_user.id, item_name))
    conn.commit()
    bot.answer_callback_query(call.id, f"Додано одиницю {item_name}")
    view_cart(call.message)  # Оновлює повідомлення з корзиною

# Обробка зменшення одиниці товару в корзині
@bot.callback_query_handler(func=lambda call: call.data.startswith("remove_cart_item_"))
def handle_remove_cart_item(call):
    item_name = call.data.split("_")[3]
    cursor.execute("SELECT quantity FROM cart WHERE user_id = ? AND item_name = ?", (call.from_user.id, item_name))
    quantity = cursor.fetchone()[0]
    if quantity > 1:
        cursor.execute("UPDATE cart SET quantity = quantity - 1 WHERE user_id = ? AND item_name = ?", (call.from_user.id, item_name))
    else:
        cursor.execute("DELETE FROM cart WHERE user_id = ? AND item_name = ?", (call.from_user.id, item_name))
    conn.commit()
    bot.answer_callback_query(call.id, f"Зменшено кількість {item_name}")
    view_cart(call.message)  # Оновлює повідомлення з корзиною



def clear_cart(user_id):
    cursor.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
    conn.commit()

@bot.message_handler(commands=['clear_cart'])
def clear_cart_command(message):
    clear_cart(message.from_user.id)
    bot.send_message(message.chat.id, "Корзину очищено.")

def checkout(user_id):
    cart_items = get_cart(user_id)
    if cart_items:
        for item_name, item_price, quantity in cart_items:
            cursor.execute("INSERT INTO orders (user_id, item_name, item_price, status) VALUES (?, ?, ?, 'в процесі')",
                           (user_id, item_name, item_price * quantity))
        conn.commit()
        clear_cart(user_id)
        return True
    return False

# Оформлення замовлення з корзини
# Оформлення замовлення з корзини з оплатою
@bot.callback_query_handler(func=lambda call: call.data == "checkout_cart")
def handle_checkout_cart(call):
    if checkout(call.from_user.id):
        bot.send_message(call.message.chat.id,
                         "Замовлення оформлено. Введіть ваше повне ім'я (Прізвище Ім'я Побатькові):")
        bot.register_next_step_handler(call.message, process_full_name_for_cart)
    else:
        bot.send_message(call.message.chat.id, "Ваша корзина порожня.")


# Обробка ПІБ для замовлення з корзини
def process_full_name_for_cart(message):
    full_name = message.text
    user_id = message.from_user.id

    # Збереження ПІБ для всіх товарів у корзині
    cursor.execute("UPDATE orders SET full_name = ? WHERE user_id = ? AND status = 'в процесі'", (full_name, user_id))
    conn.commit()

    # Запит адреси доставки
    bot.send_message(message.chat.id, "Введіть адресу для доставки:")
    bot.register_next_step_handler(message, process_address_for_cart)


# Обробка адреси доставки для замовлення з корзини
def process_address_for_cart(message):
    address = message.text
    user_id = message.from_user.id

    if len(address) > 5:  # Перевірка коректності адреси
        cursor.execute("UPDATE orders SET address = ? WHERE user_id = ? AND status = 'в процесі'", (address, user_id))
        conn.commit()

        # Ініціація оплати
        initiate_payment_for_cart(message)
    else:
        bot.send_message(message.chat.id, "Будь ласка, введіть коректну адресу.")
        bot.register_next_step_handler(message, process_address_for_cart)


# Ініціація оплати для всього замовлення з корзини
def initiate_payment_for_cart(message):
    user_id = message.from_user.id
    cursor.execute("SELECT item_name, item_price FROM orders WHERE user_id = ? AND status = 'в процесі'", (user_id,))
    items = cursor.fetchall()

    if items:
        total_price = sum([item[1] for item in items])
        order_id = str(uuid.uuid4())  # Генеруємо унікальний order_id для корзини

        # Оновлення `order_id` для всіх товарів у замовленні
        cursor.execute("UPDATE orders SET order_id = ? WHERE user_id = ? AND status = 'в процесі'", (order_id, user_id))
        conn.commit()

        # Параметри оплати
        params = {
            "public_key": TEST_PUBLIC_KEY,
            "version": "3",
            "action": "pay",
            "amount": total_price,  # Загальна ціна
            "currency": "UAH",
            "description": f"Оплата товарів з корзини (загалом {len(items)} позицій)",
            "order_id": order_id,
        }

        data = base64.b64encode(json.dumps(params).encode('utf-8')).decode('utf-8')
        signature = create_signature(data, TEST_PRIVATE_KEY)
        payment_link = f"https://www.liqpay.ua/api/3/checkout?data={data}&signature={signature}"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Підтвердити оплату", callback_data=f"payment_confirm_{order_id}"))

        bot.send_message(
            message.chat.id,
            f"[Для оплати замовлення перейдіть за цим посиланням]({payment_link})\n\n"
            "Після оплати, натисніть кнопку нижче для підтвердження.",
            parse_mode="Markdown",
            reply_markup=markup
        )
        logging.info(f"Ініційовано оплату для корзини на суму {total_price} грн, order_id: {order_id}")

@bot.message_handler(commands=['checkout'])
def checkout_command(message):
    if checkout(message.from_user.id):
        bot.send_message(message.chat.id, "Замовлення оформлено. Дякуємо за покупку!")
    else:
        bot.send_message(message.chat.id, "Ваша корзина порожня.")


# Команда /help - показує всі доступні команди
@bot.message_handler(commands=['help'])
def help_command(message):
    user_id = message.from_user.id
    if user_id in admin_ids:
        help_text = (
            "🛍 Доступні команди для адміністратора:\n\n"
            "/start - Запуск бота та вітальне повідомлення\n"
            "/help - Переглянути всі доступні команди\n"
            "/info - Інформація про магазин\n"
            "/catalog - Переглянути каталог товарів\n"
            "/weather - Отримати поточний прогноз погоди для вказаного міста\n"
            "/subscribe_weather - Підписатися на щоденну розсилку погоди\n"
            "/unsubscribe_weather - Відписатися від щоденної розсилки погоди\n"
            "/feedback - Надіслати відгук адміністраторам\n"
            "/add_item - Додати новий товар до каталогу (для адміністраторів)\n"
            "/delete_item - Видалити товар з каталогу за ID (для адміністраторів)\n"
            "/view_orders - Переглянути список усіх замовлень (для адміністраторів)\n"
            "/update_order - Оновити статус замовлення за ID (для адміністраторів)"
        )
    else:
        help_text = (
            "🛍 Доступні команди:\n\n"
            "/start - Запуск бота та вітальне повідомлення\n"
            "/help - Переглянути всі доступні команди\n"
            "/info - Інформація про магазин\n"
            "/catalog - Переглянути каталог товарів\n"
            "/weather - Отримати поточний прогноз погоди для вказаного міста\n"
            "/subscribe_weather - Підписатися на щоденну розсилку погоди\n"
            "/unsubscribe_weather - Відписатися від щоденної розсилки погоди\n"
            "/feedback - Надіслати відгук адміністраторам"
        )
    bot.send_message(message.chat.id, help_text)
    log_event("Команда /help виконана", message.from_user.id, message.from_user.username)

# Команда /feedback - користувач може залишити відгук, який надсилається адміністраторам
@bot.message_handler(commands=['feedback'])
def feedback_command(message):
    bot.send_message(message.chat.id, "Будь ласка, напишіть ваш відгук, і він буде надісланий адміністраторам.")
    bot.register_next_step_handler(message, handle_feedback)

# Обробка відгуку
def handle_feedback(message):
    feedback_text = message.text
    user_id = message.from_user.id
    username = message.from_user.username

    # Відправка відгуку адміністраторам
    for admin_id in admin_ids:
        bot.send_message(
            admin_id,
            f"Новий відгук від @{username} (ID: {user_id}):\n\n{feedback_text}"
        )

    # Підтвердження для користувача
    bot.send_message(message.chat.id, "Дякуємо за ваш відгук! Він був надісланий адміністраторам.")
    log_event(f"Відгук отримано: {feedback_text}", user_id, username)

# Команда /info - інформація про магазин
@bot.message_handler(commands=['info'])
def info_command(message):
    info_text = (
        "📢 Ласкаво просимо до магазину Техносова!\n\n"
        "🕒 Час роботи: Понеділок - П’ятниця, 9:00 - 19:00\n"
        "📅 Дні роботи: Пн-Пт\n"
        "📍 Адреса: вул. Технологій, 15, Київ\n\n"
        "У нашому магазині ви знайдете широкий асортимент електроніки: смартфони, ноутбуки, навушники "
        "та багато іншого. Наша місія - надавати якісну техніку за доступними цінами та забезпечувати "
        "високий рівень обслуговування для кожного клієнта. Дякуємо, що обрали нас! 💼\n\n"
        "Зв’яжіться з нами, якщо виникнуть питання!"
    )
    bot.send_message(message.chat.id, info_text)
    log_event("Команда /info виконана", message.from_user.id, message.from_user.username)

# Update order status
@bot.message_handler(commands=['update_order'])
def update_order_status(message):
    if message.from_user.id in admin_ids:
        bot.send_message(message.chat.id, "Введіть ID замовлення, щоб оновити статус:")
        bot.register_next_step_handler(message, process_update_status_step)
    else:
        bot.send_message(message.chat.id, "🔒Ця команда доступна лише адміністраторам.🔒")

def process_update_status_step(message):
    order_id = message.text
    cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()

    if order:
        bot.send_message(message.chat.id, "Виберіть новий статус:", reply_markup=build_status_markup(order_id))
    else:
        bot.send_message(message.chat.id, "Замовлення з таким ID не знайдено.")

def build_status_markup(order_id):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Відправлено", callback_data=f"set_status_Відпрвленно_{order_id}"),
        InlineKeyboardButton("Обробляється", callback_data=f"set_status_processing_{order_id}"),
        InlineKeyboardButton("Скасування", callback_data=f"set_status_cancelled_{order_id}")
    )
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_status_"))
def update_status(call):
    order_id = int(call.data.split("_")[-1])
    new_status = call.data.split("_")[2]

    if new_status == "cancelled":
        cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        response_message = f"Замовлення {order_id} було успішно скасоване та видалене."
    else:
        cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
        response_message = f"Статус замовлення {order_id} успішно оновлено на '{new_status}'."

    conn.commit()
    bot.answer_callback_query(call.id, response_message)
    bot.send_message(call.message.chat.id, response_message)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_order_"))
def delete_order(call):
    order_id = int(call.data.split("_")[-1])
    cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()

    bot.answer_callback_query(call.id, "Замовлення успішно видалено.")
    bot.send_message(call.message.chat.id, f"Замовлення {order_id} успішно видалено.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("catalog_navigate_"))
def navigate_catalog_items(call):
    try:
        # Логування для діагностики
        logging.info(f"Received callback data: {call.data}")
        data_parts = call.data.split("_")
        logging.info(f"Split callback data: {data_parts}")

        # Перевірка, що дані складаються з чотирьох частин
        if len(data_parts) == 4:
            _, _, index_str, item_id_str = data_parts

            # Перетворення значень у числа
            index = int(index_str)
            item_id = int(item_id_str)

            logging.info(f"Parsed index={index}, item_id={item_id}")

            # Отримуємо категорію та список товарів
            category = get_item_category(item_id)
            items = get_items_by_category(category)

            # Перевірка на наявність товарів та коректність індексу
            if items and 0 <= index < len(items):
                edit_item_details(call.message, items, index)
            else:
                bot.answer_callback_query(call.id, "Немає доступних товарів або індекс виходить за межі списку.", show_alert=True)
                logging.warning(f"Invalid index for catalog navigation: index={index}, total items={len(items)}")
        else:
            bot.answer_callback_query(call.id, "Помилка: некоректний формат даних для навігації.", show_alert=True)
            logging.error("Invalid callback data structure")

    except IndexError:
        bot.answer_callback_query(call.id, "Помилка: спроба доступу до неіснуючого товару.", show_alert=True)
        logging.error("IndexError: спроба доступу до неіснуючого товару")
    except ValueError as e:
        bot.answer_callback_query(call.id, "Помилка: недійсний індекс.", show_alert=True)
        logging.error(f"ValueError: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_order_"))
def select_order(call):
    index = int(call.data.split("_")[2])
    orders = get_all_orders()
    bot.delete_message(call.message.chat.id, call.message.message_id)  # Видаляємо попереднє повідомлення
    send_order_details(call.message, orders, index)




@bot.callback_query_handler(func=lambda call: call.data.startswith("set_status_"))
def update_status(call):
    order_id = call.data.split("_")[-1]
    new_status = call.data.split("_")[2]

    cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()

    bot.answer_callback_query(call.id, f"Статус замовлення змінено на '{new_status}'.")
    bot.send_message(call.message.chat.id, f"Статус замовлення {order_id} успішно оновлено на '{new_status}'.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("order_navigate_"))
def navigate_order_items(call):
    index = int(call.data.split("_")[2])
    orders = get_all_orders()

    if 0 <= index < len(orders):
        # Передаємо message_id, щоб оновити існуюче повідомлення
        send_order_details(call.message, orders, index, message_id=call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "Немає доступних замовлень або індекс виходить за межі списку.")


# Handle back to catalog
@bot.callback_query_handler(func=lambda call: call.data == "back_to_catalog")
def back_to_catalog(call):
    show_catalog(call.message)

# Get the category of an item
def get_item_category(item_id):
    cursor = conn.cursor()  # Створюємо новий курсор
    cursor.execute("SELECT category FROM catalog WHERE id = ?", (item_id,))
    result = cursor.fetchone()
    cursor.close()  # Закриваємо курсор після виконання запиту
    return result[0] if result else None


# Edit item details
def edit_item_details(message, items, index):
    item = items[index]
    message_text = f"**{item[1]}**\n\n{item[2]}\nЦіна: {item[3]}"

    markup = InlineKeyboardMarkup()
    navigation_buttons = []
    # Формат callback_data має бути точним
    if index > 0:
        navigation_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"catalog_navigate_{index - 1}_{item[0]}"))
    if index < len(items) - 1:
        navigation_buttons.append(InlineKeyboardButton("Далі ➡️", callback_data=f"catalog_navigate_{index + 1}_{item[0]}"))

    if navigation_buttons:
        markup.row(*navigation_buttons)

    catalog_button = InlineKeyboardButton("🗃️Каталог товарів", callback_data="back_to_catalog")
    order_button = InlineKeyboardButton("📬Замовити", callback_data=f"confirm_order_{item[0]}")
    add_cart = InlineKeyboardButton("🛒Додати в корзину", callback_data=f"add_to_cart_{item[0]}")
    markup.add(order_button, catalog_button, add_cart)

    media = InputMediaPhoto(media=item[4], caption=message_text, parse_mode='Markdown')
    bot.edit_message_media(chat_id=message.chat.id, message_id=message.message_id, media=media, reply_markup=markup)




def create_signature(data, private_key):
    # Створюємо підпис для запиту
    sign_string = private_key + data + private_key
    signature = base64.b64encode(hashlib.sha1(sign_string.encode('utf-8')).digest()).decode('utf-8')
    logging.info(f"Створено підпис для LiqPay: {signature}")
    return base64.b64encode(hashlib.sha1(sign_string.encode('utf-8')).digest()).decode('utf-8')


# Функція для перевірки наявності існуючого замовлення, щоб уникнути дублювання записів
def check_existing_order(user_id, item_name):
    cursor.execute("SELECT * FROM orders WHERE user_id = ? AND item_name = ? AND status = 'в процесі'", (user_id, item_name))
    return cursor.fetchone() is not None


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_order_"))
def confirm_order(call):
    item_id = int(call.data.split("_")[2])
    cursor.execute("SELECT name, price FROM catalog WHERE id = ?", (item_id,))
    item = cursor.fetchone()

    if item:
        item_name = item[0]

        # Очищення ціни від зайвих символів
        raw_price = item[1].replace(" грн", "").strip()

        # Прибираємо зайві крапки, залишаючи лише першу
        if raw_price.count('.') > 1:
            first_dot_index = raw_price.find('.')
            raw_price = raw_price[:first_dot_index + 1] + raw_price[first_dot_index + 1:].replace('.', '')

        # Заміна коми на крапку та конвертація у float
        item_price = float(raw_price.replace(",", "."))

        # Перевірка наявності існуючого замовлення перед додаванням нового
        if not check_existing_order(call.from_user.id, item_name):
            cursor.execute(
                "INSERT INTO orders (user_id, username, item_name, item_price, status) VALUES (?, ?, ?, ?, 'в процесі')",
                (call.from_user.id, call.from_user.username, item_name, item_price))
            conn.commit()
            bot.send_message(call.message.chat.id,
                             "Ваше замовлення збережено. Введіть ваше повне ім'я (Фамілія, ім'я, Побатькові):")
            bot.register_next_step_handler(call.message, process_full_name, item_id)
        else:
            bot.send_message(call.message.chat.id, "У вас вже є замовлення в процесі для цього товару.")


def process_full_name(message, item_id):
    full_name = message.text
    user_id = message.from_user.id

    # Оновлюємо запис замовлення, додаючи ПІБ
    cursor.execute("UPDATE orders SET full_name = ? WHERE user_id = ? AND item_name = (SELECT name FROM catalog WHERE id = ?) AND status = 'в процесі'",
                   (full_name, user_id, item_id))
    conn.commit()

    # Запитуємо адресу доставки
    bot.send_message(message.chat.id, "Введіть адресу для доставки:")
    bot.register_next_step_handler(message, process_address, item_id)

def process_address(message, item_id):
    address = message.text
    user_id = message.from_user.id

    # Перевірка коректності адреси
    if len(address) > 5:
        cursor.execute("UPDATE orders SET address = ? WHERE user_id = ? AND item_name = (SELECT name FROM catalog WHERE id = ?) AND status = 'в процесі'",
                       (address, user_id, item_id))
        conn.commit()

        # Після збереження адреси
        bot.send_message(message.chat.id, "Дякуємо! Тепер ви можете перейти до оплати.")
        initiate_payment(message, item_id)
    else:
        bot.send_message(message.chat.id, "Будь ласка, введіть коректну адресу.")
        bot.register_next_step_handler(message, process_address, item_id)


def initiate_payment(message, item_id):
    # Отримуємо деталі замовлення
    cursor.execute("SELECT name, price FROM catalog WHERE id = ?", (item_id,))
    item = cursor.fetchone()

    if item:
        item_name, item_price = item
        item_price = int(float(item_price.replace(",", "").replace(" грн", "").strip()) * 100)

        # Генеруємо унікальний order_id
        order_id = str(uuid.uuid4())

        # Перевірка наявності існуючого замовлення зі статусом "в процесі"
        cursor.execute("SELECT * FROM orders WHERE user_id = ? AND item_name = ? AND status = 'в процесі'",
                       (message.from_user.id, item_name))
        existing_order = cursor.fetchone()

        if existing_order:
            # Оновлюємо order_id для існуючого замовлення, замість створення нового
            cursor.execute("UPDATE orders SET order_id = ? WHERE id = ?", (order_id, existing_order[0]))
        else:
            # Якщо замовлення немає, створюємо нове
            cursor.execute("INSERT INTO orders (user_id, username, item_name, item_price, order_id, status) VALUES (?, ?, ?, ?, ?, 'в процесі')",
                           (message.from_user.id, message.from_user.username, item_name, item_price, order_id))
        conn.commit()

        # Створюємо посилання для оплати і відправляємо користувачу
        params = {
            "public_key": TEST_PUBLIC_KEY,
            "version": "3",
            "action": "pay",
            "amount": item_price / 100,  # Ціна в гривнях
            "currency": "UAH",
            "description": f"Оплата товару: {item_name}",
            "order_id": order_id,
        }

        data = base64.b64encode(json.dumps(params).encode('utf-8')).decode('utf-8')
        signature = create_signature(data, TEST_PRIVATE_KEY)
        payment_link = f"https://www.liqpay.ua/api/3/checkout?data={data}&signature={signature}"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Підтвердити оплату", callback_data=f"payment_confirm_{order_id}"))

        bot.send_message(
            message.chat.id,
            f"[Для оплати замовлення перейдіть за цим посиланням]({payment_link})\n\n"
            "Після оплати, натисніть кнопку нижче для підтвердження.",
            parse_mode="Markdown",
            reply_markup=markup
        )
        logging.info(f"Ініційовано оплату: {item_name}, Ціна: {item_price} копійок, order_id: {order_id}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("payment_confirm_"))
def confirm_payment_status(call):
    order_id = call.data.split("_")[2]

    # Отримуємо статус платежу для order_id
    payment_status = check_payment_status(order_id)

    if payment_status == "success":
        # Оновлюємо статус замовлення в базі даних
        cursor.execute("UPDATE orders SET status = 'оплачено' WHERE user_id = ? AND order_id = ?",
                       (call.from_user.id, order_id))
        conn.commit()

        # Повідомляємо користувача про успішну оплату
        bot.send_message(call.message.chat.id, "Ваш платіж підтверджено! Дякуємо за покупку.")
        # Сповіщаємо адміністратора про нове оплачене замовлення
        for admin_id in admin_ids:
            bot.send_message(admin_id, f"Користувач @{call.from_user.username} успішно оплатив замовлення ID {order_id}.")
        logging.info(f"Платіж підтверджено: order_id {order_id}, ID користувача: {call.from_user.id}")
    else:
        bot.send_message(call.message.chat.id, "Платіж ще не підтверджено. Спробуйте ще раз пізніше або зверніться до підтримки.")
        logging.warning(f"Невдалий платіж: order_id {order_id}, Статус: {payment_status}")


def check_payment_status(order_id):
    # Параметри запиту для перевірки статусу
    params = {
        "public_key": TEST_PUBLIC_KEY,
        "version": "3",
        "action": "status",
        "order_id": order_id,
    }
    data = base64.b64encode(json.dumps(params).encode('utf-8')).decode('utf-8')
    signature = create_signature(data, TEST_PRIVATE_KEY)

    # Перевірка на sandbox режим (симуляція успішного платежу)
    if params.get("sandbox") == 1:  # якщо sandbox увімкнено
        print("Симуляція успішного платежу в sandbox")
        logging.info(f"Статус платежу успішний для order_id {order_id}")
        return "success"

    # Відправляємо запит до LiqPay API для перевірки статусу
    response = requests.post("https://www.liqpay.ua/api/request", data={"data": data, "signature": signature})
    result = response.json()

    # Перевіряємо статус платежу в результатах
    if result.get("status") == "success":
        logging.info(f"Статус платежу успішний для order_id {order_id}")
        return "success"
    else:
        logging.error(f"Помилка при перевірці статусу платежу: {result.get('status', 'error')}")
        return result.get("status", "error")  # Повертає статус або 'error'

# Закриття бази даних при завершенні роботи
@atexit.register
def close_db():
    conn.close()

bot.remove_webhook()
# Start the bot
log_event("Бот запущений")
bot.polling(none_stop=True)