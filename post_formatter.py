import random
from datetime import datetime


# সুন্দর বাংলা ইমোজি সেট
HEADER_EMOJIS = ["🌸", "💫", "✨", "🌿", "💎", "🦋", "🌺", "⭐", "🌙", "🕊️"]
DIVIDERS = ["━━━━━━━━━━━━━━━━", "─────────────────", "• • • • • • • • •"]
FOOTER_TAGS = [
    "#বাংলা_স্ট্যাটাস", "#ভালো_কথা", "#অনুপ্রেরণা",
    "#বাংলা_উক্তি", "#জীবনের_কথা", "#বাংলা"
]


class PostFormatter:

    def format_for_channel(self, post: dict) -> str:
        """চ্যানেলের জন্য সুন্দরভাবে ফরম্যাট করো"""
        text = post.get("text", "").strip()
        page_slug = post.get("page_slug", "")
        post_url = post.get("post_url", "")

        emoji = random.choice(HEADER_EMOJIS)
        divider = random.choice(DIVIDERS)
        tags = random.sample(FOOTER_TAGS, k=min(3, len(FOOTER_TAGS)))
        tags_line = "  ".join(tags)

        now = datetime.now()
        date_str = now.strftime("%d %B %Y")  # e.g. 04 June 2025

        # মাসের বাংলা নাম
        month_bn = {
            "January": "জানুয়ারি", "February": "ফেব্রুয়ারি", "March": "মার্চ",
            "April": "এপ্রিল", "May": "মে", "June": "জুন",
            "July": "জুলাই", "August": "আগস্ট", "September": "সেপ্টেম্বর",
            "October": "অক্টোবর", "November": "নভেম্বর", "December": "ডিসেম্বর"
        }
        for en, bn in month_bn.items():
            date_str = date_str.replace(en, bn)

        formatted = (
            f"{emoji} *সুন্দর কথা*\n"
            f"{divider}\n\n"
            f"{text}\n\n"
            f"{divider}\n"
            f"{tags_line}\n\n"
            f"📅 _{date_str}_"
        )

        if post_url:
            formatted += f"\n🔗 [মূল পোস্ট]({post_url})"

        return formatted

    def format_preview(self, post: dict) -> str:
        """Admin approval preview"""
        text = post.get("text", "").strip()
        page_slug = post.get("page_slug", "")
        post_id = post.get("id", "?")
        fetched_at = post.get("fetched_at", "")

        # সময় ফরম্যাট
        try:
            dt = datetime.fromisoformat(fetched_at)
            time_str = dt.strftime("%d/%m %H:%M")
        except Exception:
            time_str = fetched_at

        preview = (
            f"📬 *নতুন পোস্ট — অনুমোদন দরকার*\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"{text}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🔖 ID: `{post_id}` | 📄 Page: `{page_slug}`\n"
            f"🕐 সংগ্রহ: _{time_str}_\n\n"
            f"⬇️ *সিদ্ধান্ত নাও:*"
        )
        return preview
