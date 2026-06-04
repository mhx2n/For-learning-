"""
Main entry point — Health Server + Telegram Bot একসাথে চালাও
Render Free Tier-এ deploy করার জন্য।
"""
import os
import sys
import logging

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Health server আগে চালাও (Render check করে)
from health_server import start_health_server
start_health_server()

# Bot চালাও
logger.info("🤖 Telegram Bot শুরু হচ্ছে...")
from bot import main
main()
