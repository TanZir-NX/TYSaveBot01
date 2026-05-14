import os
import telebot
from flask import Flask
import yt_dlp
import threading

# আপনার বট টোকেন এখানে দিন
TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN'
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Flask সার্ভার Render এর জন্য (যাতে বট চালু থাকে)
@app.route('/')
def home():
    return "Bot is running!"

# YouTube Video Download Function
def download_video(url, message):
    try:
        bot.reply_to(message, "⏳ ভিডিও ডাউনলোড হচ্ছে, দয়া করে অপেক্ষা করুন...")
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': 'video.mp4',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        bot.send_video(message.chat.id, open('video.mp4', 'rb'))
        os.remove('video.mp4') # ফাইল পাঠানোর পর ডিলিট করে দিবে
    except Exception as e:
        bot.reply_to(message, f"❌ সমস্যা হয়েছে: {str(e)}")

# Command: /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "স্বাগতম! আমাকে একটি YouTube ভিডিওর লিঙ্ক পাঠান, আমি সেটি ডাউনলোড করে দেব।")

# লিঙ্ক রিসিভ করা
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if "youtube.com" in message.text or "youtu.be" in message.text:
        download_video(message.text, message)
    else:
        bot.reply_to(message, "দয়া করে একটি সঠিক YouTube লিঙ্ক পাঠান।")

# বট এবং ফ্ল্যাস্ক একসাথে চালানো
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.polling()
