"""
Render Free Tier-এর জন্য Health Check সার্ভার।
Render প্রতি ১৫ মিনিটে ping করে — এই endpoint জবাব দেয়।
"""
import os
import logging
import asyncio
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

logger = logging.getLogger(__name__)

START_TIME = datetime.now()


class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # HTTP log suppress করো

    def do_GET(self):
        if self.path in ("/", "/health", "/healthz", "/ping"):
            uptime = (datetime.now() - START_TIME).seconds
            hours = uptime // 3600
            mins = (uptime % 3600) // 60

            body = json.dumps({
                "status": "ok",
                "service": "fb-telegram-bot",
                "uptime": f"{hours}h {mins}m",
                "timestamp": datetime.now().isoformat()
            }, ensure_ascii=False).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/status":
            # More detailed status
            body = json.dumps({
                "status": "running",
                "bot": "Facebook → Telegram Bot",
                "version": "1.0.0",
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }, ensure_ascii=False).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_HEAD(self):
        """Render uptime check-এর জন্য HEAD support"""
        self.send_response(200)
        self.end_headers()


def start_health_server():
    """Background thread-এ health server চালাও"""
    port = int(os.environ.get("HEALTH_PORT", os.environ.get("PORT", 8080)))

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"✅ Health check server চালু: port {port}")
    logger.info(f"   Endpoints: /health, /ping, /status")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
