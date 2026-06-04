from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import os

from telegram.ext import Updater, CommandHandler


# ==============================
# Render Health Server
# ==============================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def log_message(self, *args):
        pass


def start_health_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


threading.Thread(target=start_health_server, daemon=True).start()


# ==============================
# Telegram Bot
# ==============================

BOT_TOKEN = os.getenv("BOT_TOKEN")


def start(update, context):
    update.message.reply_text("Bot is working!")


updater = Updater(BOT_TOKEN, use_context=True)

dp = updater.dispatcher

dp.add_handler(CommandHandler("start", start))

print("Bot Started...")

updater.start_polling()
updater.idle()
