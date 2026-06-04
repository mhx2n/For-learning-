import os
import logging
import asyncio
import json
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import Database
from facebook_scraper import FacebookScraper
from post_formatter import PostFormatter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
OWNER_IDS = [int(x) for x in os.environ.get("OWNER_IDS", "").split(",") if x.strip()]
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
FETCH_INTERVAL_MINUTES = int(os.environ.get("FETCH_INTERVAL_MINUTES", "30"))

db = Database()
formatter = PostFormatter()
scraper = FacebookScraper()


def is_owner_or_admin(user_id: int) -> bool:
    return user_id in OWNER_IDS or user_id in ADMIN_IDS

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ তুমি এই বট ব্যবহার করার অনুমতি পাওনি।")
        return
    text = (
        "🤖 *Facebook → Telegram Bot*\n\n"
        "স্বাগতম! এই বট Facebook Page থেকে সুন্দর বাংলা স্ট্যাটাস সংগ্রহ করে চ্যানেলে পোস্ট করে।\n\n"
        "📋 *কমান্ড সমূহ:*\n"
        "`/addpage <URL>` — Facebook Page যোগ করো\n"
        "`/listpages` — সব Page দেখো\n"
        "`/removepage <ID>` — Page সরাও\n"
        "`/pending` — অনুমোদন বাকি পোস্ট দেখো\n"
        "`/fetch` — এখনই পোস্ট আনো\n"
        "`/stats` — পরিসংখ্যান দেখো\n"
        "`/help` — সাহায্য\n\n"
        f"👤 তোমার ID: `{user.id}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_cmd(update, context)


async def add_page_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ অনুমতি নেই।")
        return
    if not context.args:
        await update.message.reply_text(
            "📌 ব্যবহার: `/addpage <Facebook Page URL বা Username>`\n\nউদাহরণ:\n`/addpage https://facebook.com/pagename`",
            parse_mode="Markdown"
        )
        return
    page_input = context.args[0].strip()
    if "facebook.com/" in page_input:
        page_slug = page_input.rstrip("/").split("/")[-1]
    else:
        page_slug = page_input
    page_url = f"https://www.facebook.com/{page_slug}"
    existing = db.get_page_by_slug(page_slug)
    if existing:
        await update.message.reply_text(f"⚠️ এই Page ইতিমধ্যে যোগ করা আছে।\nID: `{existing['id']}`", parse_mode="Markdown")
        return
    page_id = db.add_page(page_slug, page_url, user.id)
    await update.message.reply_text(
        f"✅ Page যোগ হয়েছে!\n\n🔗 URL: {page_url}\n🆔 ID: `{page_id}`",
        parse_mode="Markdown"
    )


async def list_pages_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ অনুমতি নেই।")
        return
    pages = db.get_all_pages()
    if not pages:
        await update.message.reply_text("📭 কোনো Page যোগ করা নেই।\n`/addpage` দিয়ে যোগ করো।", parse_mode="Markdown")
        return
    text = "📋 *যোগ করা Facebook Pages:*\n\n"
    for p in pages:
        status = "✅ সক্রিয়" if p["active"] else "❌ বন্ধ"
        text += f"• `ID:{p['id']}` — {p['slug']} [{status}]\n"
    text += f"\n_মোট: {len(pages)}টি Page_"
    await update.message.reply_text(text, parse_mode="Markdown")


async def remove_page_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ শুধু Owner এটা করতে পারবে।")
        return
    if not context.args:
        await update.message.reply_text("📌 ব্যবহার: `/removepage <ID>`", parse_mode="Markdown")
        return
    try:
        page_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ সঠিক ID দাও।")
        return
    success = db.remove_page(page_id)
    if success:
        await update.message.reply_text(f"✅ Page ID `{page_id}` সরানো হয়েছে।", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ ID `{page_id}` পাওয়া যায়নি।", parse_mode="Markdown")


async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ অনুমতি নেই।")
        return
    posts = db.get_pending_posts(limit=5)
    if not posts:
        await update.message.reply_text("✅ কোনো pending পোস্ট নেই।")
        return
    await update.message.reply_text(f"📬 *{len(posts)}টি পোস্ট অনুমোদনের অপেক্ষায়:*", parse_mode="Markdown")
    for post in posts:
        await send_approval_request(context.bot, user.id, post)


async def fetch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ অনুমতি নেই।")
        return
    msg = await update.message.reply_text("⏳ Facebook থেকে পোস্ট আনছি...")
    count = await fetch_and_queue_posts(context.bot)
    await msg.edit_text(f"✅ {count}টি নতুন পোস্ট পাওয়া গেছে।")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ অনুমতি নেই।")
        return
    stats = db.get_stats()
    bw_kb = int(stats.get("bandwidth_used_kb", 0))
    bw_mb = bw_kb / 1024
    bw_gb = bw_mb / 1024
    bw_pct = min((bw_gb / 5.0) * 100, 100)
    bar_filled = int(bw_pct / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    text = (
        "📊 *বট পরিসংখ্যান*\n\n"
        f"📄 মোট সংগ্রহ: `{stats.get('total_fetched', 0)}`\n"
        f"✅ প্রকাশিত: `{stats.get('approved_posted', 0)}`\n"
        f"❌ প্রত্যাখ্যাত: `{stats.get('rejected', 0)}`\n"
        f"⏳ Pending: `{stats.get('pending', 0)}`\n\n"
        f"🌐 *Bandwidth:*\n`{bar}` {bw_pct:.1f}%\n`{bw_mb:.2f} MB / 5120 MB`\n\n"
        f"📡 Pages: `{stats.get('total_pages', 0)}`\n"
        f"🕐 শেষ fetch: `{stats.get('last_fetch', 'কখনো না')}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def send_approval_request(bot: Bot, user_id: int, post: dict):
    preview = formatter.format_preview(post)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ অনুমোদন দাও", callback_data=f"approve:{post['id']}"),
            InlineKeyboardButton("❌ বাতিল করো", callback_data=f"reject:{post['id']}"),
        ],
        [InlineKeyboardButton("✏️ সম্পাদনা করো", callback_data=f"edit:{post['id']}")]
    ])
    try:
        await bot.send_message(chat_id=user_id, text=preview, reply_markup=keyboard, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Approval send error: {e}")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_owner_or_admin(user.id):
        await query.answer("❌ অনুমতি নেই।")
        return
    await query.answer()
    data = query.data
    if data.startswith("approve:"):
        post_id = int(data.split(":")[1])
        await approve_post(query, context.bot, post_id)
    elif data.startswith("reject:"):
        post_id = int(data.split(":")[1])
        db.update_post_status(post_id, "rejected")
        await query.edit_message_text(query.message.text + "\n\n❌ *বাতিল করা হয়েছে।*", parse_mode="Markdown")
    elif data.startswith("edit:"):
        post_id = int(data.split(":")[1])
        context.user_data["editing_post_id"] = post_id
        await query.edit_message_text("✏️ *নতুন টেক্সট পাঠাও:*", parse_mode="Markdown")


async def approve_post(query, bot: Bot, post_id: int):
    post = db.get_post_by_id(post_id)
    if not post:
        await query.edit_message_text("❌ পোস্টটি পাওয়া যায়নি।")
        return
    if post["status"] != "pending":
        await query.edit_message_text(f"⚠️ পোস্টটি আগেই `{post['status']}` হয়েছে।", parse_mode="Markdown")
        return
    formatted = formatter.format_for_channel(post)
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=formatted, parse_mode="Markdown", disable_web_page_preview=True)
        db.update_post_status(post_id, "posted")
        db.increment_stat("approved_posted")
        await query.edit_message_text(query.message.text + "\n\n✅ *চ্যানেলে পোস্ট করা হয়েছে!*", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Channel post error: {e}")
        await query.edit_message_text(f"❌ পোস্ট করতে সমস্যা: `{e}`", parse_mode="Markdown")


async def edit_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        return
    post_id = context.user_data.get("editing_post_id")
    if not post_id:
        return
    new_text = update.message.text
    db.update_post_content(post_id, new_text)
    del context.user_data["editing_post_id"]
    post = db.get_post_by_id(post_id)
    preview = formatter.format_preview(post)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ এখন পোস্ট করো", callback_data=f"approve:{post_id}"),
            InlineKeyboardButton("❌ বাতিল", callback_data=f"reject:{post_id}"),
        ]
    ])
    await update.message.reply_text(f"✏️ আপডেট হয়েছে:\n\n{preview}", reply_markup=keyboard, parse_mode="Markdown")


async def fetch_and_queue_posts(bot: Bot) -> int:
    pages = db.get_active_pages()
    new_count = 0
    for page in pages:
        try:
            posts = await scraper.fetch_posts(page["slug"], page["url"])
            db.add_bandwidth_usage(scraper.last_request_bytes)
            for raw_post in posts:
                if db.post_exists(raw_post["post_id"]):
                    continue
                if len(raw_post.get("text", "")) < 30:
                    continue
                post_db_id = db.save_post(
                    fb_post_id=raw_post["post_id"],
                    page_slug=page["slug"],
                    text=raw_post["text"],
                    post_url=raw_post.get("url", ""),
                    fetched_at=datetime.now().isoformat()
                )
                db.increment_stat("total_fetched")
                new_count += 1
                notify_ids = list(set(OWNER_IDS + ADMIN_IDS))
                post = db.get_post_by_id(post_db_id)
                for uid in notify_ids:
                    try:
                        await send_approval_request(bot, uid, post)
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        logger.warning(f"Notify {uid} failed: {e}")
        except Exception as e:
            logger.error(f"Fetch error for {page['slug']}: {e}")
    db.set_stat("last_fetch", datetime.now().strftime("%d/%m/%Y %H:%M"))
    return new_count


async def scheduled_fetch(bot: Bot):
    logger.info("⏰ Scheduled fetch শুরু...")
    count = await fetch_and_queue_posts(bot)
    logger.info(f"⏰ Scheduled fetch শেষ। {count}টি নতুন পোস্ট।")


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable সেট করো!")
    if not CHANNEL_ID:
        raise ValueError("CHANNEL_ID environment variable সেট করো!")
    if not OWNER_IDS:
        raise ValueError("OWNER_IDS environment variable সেট করো!")

    db.init()

    async def post_init(application):
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            scheduled_fetch,
            "interval",
            minutes=FETCH_INTERVAL_MINUTES,
            args=[application.bot],
            next_run_time=datetime.now() + timedelta(minutes=1)
        )
        scheduler.start()
        logger.info(f"✅ Scheduler শুরু — প্রতি {FETCH_INTERVAL_MINUTES} মিনিটে fetch করবে।")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("addpage", add_page_cmd))
    app.add_handler(CommandHandler("listpages", list_pages_cmd))
    app.add_handler(CommandHandler("removepage", remove_page_cmd))
    app.add_handler(CommandHandler("pending", pending_cmd))
    app.add_handler(CommandHandler("fetch", fetch_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, edit_message_handler))

    webhook_url = os.environ.get("WEBHOOK_URL", "")
    port = int(os.environ.get("PORT", 8080))

    async with app:
        await app.initialize()
        if webhook_url:
            logger.info(f"🌐 Webhook mode: {webhook_url}")
            await app.bot.set_webhook(
                url=f"{webhook_url}/webhook/{BOT_TOKEN}",
                allowed_updates=Update.ALL_TYPES,
            )
            await app.start()

            from aiohttp import web as aiohttp_web

            async def handle_webhook(request):
                data = await request.json()
                update = Update.de_json(data, app.bot)
                await app.process_update(update)
                return aiohttp_web.Response(text="ok")

            async def handle_health(request):
                return aiohttp_web.Response(
                    text='{"status":"ok","service":"fb-telegram-bot"}',
                    content_type="application/json"
                )

            aio_app = aiohttp_web.Application()
            aio_app.router.add_post(f"/webhook/{BOT_TOKEN}", handle_webhook)
            aio_app.router.add_get("/health", handle_health)
            aio_app.router.add_get("/ping", handle_health)
            aio_app.router.add_get("/", handle_health)

            runner = aiohttp_web.AppRunner(aio_app)
            await runner.setup()
            site = aiohttp_web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            logger.info(f"✅ Webhook server চালু — port {port}")

            await asyncio.Event().wait()  # চিরকাল চলো
        else:
            logger.info("🔄 Polling mode (local dev)")
            await app.start()
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
