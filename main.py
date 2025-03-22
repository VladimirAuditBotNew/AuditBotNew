import telebot
from flask import Flask, request
from threading import Thread
import sqlite3
from datetime import datetime, timedelta
import time
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

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
GROUP_ID = "-1002605146277"  # ID группы
CHANNEL_ID = "-1002570139251"  # ID канала
ADMIN_ID = 5935811078  # Твой ID для уведомлений
GROUP_LINK = "https://t.me/+mkgmZ69oXJIzZTFi"  # Замени на реальную ссылку на группу

# Хранилище ссылок для аннулирования
pending_links = {}  # {user_id: {"link": invite_link, "time_issued": timestamp, "username": username, "attempts": int, "link_used": bool}}
# Хранилище заявок с таймстемпом
pending_requests = {}  # {user_id: {"username": username, "timestamp": timestamp}}
# Хранилище запросов на новую ссылку
pending_resend_requests = {}  # {user_id: {"username": username, "timestamp": timestamp}}

def init_db():
    try:
        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, username TEXT, start_date TEXT, end_date TEXT, 
                      invite_link_used INTEGER DEFAULT 0, added_to_channel INTEGER DEFAULT 0,
                      reminder_sent_1day INTEGER DEFAULT 0, reminder_sent_10min INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscription_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, 
                      start_date TEXT, end_date TEXT, months INTEGER)''')
        c.execute('''PRAGMA table_info(subscriptions)''')
        columns = [col[1] for col in c.fetchall()]
        if 'invite_link_used' not in columns:
            c.execute('''ALTER TABLE subscriptions ADD COLUMN invite_link_used INTEGER DEFAULT 0''')
        if 'added_to_channel' not in columns:
            c.execute('''ALTER TABLE subscriptions ADD COLUMN added_to_channel INTEGER DEFAULT 0''')
        if 'reminder_sent_1day' not in columns:
            c.execute('''ALTER TABLE subscriptions ADD COLUMN reminder_sent_1day INTEGER DEFAULT 0''')
        if 'reminder_sent_10min' not in columns:
            c.execute('''ALTER TABLE subscriptions ADD COLUMN reminder_sent_10min INTEGER DEFAULT 0''')
        conn.commit()
        conn.close()
        print("База данных инициализирована")
    except Exception as e:
        print(f"Ошибка инициализации базы данных: {e}")

def revoke_all_links():
    try:
        for user_id, link_info in list(pending_links.items()):
            try:
                bot.revoke_chat_invite_link(CHANNEL_ID, link_info["link"])
                print(f"Ссылка для @{link_info['username']} аннулирована при старте бота")
            except Exception as e:
                print(f"Ошибка аннулирования ссылки для @{link_info['username']}: {e}")
            del pending_links[user_id]
        print("Все старые ссылки аннулированы при старте бота")
    except Exception as e:
        print(f"Ошибка аннулирования всех ссылок при старте: {e}")

def add_subscription(user_id, username, months=1):
    try:
        start_date = datetime.now()
        end_date = start_date + timedelta(days=30 * months)
        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO subscriptions (user_id, username, start_date, end_date, invite_link_used, added_to_channel, reminder_sent_1day, reminder_sent_10min) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'), 0, 0, 0, 0))
        c.execute(
            "INSERT INTO subscription_history (user_id, username, start_date, end_date, months) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'), months))
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
            bot.send_message(ADMIN_ID, f"Подписка @{username} истекла. Удали его из канала и группы 'Аудит VIP'.")
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

        # Проверка просроченных ссылок
        current_time = datetime.now().timestamp()
        for user_id, link_info in list(pending_links.items()):
            username = link_info.get("username", "unknown")
            invite_link = link_info["link"]
            time_issued = link_info["time_issued"]
            time_passed = current_time - time_issued
            if time_passed >= 600:  # 10 минут — аннулирование
                try:
                    bot.revoke_chat_invite_link(CHANNEL_ID, invite_link)
                    bot.send_message(user_id, "Твоя ссылка истекла. Запроси новую: /resend_link")
                    print(f"Ссылка для @{username} аннулирована (прошло 10 минут с момента выдачи)")
                    del pending_links[user_id]
                except Exception as e:
                    print(f"Ошибка аннулирования ссылки для @{username}: {e}")

        # Проверка просроченных заявок
        current_time = datetime.now().timestamp()
        for user_id, request_info in list(pending_requests.items()):
            username = request_info["username"]
            timestamp = request_info["timestamp"]
            time_passed = current_time - timestamp
            if time_passed >= 24 * 3600:  # Каждые 24 часа
                bot.send_message(ADMIN_ID, f"⏰ Напоминание: обработайте заявку для @{username}. Прошло {int(time_passed // (24 * 3600))} дн.")
                pending_requests[user_id]["timestamp"] = current_time

        # Проверка запросов на новую ссылку
        for user_id, request_info in list(pending_resend_requests.items()):
            username = request_info["username"]
            timestamp = request_info["timestamp"]
            time_passed = current_time - timestamp
            if time_passed >= 24 * 3600:  # Каждые 24 часа
                bot.send_message(ADMIN_ID, f"⏰ Напоминание: обработайте запрос на новую ссылку для @{username}. Прошло {int(time_passed // (24 * 3600))} дн.")
                pending_resend_requests[user_id]["timestamp"] = current_time

        conn.close()
    except Exception as e:
        print(f"Ошибка проверки подписок: {e}")

@bot.message_handler(content_types=['new_chat_members'])
def handle_new_chat_member(update):
    try:
        chat_id = update.chat.id
        if str(chat_id) == CHANNEL_ID:
            user_id = update.from_user.id
            username = update.from_user.username or str(user_id)
            print(f"Пользователь @{username} вступил в канал")
            conn = sqlite3.connect('subscriptions.db')
            c = conn.cursor()
            c.execute("SELECT username FROM subscriptions WHERE user_id = ?", (user_id,))
            result = c.fetchone()
            if result:
                db_username = result[0]
                if user_id in pending_links:
                    link_info = pending_links[user_id]
                    invite_link = link_info["link"]
                    time_issued = link_info["time_issued"]
                    time_passed = datetime.now().timestamp() - time_issued
                    if time_passed < 600:  # Если прошло меньше 10 минут
                        time_to_wait = 600 - time_passed
                        print(f"Ожидание {time_to_wait} секунд перед аннулированием ссылки для @{username}")
                        time.sleep(time_to_wait)
                    bot.revoke_chat_invite_link(CHANNEL_ID, invite_link)
                    print(f"Ссылка для @{username} аннулирована после вступления")
                    pending_links[user_id]["link_used"] = True  # Отмечаем, что ссылка использована
                    # Обновляем статус в базе данных (оставляем для совместимости)
                    c.execute("UPDATE subscriptions SET added_to_channel = 1, invite_link_used = 1 WHERE user_id = ?", (user_id,))
                    conn.commit()
                    print(f"Обновлены данные для @{username}: added_to_channel = 1, invite_link_used = 1")
                    # Отправляем ссылку на группу
                    bot.send_message(user_id, f"Ты успешно вступил в канал! Теперь подай заявку в группу 'Аудит VIP': {GROUP_LINK}")
            else:
                print(f"Пользователь @{username} не найден в базе подписок, удаление из канала")
                try:
                    bot.ban_chat_member(CHANNEL_ID, user_id)
                    bot.unban_chat_member(CHANNEL_ID, user_id)  # Это удаляет пользователя
                except Exception as e:
                    print(f"Ошибка удаления @{username} из канала: {e}")
            conn.close()
    except Exception as e:
        print(f"Ошибка обработки вступления в канал: {e}")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        if message.chat.type == 'private':
            bot.reply_to(message, "Привет! Я бот 'Аудит на автопилоте'. Выбери: /subscribe — подписка 500 руб/мес, /premium — личный аудит 2000 руб, /stats — статистика, /help — помощь.")
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

def create_resend_link_keyboard(user_id, username):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("Подтвердить", callback_data=f"approve_resend_{user_id}"))
    keyboard.add(InlineKeyboardButton("Отклонить", callback_data=f"reject_resend_{user_id}"))
    return keyboard

def process_payment(message):
    try:
        user_id = message.from_user.id
        username = message.text.strip()
        if not username.startswith('@'):
            bot.reply_to(message, "Пожалуйста, укажи свой ник в формате @username (например, @AVIT0Master).")
            return
        username = username[1:]
        if add_subscription(user_id, username, months=1):
            bot.reply_to(message, "Подписка оформлена! Ожидай подтверждения оплаты от администратора.")
            pending_requests[user_id] = {"username": username, "timestamp": time.time()}
            keyboard = create_subscription_keyboard(user_id, username)
            bot.send_message(ADMIN_ID, f"@{username} оплатил подписку. Проверь оплату с комментарием 'Audit_@{username}'. Выбери период подписки:", reply_markup=keyboard)
        else:
            bot.reply_to(message, "Не удалось оформить подписку. Напиши @AVIT0Master для помощи.")
        print(f"Оплата обработана для @{username}")
    except Exception as e:
        print(f"Ошибка обработки оплаты: {e}")
        bot.send_message(ADMIN_ID, f"⚠️ Ошибка обработки оплаты для @{username}: {e}")

@bot.message_handler(commands=['subscribe'])
def send_subscribe(message):
    try:
        username = message.from_user.username
        if not username:
            bot.reply_to(message, "У тебя нет ника (@username). Укажи его в настройках Telegram и попробуй снова.")
            return
        bot.reply_to(message, f"Оплати 500 рублей на карту: 4276 5201 1247 3919 с комментарием 'Audit_@{username}'. Пришли свой ник (например, @{username}).")
        bot.register_next_step_handler(message, process_payment)
        print(f"Команда /subscribe обработана для {username}")
    except Exception as e:
        print(f"Ошибка обработки /subscribe: {e}")

@bot.callback_query_handler(func=lambda call: True)
def handle_subscription_period(call):
    try:
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Только администратор может подтверждать оплату.")
            return

        data = call.data.split('_')
        action = data[0]
        if len(data) < 2 or not data[1].isdigit():
            bot.answer_callback_query(call.id, "Некорректный запрос.")
            return

        user_id = int(data[1])

        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        c.execute("SELECT username, invite_link_used FROM subscriptions WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        if not result:
            bot.answer_callback_query(call.id, "Пользователь не найден в подписках.")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            return

        username, invite_link_used = result

        if action == "reject":
            bot.send_message(user_id, "Твоя оплата не подтверждена. Свяжитесь с @AVIT0Master.")
            bot.send_message(ADMIN_ID, f"Оплата для @{username} отклонена.")
            c.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
            conn.commit()
            if user_id in pending_requests:
                del pending_requests[user_id]
            print(f"Оплата для @{username} отклонена")
        elif action == "period":
            months = int(data[2])
            if invite_link_used == 1:
                bot.send_message(ADMIN_ID, f"@{username} уже использовал одноразовую ссылку. Если нужно обновить доступ, попроси его оплатить заново: /subscribe")
                bot.delete_message(call.message.chat.id, call.message.message_id)
                return

            start_date = datetime.now()
            end_date = start_date + timedelta(days=30 * months)
            c.execute("UPDATE subscriptions SET start_date = ?, end_date = ?, reminder_sent_1day = 0, reminder_sent_10min = 0 WHERE user_id = ?",
                      (start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'), user_id))
            c.execute(
                "INSERT INTO subscription_history (user_id, username, start_date, end_date, months) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'), months))
            channel_link = bot.create_chat_invite_link(CHANNEL_ID, member_limit=1).invite_link
            c.execute("UPDATE subscriptions SET added_to_channel = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            pending_links[user_id] = {
                "link": channel_link,
                "time_issued": datetime.now().timestamp(),
                "username": username,
                "attempts": 0,
                "link_used": False
            }
            bot.send_message(ADMIN_ID, f"Оплата для @{username} подтверждена на {months} месяцев (до {end_date.strftime('%Y-%m-%d %H:%M:%S')}). Ссылка на канал отправлена пользователю.")
            bot.send_message(user_id, f"Твоя оплата подтверждена! Вступай в канал: {channel_link}\nСсылка активна 10 минут.")
            if user_id in pending_requests:
                del pending_requests[user_id]
            print(f"Одноразовая ссылка на канал выдана для @{username}")
        elif action == "approve_resend":
            if user_id in pending_links:
                bot.revoke_chat_invite_link(CHANNEL_ID, pending_links[user_id]["link"])
                print(f"Старая ссылка для @{username} аннулирована перед выдачей новой")
                del pending_links[user_id]
            channel_link = bot.create_chat_invite_link(CHANNEL_ID, member_limit=1).invite_link
            pending_links[user_id] = {
                "link": channel_link,
                "time_issued": datetime.now().timestamp(),
                "username": username,
                "attempts": pending_links.get(user_id, {}).get("attempts", 0) + 1,
                "link_used": False
            }
            bot.send_message(user_id, f"Новая ссылка выдана: {channel_link}\nСсылка активна 10 минут.")
            bot.send_message(ADMIN_ID, f"Новая ссылка выдана для @{username}.")
            if user_id in pending_resend_requests:
                del pending_resend_requests[user_id]
            print(f"Новая ссылка выдана для @{username} после подтверждения")
        elif action == "reject_resend":
            bot.send_message(user_id, "Запрос на новую ссылку отклонён. Свяжитесь с @AVIT0Master.")
            bot.send_message(ADMIN_ID, f"Запрос на новую ссылку для @{username} отклонён.")
            if user_id in pending_resend_requests:
                del pending_resend_requests[user_id]
            print(f"Запрос на новую ссылку для @{username} отклонён")

        conn.close()
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Действие выполнено.")
    except Exception as e:
        print(f"Ошибка обработки периода подписки: {e}")
        bot.send_message(ADMIN_ID, f"⚠️ Ошибка обработки периода подписки для @{username}: {e}")

@bot.message_handler(commands=['premium'])
def send_premium(message):
    try:
        username = message.from_user.username or str(message.from_user.id)
        bot.reply_to(message, "Оплати 2000 рублей на карту: 4276 5201 1247 3919. Пришли чек и текст объявления.")
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
        
        # Текущие активные подписки
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

        # История доходов по месяцам
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

@bot.message_handler(commands=['resend_link'])
def resend_link(message):
    try:
        user_id = message.from_user.id
        conn = sqlite3.connect('subscriptions.db')
        c = conn.cursor()
        c.execute("SELECT username, invite_link_used FROM subscriptions WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        if not result:
            bot.reply_to(message, "У тебя нет активной подписки. Оплати: /subscribe")
            return
        username, invite_link_used = result
        if invite_link_used == 1:
            bot.reply_to(message, "Ты уже использовал одноразовую ссылку. Оплати заново: /subscribe")
            return

        if user_id in pending_resend_requests:
            bot.reply_to(message, "Твой запрос на новую ссылку уже отправлен. Ожидай подтверждения от администратора.")
            return

        daily_attempts = sum(1 for user, info in pending_links.items() if info["username"] == username and (datetime.now().timestamp() - info["time_issued"]) < 24 * 3600)
        if daily_attempts >= 2:
            bot.reply_to(message, "Превышен лимит попыток (2 раза в сутки). Обратитесь к @AVIT0Master.")
            return

        pending_resend_requests[user_id] = {
            "username": username,
            "timestamp": datetime.now().timestamp()
        }
        keyboard = create_resend_link_keyboard(user_id, username)
        bot.reply_to(message, "Запрос на новую ссылку отправлен администратору. Ожидай подтверждения.")
        bot.send_message(ADMIN_ID, f"@{username} запросил новую ссылку для доступа к каналу. Подтвердить?", reply_markup=keyboard)
        print(f"Запрос на новую ссылку отправлен админу для @{username}")
        conn.close()
    except Exception as e:
        print(f"Ошибка обработки /resend_link для @{username}: {e}")
        bot.send_message(ADMIN_ID, f"⚠️ Ошибка обработки /resend_link для @{username}: {e}")

@bot.message_handler(commands=['revoke_all_links'])
def revoke_all_links_command(message):
    try:
        if message.from_user.id != ADMIN_ID:
            bot.reply_to(message, "Только администратор может аннулировать все ссылки.")
            return

        for user_id, link_info in list(pending_links.items()):
            try:
                bot.revoke_chat_invite_link(CHANNEL_ID, link_info["link"])
                print(f"Ссылка для @{link_info['username']} аннулирована администратором")
            except Exception as e:
                print(f"Ошибка аннулирования ссылки для @{link_info['username']}: {e}")
            del pending_links[user_id]
        bot.reply_to(message, "Все активные ссылки аннулированы.")
        print("Все ссылки аннулированы администратором")
    except Exception as e:
        print(f"Ошибка обработки /revoke_all_links: {e}")
        bot.send_message(ADMIN_ID, f"⚠️ Ошибка аннулирования всех ссылок: {e}")

def schedule_subscription_check():
    while True:
        print("Запуск проверки подписок...")
        check_subscriptions()
        print("Проверка завершена, следующая через 5 минут")
        time.sleep(300)

try:
    print("Запускаем бота...")
    init_db()
    revoke_all_links()
    subscription_thread = Thread(target=schedule_subscription_check)
    subscription_thread.start()
    print("Бот запущен, настройка вебхука...")
    # Настройка вебхука
    bot.remove_webhook()  # Удаляем старый вебхук, если есть
    time.sleep(1)
    webhook_url = "https://auditbot.onrender.com/"
    bot.set_webhook(url=webhook_url)
    print(f"Вебхук установлен: {webhook_url}")
    keep_alive()  # Запускаем Flask-сервер
except Exception as e:
    print(f"Критическая ошибка запуска бота: {e}")