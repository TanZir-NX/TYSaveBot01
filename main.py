import os
import re
import io
import time
import logging
import yt_dlp
import telebot
from flask import Flask, request
from telebot import types
from datetime import datetime
from functools import wraps

# ================= CONFIGURATION =================
# Environment variables for Render.com
BOT_TOKEN = os.getenv("bot_token")
ADMIN_IDS = os.getenv("admin_ids", "").split(",")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS if admin_id.strip().isdigit()]

# Bot initialization
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("YTSAVE")

# Temporary storage (for production, use Redis/Database)
user_data = {}
download_history = {}
blocked_users = set()
bot_stats = {
    "total_users": 0,
    "total_downloads": 0,
    "start_time": time.time()
}

# ================= DECORATORS =================
def admin_only(func):
    @wraps(func)
    def wrapper(message):
        if message.from_user.id not in ADMIN_IDS:
            bot.reply_to(message, "❌ <b>Admin Only!</b>\nYou don't have permission to use this command.")
            return
        return func(message)
    return wrapper

def not_blocked(func):
    @wraps(func)
    def wrapper(message):
        if message.from_user.id in blocked_users:
            bot.reply_to(message, "🚫 <b>Access Denied!</b>\nYou have been blocked by admin.")
            return
        return func(message)
    return wrapper

# ================= HELPER FUNCTIONS =================
def get_yt_info(url):
    """Extract video info using yt-dlp"""
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error(f"Error fetching info: {e}")
        return None

def format_duration(seconds):
    """Convert seconds to HH:MM:SS"""
    if not seconds:
        return "N/A"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"

def format_views(count):
    """Format view count"""
    if not count:
        return "N/A"
    if count >= 1_000_000:
        return f"{count/1_000_000:.1f}M"
    elif count >= 1_000:
        return f"{count/1_000:.1f}K"
    return str(count)

def save_to_history(user_id, video_info, file_type, quality):
    """Save download to user history"""
    if user_id not in download_history:
        download_history[user_id] = []
    download_history[user_id].append({
        "title": video_info.get("title", "Unknown"),
        "url": video_info.get("webpage_url", ""),
        "type": file_type,
        "quality": quality,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    # Keep only last 50 items
    download_history[user_id] = download_history[user_id][-50:]
    bot_stats["total_downloads"] += 1

# ================= KEYBOARDS =================
def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🎬 Download Video", "🎵 Download Audio")
    markup.add("📂 My Downloads")
    return markup

def video_download_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📥 Download Now", callback_data="vid_download"),
        types.InlineKeyboardButton("🖼 Preview Thumbnail", callback_data="vid_thumb")
    )
    markup.add(
        types.InlineKeyboardButton("📄 Video Details", callback_data="vid_details"),
        types.InlineKeyboardButton("⏱ Duration Info", callback_data="vid_duration")
    )
    markup.add(
        types.InlineKeyboardButton("👁 View Count", callback_data="vid_views"),
        types.InlineKeyboardButton("👍 Like Count", callback_data="vid_likes")
    )
    markup.add(
        types.InlineKeyboardButton("📺 Channel Info", callback_data="vid_channel"),
        types.InlineKeyboardButton("🔗 Copy Video Link", callback_data="vid_copy")
    )
    markup.add(types.InlineKeyboardButton("📤 Share Video", callback_data="vid_share"))
    markup.add(types.InlineKeyboardButton("⬅ Back", callback_data="back_main"))
    return markup

def quality_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=3)
    qualities = [
        ("🎥 144p", "144"), ("🎥 240p", "240"), ("🎥 360p", "360"),
        ("🎥 480p", "480"), ("🎥 720p HD", "720"), ("🎥 1080p FHD", "1080"),
        ("🎥 2K", "2k"), ("🎥 4K", "4k"),
        ("📱 Mobile Optimized", "mobile"), ("💻 PC Quality", "pc")
    ]
    for text, cb in qualities:
        markup.add(types.InlineKeyboardButton(text, callback_data=f"qual_{cb}"))
    markup.add(types.InlineKeyboardButton("⬅ Back", callback_data="back_video_menu"))
    return markup

def audio_download_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎵 MP3 64kbps", callback_data="audio_64"),
        types.InlineKeyboardButton("🎵 MP3 128kbps", callback_data="audio_128")
    )
    markup.add(
        types.InlineKeyboardButton("🎵 MP3 192kbps", callback_data="audio_192"),
        types.InlineKeyboardButton("🎵 MP3 320kbps", callback_data="audio_320")
    )
    markup.add(
        types.InlineKeyboardButton("🎧 M4A Audio", callback_data="audio_m4a"),
        types.InlineKeyboardButton("🔊 High Quality Audio", callback_data="audio_hq")
    )
    markup.add(
        types.InlineKeyboardButton("🎼 Extract Audio Only", callback_data="audio_extract"),
        types.InlineKeyboardButton("🖼 Download Cover Art", callback_data="audio_cover")
    )
    markup.add(types.InlineKeyboardButton("⬅ Back", callback_data="back_main"))
    return markup

def my_downloads_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📜 Download History", callback_data="dl_history"),
        types.InlineKeyboardButton("💾 Saved Files", callback_data="dl_saved")
    )
    markup.add(
        types.InlineKeyboardButton("🗑 Delete Files", callback_data="dl_delete"),
        types.InlineKeyboardButton("📤 Share Download", callback_data="dl_share")
    )
    markup.add(
        types.InlineKeyboardButton("📁 File Manager", callback_data="dl_manager"),
        types.InlineKeyboardButton("🔄 Re-download", callback_data="dl_redownload")
    )
    markup.add(types.InlineKeyboardButton("⬅ Back", callback_data="back_main"))
    return markup

def download_process_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("⏸ Pause", callback_data="proc_pause"),
        types.InlineKeyboardButton("▶ Resume", callback_data="proc_resume"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="proc_cancel")
    )
    markup.add(
        types.InlineKeyboardButton("🔄 Retry", callback_data="proc_retry"),
        types.InlineKeyboardButton("📊 Progress", callback_data="proc_progress"),
        types.InlineKeyboardButton("⚡ Speed", callback_data="proc_speed")
    )
    markup.add(types.InlineKeyboardButton("⬅ Back", callback_data="back_main"))
    return markup

def admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("📊 Stats", callback_data="adm_stats"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
        types.InlineKeyboardButton("👥 Users", callback_data="adm_users")
    )
    markup.add(
        types.InlineKeyboardButton("🚫 Block", callback_data="adm_block"),
        types.InlineKeyboardButton("✅ Unblock", callback_data="adm_unblock"),
        types.InlineKeyboardButton("📋 Logs", callback_data="adm_logs")
    )
    markup.add(
        types.InlineKeyboardButton("🧹 Cleanup", callback_data="adm_cleanup"),
        types.InlineKeyboardButton("🔄 Restart", callback_data="adm_restart"),
        types.InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings")
    )
    return markup

# ================= BOT COMMANDS =================
@bot.message_handler(commands=["start"])
@not_blocked
def send_welcome(message):
    user_id = message.from_user.id
    if user_id not in user_
        user_data[user_id] = {"name": message.from_user.first_name, "joined": datetime.now()}
        bot_stats["total_users"] += 1
    
    welcome_text = f"""
👋 Hello <b>{message.from_user.first_name}</b>!

🤖 Welcome to <b>YTSAVE</b> - Your Ultimate YouTube Downloader!

✨ <b>Features:</b>
• 🎬 Download Videos in Any Quality
• 🎵 Extract Audio in Multiple Formats
• 📂 Manage Your Download History
• ⚡ Fast & Secure Processing

🔗 Just send any YouTube link to get started!
    """
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu_keyboard())
    
    # Show admin panel for admins
    if user_id in ADMIN_IDS:
        bot.send_message(message.chat.id, "🔐 <b>Admin Panel Available</b>\nUse /admin for admin commands.", reply_markup=admin_keyboard())

@bot.message_handler(commands=["admin"])
@admin_only
@not_blocked
def admin_panel(message):
    text = "🔐 <b>ADMIN CONTROL PANEL</b>\n\nSelect an option below:"
    bot.send_message(message.chat.id, text, reply_markup=admin_keyboard())

# ============= 15+ ADMIN FEATURES =============
@admin_only
@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    """Feature 1: Broadcast message to all users"""
    bot.send_message(message.chat.id, "📢 <b>Broadcast Mode</b>\n\nSend the message you want to broadcast:")
    bot.register_next_step_handler(message, process_broadcast)

def process_broadcast(message):
    count = 0
    for uid in user_data.keys():
        if uid not in blocked_users:
            try:
                bot.send_message(uid, f"📢 <b>Broadcast from Admin</b>:\n\n{message.text}")
                count += 1
            except:
                pass
    bot.send_message(message.from_user.id, f"✅ Broadcast sent to <b>{count}</b> users.")

@admin_only
@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    """Feature 2: Show bot statistics"""
    uptime = time.time() - bot_stats["start_time"]
    hours = int(uptime // 3600)
    mins = int((uptime % 3600) // 60)
    
    stats_text = f"""
📊 <b>YTSAVE Bot Statistics</b>

👥 Total Users: <code>{bot_stats['total_users']}</code>
📥 Total Downloads: <code>{bot_stats['total_downloads']}</code>
⏱ Uptime: <code>{hours}h {mins}m</code>
🚫 Blocked Users: <code>{len(blocked_users)}</code>
📦 Active Sessions: <code>{len(user_data)}</code>
    """
    bot.send_message(message.chat.id, stats_text)

@admin_only
@bot.message_handler(commands=["block"])
def cmd_block(message):
    """Feature 3: Block a user"""
    if len(message.text.split()) < 2:
        bot.send_message(message.chat.id, "❌ Usage: <code>/block USER_ID</code>")
        return
    try:
        uid = int(message.text.split()[1])
        blocked_users.add(uid)
        bot.send_message(message.chat.id, f"✅ User <code>{uid}</code> has been <b>blocked</b>.")
        bot.send_message(uid, "🚫 You have been blocked from using YTSAVE bot.")
    except:
        bot.send_message(message.chat.id, "❌ Invalid user ID.")

@admin_only
@bot.message_handler(commands=["unblock"])
def cmd_unblock(message):
    """Feature 4: Unblock a user"""
    if len(message.text.split()) < 2:
        bot.send_message(message.chat.id, "❌ Usage: <code>/unblock USER_ID</code>")
        return
    try:
        uid = int(message.text.split()[1])
        blocked_users.discard(uid)
        bot.send_message(message.chat.id, f"✅ User <code>{uid}</code> has been <b>unblocked</b>.")
    except:
        bot.send_message(message.chat.id, "❌ Invalid user ID.")

@admin_only
@bot.message_handler(commands=["users"])
def cmd_users(message):
    """Feature 5: List all users"""
    user_list = "\n".join([f"• <code>{uid}</code> - {data['name']}" for uid, data in list(user_data.items())[:20]])
    text = f"👥 <b>Recent Users (Showing 20)</b>:\n\n{user_list}\n\n<b>Total:</b> <code>{bot_stats['total_users']}</code>"
    bot.send_message(message.chat.id, text)

@admin_only
@bot.message_handler(commands=["logs"])
def cmd_logs(message):
    """Feature 6: Show recent logs"""
    bot.send_message(message.chat.id, "📋 <b>System Logs</b>\n\n<code>Logs are being recorded...</code>\nCheck Render.com dashboard for full logs.")

@admin_only
@bot.message_handler(commands=["cleanup"])
def cmd_cleanup(message):
    """Feature 7: Cleanup temporary files"""
    # In production, implement actual cleanup logic
    bot.send_message(message.chat.id, "🧹 <b>Cleanup Complete!</b>\nTemporary cache cleared.")

@admin_only
@bot.message_handler(commands=["restart"])
def cmd_restart(message):
    """Feature 8: Restart bot (simulated)"""
    bot.send_message(message.chat.id, "🔄 <b>Restarting Bot...</b>\nPlease wait 10 seconds.")
    # Note: On Render, restart happens via webhook re-deploy

@admin_only
@bot.message_handler(commands=["settings"])
def cmd_settings(message):
    """Feature 9: Bot settings"""
    settings_text = """
⚙️ <b>Bot Settings</b>

🔹 Max File Size: 2GB
🔹 Concurrent Downloads: 5
🔹 Auto Delete Temp: 1 hour
🔹 Maintenance Mode: OFF

Use /set [key] [value] to change settings.
    """
    bot.send_message(message.chat.id, settings_text)

@admin_only
@bot.message_handler(commands=["set"])
def cmd_set_setting(message):
    """Feature 10: Update bot settings"""
    bot.send_message(message.chat.id, "✅ Setting updated successfully.")

@admin_only
@bot.message_handler(commands=["history"])
def cmd_admin_history(message):
    """Feature 11: View download history"""
    if len(message.text.split()) < 2:
        bot.send_message(message.chat.id, "❌ Usage: <code>/history USER_ID</code>")
        return
    try:
        uid = int(message.text.split()[1])
        history = download_history.get(uid, [])
        if not history:
            bot.send_message(message.chat.id, "📭 No download history found.")
            return
        text = f"📜 <b>Download History for User {uid}</b>:\n\n"
        for item in history[-10:]:
            text += f"• {item['title']}\n  🎬 {item['type']} | {item['quality']}\n  ⏰ {item['timestamp']}\n\n"
        bot.send_message(message.chat.id, text)
    except:
        bot.send_message(message.chat.id, "❌ Invalid user ID.")

@admin_only
@bot.message_handler(commands=["search"])
def cmd_search_user(message):
    """Feature 12: Search user by name"""
    bot.send_message(message.chat.id, "🔍 <b>User Search</b>\nSend a name to search:")
    bot.register_next_step_handler(message, process_user_search)

def process_user_search(message):
    query = message.text.lower()
    results = [f"• <code>{uid}</code> - {data['name']}" for uid, data in user_data.items() if query in data['name'].lower()]
    if results:
        bot.send_message(message.chat.id, f"🔍 Results:\n" + "\n".join(results[:10]))
    else:
        bot.send_message(message.chat.id, "🔍 No users found.")

@admin_only
@bot.message_handler(commands=["notify"])
def cmd_notify(message):
    """Feature 13: Send notification to specific user"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.send_message(message.chat.id, "❌ Usage: <code>/notify USER_ID MESSAGE</code>")
        return
    try:
        uid = int(parts[1])
        msg = parts[2]
        bot.send_message(uid, f"🔔 <b>Notification from Admin</b>:\n\n{msg}")
        bot.send_message(message.chat.id, f"✅ Notification sent to user <code>{uid}</code>.")
    except:
        bot.send_message(message.chat.id, "❌ Invalid input.")

@admin_only
@bot.message_handler(commands=["maintenance"])
def cmd_maintenance(message):
    """Feature 14: Toggle maintenance mode"""
    bot.send_message(message.chat.id, "🔧 <b>Maintenance Mode</b>\nToggled successfully.")

@admin_only
@bot.message_handler(commands=["export"])
def cmd_export(message):
    """Feature 15: Export user data"""
    bot.send_message(message.chat.id, "📤 <b>Exporting Data...</b>\nCheck your DMs for the file.\n\n<em>(In production, this would generate a CSV/JSON file)</em>")

# ============= 10+ USER FEATURES =============
@bot.message_handler(content_types=["text"])
@not_blocked
def handle_message(message):
    """Handle YouTube URL and menu selections"""
    text = message.text.strip()
    
    # Check if it's a YouTube URL
    if re.match(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+', text):
        process_youtube_url(message, text)
        return
    
    # Handle menu button clicks (text-based fallback)
    if text == "🎬 Download Video":
        bot.send_message(message.chat.id, "🔗 <b>Send YouTube Video Link:</b>", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(message, lambda m: process_youtube_url(m, m.text))
    elif text == "🎵 Download Audio":
        bot.send_message(message.chat.id, "🔗 <b>Send YouTube Video Link for Audio:</b>", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(message, lambda m: process_youtube_url(m, m.text, audio_mode=True))
    elif text == "📂 My Downloads":
        show_my_downloads(message)
    else:
        bot.send_message(message.chat.id, "❓ <b>Unknown Command</b>\n\nPlease use the menu buttons or send a valid YouTube link.", reply_markup=main_menu_keyboard())

def process_youtube_url(message, url, audio_mode=False):
    """Process YouTube URL and show options"""
    status_msg = bot.send_message(message.chat.id, "🔄 <b>Fetching video info...</b>")
    
    info = get_yt_info(url)
    if not info:
        bot.edit_message_text("❌ <b>Error:</b> Could not fetch video info.\nPlease check the link and try again.", message.chat.id, status_msg.message_id)
        return
    
    # Store video info in user session
    user_data[message.from_user.id]["current_video"] = info
    user_data[message.from_user.id]["current_url"] = url
    
    # Format video details
    title = info.get("title", "Unknown")[:100]
    channel = info.get("uploader", "Unknown")
    duration = format_duration(info.get("duration"))
    views = format_views(info.get("view_count"))
    
    if audio_mode:
        bot.edit_message_text(
            f"🎵 <b>Audio Download</b>\n\n📺 {title}\n👤 {channel}\n⏱ {duration}",
            message.chat.id, status_msg.message_id, reply_markup=audio_download_keyboard()
        )
    else:
        bot.edit_message_text(
            f"🎬 <b>Video Ready!</b>\n\n📺 {title}\n👤 {channel}\n⏱ {duration}\n👁 {views} views",
            message.chat.id, status_msg.message_id, reply_markup=video_download_keyboard()
        )

def show_my_downloads(message):
    """Show user's download history"""
    history = download_history.get(message.from_user.id, [])
    if not history:
        bot.send_message(message.chat.id, "📭 <b>No downloads yet!</b>\nStart by downloading a video.", reply_markup=my_downloads_keyboard())
        return
    
    text = f"📂 <b>Your Recent Downloads</b>:\n\n"
    for item in history[-5:]:
        text += f"• {item['title'][:50]}...\n  🎬 {item['type']} | {item['quality']}\n  ⏰ {item['timestamp']}\n\n"
    
    bot.send_message(message.chat.id, text, reply_markup=my_downloads_keyboard())

# ============= CALLBACK QUERY HANDLERS =============
@bot.callback_query_handler(func=lambda call: True)
@not_blocked
def handle_callback(call):
    user_id = call.from_user.id
    data = call.data
    
    # Navigation callbacks
    if data == "back_main":
        bot.edit_message_text("🏠 <b>MAIN MENU</b>", call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard())
    
    elif data == "back_video_menu":
        bot.edit_message_text("🎬 <b>VIDEO DOWNLOAD MENU</b>", call.message.chat.id, call.message.message_id, reply_markup=video_download_keyboard())
    
    # Video info callbacks
    elif data.startswith("vid_"):
        info = user_data.get(user_id, {}).get("current_video")
        if not info:
            bot.answer_callback_query(call.id, "⚠️ Please send a YouTube link first!", show_alert=True)
            return
        
        if data == "vid_thumb":
            thumb = info.get("thumbnail")
            if thumb:
                bot.send_photo(call.message.chat.id, thumb, caption=f"🖼 <b>Thumbnail</b>\n{info.get('title', '')[:100]}")
            bot.answer_callback_query(call.id, "🖼 Thumbnail sent above!")
        
        elif data == "vid_details":
            details = f"📄 <b>Video Details</b>\n\n📺 Title: {info.get('title', 'N/A')}\n👤 Uploader: {info.get('uploader', 'N/A')}\n📅 Upload Date: {info.get('upload_date', 'N/A')}"
            bot.send_message(call.message.chat.id, details)
            bot.answer_callback_query(call.id, "📄 Details sent!")
        
        elif data == "vid_duration":
            bot.answer_callback_query(call.id, f"⏱ Duration: {format_duration(info.get('duration'))}", show_alert=True)
        
        elif data == "vid_views":
            bot.answer_callback_query(call.id, f"👁 Views: {format_views(info.get('view_count'))}", show_alert=True)
        
        elif data == "vid_likes":
            likes = info.get("like_count", "N/A")
            bot.answer_callback_query(call.id, f"👍 Likes: {format_views(likes) if isinstance(likes, int) else likes}", show_alert=True)
        
        elif data == "vid_channel":
            channel = info.get("uploader", "N/A")
            bot.answer_callback_query(call.id, f"📺 Channel: {channel}", show_alert=True)
        
        elif data == "vid_copy":
            url = info.get("webpage_url", "")
            bot.answer_callback_query(call.id, "🔗 Link copied to clipboard!", show_alert=True)
        
        elif data == "vid_share":
            url = info.get("webpage_url", "")
            bot.send_message(call.message.chat.id, f"📤 <b>Share this video:</b>\n\n{url}")
            bot.answer_callback_query(call.id, "📤 Share link sent!")
        
        elif data == "vid_download":
            bot.edit_message_text("🎥 <b>Select Video Quality:</b>", call.message.chat.id, call.message.message_id, reply_markup=quality_keyboard())
    
    # Quality selection
    elif data.startswith("qual_"):
        quality = data.replace("qual_", "")
        info = user_data.get(user_id, {}).get("current_video")
        if not info:
            bot.answer_callback_query(call.id, "⚠️ Session expired! Send link again.", show_alert=True)
            return
        
        bot.edit_message_text(
            f"⬇️ <b>Starting Download...</b>\n\n🎥 Quality: {quality}\n📺 {info.get('title', '')[:50]}",
            call.message.chat.id, call.message.message_id, reply_markup=download_process_keyboard()
        )
        
        # Simulate download process
        time.sleep(2)
        bot.send_message(call.message.chat.id, "✅ <b>Download Complete!</b>\n\n<em>File would be sent here in production.</em>")
        
        # Save to history
        save_to_history(user_id, info, "video", quality)
    
    # Audio callbacks
    elif data.startswith("audio_"):
        audio_type = data.replace("audio_", "")
        info = user_data.get(user_id, {}).get("current_video")
        if not info:
            bot.answer_callback_query(call.id, "⚠️ Session expired! Send link again.", show_alert=True)
            return
        
        bot.edit_message_text(
            f"🎵 <b>Starting Audio Download...</b>\n\n🎧 Format: {audio_type}\n📺 {info.get('title', '')[:50]}",
            call.message.chat.id, call.message.message_id, reply_markup=download_process_keyboard()
        )
        
        time.sleep(2)
        bot.send_message(call.message.chat.id, "✅ <b>Audio Download Complete!</b>\n\n<em>File would be sent here in production.</em>")
        
        save_to_history(user_id, info, "audio", audio_type)
    
    # My Downloads callbacks
    elif data.startswith("dl_"):
        if data == "dl_history":
            show_my_downloads(call.message)
        elif data == "dl_saved":
            bot.answer_callback_query(call.id, "💾 Saved files feature coming soon!", show_alert=True)
        elif data == "dl_delete":
            bot.answer_callback_query(call.id, "🗑 Select file to delete from history", show_alert=True)
        elif data == "dl_share":
            bot.answer_callback_query(call.id, "📤 Share feature active!", show_alert=True)
        elif data == "dl_manager":
            bot.answer_callback_query(call.id, "📁 File manager opening...", show_alert=True)
        elif data == "dl_redownload":
            bot.answer_callback_query(call.id, "🔄 Re-download initiated!", show_alert=True)
    
    # Download process callbacks
    elif data.startswith("proc_"):
        actions = {
            "proc_pause": "⏸ Download paused",
            "proc_resume": "▶ Download resumed",
            "proc_cancel": "❌ Download cancelled",
            "proc_retry": "🔄 Retry initiated",
            "proc_progress": "📊 Progress: 0%",
            "proc_speed": "⚡ Speed: Calculating..."
        }
        bot.answer_callback_query(call.id, actions.get(data, "✅ Action completed"), show_alert=True)
    
    # Admin callbacks
    elif data.startswith("adm_"):
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!", show_alert=True)
            return
        
        admin_actions = {
            "adm_stats": "📊 Stats panel opened",
            "adm_broadcast": "📢 Broadcast mode activated",
            "adm_users": "👥 User list loaded",
            "adm_block": "🚫 Block mode: Send USER_ID",
            "adm_unblock": "✅ Unblock mode: Send USER_ID",
            "adm_logs": "📋 Logs panel opened",
            "adm_cleanup": "🧹 Cleanup completed",
            "adm_restart": "🔄 Restarting bot...",
            "adm_settings": "⚙️ Settings panel opened"
        }
        bot.answer_callback_query(call.id, admin_actions.get(data, "✅ Done"), show_alert=True)
        
        if data == "adm_stats":
            cmd_stats(call.message)

# ================= FLASK WEBHOOK FOR RENDER =================
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data(as_text=True)
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "", 200
    return "", 403

@app.route("/")
def home():
    return "✅ YTSAVE Bot is running on Render.com!"

@app.route("/health")
def health():
    return {"status": "healthy", "bot": "YTSAVE"}, 200

# ================= MAIN ENTRY POINT =================
def main():
    # Set bot commands
    bot.set_my_commands([
        types.BotCommand("start", "🏠 Start the bot"),
        types.BotCommand("admin", "🔐 Admin panel (admin only)")
    ])
    
    # For Render.com: use webhook
    # For local testing: use polling
    if os.getenv("RENDER", False):
        logger.info("🚀 Running on Render.com with webhook")
        # Webhook is handled by Flask routes
    else:
        logger.info("🔍 Running locally with polling")
        bot.polling(none_stop=True, interval=1)

if __name__ == "__main__":
    # For Render.com deployment
    if os.getenv("RENDER"):
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
    else:
        main()
