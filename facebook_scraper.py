import re
import json
import hashlib
import logging
import asyncio
import httpx
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class FacebookScraper:
    """
    Facebook Page থেকে পোস্ট সংগ্রহ করে।
    ১. Facebook Graph API (Access Token থাকলে — সবচেয়ে নির্ভরযোগ্য)
    ২. mbasic.facebook.com fallback (Token না থাকলে)
    পুরোনো পোস্টও আনতে পারে pagination-এর মাধ্যমে।
    """

    def __init__(self):
        self.last_request_bytes = 0
        self.session_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "bn-BD,bn;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        self._access_token: Optional[str] = None

    def set_access_token(self, token: str):
        """Facebook Graph API Access Token সেট করো"""
        self._access_token = token.strip() if token else None

    # ══════════════════════════════════════════════════════════
    # PUBLIC — প্রধান ফাংশন
    # ══════════════════════════════════════════════════════════

    async def fetch_posts(
        self,
        page_slug: str,
        page_url: str,
        fetch_old: bool = False,
        max_pages: int = 3,
    ) -> List[Dict]:
        """
        Facebook Page থেকে পোস্ট আনো।
        fetch_old=True হলে pagination দিয়ে পুরোনো পোস্টও আনবে।
        max_pages = কতটি pagination page ঘুরবে (Graph API)।
        """
        if self._access_token:
            logger.info(f"🔑 Graph API দিয়ে fetch: {page_slug}")
            return await self._fetch_via_graph_api(
                page_slug, page_url, fetch_old=fetch_old, max_pages=max_pages
            )
        else:
            logger.info(f"🌐 mbasic দিয়ে fetch: {page_slug}")
            return await self._fetch_via_mbasic(page_slug, page_url, fetch_old=fetch_old)

    # ══════════════════════════════════════════════════════════
    # METHOD 1 — FACEBOOK GRAPH API
    # ══════════════════════════════════════════════════════════

    async def _fetch_via_graph_api(
        self,
        page_slug: str,
        page_url: str,
        fetch_old: bool = False,
        max_pages: int = 3,
    ) -> List[Dict]:
        """Graph API দিয়ে posts আনো (pagination সহ)"""
        all_posts = []
        # প্রথমে page ID বের করো slug থেকে
        page_id = await self._get_page_id(page_slug)
        if not page_id:
            logger.warning(f"Page ID পাওয়া যায়নি: {page_slug} — mbasic fallback")
            return await self._fetch_via_mbasic(page_slug, page_url, fetch_old=fetch_old)

        url = (
            f"https://graph.facebook.com/v19.0/{page_id}/posts"
            f"?fields=id,message,story,created_time,permalink_url"
            f"&limit=25"
            f"&access_token={self._access_token}"
        )

        page_count = 0
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            while url and page_count < max_pages:
                try:
                    resp = await client.get(url)
                    self.last_request_bytes += len(resp.content)
                    data = resp.json()

                    if "error" in data:
                        logger.error(f"Graph API error: {data['error'].get('message')}")
                        break

                    for item in data.get("data", []):
                        text = item.get("message") or item.get("story") or ""
                        text = text.strip()
                        if len(text) < 30:
                            continue
                        post_id = hashlib.md5(
                            f"{page_slug}:{item['id']}".encode()
                        ).hexdigest()[:16]
                        all_posts.append({
                            "post_id": post_id,
                            "fb_raw_id": item.get("id", ""),
                            "text": text,
                            "url": item.get("permalink_url", ""),
                            "page_slug": page_slug,
                            "created_time": item.get("created_time", ""),
                            "fetched_at": datetime.now().isoformat(),
                        })

                    # পরের page-এর URL
                    next_url = data.get("paging", {}).get("next")
                    url = next_url if (fetch_old and next_url) else None
                    page_count += 1

                    if url:
                        await asyncio.sleep(1)  # rate limit এড়াও

                except Exception as e:
                    logger.error(f"Graph API fetch error: {e}")
                    break

        logger.info(f"📥 Graph API: {page_slug} → {len(all_posts)}টি পোস্ট")
        return all_posts

    async def _get_page_id(self, page_slug: str) -> Optional[str]:
        """Page slug থেকে numeric page ID বের করো"""
        # যদি ইতিমধ্যে numeric হয়
        if page_slug.isdigit():
            return page_slug
        url = (
            f"https://graph.facebook.com/v19.0/{page_slug}"
            f"?fields=id&access_token={self._access_token}"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                data = resp.json()
                return data.get("id")
        except Exception as e:
            logger.error(f"Page ID lookup error: {e}")
            return None

    # ══════════════════════════════════════════════════════════
    # METHOD 2 — MBASIC SCRAPER (Fallback)
    # ══════════════════════════════════════════════════════════

    async def _fetch_via_mbasic(
        self,
        page_slug: str,
        page_url: str,
        fetch_old: bool = False,
    ) -> List[Dict]:
        """mbasic.facebook.com থেকে পোস্ট আনো (pagination সহ)"""
        all_posts = []
        urls_to_fetch = [f"https://mbasic.facebook.com/{page_slug}"]

        async with httpx.AsyncClient(
            headers=self.session_headers,
            timeout=25.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=2),
        ) as client:
            visited = set()
            while urls_to_fetch:
                url = urls_to_fetch.pop(0)
                if url in visited:
                    continue
                visited.add(url)

                try:
                    logger.info(f"🌐 Fetching: {url}")
                    resp = await client.get(url)
                    self.last_request_bytes += len(resp.content)

                    if resp.status_code != 200:
                        logger.warning(f"HTTP {resp.status_code}: {url}")
                        continue

                    posts, next_url = self._parse_mbasic_v2(
                        resp.text, page_slug, page_url
                    )
                    all_posts.extend(posts)

                    # পুরোনো পোস্ট চাইলে পরের page-ও যাও
                    if fetch_old and next_url and next_url not in visited:
                        urls_to_fetch.append(next_url)
                        await asyncio.sleep(2)  # rate limit

                except httpx.TimeoutException:
                    logger.error(f"Timeout: {url}")
                except Exception as e:
                    logger.error(f"mbasic error {url}: {e}")

        logger.info(f"📥 mbasic: {page_slug} → {len(all_posts)}টি পোস্ট")
        return all_posts

    def _parse_mbasic_v2(
        self, html: str, page_slug: str, base_url: str
    ):
        """mbasic HTML পার্স করো — উন্নত version"""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("beautifulsoup4 ইন্সটল করো")
            return [], None

        soup = BeautifulSoup(html, "html.parser")
        posts = []

        # ── পোস্ট খোঁজার কৌশল (একাধিক selector) ──────────────

        # কৌশল ১: m_story div
        story_divs = soup.find_all("div", id=re.compile(r"^m_story"))

        # কৌশল ২: article tag
        if not story_divs:
            story_divs = soup.find_all("article")

        # কৌশল ৩: বড় text block যুক্ত div (fallback)
        if not story_divs:
            candidates = []
            for div in soup.find_all("div"):
                text = div.get_text(strip=True)
                # অন্তত ৫০ char, বাংলা text আছে
                if len(text) >= 50 and self._has_bangla(text):
                    # শুধু leaf-like div (nested div বেশি নেই)
                    child_divs = div.find_all("div", recursive=False)
                    if len(child_divs) <= 3:
                        candidates.append(div)
            story_divs = candidates[:15]

        # ── প্রতিটি div থেকে পোস্ট extract ──────────────────

        seen_texts = set()
        for div in story_divs[:15]:
            raw_text = div.get_text(separator="\n", strip=True)

            # Clean up: UI জাংক সরাও
            cleaned = self._clean_fb_text(raw_text)

            if len(cleaned) < 40 or len(cleaned) > 3000:
                continue

            # Duplicate check (প্রথম ৮০ char দিয়ে)
            key = cleaned[:80]
            if key in seen_texts:
                continue
            seen_texts.add(key)

            # Post URL খোঁজো
            post_url = self._extract_post_url(div)

            post_id = hashlib.md5(
                f"{page_slug}:{cleaned[:100]}".encode()
            ).hexdigest()[:16]

            posts.append({
                "post_id": post_id,
                "text": cleaned,
                "url": post_url,
                "page_slug": page_slug,
                "fetched_at": datetime.now().isoformat(),
            })

        # ── "আরও পোস্ট দেখো" বা "See More" link ──────────────

        next_url = None
        for a in soup.find_all("a", href=True):
            text_lower = a.get_text(strip=True).lower()
            href = a["href"]
            if any(kw in text_lower for kw in ["see more posts", "আরও পোস্ট", "more posts", "older posts"]):
                next_url = (
                    f"https://mbasic.facebook.com{href}"
                    if href.startswith("/")
                    else href
                )
                break

        return posts, next_url

    # ══════════════════════════════════════════════════════════
    # HELPER METHODS
    # ══════════════════════════════════════════════════════════

    def _clean_fb_text(self, raw: str) -> str:
        """Facebook-এর UI জাংক পরিষ্কার করো"""
        # প্রতিটি লাইন আলাদা করে clean করো
        lines = raw.splitlines()
        cleaned_lines = []
        junk_patterns = re.compile(
            r"^(Like|Comment|Share|See More|Translate|Reply|Follow|"
            r"লাইক|কমেন্ট|শেয়ার|আরও দেখুন|অনুবাদ|"
            r"Write a comment|View \d+ comment|"
            r"\d+ (Like|Comment|Share|লাইক|কমেন্ট|শেয়ার)|"
            r"Sponsored|বিজ্ঞাপন|"
            r"mins?|hours?|days?|weeks?|"
            r"\d+[mhd]|Just now|·).*$",
            re.IGNORECASE,
        )
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if junk_patterns.match(line):
                continue
            if len(line) < 3:
                continue
            cleaned_lines.append(line)

        text = "\n".join(cleaned_lines)
        # Multiple newlines → double newline
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_post_url(self, div) -> str:
        """div থেকে post URL বের করো"""
        patterns = [
            re.compile(r"/story\.php"),
            re.compile(r"/permalink/"),
            re.compile(r"/posts/"),
            re.compile(r"story_fbid="),
        ]
        for pat in patterns:
            link = div.find("a", href=pat)
            if link:
                href = link.get("href", "")
                if href.startswith("/"):
                    return f"https://facebook.com{href}"
                return href
        return ""

    def _has_bangla(self, text: str) -> bool:
        """বাংলা টেক্সট আছে কিনা চেক করো"""
        bangla_chars = sum(1 for c in text if "\u0980" <= c <= "\u09FF")
        return bangla_chars >= 5

    def _is_mostly_bangla(self, text: str) -> bool:
        """৩০%+ বাংলা কিনা"""
        if not text:
            return False
        bangla = sum(1 for c in text if "\u0980" <= c <= "\u09FF")
        return bangla / len(text) >= 0.3
