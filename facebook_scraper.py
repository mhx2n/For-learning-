import re
import json
import hashlib
import logging
import asyncio
import httpx
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin

logger = logging.getLogger(__name__)


class FacebookScraper:
    """
    Advanced Facebook Post Scraper — v4
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    • Graph API (token থাকলে)
    • mbasic.facebook.com scraping (multiple strategies)
    • Facebook Groups support
    • Share link / mibextid URL cleanup
    • Dynamic HTML parser (Facebook নতুন structure)
    """

    # UI জাংক patterns
    JUNK_RE = re.compile(
        r"^(Like|Comment|Share|See More|Translate|Reply|Follow|Report|"
        r"লাইক|কমেন্ট|শেয়ার|আরও দেখুন|অনুবাদ|রিপ্লাই|ফলো|"
        r"Write a comment.*|View \d+.*comment.*|"
        r"\d+\s*(Like|Comment|Share|লাইক|কমেন্ট|শেয়ার|Reaction).*|"
        r"Sponsored|বিজ্ঞাপন|Promoted|"
        r"\d+\s*(min|hour|day|week|month|year|ঘণ্টা|দিন|সপ্তাহ|মাস|বছর).*ago|"
        r"Just now|·|\.\.\.|More|আরও)$",
        re.IGNORECASE,
    )

    # User-Agent rotation
    USER_AGENTS = [
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 12; Samsung Galaxy S21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    ]

    def __init__(self):
        self.last_request_bytes = 0
        self._access_token: Optional[str] = None
        self._ua_index = 0

    def set_access_token(self, token: str):
        self._access_token = token.strip() if token else None

    def _get_headers(self) -> dict:
        ua = self.USER_AGENTS[self._ua_index % len(self.USER_AGENTS)]
        self._ua_index += 1
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "bn-BD,bn;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "no-cache",
            "DNT": "1",
        }

    # ══════════════════════════════════════════════════════════
    # URL CLEANUP — সবচেয়ে গুরুত্বপূর্ণ fix
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def clean_fb_url(raw_url: str) -> Tuple[str, str, bool]:
        """
        Facebook URL থেকে clean slug ও URL বের করো।
        Returns: (clean_url, slug, is_group)
        
        Examples:
          https://www.facebook.com/groups/potarona.group/?ref=share&mibextid=NSMWBT
          → (https://mbasic.facebook.com/groups/potarona.group, potarona.group, True)
          
          https://www.facebook.com/share/18rwZL6t6x/
          → (https://mbasic.facebook.com/18rwZL6t6x, 18rwZL6t6x, False)
          
          https://www.facebook.com/pagename/?ref=share&mibextid=NSMWBT
          → (https://mbasic.facebook.com/pagename, pagename, False)
        """
        raw_url = raw_url.strip()
        if not raw_url.startswith("http"):
            raw_url = "https://www.facebook.com/" + raw_url.lstrip("/")

        try:
            parsed = urlparse(raw_url)
            path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        except Exception:
            slug = raw_url.split("facebook.com/")[-1].split("?")[0].strip("/")
            return f"https://mbasic.facebook.com/{slug}", slug, False

        is_group = False
        slug = ""

        # Case 1: /groups/<group_slug>/
        if path_parts and path_parts[0] == "groups":
            is_group = True
            slug = path_parts[1] if len(path_parts) > 1 else ""
            clean_url = f"https://mbasic.facebook.com/groups/{slug}"

        # Case 2: /share/<share_id>/  →  short share link
        elif path_parts and path_parts[0] == "share":
            slug = path_parts[1] if len(path_parts) > 1 else ""
            clean_url = f"https://mbasic.facebook.com/{slug}"

        # Case 3: /<page_slug>/  (normal page)
        elif path_parts:
            # query param ?ref=... ও mibextid=... থাকলেও আমরা শুধু path নেব
            slug = path_parts[0]
            # যদি slug-এ ? থাকে তাহলে কেটে দাও
            slug = slug.split("?")[0]
            clean_url = f"https://mbasic.facebook.com/{slug}"

        else:
            slug = raw_url
            clean_url = f"https://mbasic.facebook.com/{slug}"

        return clean_url, slug, is_group

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
        """Facebook Page/Group থেকে পোস্ট আনো।"""

        # slug ও url পরিষ্কার করো (DB-তে dirty slug থাকতে পারে)
        clean_url, clean_slug, is_group = self.clean_fb_url(page_url or page_slug)

        logger.info(f"🔍 Fetch: slug={clean_slug}, group={is_group}, url={clean_url}")

        if self._access_token and not is_group:
            logger.info(f"🔑 Graph API দিয়ে fetch: {clean_slug}")
            posts = await self._fetch_via_graph_api(
                clean_slug, clean_url, fetch_old=fetch_old, max_pages=max_pages
            )
            if posts:
                return posts
            logger.info("Graph API ব্যর্থ — mbasic fallback")

        logger.info(f"🌐 mbasic দিয়ে fetch: {clean_slug} (group={is_group})")
        return await self._fetch_via_mbasic(
            clean_slug, clean_url, fetch_old=fetch_old, is_group=is_group
        )

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
        all_posts = []
        page_id = await self._get_page_id(page_slug)
        if not page_id:
            logger.warning(f"Page ID পাওয়া যায়নি: {page_slug}")
            return []

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

                    next_url = data.get("paging", {}).get("next")
                    url = next_url if (fetch_old and next_url) else None
                    page_count += 1
                    if url:
                        await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"Graph API fetch error: {e}")
                    break

        logger.info(f"📥 Graph API: {page_slug} → {len(all_posts)}টি পোস্ট")
        return all_posts

    async def _get_page_id(self, page_slug: str) -> Optional[str]:
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
    # METHOD 2 — MBASIC SCRAPER (Advanced)
    # ══════════════════════════════════════════════════════════

    async def _fetch_via_mbasic(
        self,
        page_slug: str,
        page_url: str,
        fetch_old: bool = False,
        is_group: bool = False,
    ) -> List[Dict]:
        all_posts = []

        # mbasic URL তৈরি
        if page_url.startswith("https://mbasic.facebook.com"):
            start_url = page_url
        elif is_group:
            start_url = f"https://mbasic.facebook.com/groups/{page_slug}"
        else:
            start_url = f"https://mbasic.facebook.com/{page_slug}"

        urls_to_fetch = [start_url]

        async with httpx.AsyncClient(
            headers=self._get_headers(),
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=2),
        ) as client:
            visited = set()
            page_num = 0
            max_mbasic_pages = 5 if fetch_old else 1

            while urls_to_fetch and page_num < max_mbasic_pages:
                url = urls_to_fetch.pop(0)
                if url in visited:
                    continue
                visited.add(url)

                try:
                    logger.info(f"🌐 Fetching page {page_num+1}: {url}")

                    # Header refresh করো প্রতিটি request-এ
                    client.headers.update(self._get_headers())

                    resp = await client.get(url)
                    self.last_request_bytes += len(resp.content)

                    logger.info(f"📡 HTTP {resp.status_code} | {len(resp.content)} bytes | URL: {resp.url}")

                    if resp.status_code == 302 or resp.status_code == 301:
                        logger.info(f"↪️ Redirect to: {resp.headers.get('location', '?')}")

                    if resp.status_code != 200:
                        logger.warning(f"HTTP {resp.status_code}: {url}")
                        # login redirect? Try with /pg/ prefix
                        if resp.status_code in (400, 302) and not is_group:
                            alt_url = f"https://mbasic.facebook.com/pg/{page_slug}/posts"
                            if alt_url not in visited:
                                urls_to_fetch.insert(0, alt_url)
                        continue

                    posts, next_url = self._parse_mbasic_advanced(
                        resp.text, page_slug, url, is_group
                    )
                    logger.info(f"📦 Parsed {len(posts)} posts from page {page_num+1}")
                    all_posts.extend(posts)
                    page_num += 1

                    if fetch_old and next_url and next_url not in visited:
                        urls_to_fetch.append(next_url)
                        await asyncio.sleep(2)

                except httpx.TimeoutException:
                    logger.error(f"⏱️ Timeout: {url}")
                except Exception as e:
                    logger.error(f"mbasic error {url}: {e}", exc_info=True)

        # Dedup across pages
        seen_ids = set()
        unique_posts = []
        for p in all_posts:
            if p["post_id"] not in seen_ids:
                seen_ids.add(p["post_id"])
                unique_posts.append(p)

        logger.info(f"📥 mbasic total: {page_slug} → {len(unique_posts)}টি unique পোস্ট")
        return unique_posts

    def _parse_mbasic_advanced(
        self, html: str, page_slug: str, base_url: str, is_group: bool = False
    ) -> Tuple[List[Dict], Optional[str]]:
        """
        Advanced mbasic HTML parser — multiple fallback strategies
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("beautifulsoup4 ইন্সটল করো: pip install beautifulsoup4")
            return [], None

        soup = BeautifulSoup(html, "html.parser")
        posts = []
        seen_texts = set()

        # ── Strategy 1: #m_story_* divs ──────────────────────────────
        story_divs = soup.find_all("div", id=re.compile(r"^m_story"))
        logger.debug(f"Strategy 1 (m_story): {len(story_divs)} divs")

        # ── Strategy 2: article tags ──────────────────────────────────
        if not story_divs:
            story_divs = soup.find_all("article")
            logger.debug(f"Strategy 2 (article): {len(story_divs)} tags")

        # ── Strategy 3: div[data-ft] — Facebook internal data attribute
        if not story_divs:
            story_divs = soup.find_all("div", attrs={"data-ft": True})
            logger.debug(f"Strategy 3 (data-ft): {len(story_divs)} divs")

        # ── Strategy 4: div[data-store] ──────────────────────────────
        if not story_divs:
            story_divs = soup.find_all("div", attrs={"data-store": True})
            logger.debug(f"Strategy 4 (data-store): {len(story_divs)} divs")

        # ── Strategy 5: div.story_body_container ─────────────────────
        if not story_divs:
            story_divs = soup.find_all("div", class_=re.compile(r"story|post|feed", re.I))
            logger.debug(f"Strategy 5 (class story/post/feed): {len(story_divs)} divs")

        # ── Strategy 6: Smart text block extraction ───────────────────
        if not story_divs:
            logger.debug("Strategy 6: Smart text block extraction")
            story_divs = self._smart_extract_blocks(soup)
            logger.debug(f"Strategy 6 found: {len(story_divs)} blocks")

        # ── Strategy 7: Direct <p> text extraction ────────────────────
        if not story_divs:
            logger.debug("Strategy 7: paragraph extraction")
            return self._extract_from_paragraphs(soup, page_slug, base_url), self._find_next_url(soup, base_url)

        # ── পোস্ট বের করো ─────────────────────────────────────────────
        for div in story_divs[:20]:
            raw_text = div.get_text(separator="\n", strip=True)
            cleaned = self._clean_fb_text(raw_text)

            if len(cleaned) < 30 or len(cleaned) > 5000:
                continue

            key = cleaned[:80]
            if key in seen_texts:
                continue
            seen_texts.add(key)

            post_url = self._extract_post_url(div, base_url)
            post_id = hashlib.md5(f"{page_slug}:{cleaned[:100]}".encode()).hexdigest()[:16]

            posts.append({
                "post_id": post_id,
                "text": cleaned,
                "url": post_url,
                "page_slug": page_slug,
                "fetched_at": datetime.now().isoformat(),
            })

        next_url = self._find_next_url(soup, base_url)
        return posts, next_url

    def _smart_extract_blocks(self, soup) -> list:
        """
        Text-heavy div blocks খোঁজো যেগুলো likely posts।
        নতুন Facebook mbasic structure-এর জন্য।
        """
        candidates = []
        seen_texts = set()

        # সব div এর মধ্যে যেগুলোতে পর্যাপ্ত text আছে
        for div in soup.find_all(["div", "section", "td"]):
            text = div.get_text(separator=" ", strip=True)

            # কমপক্ষে ৫০ char
            if len(text) < 50 or len(text) > 6000:
                continue

            # বাংলা বা ইংরেজি যথেষ্ট text
            has_content = (
                self._has_bangla(text) or
                len([w for w in text.split() if len(w) > 3]) >= 8
            )
            if not has_content:
                continue

            # UI element না হলে
            if self._is_ui_element(text):
                continue

            # Nested div বেশি না (leaf-like)
            child_divs = len(div.find_all("div", recursive=False))
            if child_divs > 5:
                continue

            key = text[:80]
            if key in seen_texts:
                continue
            seen_texts.add(key)

            candidates.append(div)
            if len(candidates) >= 20:
                break

        return candidates

    def _extract_from_paragraphs(self, soup, page_slug: str, base_url: str) -> List[Dict]:
        """<p> tag থেকে সরাসরি text বের করো"""
        posts = []
        seen = set()
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) < 50:
                continue
            if self._is_ui_element(text):
                continue
            key = text[:80]
            if key in seen:
                continue
            seen.add(key)
            post_id = hashlib.md5(f"{page_slug}:{text[:100]}".encode()).hexdigest()[:16]
            posts.append({
                "post_id": post_id,
                "text": text,
                "url": base_url,
                "page_slug": page_slug,
                "fetched_at": datetime.now().isoformat(),
            })
        return posts[:15]

    def _find_next_url(self, soup, base_url: str) -> Optional[str]:
        """পরের page-এর URL খোঁজো"""
        keywords = [
            "see more posts", "আরও পোস্ট", "more posts", "older posts",
            "পুরোনো পোস্ট", "load more", "আরও লোড",
            "next page", "পরের পাতা",
        ]
        for a in soup.find_all("a", href=True):
            text_lower = a.get_text(strip=True).lower()
            href = a["href"]
            if any(kw in text_lower for kw in keywords):
                if href.startswith("/"):
                    return f"https://mbasic.facebook.com{href}"
                elif href.startswith("http"):
                    return href
                else:
                    return urljoin(base_url, href)

        # ?cursor= বা ?page= link
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "cursor=" in href or "&page=" in href or "start_time=" in href:
                if href.startswith("/"):
                    return f"https://mbasic.facebook.com{href}"
                elif href.startswith("http"):
                    return href

        return None

    # ══════════════════════════════════════════════════════════
    # HELPER METHODS
    # ══════════════════════════════════════════════════════════

    def _clean_fb_text(self, raw: str) -> str:
        """Facebook UI জাংক সরিয়ে clean text দাও"""
        lines = raw.splitlines()
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if not line or len(line) < 2:
                continue
            if self.JUNK_RE.match(line):
                continue
            # শুধু সংখ্যা/emoji line বাদ দাও
            if re.match(r"^[\d\s\.,]+$", line):
                continue
            cleaned_lines.append(line)

        text = "\n".join(cleaned_lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _is_ui_element(self, text: str) -> bool:
        """UI navigation text কিনা"""
        ui_keywords = [
            "log in", "sign up", "create account", "facebook",
            "লগইন", "সাইন আপ", "নিবন্ধন", "হোম", "home", "menu",
            "privacy", "terms", "cookies", "গোপনীয়তা",
        ]
        text_lower = text.lower().strip()
        if len(text_lower) < 100 and any(kw in text_lower for kw in ui_keywords):
            return True
        return False

    def _extract_post_url(self, div, base_url: str) -> str:
        """div থেকে post URL বের করো"""
        patterns = [
            re.compile(r"/story\.php"),
            re.compile(r"/permalink/"),
            re.compile(r"/posts/"),
            re.compile(r"story_fbid="),
            re.compile(r"/groups/.+/permalink/"),
        ]
        for pat in patterns:
            link = div.find("a", href=pat)
            if link:
                href = link.get("href", "")
                if href.startswith("/"):
                    return f"https://facebook.com{href}"
                return href
        return base_url

    def _has_bangla(self, text: str) -> bool:
        bangla_chars = sum(1 for c in text if "\u0980" <= c <= "\u09FF")
        return bangla_chars >= 5

    def _is_mostly_bangla(self, text: str) -> bool:
        if not text:
            return False
        bangla = sum(1 for c in text if "\u0980" <= c <= "\u09FF")
        return bangla / len(text) >= 0.3
