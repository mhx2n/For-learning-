import re
import json
import hashlib
import logging
import asyncio
import httpx
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)


class FacebookScraper:
    """
    Facebook Page থেকে পোস্ট সংগ্রহ করে।
    mbasic.facebook.com ব্যবহার করে — হালকা ও bandwidth-efficient।
    """

    def __init__(self):
        self.last_request_bytes = 0
        self.session_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10; K) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/114.0.0.0 Mobile Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "bn-BD,bn;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }

    async def fetch_posts(self, page_slug: str, page_url: str) -> List[Dict]:
        """mbasic Facebook থেকে পোস্ট আনো"""
        results = []

        # mbasic = lightweight, কম bandwidth
        url = f"https://mbasic.facebook.com/{page_slug}"

        try:
            async with httpx.AsyncClient(
                headers=self.session_headers,
                timeout=20.0,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=2)
            ) as client:
                response = await client.get(url)
                self.last_request_bytes = len(response.content)

                if response.status_code == 200:
                    posts = self._parse_mbasic(response.text, page_slug, page_url)
                    results.extend(posts)
                else:
                    logger.warning(f"HTTP {response.status_code} for {page_slug}")

        except httpx.TimeoutException:
            logger.error(f"Timeout: {page_slug}")
        except Exception as e:
            logger.error(f"Scrape error {page_slug}: {e}")

        return results

    def _parse_mbasic(self, html: str, page_slug: str, base_url: str) -> List[Dict]:
        """mbasic HTML পার্স করো"""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("beautifulsoup4 ইন্সটল করো: pip install beautifulsoup4")
            return []

        soup = BeautifulSoup(html, "html.parser")
        posts = []

        # mbasic-এ পোস্টগুলো div[id^=m_story] বা article ট্যাগে থাকে
        story_divs = soup.find_all("div", id=re.compile(r"^m_story"))
        if not story_divs:
            # Fallback — যেকোনো বড় paragraph
            story_divs = soup.find_all("div", class_=re.compile(r"story|post|feed", re.I))

        for div in story_divs[:10]:  # প্রতি page থেকে সর্বোচ্চ ১০টি
            text = div.get_text(separator=" ", strip=True)
            # Clean up
            text = re.sub(r'\s+', ' ', text).strip()
            text = re.sub(r'(Like|Comment|Share|See More|Translate|Reply)(\s*·\s*)?', '', text)
            text = text.strip()

            # খুব ছোট বা spam-like পোস্ট বাদ দাও
            if len(text) < 30 or len(text) > 2000:
                continue

            # Unique ID তৈরি করো
            post_id = hashlib.md5(f"{page_slug}:{text[:100]}".encode()).hexdigest()[:16]

            # Post URL
            story_link = div.find("a", href=re.compile(r"/story\.php|/permalink/"))
            post_url = ""
            if story_link:
                href = story_link.get("href", "")
                post_url = f"https://facebook.com{href}" if href.startswith("/") else href

            posts.append({
                "post_id": post_id,
                "text": text,
                "url": post_url,
                "page_slug": page_slug,
                "fetched_at": datetime.now().isoformat()
            })

        logger.info(f"📥 {page_slug} থেকে {len(posts)}টি পোস্ট পাওয়া গেছে।")
        return posts

    def _is_bangla(self, text: str) -> bool:
        """বাংলা টেক্সট চেক করো"""
        bangla_chars = sum(1 for c in text if '\u0980' <= c <= '\u09FF')
        return bangla_chars > len(text) * 0.2  # ২০%+ বাংলা হলে বাংলা পোস্ট
