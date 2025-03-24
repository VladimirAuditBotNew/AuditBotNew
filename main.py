import telebot
from flask import Flask, request
from threading import Thread
import sqlite3
from datetime import datetime, timedelta
import time
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

app = Flask('')

@app.route('/')
def home():
    print("Получен запрос к Flask-серверу")
    return "Бот работает!"

@app.route('/', methods=['POST'])
def webhook():
    try:
        update = telebot.types.Update.de_json(request.get_json())
        bot.process_new_updates([update])
        return 'OK', 200
    except Exception as e:
        print(f"Ошибка обработки вебхука: {e}")
        return 'Error', 500

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

bot = telebot.TeleBot("7244223580:AAHR_tjEJSQVp0Gga9bqvoBdvureE3ZMLZU")
CHANNEL_ID = "-1002570139251"  # ID канала
ADMIN_ID = 5935811078  # Твой ID для уведомлений

# Хранилище заявок с таймстемпом (только для отклонённых заявок)
pending_requests = {}  # {user_id: {"username": username, "timestamp": timestamp}}
# Хранилище пользователей в процессе подачи заявки
in_progress = {}  # {user_id: True}

# Создаём клавиатуру с кнопками
def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(KeyboardButton("Подписка (500 руб/мес)"))
    keyboard.add(KeyboardButton("Личный аудит (2000 руб)"))
    keyboard.add(KeyboardButton("Статистика"))
    keyboard.add(KeyboardButton("Помощь"))
    return keyboard

# Словарь для сопоставления команд с их обработчиками
command_handlers = {
    '/subscribe': lambda message: send_subscribe(message),
    '/premium': lambda message: send_premium(message),
    '/start': lambda message: send_welcome(message),
    '/stats': lambda message: send_stats(message),
    '/help': lambda message: send_help(message),
    'Подписка (500 руб/мес)': lambda message: send_subscribe(message),
    'Личный аудит (2000 руб)': lambda message: send_premium(message),
    'Статистика': lambda message: send_stats(message),
    'Помощь': lambda message: send_help(message)
}

def init_db():
    try:
        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        # Таблица подписок
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, username TEXT, start_date TEXT, end_date TEXT, 
                      reminder_sent_1day INTEGER DEFAULT 0, reminder_sent_10min INTEGER DEFAULT 0)''')
        # Таблица истории подписок
        c.execute('''CREATE TABLE IF NOT EXISTS subscription_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, 
                      start_date TEXT, end_date TEXT, months INTEGER)''')
        conn.commit()
        conn.close()
        print("База данных инициализирована")
    except Exception as e:
        print(f"Ошибка инициализации базы данных: {e}")

def add_subscription(user_id, username, months=1):
    try:
        start_date = datetime.now()
        end_date = start_date + timedelta(days=30 * months)
        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO subscriptions (user_id, username, start_date, end_date, reminder_sent_1day, reminder_sent_10min) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'), 0, 0))
        conn.commit()
        conn.close()
        print(f"Подписка для @{username} активирована до {end_date} (на {months} месяцев)")
        return True
    except Exception as e:
        print(f"Ошибка добавления подписки для {user_id}: {e}")
        return False

def expire_subscription(user_id, username):
    conn = None
    try:
        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("UPDATE subscriptions SET end_date = ? WHERE user_id = ?", (today, user_id))
        conn.commit()
        c.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        conn.commit()
        try:
            bot.send_message(user_id, "Твоя подписка завершена. Оплати снова: /subscribe")
            print(f"Уведомление отправлено пользователю @{username}")
        except Exception as e:
            print(f"Ошибка отправки уведомления пользователю @{username}: {e}")
        try:
            bot.send_message(ADMIN_ID, f"Подписка @{username} истекла. Удали его из канала 'Аудит VIP'.")
            print(f"Уведомление отправлено админу о завершении подписки @{username}")
        except Exception as e:
            print(f"Ошибка отправки уведомления админу о завершении подписки @{username}: {e}")
    except Exception as e:
        print(f"Ошибка завершения подписки для {user_id}: {e}")
        bot.send_message(ADMIN_ID, f"⚠️ Ошибка завершения подписки @{username}: {e}. Проверь вручную.")
    finally:
        if conn:
            conn.close()

def check_subscriptions():
    try:
        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        c.execute("SELECT user_id, username, end_date, reminder_sent_1day, reminder_sent_10min FROM subscriptions")
        subscriptions = c.fetchall()
        now = datetime.now()
        print(f"Проверка подписок на {now}: {len(subscriptions)} записей")
        for user_id, username, end_date, reminder_sent_1day, reminder_sent_10min in subscriptions:
            end_date_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
            time_left = end_date_dt - now
            print(f"Проверка пользователя @{username}: конец подписки {end_date}, осталось времени: {time_left}")

            if time_left <= timedelta(days=1) and time_left > timedelta(minutes=10) and reminder_sent_1day == 0:
                try:
                    bot.send_message(user_id, "Твоя подписка истекает через 1 день. Продли: /subscribe")
                    bot.send_message(ADMIN_ID, f"Подписка @{username} истекает через 1 день.")
                    c.execute("UPDATE subscriptions SET reminder_sent_1day = 1 WHERE user_id = ?", (user_id,))
                    conn.commit()
                except Exception as e:
                    print(f"Ошибка отправки напоминания за 1 день для @{username}: {e}")

            if time_left <= timedelta(minutes=10) and time_left > timedelta(seconds=0) and reminder_sent_10min == 0:
                try:
                    bot.send_message(user_id, "Твоя подписка истекает через 10 минут! Скорее продли: /subscribe")
                    bot.send_message(ADMIN_ID, f"Подписка @{username} истекает через 10 минут!")
                    c.execute("UPDATE subscriptions SET reminder_sent_10min = 1 WHERE user_id = ?", (user_id,))
                    conn.commit()
                except Exception as e:
                    print(f"Ошибка отправки напоминания за 10 минут для @{username}: {e}")

            if now >= end_date_dt:
                expire_subscription(user_id, username)

        # Проверка просроченных отклонённых заявок
        current_time = datetime.now().timestamp()
        for user_id, request_info in list(pending_requests.items()):
            username = request_info["username"]
            timestamp = request_info["timestamp"]
            time_passed = current_time - timestamp
            if time_passed >= 24 * 3600:  # Если прошло 24 часа, удаляем из pending_requests
                del pending_requests[user_id]
                print(f"Ограничение на 24 часа для @{username} снято")

        conn.close()
    except Exception as e:
        print(f"Ошибка проверки подписок: {e}")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        if message.chat.type == 'private':
            bot.reply_to(message, "Привет! Я бот 'Аудит на автопилоте'. Выбери действие:", reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, "Привет! Это канал 'Аудит на автопилоте'. Пиши мне в личку: @AuditAutopilotBot /subscribe.")
        print(f"Команда /start обработана для {message.from_user.username}")
    except Exception as e:
        print(f"Ошибка обработки /start: {e}")

def create_subscription_keyboard(user_id, username):
    keyboard = InlineKeyboardMarkup(row_width=4)
    for month in range(1, 13):
        keyboard.add(InlineKeyboardButton(f"{month} мес", callback_data=f"period_{user_id}_{month}"))
    keyboard.add(InlineKeyboardButton("Отклонить", callback_data=f"reject_{user_id}"))
    return keyboard

def process_payment(message):
    try:
        user_id = message.from_user.id
        text = message.text.strip()

        # Проверяем, является ли сообщение командой или текстом кнопки
        if text.startswith('/') or text in command_handlers:
            command = text.split()[0].lower() if text.startswith('/') else text
            if command in command_handlers:
                # Прерываем ожидание ника и снимаем флаг in_progress
                if user_id in in_progress:
                    del in_progress[user_id]
                print(f"Пользователь {user_id} отправил команду {command} во время ожидания ника, прерываем процесс")
                # Вызываем обработчик команды напрямую
                command_handlers[command](message)
                return

        # Проверяем формат никнейма
        if not text.startswith('@'):
            bot.reply_to(message, "Пожалуйста, укажи свой ник в формате @username (например, @AVIT0Master).")
            bot.register_next_step_handler(message, process_payment)
            return

        username = text[1:]  # Убираем @

        # Проверяем, есть ли предыдущие заявки
        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        c.execute("SELECT start_date FROM subscriptions WHERE user_id = ?", (user_id,))
        existing_subscription = c.fetchone()
        if existing_subscription:
            start_date = existing_subscription[0]
            bot.send_message(ADMIN_ID, f"Пользователь @{username} уже подавал заявку {start_date}.")
        else:
            c.execute("SELECT start_date FROM subscription_history WHERE user_id = ? ORDER BY start_date DESC LIMIT 1", (user_id,))
            previous_subscription = c.fetchone()
            if previous_subscription:
                start_date = previous_subscription[0]
                bot.send_message(ADMIN_ID, f"Пользователь @{username} уже подавал заявка {start_date} (история).")

        if add_subscription(user_id, username, months=1):
            bot.reply_to(message, "Подписка оформлена! Ожидай подтверждения оплаты от администратора.")
            keyboard = create_subscription_keyboard(user_id, username)
            bot.send_message(ADMIN_ID, f"@{username} оплатил подписку. Проверь оплату с комментарием 'Audit_@{username}'. Выбери период подписки:", reply_markup=keyboard)
        else:
            bot.reply_to(message, "Не удалось оформить подписку. Напиши @AVIT0Master для помощи.")
        
        # Снимаем флаг in_progress после успешной обработки
        if user_id in in_progress:
            del in_progress[user_id]
        print(f"Оплата обработана для @{username}")
        conn.close()
    except Exception as e:
        print(f"Ошибка обработки оплаты: {e}")
        bot.send_message(ADMIN_ID, f"⚠️ Ошибка обработки оплаты для user_id {user_id}: {e}")
        if user_id in in_progress:
            del in_progress[user_id]

@bot.message_handler(commands=['subscribe'])
def send_subscribe(message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        if not username:
            bot.reply_to(message, "У тебя нет ника (@username). Укажи его в настройках Telegram и попробуй снова.")
            return

        # Проверка, есть ли активная подписка
        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        c.execute("SELECT end_date FROM subscriptions WHERE user_id = ?", (user_id,))
        subscription = c.fetchone()
        if subscription:
            end_date = subscription[0]
            end_date_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
            now = datetime.now()
            if now < end_date_dt:
                bot.reply_to(message, f"У тебя уже есть активная подписка! Она действует до {end_date}. Если хочешь продлить, дождись окончания текущей подписки.")
                print(f"Пользователь @{username} пытался оформить подписку, но у него уже есть активная подписка до {end_date}")
                conn.close()
                return
        conn.close()

        # Проверка, если пользователь недавно подавал заявку и она была отклонена
        if user_id in pending_requests:
            last_request_time = pending_requests[user_id]["timestamp"]
            current_time = time.time()
            time_passed = current_time - last_request_time
            if time_passed < 24 * 3600:  # Если прошло менее 24 часов
                bot.reply_to(message, "Ты недавно подавал заявку, и она была отклонена. Следующая заявка возможна через 24 часа после последней попытки.")
                print(f"Пользователь @{username} пытался повторно отправить /subscribe, но прошло только {time_passed} секунд после отклонения")
                return

        # Проверка, находится ли пользователь в процессе подачи заявки
        if user_id in in_progress:
            print(f"Пользователь @{username} уже в процессе подачи заявки, игнорируем повторный /subscribe")
            return  # Игнорируем команду

        # Если все проверки пройдены, показываем предупреждение
        bot.reply_to(message, f"Внимательно проверь свой ник нейм перед отправкой. Ссылка выдаётся один раз. Твой ник нейм @{username}\n\n"
                              f"Оплати 500 рублей на карту: 4276 5201 1247 3919 с комментарием 'Audit_@{username}'. Пришли свой ник (например, @{username}).")
        
        # Помечаем, что пользователь в процессе подачи заявки
        in_progress[user_id] = True
        bot.register_next_step_handler(message, process_payment)
        print(f"Команда /subscribe обработана для {username}")
    except Exception as e:
        print(f"Ошибка обработки /subscribe: {e}")
        if user_id in in_progress:
            del in_progress[user_id]

@bot.callback_query_handler(func=lambda call: True)
def handle_subscription_period(call):
    try:
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Только администратор может подтверждать оплату.")
            return

        print(f"Получен callback: call.data = {call.data}")

        if not isinstance(call.data, str):
            print(f"Ошибка: call.data не является строкой: {call.data}")
            bot.answer_callback_query(call.id, "Некорректный запрос: данные повреждены.")
            return

        data = call.data.split('_')
        if len(data) < 2:
            print(f"Некорректный формат call.data: {call.data}")
            bot.answer_callback_query(call.id, "Некорректный запрос: недостаточно данных.")
            return

        action = data[0]
        user_id_str = data[1] if len(data) > 1 else None

        if not user_id_str or not user_id_str.isdigit():
            print(f"Некорректный user_id в call.data: {call.data}")
            bot.answer_callback_query(call.id, "Некорректный запрос: user_id не является числом.")
            return

        user_id = int(user_id_str)
        print(f"Обработка callback для user_id: {user_id}, action: {action}")

        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        c.execute("SELECT username, end_date FROM subscriptions WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        username = None
        end_date = None
        if result:
            username, end_date = result
            print(f"Найден пользователь: @{username}, end_date: {end_date}")
        else:
            print(f"Пользователь {user_id} не найден в базе подписок")
            if user_id in pending_requests:
                username = pending_requests[user_id]["username"]
            if not username:
                bot.answer_callback_query(call.id, "Пользователь не найден в подписках.")
                bot.delete_message(call.message.chat.id, call.message.message_id)
                conn.close()
                return

        if action == "reject":
            print(f"Отклонение оплаты для @{username}")
            bot.send_message(user_id, "Твоя оплата не подтверждена. Свяжитесь с @AVIT0Master.")
            bot.send_message(ADMIN_ID, f"Оплата для @{username} отклонена.")
            c.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
            conn.commit()
            # Добавляем пользователя в pending_requests, чтобы ограничить повторные заявки на 24 часа
            pending_requests[user_id] = {"username": username, "timestamp": time.time()}
            if user_id in in_progress:
                del in_progress[user_id]
            print(f"Оплата для @{username} отклонена, ограничение на 24 часа установлено")
        elif action == "period":
            if len(data) < 3 or not data[2].isdigit():
                print(f"Некорректный формат call.data для period: {call.data}")
                bot.answer_callback_query(call.id, "Некорректный запрос: отсутствует количество месяцев.")
                conn.close()
                return
            print(f"Подтверждение оплаты для @{username}")
            months = int(data[2])
            start_date = datetime.now()
            end_date = start_date + timedelta(days=30 * months)

            # Проверяем, есть ли уже запись в subscription_history с пересекающимся периодом
            c.execute("SELECT start_date, end_date FROM subscription_history WHERE user_id = ? ORDER BY start_date DESC LIMIT 1", (user_id,))
            existing_history = c.fetchone()
            if existing_history:
                existing_start = datetime.strptime(existing_history[0], '%Y-%m-%d %H:%M:%S')
                existing_end = datetime.strptime(existing_history[1], '%Y-%m-%d %H:%M:%S')
                if start_date <= existing_end:
                    # Если периоды пересекаются, обновляем существующую запись
                    c.execute("UPDATE subscription_history SET start_date = ?, end_date = ?, months = ? WHERE user_id = ? AND start_date = ?",
                              (start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'), months, user_id, existing_history[0]))
                    print(f"Обновлена существующая запись в subscription_history для @{username}")
                else:
                    # Если периоды не пересекаются, добавляем новую запись
                    c.execute(
                        "INSERT INTO subscription_history (user_id, username, start_date, end_date, months) VALUES (?, ?, ?, ?, ?)",
                        (user_id, username, start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'), months))
                    print(f"Добавлена новая запись в subscription_history для @{username}")
            else:
                # Если записей нет, добавляем новую
                c.execute(
                    "INSERT INTO subscription_history (user_id, username, start_date, end_date, months) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'), months))
                print(f"Добавлена новая запись в subscription_history для @{username}")

            # Обновляем текущую подписку
            link_expiry_date = start_date + timedelta(days=30 * months)
            link_expiry_timestamp = int(link_expiry_date.timestamp())
            channel_link = bot.create_chat_invite_link(CHANNEL_ID, member_limit=1, expire_date=link_expiry_timestamp, name=f"link_{user_id}_{int(start_date.timestamp())}").invite_link
            c.execute("UPDATE subscriptions SET start_date = ?, end_date = ?, reminder_sent_1day = 0, reminder_sent_10min = 0 WHERE user_id = ?",
                      (start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'), user_id))
            conn.commit()
            bot.send_message(ADMIN_ID, f"Пользователь @{username} получил ссылку на канал.")
            bot.send_message(user_id, f"Оплата подтверждена! Вступай в канал: {channel_link}")
            if user_id in in_progress:
                del in_progress[user_id]
            print(f"Одноразовая ссылка на канал выдана для @{username}, действует до {link_expiry_date}")
        else:
            print(f"Неизвестное действие в call.data: {action}")
            bot.answer_callback_query(call.id, "Некорректный запрос: неизвестное действие.")
            conn.close()
            return

        conn.close()
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Действие выполнено.")
    except Exception as e:
        print(f"Ошибка обработки callback: {e}")
        bot.send_message(ADMIN_ID, f"⚠️ Ошибка обработки callback для user_id {user_id if 'user_id' in locals() else 'не определён'}: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка. Проверьте логи.")

@bot.message_handler(commands=['premium'])
def send_premium(message):
    try:
        username = message.from_user.username or str(message.from_user.id)
        bot.reply_to(message, "Оплати 2000 рублей на номер карты 4276 5201 1247 3919. Пришли чек и текст объявления @AVIT0Master.")
        print(f"Команда /premium обработана для {username}")
    except Exception as e:
        print(f"Ошибка обработки /premium: {e}")

@bot.message_handler(commands=['stats'])
def send_stats(message):
    try:
        if message.from_user.id != ADMIN_ID:
            bot.reply_to(message, "Только администратор может видеть статистику.")
            return

        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        
        c.execute("SELECT user_id, start_date, end_date FROM subscriptions")
        active_subscriptions = c.fetchall()

        active_count = 0
        subscription_earnings = 0
        today = datetime.now()
        for sub in active_subscriptions:
            start_date = datetime.strptime(sub[1], '%Y-%m-%d %H:%M:%S')
            end_date = datetime.strptime(sub[2], '%Y-%m-%d %H:%M:%S')
            if today <= end_date:
                active_count += 1
                months_active = (end_date - start_date).days // 30
                subscription_earnings += 500 * months_active

        c.execute("SELECT start_date, months FROM subscription_history")
        history = c.fetchall()
        monthly_earnings = {}
        for entry in history:
            start_date = datetime.strptime(entry[0], '%Y-%m-%d %H:%M:%S')
            months = entry[1]
            earnings = 500 * months
            month_key = start_date.strftime('%Y-%m')
            if month_key in monthly_earnings:
                monthly_earnings[month_key] += earnings
            else:
                monthly_earnings[month_key] = earnings

        history_text = ""
        for month_key, earnings in sorted(monthly_earnings.items()):
            year, month = month_key.split('-')
            month_name = {
                '01': 'январь', '02': 'февраль', '03': 'март', '04': 'апрель',
                '05': 'май', '06': 'июнь', '07': 'июль', '08': 'август',
                '09': 'сентябрь', '10': 'октябрь', '11': 'ноябрь', '12': 'декабрь'
            }[month]
            history_text += f"- Доход за {month_name} {year}: {earnings} руб\n"

        bot.reply_to(message, f"Статистика:\n"
                              f"- Активных подписок: {active_count}\n"
                              f"- Заработок от подписок: {subscription_earnings} руб\n"
                              f"\nИстория доходов:\n{history_text}")
        print(f"Статистика отправлена админу")
        conn.close()
    except Exception as e:
        print(f"Ошибка обработки /stats: {e}")
        bot.send_message(ADMIN_ID, f"⚠️ Ошибка получения статистики: {e}")

@bot.message_handler(commands=['help'])
def send_help(message):
    try:
        bot.reply_to(message, "Вопросы? Пиши @AVIT0Master.")
        print(f"Команда /help обработана для {message.from_user.username}")
    except Exception as e:
        print(f"Ошибка обработки /help: {e}")

# Обработчик текстовых сообщений (для кнопок)
@bot.message_handler(content_types=['text'])
def handle_text(message):
    try:
        text = message.text
        if text in command_handlers:
            command_handlers[text](message)
    except Exception as e:
        print(f"Ошибка обработки текстового сообщения: {e}")

def schedule_subscription_check():
    while True:
        print("Запуск проверки подписок...")
        check_subscriptions()
        print("Проверка завершена, следующая через 5 минут")
        time.sleep(300)

try:
    print("Запускаем бота...")
    init_db()
    subscription_thread = Thread(target=schedule_subscription_check)
    subscription_thread.start()
    print("Бот запущен, настройка вебхука...")
    bot.remove_webhook()
    time.sleep(1)
    webhook_url = "https://auditbot.onrender.com/"
    bot.set_webhook(url=webhook_url)
    print(f"Вебхук установлен: {webhook_url}")
    keep_alive()
except Exception as e:
    print(f"Критическая ошибка запуска бота: {e}")