import telebot
from telebot import types
import requests
from requests.exceptions import Timeout
from bs4 import BeautifulSoup
import time
import threading
from datetime import datetime, timezone, timedelta

TOKEN = ''
URL = 'https://www.ege.spb.ru/result/index.php?mode=gia2026'

bot = telebot.TeleBot(TOKEN)

active_tasks = {}
current_subjects = {}

SUBJECTS_BY_DATE = {
    "9_june": ["Русский язык", "Русский язык (ГВЭ-9)"],
    "16_june": [
        "Физика", "Химия", "Информатика",
        "Биология", "История", "География",
        "Английский язык", "Немецкий язык", "Французский язык",
        "Обществознание", "Испанский язык", "Литература"
        ]
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1'
}

def get_moscow_time():
    tz_msk = timezone(timedelta(hours=3))
    return datetime.now(tz_msk).strftime("%H:%M:%S")

def get_current_statuses(subjects_to_check):
    try:
        response = requests.get(URL, headers=HEADERS, timeout=45)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        main_period = soup.find(id='w2')
        if main_period:
            rows = main_period.find_all('div', class_='row')
        else:
            rows = soup.find_all('div', class_='row')
            
        found_dict = {} 
        
        for row in rows:
            col_name = row.find('div', class_=lambda c: c and 'col-md-5' in c)
            col_status = row.find('div', class_=lambda c: c and 'col-md-7' in c)
            
            if col_name and col_status:
                subject_name = col_name.get_text(separator=" ", strip=True).replace('\xa0', ' ')
                status_text = col_status.get_text(separator=" ", strip=True).replace('\xa0', ' ')
                
                if any(m in status_text.lower() for m in ['февраля', 'марта', 'апреля', 'мая']):
                    continue
                    
                for sub in subjects_to_check:
                    if sub.lower() == subject_name.lower():
                        clean_status = status_text.replace('\n', ' ').strip()
                        found_dict[subject_name.lower()] = f"• <b>{subject_name}</b> — <i>{clean_status}</i>"
                        
        if not found_dict:
            return "❌ Предметы не найдены (страница скачана, но нужных строк нет)."
            
        return "\n".join(found_dict.values())

    except Timeout:
        return '⚠️ Сайт сильно перегружен и не отвечает (Таймаут). Бот попытается снова.'

    except Exception as e:
        return f"⚠️ Ошибка связи с сайтом: {e}"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("📅 9 июня (Русский язык)", callback_data="9_june")
    btn2 = types.InlineKeyboardButton("📅 16 июня (Информатика, Биология...)", callback_data="16_june")
    markup.add(btn1, btn2)
    
    bot.send_message(
        message.chat.id, 
        "Привет! Выбери дату экзамена. Я запущу фоновый мониторинг.", 
        reply_markup=markup
    )

def back_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_menu = types.InlineKeyboardButton("🏠 В меню", callback_data="menu")
    markup.add(btn_menu)
    return markup

def get_control_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_update = types.InlineKeyboardButton("🔄 Обновить", callback_data="update_status")
    btn_stop = types.InlineKeyboardButton("🛑 Остановить", callback_data="stop")
    btn_menu = types.InlineKeyboardButton("🏠 В меню", callback_data="menu")
    markup.add(btn_update, btn_stop)
    markup.add(btn_menu)
    return markup

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    chat_id = call.message.chat.id
    action = call.data
    
    if action == 'menu':
        active_tasks[chat_id] = False
        markup = types.InlineKeyboardMarkup(row_width=1)
        btn1 = types.InlineKeyboardButton("📅 9 июня (Русский язык)", callback_data="9_june")
        btn2 = types.InlineKeyboardButton("📅 16 июня (Информатика, Биология...)", callback_data="16_june")
        markup.add(btn1, btn2)
        
        bot.answer_callback_query(call.id, "Возвращаемся в меню...")
        
        bot.edit_message_text(
            "📋 <b>Главное меню</b>\nВыбери дату экзамена. Я запущу фоновый мониторинг.", 
            chat_id, 
            call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML"
        )
        return

    if action == "stop":
        active_tasks[chat_id] = False
        bot.answer_callback_query(call.id, "Останавливаю...")
        bot.edit_message_text(
            f"🛑 <b>Мониторинг остановлен.</b>\n🕒 Время остановки: {get_moscow_time()} (МСК)", 
            chat_id, 
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=back_menu()
        )
        return

    if action == "update_status":
        if not active_tasks.get(chat_id, False):
            bot.answer_callback_query(call.id, "Сначала запустите мониторинг!", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, "Обновляю данные с сайта...")
        
        subjects = current_subjects.get(chat_id, [])
        status_text = get_current_statuses(subjects)
        
        new_text = (
            f"✅ <b>Фоновый мониторинг активен</b>\n"
            f"🕒 Последнее обновление: {get_moscow_time()} (МСК)\n\n"
            f"<b>Текущие статусы:</b>\n{status_text}"
        )
        
        try:
            bot.edit_message_text(
                new_text, 
                chat_id, 
                call.message.message_id, 
                reply_markup=get_control_keyboard(),
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    if action in SUBJECTS_BY_DATE:
        active_tasks[chat_id] = False 
        time.sleep(1) 
        
        active_tasks[chat_id] = True
        subjects_to_check = SUBJECTS_BY_DATE[action]
        current_subjects[chat_id] = subjects_to_check
        
        bot.answer_callback_query(call.id, "Запускаю...")
        
        status_text = get_current_statuses(subjects_to_check)
        
        text = (
            f"✅ <b>Фоновый мониторинг запущен!</b>\n"
            f"Бот будет проверять сайт каждые 3 минуты.\n"
            f"🕒 Время запуска: {get_moscow_time()} (МСК)\n\n"
            f"<b>Текущие статусы:</b>\n{status_text}"
        )
        
        bot.send_message(chat_id, text, reply_markup=get_control_keyboard(), parse_mode="HTML")
        
        thread = threading.Thread(target=monitor_website, args=(chat_id, subjects_to_check))
        thread.start()

def monitor_website(chat_id, subjects_to_check):
    while active_tasks.get(chat_id, False):
        try:
            response = requests.get(URL, headers=HEADERS, timeout=45)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            main_period = soup.find(id='w2')
            if main_period:
                rows = main_period.find_all('div', class_='row')
            else:
                rows = soup.find_all('div', class_='row')
            
            found_dict = {}
            
            for row in rows:
                col_name = row.find('div', class_=lambda c: c and 'col-md-5' in c)
                col_status = row.find('div', class_=lambda c: c and 'col-md-7' in c)
                
                if col_name and col_status:
                    subject_name = col_name.get_text(separator=" ", strip=True).replace('\xa0', ' ')
                    status_text = col_status.get_text(separator=" ", strip=True).replace('\xa0', ' ')
                    
                    if any(m in status_text.lower() for m in ['февраля', 'марта', 'апреля', 'мая']):
                        continue
                        
                    for sub in subjects_to_check:
                        if sub.lower() == subject_name.lower():
                            found_dict[subject_name.lower()] = {
                                'name': subject_name,
                                'status': status_text
                            }
            
            for item in found_dict.values():
                if 'Обработка' not in item['status'] and 'Результаты размещены' in item['status']:
                    
                    bot.send_message(
                        chat_id, 
                        f"🚨 <b>Результаты!</b> 🚨\n"
                        f"Предмет: <b>{item['name']}</b>\n"
                        f"Статус: {item['status']}\n\n"
                        f"Скорее проверяй: {URL}", 
                        parse_mode="HTML"
                    )
                    active_tasks[chat_id] = False
                    break 
                
        except Exception:
            pass 
            
        for _ in range(36): 
            if not active_tasks.get(chat_id, False):
                break
            time.sleep(5)

if __name__ == '__main__':
    print("Бот запущен!")
    bot.infinity_polling()
