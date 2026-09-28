import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import logging
import threading
import re
import sys
import atexit
import requests
import json
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I am ADITYA HOSTING BOT"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive server started.")

# --- TUMHARI SETTINGS ---
TOKEN = os.getenv('BOT_TOKEN', '8692170870:AAGB0eUdy5-5fgHrP4dJLiSSaiIxOqBN82E')
OWNER_ID = int(os.getenv('OWNER_ID', '8725461956'))
ADMIN_ID = int(os.getenv('ADMIN_ID', '8725461956'))
DUMP_CHANNEL = int(os.getenv('DUMP_CHANNEL', '-1003977505145')) 
YOUR_USERNAME = os.getenv('OWNER_USERNAME', '@Aditya_dark0')
UPDATE_CHANNEL = os.getenv('UPDATE_CHANNEL', 'https://t.me/AdityaXcyber')
# ------------------------

PLANS = {
    'Free': {'files': 1, 'storage_mb': 200},
    'Baby': {'files': 4, 'storage_mb': 300},
    'Basic': {'files': 8, 'storage_mb': 800},
    'Premium': {'files': 20, 'storage_mb': 1200},
    'God': {'files': 50, 'storage_mb': 1600},
    'Ultimate': {'files': 150, 'storage_mb': 3000},
    'Lifetime': {'files': float('inf'), 'storage_mb': float('inf')}
}

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')
os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
bot_locked = False
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
banned_users = set()
DB_LOCK = threading.Lock()

def init_db():
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, expiry TEXT, plan_name TEXT DEFAULT 'Premium')''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files (user_id INTEGER, file_name TEXT, file_type TEXT, PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER PRIMARY KEY, join_date TEXT, last_seen TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_by INTEGER, added_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY, reason TEXT, banned_by INTEGER, ban_date TEXT)''')
        
        # New Tables for Virtual Quota System (VQS)
        c.execute('''CREATE TABLE IF NOT EXISTS global_modules (module_name TEXT PRIMARY KEY, size_mb REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_modules (user_id INTEGER, module_name TEXT, PRIMARY KEY (user_id, module_name))''')
        
        c.execute('INSERT OR IGNORE INTO admins VALUES (?, ?, ?)', (OWNER_ID, OWNER_ID, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

def load_data():
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT user_id, expiry, plan_name FROM subscriptions')
        for uid, exp, plan in c.fetchall():
            user_subscriptions[uid] = {'expiry': datetime.fromisoformat(exp), 'plan_name': plan}
        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for uid, fn, ft in c.fetchall(): user_files.setdefault(uid, []).append((fn, ft))
        c.execute('SELECT user_id FROM active_users')
        active_users.update(u for (u,) in c.fetchall())
        c.execute('SELECT user_id FROM admins')
        admin_ids.update(u for (u,) in c.fetchall())
        c.execute('SELECT user_id FROM banned_users')
        banned_users.update(u for (u,) in c.fetchall())
        conn.close()
    except: pass

init_db()
load_data()

def get_dir_size(path):
    total = 0
    if not os.path.exists(path): return 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp): total += os.path.getsize(fp)
    return total / (1024 * 1024)

# --- VIRTUAL QUOTA SYSTEM (VQS) ---
def add_to_user_quota(user_id, module_name, is_node=False):
    module_name = module_name.lower().strip()
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT size_mb FROM global_modules WHERE module_name = ?', (module_name,))
        row = c.fetchone()
        size_mb = 0
        
        if row:
            size_mb = row[0]
        else:
            # Measure actual size of globally installed package
            if not is_node:
                res = subprocess.run([sys.executable, '-m', 'pip', 'show', module_name], capture_output=True, text=True)
                loc = None
                for line in res.stdout.split('\n'):
                    if line.startswith('Location:'):
                        loc = line.split(':', 1)[1].strip()
                        break
                if loc:
                    pkg_dir = os.path.join(loc, module_name.replace('-', '_'))
                    if not os.path.exists(pkg_dir): pkg_dir = os.path.join(loc, module_name)
                    if os.path.exists(pkg_dir): size_mb = get_dir_size(pkg_dir)
            else:
                try:
                    npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
                    pkg_dir = os.path.join(npm_root, module_name)
                    if os.path.exists(pkg_dir): size_mb = get_dir_size(pkg_dir)
                except: pass
                
            if size_mb <= 0: size_mb = 3.5 # Standard fallback MB if measuring fails
            c.execute('INSERT OR REPLACE INTO global_modules VALUES (?, ?)', (module_name, size_mb))
            
        c.execute('INSERT OR IGNORE INTO user_modules VALUES (?, ?)', (user_id, module_name))
        conn.commit()
        conn.close()

def get_user_virtual_storage(user_id):
    physical_size = get_dir_size(get_user_folder(user_id))
    virtual_size = 0.0
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT m.size_mb FROM user_modules u JOIN global_modules m ON u.module_name = m.module_name WHERE u.user_id = ?', (user_id,))
        for row in c.fetchall():
            virtual_size += row[0]
        conn.close()
    return physical_size + virtual_size

def get_user_plan(user_id):
    if user_id == OWNER_ID or user_id in admin_ids: return PLANS['Lifetime']
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return PLANS.get(user_subscriptions[user_id].get('plan_name', 'Premium'), PLANS['Premium'])
    return PLANS['Free']

def enforce_storage_limit(user_id):
    plan = get_user_plan(user_id)
    limit_mb = plan['storage_mb']
    total_used = get_user_virtual_storage(user_id)
    
    if total_used > limit_mb:
        for fn, _ in user_files.get(user_id, []).copy():
            sk = f"{user_id}_{fn}"
            if sk in bot_scripts:
                kill_process_tree(bot_scripts[sk])
                del bot_scripts[sk]
        
        user_folder = get_user_folder(user_id)
        shutil.rmtree(user_folder, ignore_errors=True)
        os.makedirs(user_folder, exist_ok=True)
        if user_id in user_files: del user_files[user_id]
        
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            conn.execute('DELETE FROM user_files WHERE user_id = ?', (user_id,))
            conn.execute('DELETE FROM user_modules WHERE user_id = ?', (user_id,)) # Clear their quota
            conn.commit()
            conn.close()
            
        try: bot.send_message(user_id, f"⚠️ *Storage Limit Exceeded!*\nAapka total usage (Files + Modules) {limit_mb}MB cross kar gaya. System clear kar diya gaya hai.", parse_mode='Markdown')
        except: pass
        return False
    return True

def storage_monitor_loop():
    while True:
        for user_id in list(active_users):
            enforce_storage_limit(user_id)
        time.sleep(60)

threading.Thread(target=storage_monitor_loop, daemon=True).start()

def get_user_folder(user_id):
    folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    if script_key in bot_scripts and bot_scripts[script_key].get('process'):
        try: return psutil.Process(bot_scripts[script_key]['process'].pid).is_running()
        except: pass
    return False

def kill_process_tree(process_info):
    try:
        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
            parent = psutil.Process(process.pid)
            for child in parent.children(recursive=True): child.kill()
            parent.kill()
    except: pass

def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.execute('INSERT OR REPLACE INTO user_files VALUES (?, ?, ?)', (user_id, file_name, file_type)).connection.commit()
        conn.close()
        if user_id not in user_files: user_files[user_id] = []
        user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
        user_files[user_id].append((file_name, file_type))

def check_code_security(file_path, file_type):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
        malicious_patterns = [r'rm\s+-rf\s+/', r'os\.remove\s*\(\s*[\'"]/', r'curl\s+.*\|\s*sh']
        if any(re.search(p, content, re.I) for p in malicious_patterns):
            return False, "Malicious patterns found", 'malicious'
        return True, "Clean", 'clean'
    except Exception: return False, "Scan failed", 'malicious'

def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL),
        types.InlineKeyboardButton('📤 Upload File', callback_data='upload'),
        types.InlineKeyboardButton('📂 Check Files', callback_data='check_files'),
        types.InlineKeyboardButton('📊 Storage Details', callback_data='stats'),
        types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}')
    ]
    if user_id in admin_ids:
        markup.add(*buttons[:2])
        markup.add(buttons[2], buttons[3])
        markup.add(types.InlineKeyboardButton('💳 Manage Subs', callback_data='subscription'))
        markup.add(types.InlineKeyboardButton('👑 Admin Panel', callback_data='admin_panel'), buttons[4])
    else:
        markup.add(*buttons)
    return markup

def run_script(script_path, owner_id, user_folder, file_name, msg_obj, attempt=1):
    if attempt > 3:
        bot.send_message(msg_obj.chat.id, f"❌ Failed to start `{file_name}` after multiple auto-install attempts.")
        return

    check_proc = None
    env = os.environ.copy()
    try:
        npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
        env['NODE_PATH'] = npm_root
    except: pass

    try:
        if script_path.endswith('.py'):
            check_proc = subprocess.Popen([sys.executable, script_path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        else:
            check_proc = subprocess.Popen(['node', script_path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        
        stdout, stderr = check_proc.communicate(timeout=5)
        
        if check_proc.returncode != 0 and stderr:
            module_name = None
            if script_path.endswith('.py'):
                match = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                if match: module_name = match.group(1).strip().strip("'\"")
            else:
                match = re.search(r"Cannot find module '(.+?)'", stderr)
                if match: module_name = match.group(1).strip().strip("'\"")

            if module_name and not module_name.startswith('.') and not module_name.startswith('/'):
                bot.send_message(msg_obj.chat.id, f"🔄 Auto-installing `{module_name}`...\n*(System space saved, par virtual MBs tumhare account mein jod diye jayenge)*", parse_mode='Markdown')
                st_time = time.time()
                
                # GLOBAL INSTALL TO SAVE RAILWAY SPACE
                if script_path.endswith('.py'):
                    subprocess.run([sys.executable, '-m', 'pip', 'install', module_name], check=False)
                    add_to_user_quota(owner_id, module_name, is_node=False)
                else:
                    subprocess.run(['npm', 'install', '-g', module_name], check=False)
                    add_to_user_quota(owner_id, module_name, is_node=True)
                
                tt = round(time.time() - st_time, 2)
                used_mb = get_user_virtual_storage(owner_id)
                bot.send_message(msg_obj.chat.id, f"✅ `{module_name}` mapped in {tt}s.\n💾 Storage Used: **{used_mb:.2f} MB**", parse_mode='Markdown')
                
                if not enforce_storage_limit(owner_id): return
                return run_script(script_path, owner_id, user_folder, file_name, msg_obj, attempt + 1)
            else:
                bot.send_message(msg_obj.chat.id, f"❌ Code Error:\n```\n{stderr[:500]}\n```", parse_mode='Markdown')
                return

        # Start Actual Background Process
        if script_path.endswith('.py'):
            proc = subprocess.Popen([sys.executable, script_path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            proc = subprocess.Popen(['node', script_path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        
        bot_scripts[f"{owner_id}_{file_name}"] = {'process': proc, 'file_name': file_name}
        bot.send_message(msg_obj.chat.id, f"✅ Successfully Started `{file_name}`!")

    except subprocess.TimeoutExpired:
        if check_proc and check_proc.poll() is None: check_proc.kill()
        
        if script_path.endswith('.py'):
            proc = subprocess.Popen([sys.executable, script_path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            proc = subprocess.Popen(['node', script_path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        
        bot_scripts[f"{owner_id}_{file_name}"] = {'process': proc, 'file_name': file_name}
        bot.send_message(msg_obj.chat.id, f"✅ Successfully Started `{file_name}`!")
    except Exception as e:
        bot.send_message(msg_obj.chat.id, f"❌ Failed to start: {e}")

@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if uid in banned_users: return bot.reply_to(message, "❌ Banned.")
    if uid not in active_users:
        active_users.add(uid)
        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute('INSERT OR REPLACE INTO active_users VALUES (?, ?, ?)', (uid, datetime.now().isoformat(), datetime.now().isoformat())).connection.commit()
    bot.reply_to(message, f"Welcome to Aditya Hosting Bot!\nUpload files and let us handle everything automatically.", reply_markup=create_main_menu_inline(uid))

@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    if user_id in banned_users: return bot.reply_to(message, "❌ Banned.")
    if not enforce_storage_limit(user_id): return
    
    doc = message.document
    file_name = doc.file_name
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py', '.js', '.zip']: return bot.reply_to(message, "⚠️ Only .py, .js, .zip files allowed.")

    try: bot.forward_message(DUMP_CHANNEL, message.chat.id, message.message_id)
    except: pass

    wait = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
    file_info = bot.get_file(doc.file_id)
    downloaded = bot.download_file(file_info.file_path)
    
    user_folder = get_user_folder(user_id)
    
    if file_ext == '.zip':
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, file_name)
        with open(zip_path, 'wb') as f: f.write(downloaded)
        
        bot.edit_message_text(f"✅ Extracting & Reading Code...", message.chat.id, wait.message_id)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(user_folder)
        shutil.rmtree(temp_dir)
        
        # Parse requirements.txt globally and add to user quota
        req_path = os.path.join(user_folder, 'requirements.txt')
        if os.path.exists(req_path):
            bot.edit_message_text(f"🔄 Mapping requirements globally...", message.chat.id, wait.message_id)
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', req_path], check=False)
            with open(req_path, 'r') as f:
                for line in f:
                    mod = re.split('>=|==|<=', line.strip())[0].strip()
                    if mod: add_to_user_quota(user_id, mod, False)

        # Parse package.json globally and add to user quota
        pkg_path = os.path.join(user_folder, 'package.json')
        if os.path.exists(pkg_path):
            bot.edit_message_text(f"🔄 Mapping node modules globally...", message.chat.id, wait.message_id)
            try:
                with open(pkg_path, 'r') as f:
                    deps = json.load(f).get('dependencies', {})
                    for dep in deps:
                        subprocess.run(['npm', 'install', '-g', dep], check=False)
                        add_to_user_quota(user_id, dep, True)
            except: pass

        main_script = None
        for f in os.listdir(user_folder):
            if f in ['main.py', 'bot.py', 'index.js', 'server.js']:
                main_script = f
                break
        
        if not enforce_storage_limit(user_id): return
        
        if main_script:
            save_user_file(user_id, main_script, 'py' if main_script.endswith('.py') else 'js')
            bot.edit_message_text(f"🚀 Preparing to start...", message.chat.id, wait.message_id)
            run_script(os.path.join(user_folder, main_script), user_id, user_folder, main_script, message)
        return

    # Single file
    temp_path = os.path.join(user_folder, f"_scan_{file_name}")
    with open(temp_path, 'wb') as f: f.write(downloaded)
    is_safe, reason, sev = check_code_security(temp_path, file_ext)
    if not is_safe:
        os.remove(temp_path)
        bot.edit_message_text(f"❌ Rejected: {reason}", message.chat.id, wait.message_id)
        return

    final_path = os.path.join(user_folder, file_name)
    shutil.move(temp_path, final_path)
    save_user_file(user_id, file_name, file_ext[1:])
    
    if not enforce_storage_limit(user_id): return
    bot.edit_message_text(f"✅ Executing script...", message.chat.id, wait.message_id)
    run_script(final_path, user_id, user_folder, file_name, message)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    data = call.data
    user_id = call.from_user.id
    
    if data == 'stats':
        if user_id in admin_ids:
            disk = psutil.disk_usage('/')
            total_gb = disk.total / (1024**3)
            used_gb = disk.used / (1024**3)
            free_gb = disk.free / (1024**3)
            
            msg = f"👑 **Admin Server Stats**\n\n"
            msg += f"💽 Total Server Disk: `{total_gb:.2f} GB`\n"
            msg += f"💾 Used Server Disk: `{used_gb:.2f} GB`\n"
            msg += f"🟢 Free Server Disk: `{free_gb:.2f} GB`\n"
            msg += f"👥 Total Users: `{len(active_users)}`\n"
            msg += f"🤖 Bots Running: `{len(bot_scripts)}`"
        else:
            plan = get_user_plan(user_id)
            limit_mb = plan['storage_mb']
            used_mb = get_user_virtual_storage(user_id)
            plan_name = user_subscriptions.get(user_id, {}).get('plan_name', 'Free') if user_id not in admin_ids else 'Lifetime'
            
            msg = f"📊 **Your Storage Details**\n\n"
            msg += f"📦 Current Plan: **{plan_name}**\n"
            msg += f"💾 Quota Used: **{used_mb:.2f} MB**\n"
            msg += f"📈 Quota Limit: **{limit_mb} MB**\n\n"
            msg += f"*(Isme physical files aur aapke mapped python/node modules dono ka MB account kiya gaya hai)*"
            
        bot.answer_callback_query(call.id)
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(user_id), parse_mode='Markdown')

    elif data == 'check_files':
        files_list = user_files.get(user_id, [])
        if not files_list: return bot.answer_callback_query(call.id, "⚠️ No files uploaded.", show_alert=True)
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        for fn, ft in sorted(files_list):
            status = "🟢 Running" if is_bot_running(user_id, fn) else "🔴 Stopped"
            markup.add(types.InlineKeyboardButton(f"{fn} - {status}", callback_data=f'noop'))
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_main'))
        bot.edit_message_text("📂 Your uploaded files:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data == 'back_main':
        bot.edit_message_text("Welcome back!", call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))

    elif data == 'subscription' and user_id in admin_ids:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("➕ Add Sub", callback_data='add_sub'))
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_main'))
        bot.edit_message_text("💳 Manage Subscriptions", call.message.chat.id, call.message.message_id, reply_markup=markup)
        
    elif data == 'add_sub' and user_id in admin_ids:
        msg = bot.send_message(call.message.chat.id, "Send User ID:")
        bot.register_next_step_handler(msg, step_sub_user_id)
        
    elif data.startswith('setplan_') and user_id in admin_ids:
        _, uid, plan = data.split('_')
        msg = bot.send_message(call.message.chat.id, f"Plan {plan} for {uid}. Enter validity (days):")
        bot.register_next_step_handler(msg, step_sub_days, int(uid), plan)

def step_sub_user_id(message):
    try: uid = int(message.text)
    except: return bot.reply_to(message, "Invalid ID.")
    markup = types.InlineKeyboardMarkup()
    for plan in PLANS.keys():
        if plan != 'Free': markup.add(types.InlineKeyboardButton(plan, callback_data=f"setplan_{uid}_{plan}"))
    bot.reply_to(message, "Select Plan:", reply_markup=markup)

def step_sub_days(message, uid, plan):
    try: days = int(message.text)
    except: return bot.reply_to(message, "Invalid days.")
    save_subscription(uid, datetime.now() + timedelta(days=days), plan)
    bot.reply_to(message, f"✅ User `{uid}` is now on **{plan}** plan for {days} days.", parse_mode='Markdown')
    try: bot.send_message(uid, f"🎉 You have been upgraded to the **{plan}** plan for {days} days!", parse_mode='Markdown')
    except: pass

if __name__ == '__main__':
    logger.info("Aditya Hosting Bot Started!")
    keep_alive()
    bot.infinity_polling(timeout=60, long_polling_timeout=30)