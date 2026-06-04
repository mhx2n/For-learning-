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
# Facebook Graph API Access Token (optional কিন্তু recommended)
FB_ACCESS_TOKEN = os.environ.get("FB_ACCESS_TOKEN", "")

db = Database()
formatter = PostFormatter()
scraper = FacebookScraper()

# Access Token থাকলে scraper-এ সেট করো
if FB_ACCESS_TOKEN:
    scraper.set_access_token(FB_ACCESS_TOKEN)
    logger.info("✅ Facebook Graph API Token সেট হয়েছে।")
else:
    logger.warning("⚠️ FB_ACCESS_TOKEN নেই — mbasic fallback ব্যবহার করা হবে।")


def is_owner_or_admin(user_id: int) -> bool:
    return user_id in OWNER_IDS or user_id in ADMIN_IDS

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ তুমি এই বট ব্যবহার করার অনুমতি পাওনি।")
        return
    api_status = "✅ Graph API" if FB_ACCESS_TOKEN else "⚠️ mbasic (Token নেই)"
    text = (
        "🤖 *Facebook → Telegram Bot*\n\n"
        "স্বাগতম! এই বট Facebook Page থেকে সুন্দর বাংলা স্ট্যাটাস সংগ্রহ করে চ্যানেলে পোস্ট করে।\n\n"
        f"🔌 *API Mode:* {api_status}\n\n"
        "📋 *কমান্ড সমূহ:*\n"
        "`/addpage <URL>` — Facebook Page যোগ করো\n"
        "`/listpages` — সব Page দেখো\n"
        "`/removepage <ID>` — Page সরাও\n"
        "`/pending` — অনুমোদন বাকি পোস্ট দেখো\n"
        "`/fetch` — নতুন পোস্ট আনো\n"
        "`/fetchold` — পুরোনো পোস্টও আনো (সব)\n"
        "`/fetchold <পেজ slug>` — নির্দিষ্ট পেজের পুরোনো পোস্ট\n"
        "`/settoken <token>` — FB Access Token সেট করো\n"
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
            "📌 ব্যবহার: `/addpage <Facebook Page/Group URL>`\n\n"
            "উদাহরণ:\n"
            "`/addpage https://facebook.com/pagename`\n"
            "`/addpage https://www.facebook.com/groups/groupname/`\n"
            "`/addpage https://www.facebook.com/share/18rwZL6t6x/`",
            parse_mode="Markdown"
        )
        return

    page_input = context.args[0].strip()

    # Advanced URL cleanup — ?ref=share&mibextid=NSMWBT সহ সব handle করে
    from facebook_scraper import FacebookScraper as _FS
    clean_url, page_slug, is_group = _FS.clean_fb_url(page_input)

    if not page_slug:
        await update.message.reply_text("❌ সঠিক Facebook URL দাও।")
        return

    page_type = "Group" if is_group else "Page"

    # Duplicate check (slug দিয়ে)
    existing = db.get_page_by_slug(page_slug)
    if existing:
        await update.message.reply_text(
            f"⚠️ এই {page_type} ইতিমধ্যে যোগ করা আছে।\nID: `{existing['id']}`",
            parse_mode="Markdown"
        )
        return

    # original full URL সেভ করো (মূল URL, clean mbasic URL নয়)
    original_url = page_input if "facebook.com" in page_input else f"https://www.facebook.com/{page_slug}"

    page_id = db.add_page(page_slug, original_url, user.id)
    await update.message.reply_text(
        f"✅ {page_type} যোগ হয়েছে!\n\n"
        f"🔗 Slug: `{page_slug}`\n"
        f"🆔 ID: `{page_id}`\n"
        f"{'👥 Group' if is_group else '📄 Page'}: সক্রিয়\n\n"
        f"💡 এখন `/fetch` দিয়ে নতুন পোস্ট অথবা\n"
        f"`/fetchold {page_slug}` দিয়ে পুরোনো পোস্টও আনতে পারো।",
        parse_mode="Markdown"
    )


async def list_pages_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ অনুমতি নেই।")
        return
    pages = db.get_all_pages()
    if not pages:
        await update.message.reply_text(
            "📭 কোনো Page যোগ করা নেই।\n`/addpage` দিয়ে যোগ করো।",
            parse_mode="Markdown"
        )
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
    """নতুন পোস্ট আনো (শুধু সর্বশেষ পোস্ট)"""
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ অনুমতি নেই।")
        return
    msg = await update.message.reply_text("⏳ Facebook থেকে নতুন পোস্ট আনছি...")
    count = await fetch_and_queue_posts(context.bot, fetch_old=False)
    if count == 0:
        await msg.edit_text(
            "✅ ০টি নতুন পোস্ট পাওয়া গেছে।\n\n"
            "💡 *পুরোনো পোস্ট আনতে:* `/fetchold` ব্যবহার করো।",
            parse_mode="Markdown"
        )
    else:
        await msg.edit_text(f"✅ {count}টি নতুন পোস্ট পাওয়া গেছে!")


async def fetch_old_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """পুরোনো পোস্টসহ সব পোস্ট আনো"""
    user = update.effective_user
    if not is_owner_or_admin(user.id):
        await update.message.reply_text("❌ অনুমতি নেই।")
        return

    # নির্দিষ্ট page slug দেওয়া থাকলে
    target_slug = context.args[0].strip() if context.args else None

    if target_slug:
        msg = await update.message.reply_text(
            f"⏳ `{target_slug}` পেজের পুরোনো পোস্টও আনছি...\n"
            f"_(এটা একটু সময় নিতে পারে)_",
            parse_mode="Markdown"
        )
        # ওই page খোঁজো
        page = db.get_page_by_slug(target_slug)
        if not page:
            await msg.edit_text(f"❌ `{target_slug}` নামের কোনো page পাওয়া যায়নি।\nআগে `/addpage` দিয়ে যোগ করো।", parse_mode="Markdown")
            return
        pages = [page]
    else:
        pages = db.get_active_pages()
        if not pages:
            await update.message.reply_text("❌ কোনো active page নেই।")
            return
        msg = await update.message.reply_text(
            f"⏳ সব {len(pages)}টি পেজের পুরোনো পোস্টও আনছি...\n"
            f"_(এটা একটু সময় নিতে পারে)_",
            parse_mode="Markdown"
        )

    count = await fetch_and_queue_posts(context.bot, fetch_old=True, specific_pages=pages)
    await msg.edit_text(
        f"✅ সম্পন্ন! মোট *{count}টি নতুন পোস্ট* সংগ্রহ হয়েছে।\n\n"
        f"📬 `/pending` দিয়ে approve করো।",
        parse_mode="Markdown"
    )


async def set_token_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Facebook Graph API Access Token সেট করো"""
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ শুধু Owner এটা করতে পারবে।")
        return
    if not context.args:
        await update.message.reply_text(
            "📌 ব্যবহার: `/settoken <your_facebook_access_token>`\n\n"
            "🔑 Token পেতে:\n"
            "১. https://developers.facebook.com/ এ যাও\n"
            "২. App তৈরি করো\n"
            "৩. Page Access Token নাও\n\n"
            "⚠️ Token private রাখো — কাউকে দিও না!",
            parse_mode="Markdown"
        )
        return
    token = context.args[0].strip()
    scraper.set_access_token(token)
    # .env-এ save না করলেও runtime-এ কাজ করবে
    await update.message.reply_text(
        "✅ Facebook Access Token সেট হয়েছে!\n\n"
        "💡 এটা restart হলে হারিয়ে যাবে। স্থায়ী করতে `.env`-এ `FB_ACCESS_TOKEN=...` যোগ করো।",
        parse_mode="Markdown"
    )
    # Token message মুছে দাও security-র জন্য
    try:
        await update.message.delete()
    except Exception:
        pass



async def fixpages_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """DB-তে থাকা dirty URL/slug গুলো clean করো"""
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ শুধু Owner এটা করতে পারবে।")
        return
    from facebook_scraper import FacebookScraper as _FS
    pages = db.get_all_pages()
    fixed = []
    for page in pages:
        old_slug = page["slug"]
        old_url = page.get("url", "")
        _, new_slug, is_group = _FS.clean_fb_url(old_url or old_slug)
        if new_slug and new_slug != old_slug:
            with db._conn() as conn:
                conn.execute("UPDATE pages SET slug=? WHERE id=?", (new_slug, page["id"]))
                conn.commit()
            fixed.append("ID:" + str(page["id"]) + " `" + old_slug + "` → `" + new_slug + "`")
    if fixed:
        count = len(fixed)
        lines = "\n".join(fixed)
        msg = f"✅ {count}টি Page fix হয়েছে:\n{lines}"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ সব Page ইতিমধ্যে সঠিক আছে।")


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
    api_mode = "✅ Graph API" if FB_ACCESS_TOKEN or scraper._access_token else "⚠️ mbasic"
    text = (
        "📊 *বট পরিসংখ্যান*\n\n"
        f"📄 মোট সংগ্রহ: `{stats.get('total_fetched', 0)}`\n"
        f"✅ প্রকাশিত: `{stats.get('approved_posted', 0)}`\n"
        f"❌ প্রত্যাখ্যাত: `{stats.get('rejected', 0)}`\n"
        f"⏳ Pending: `{stats.get('pending', 0)}`\n\n"
        f"🌐 *Bandwidth:*\n`{bar}` {bw_pct:.1f}%\n`{bw_mb:.2f} MB / 5120 MB`\n\n"
        f"📡 Pages: `{stats.get('total_pages', 0)}`\n"
        f"🔌 API: {api_mode}\n"
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
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=formatted,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        db.update_post_status(post_id, "posted")
        db.increment_stat("approved_posted")
        await query.edit_message_text(
            query.message.text + "\n\n✅ *চ্যানেলে পোস্ট করা হয়েছে!*",
            parse_mode="Markdown"
        )
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


async def fetch_and_queue_posts(
    bot: Bot,
    fetch_old: bool = False,
    specific_pages: list = None
) -> int:
    """পোস্ট আনো এবং DB-তে queue করো"""
    pages = specific_pages if specific_pages is not None else db.get_active_pages()
    new_count = 0

    for page in pages:
        try:
            # DB-তে dirty slug/URL থাকলেও scraper নিজেই clean করে নেবে
            page_url_for_fetch = page.get('url') or page['slug']
            posts = await scraper.fetch_posts(
                page['slug'],
                page_url_for_fetch,
                fetch_old=fetch_old,
                max_pages=5 if fetch_old else 2,
            )
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

                # Owner/Admin-দের notify করো
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
    count = await fetch_and_queue_posts(bot, fetch_old=False)
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
    app.add_handler(CommandHandler("fetchold", fetch_old_cmd))   # ← নতুন
    app.add_handler(CommandHandler("settoken", set_token_cmd))   # ← নতুন
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("fixpages", fixpages_cmd))   # ← dirty slug fix
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

            await asyncio.Event().wait()
        else:
            logger.info("🔄 Polling mode (local dev)")
            await app.start()
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
