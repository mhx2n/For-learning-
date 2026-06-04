import re
import json
import hashlib
import logging
import asyncio
import httpx
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)


class FacebookScraper:
    """
    Advanced Facebook Post Scraper — v5
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    • Graph API (token থাকলে — সবচেয়ে নির্ভরযোগ্য)
    • m.facebook.com scraping (mbasic block হলে fallback)
    • mbasic.facebook.com scraping
    • Block/Warning page detection
    • Groups + Pages support
    • Share/mibextid URL cleanup
    """

    # Facebook block/warning indicators
    BLOCK_INDICATORS = [
        "এই ব্রাউজারে Facebook উপলভ্য নয়",
        "Facebook isn't available in this browser",
        "This browser is not supported",
        "download a supported browser",
        "ব্রাউজার ডাউনলোড করুন",
        "Chrome\nFirefox\nEdge",
        "You must log in to continue",
        "Log in to Facebook",
        "লগ ইন করুন",
        "Create new account",
        "নতুন অ্যাকাউন্ট তৈরি করুন",
        "login_form",
        "checkpoint",
        "unsupported_browser",
    ]

    # UI জাংক patterns
    JUNK_RE = re.compile(
        r"^(Like|Comment|Share|See More|Translate|Reply|Follow|Report|"
        r"লাইক|কমেন্ট|শেয়ার|আরও দেখুন|অনুবাদ|রিপ্লাই|ফলো|"
        r"Write a comment.*|View \d+.*comment.*|"
        r"\d+\s*(Like|Comment|Share|লাইক|কমেন্ট|শেয়ার|Reaction).*|"
        r"Sponsored|বিজ্ঞাপন|Promoted|"
        r"\d+\s*(min|hour|day|week|month|year|ঘণ্টা|দিন|সপ্তাহ|মাস|বছর).*ago|"
        r"Just now|·|\.\.\.|More|আরও|"
        r"Chrome|Firefox|Edge|Safari|Opera|"
        r"ব্রাউজার|browser|Download|ডাউনলোড)$",
        re.IGNORECASE,
    )

    # mbasic-এর জন্য ভালো User-Agent (old/simple browser যেন block না হয়)
    MBASIC_USER_AGENTS = [
        # পুরনো Android browser — mbasic-এর জন্য ভালো
        "Mozilla/5.0 (Linux; Android 4.4.2; GT-I9500 Build/KOT49H) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/30.0.0.0 Mobile Safari/537.36",
        # Nokia/feature phone style
        "Mozilla/5.0 (Series40; Nokia305/05.97; Profile/MIDP-2.1 Configuration/CLDC-1.1) Gecko/20100401 S40OviBrowser/3.1.1.0.27",
        # Older Android WebView
        "Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/45.0.2454.94 Mobile Safari/537.36",
        # Simple mobile browser
        "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Mobile Safari/537.36",
    ]

    # m.facebook.com-এর জন্য modern User-Agent
    M_FB_USER_AGENTS = [
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    ]

    def __init__(self):
        self.last_request_bytes = 0
        self._access_token: Optional[str] = None
        self._ua_index = 0

    def set_access_token(self, token: str):
        self._access_token = token.strip() if token else None

    def _is_blocked_response(self, html: str) -> bool:
        """Facebook block/login/warning page detect করো"""
        for indicator in self.BLOCK_INDICATORS:
            if indicator in html:
                logger.warning(f"🚫 Block detected: '{indicator[:40]}'")
                return True
        # login form check
        if 'id="login_form"' in html or 'name="login"' in html:
            return True
        # checkpoint
        if "/checkpoint/" in html and "Enter" in html:
            return True
        return False

    def _get_mbasic_headers(self) -> dict:
        ua = self.MBASIC_USER_AGENTS[self._ua_index % len(self.MBASIC_USER_AGENTS)]
        self._ua_index += 1
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    def _get_m_fb_headers(self) -> dict:
        ua = self.M_FB_USER_AGENTS[self._ua_index % len(self.M_FB_USER_AGENTS)]
        self._ua_index += 1
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "bn-BD,bn;q=0.9,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    # ══════════════════════════════════════════════════════════
    # URL CLEANUP
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def clean_fb_url(raw_url: str) -> Tuple[str, str, bool]:
        """
        Facebook URL clean করো।
        Returns: (clean_url, slug, is_group)

        Examples:
          https://www.facebook.com/groups/likhalikhi/?ref=share&mibextid=NSMWBT
          → ("https://mbasic.facebook.com/groups/likhalikhi", "likhalikhi", True)

          https://www.facebook.com/share/18rwZL6t6x/
          → ("https://mbasic.facebook.com/18rwZL6t6x", "18rwZL6t6x", False)
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

        if path_parts and path_parts[0] == "groups":
            is_group = True
            slug = path_parts[1] if len(path_parts) > 1 else ""
            clean_url = f"https://mbasic.facebook.com/groups/{slug}"

        elif path_parts and path_parts[0] == "share":
            slug = path_parts[1] if len(path_parts) > 1 else ""
            clean_url = f"https://mbasic.facebook.com/{slug}"

        elif path_parts:
            slug = path_parts[0].split("?")[0]
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

        clean_url, clean_slug, is_group = self.clean_fb_url(page_url or page_slug)
        logger.info(f"🔍 Fetch: slug={clean_slug}, group={is_group}")

        # Strategy 1: Graph API (সবচেয়ে নির্ভরযোগ্য)
        if self._access_token and not is_group:
            logger.info(f"🔑 Graph API: {clean_slug}")
            posts = await self._fetch_via_graph_api(
                clean_slug, clean_url, fetch_old=fetch_old, max_pages=max_pages
            )
            if posts:
                return posts
            logger.info("Graph API ব্যর্থ — mbasic try করছি")

        # Strategy 2: mbasic.facebook.com
        logger.info(f"🌐 mbasic try: {clean_slug}")
        posts = await self._fetch_via_scraper(
            clean_slug, clean_url, fetch_old=fetch_old,
            is_group=is_group, use_mbasic=True
        )
        if posts:
            return posts

        # Strategy 3: m.facebook.com (mbasic block হলে)
        logger.info(f"📱 m.facebook.com try: {clean_slug}")
        posts = await self._fetch_via_scraper(
            clean_slug, clean_url, fetch_old=fetch_old,
            is_group=is_group, use_mbasic=False
        )
        return posts

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
            return []

        url = (
            f"https://graph.facebook.com/v19.0/{page_id}/posts"
            f"?fields=id,message,story,created_time,permalink_url"
            f"&limit=25&access_token={self._access_token}"
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
                        text = (item.get("message") or item.get("story") or "").strip()
                        if len(text) < 30:
                            continue
                        post_id = hashlib.md5(
                            f"{page_slug}:{item['id']}".encode()
                        ).hexdigest()[:16]
                        all_posts.append({
                            "post_id": post_id,
                            "text": text,
                            "url": item.get("permalink_url", ""),
                            "page_slug": page_slug,
                            "fetched_at": datetime.now().isoformat(),
                        })
                    next_url = data.get("paging", {}).get("next")
                    url = next_url if (fetch_old and next_url) else None
                    page_count += 1
                    if url:
                        await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Graph API error: {e}")
                    break

        logger.info(f"📥 Graph API: {len(all_posts)} posts")
        return all_posts

    async def _get_page_id(self, page_slug: str) -> Optional[str]:
        if page_slug.isdigit():
            return page_slug
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://graph.facebook.com/v19.0/{page_slug}"
                    f"?fields=id&access_token={self._access_token}"
                )
                return resp.json().get("id")
        except Exception as e:
            logger.error(f"Page ID error: {e}")
            return None

    # ══════════════════════════════════════════════════════════
    # METHOD 2 — SCRAPER (mbasic + m.facebook.com)
    # ══════════════════════════════════════════════════════════

    async def _fetch_via_scraper(
        self,
        page_slug: str,
        page_url: str,
        fetch_old: bool = False,
        is_group: bool = False,
        use_mbasic: bool = True,
    ) -> List[Dict]:

        base_domain = "mbasic.facebook.com" if use_mbasic else "m.facebook.com"

        # URL তৈরি
        if is_group:
            start_url = f"https://{base_domain}/groups/{page_slug}"
        else:
            start_url = f"https://{base_domain}/{page_slug}"

        # m.facebook.com-এ /pg/ path ভালো কাজ করে
        alt_urls = []
        if not is_group:
            if use_mbasic:
                alt_urls = [
                    f"https://mbasic.facebook.com/pg/{page_slug}/posts/",
                    f"https://mbasic.facebook.com/{page_slug}?v=timeline",
                ]
            else:
                alt_urls = [
                    f"https://m.facebook.com/{page_slug}?v=timeline",
                    f"https://m.facebook.com/pg/{page_slug}/posts/",
                ]

        headers_fn = self._get_mbasic_headers if use_mbasic else self._get_m_fb_headers
        all_posts = []

        async with httpx.AsyncClient(
            headers=headers_fn(),
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=2),
        ) as client:
            visited = set()
            urls_to_try = [start_url] + alt_urls
            page_num = 0
            max_scrape_pages = 5 if fetch_old else 2
            found_real_content = False

            while urls_to_try and page_num < max_scrape_pages:
                url = urls_to_try.pop(0)
                if url in visited:
                    continue
                visited.add(url)

                try:
                    logger.info(f"{'mbasic' if use_mbasic else 'm.fb'} [{page_num+1}]: {url}")
                    client.headers.update(headers_fn())
                    resp = await client.get(url)
                    self.last_request_bytes += len(resp.content)

                    html = resp.text
                    logger.info(f"📡 HTTP {resp.status_code} | {len(html)} chars")

                    if resp.status_code != 200:
                        logger.warning(f"HTTP {resp.status_code}: {url}")
                        continue

                    # Block/warning page detect করো
                    if self._is_blocked_response(html):
                        logger.warning(f"🚫 Blocked/login page — skipping: {url}")
                        continue

                    posts, next_url = self._parse_html(html, page_slug, url, is_group)

                    if posts:
                        logger.info(f"✅ {len(posts)} posts found at page {page_num+1}")
                        all_posts.extend(posts)
                        found_real_content = True
                        page_num += 1

                        if fetch_old and next_url and next_url not in visited:
                            urls_to_try.insert(0, next_url)
                            await asyncio.sleep(2)
                    else:
                        logger.info(f"⚠️ No posts at: {url}")
                        if not found_real_content:
                            # Try next URL from the list
                            page_num += 1

                except httpx.TimeoutException:
                    logger.error(f"⏱️ Timeout: {url}")
                except Exception as e:
                    logger.error(f"Scraper error: {e}", exc_info=True)

        # Deduplicate
        seen, unique = set(), []
        for p in all_posts:
            if p["post_id"] not in seen:
                seen.add(p["post_id"])
                unique.append(p)

        domain = "mbasic" if use_mbasic else "m.fb"
        logger.info(f"📥 {domain}: {page_slug} → {len(unique)} unique posts")
        return unique

    # ══════════════════════════════════════════════════════════
    # HTML PARSER
    # ══════════════════════════════════════════════════════════

    def _parse_html(
        self, html: str, page_slug: str, base_url: str, is_group: bool = False
    ) -> Tuple[List[Dict], Optional[str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("beautifulsoup4 দরকার: pip install beautifulsoup4")
            return [], None

        soup = BeautifulSoup(html, "html.parser")
        posts = []
        seen_texts = set()

        # ── Block/junk page early check ──
        page_text = soup.get_text()
        if self._is_blocked_response(page_text):
            logger.warning("Block page detected in parsed HTML")
            return [], None

        story_divs = []

        # Strategy 1: id="m_story_*"
        story_divs = soup.find_all("div", id=re.compile(r"^m_story"))

        # Strategy 2: article tags
        if not story_divs:
            story_divs = soup.find_all("article")

        # Strategy 3: data-ft attribute (Facebook internal)
        if not story_divs:
            story_divs = soup.find_all("div", attrs={"data-ft": True})

        # Strategy 4: data-store
        if not story_divs:
            story_divs = soup.find_all("div", attrs={"data-store": True})

        # Strategy 5: class matching
        if not story_divs:
            story_divs = soup.find_all(
                "div",
                class_=re.compile(r"(story|post|feed|update)", re.I)
            )

        # Strategy 6: Smart block extraction
        if not story_divs:
            story_divs = self._smart_blocks(soup)

        logger.debug(f"Found {len(story_divs)} candidate blocks")

        for div in story_divs[:20]:
            raw = div.get_text(separator="\n", strip=True)
            cleaned = self._clean_text(raw)

            # Block content skip করো
            if self._is_blocked_response(cleaned):
                continue

            if len(cleaned) < 40 or len(cleaned) > 5000:
                continue

            # "Chrome Firefox Edge" pattern skip
            browser_names = sum(1 for b in ["Chrome", "Firefox", "Edge", "Safari"] if b in cleaned)
            if browser_names >= 2 and len(cleaned) < 200:
                continue

            key = cleaned[:80]
            if key in seen_texts:
                continue
            seen_texts.add(key)

            post_url = self._extract_url(div, base_url)
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

    def _smart_blocks(self, soup) -> list:
        """Text-heavy content blocks খোঁজো"""
        candidates = []
        seen = set()
        for tag in soup.find_all(["div", "section", "td"]):
            text = tag.get_text(separator=" ", strip=True)
            if len(text) < 60 or len(text) > 6000:
                continue
            if self._is_blocked_response(text):
                continue
            has_content = (
                self._has_bangla(text)
                or len([w for w in text.split() if len(w) > 3]) >= 8
            )
            if not has_content:
                continue
            if self._is_ui_noise(text):
                continue
            child_divs = len(tag.find_all("div", recursive=False))
            if child_divs > 6:
                continue
            key = text[:80]
            if key in seen:
                continue
            seen.add(key)
            candidates.append(tag)
            if len(candidates) >= 20:
                break
        return candidates

    def _find_next_url(self, soup, base_url: str) -> Optional[str]:
        keywords = [
            "see more posts", "আরও পোস্ট", "more posts", "older posts",
            "পুরোনো পোস্ট", "load more", "next page", "পরের পাতা",
        ]
        for a in soup.find_all("a", href=True):
            text_lower = a.get_text(strip=True).lower()
            href = a["href"]
            if any(kw in text_lower for kw in keywords):
                if href.startswith("/"):
                    domain = base_url.split("/")[2]
                    return f"https://{domain}{href}"
                elif href.startswith("http"):
                    return href
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "cursor=" in href or "start_time=" in href:
                if href.startswith("/"):
                    domain = base_url.split("/")[2]
                    return f"https://{domain}{href}"
                elif href.startswith("http"):
                    return href
        return None

    # ══════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════

    def _clean_text(self, raw: str) -> str:
        lines = raw.splitlines()
        cleaned = []
        for line in lines:
            line = line.strip()
            if not line or len(line) < 2:
                continue
            if self.JUNK_RE.match(line):
                continue
            if re.match(r"^[\d\s\.,]+$", line):
                continue
            cleaned.append(line)
        text = "\n".join(cleaned)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _is_ui_noise(self, text: str) -> bool:
        noise = [
            "log in", "sign up", "create account", "facebook",
            "লগইন", "সাইন আপ", "নিবন্ধন", "হোম", "menu",
            "privacy", "terms", "cookies",
            "Chrome", "Firefox", "Edge",
            "ব্রাউজার ডাউনলোড",
        ]
        tl = text.lower()
        if len(text) < 150 and any(n.lower() in tl for n in noise):
            return True
        return False

    def _extract_url(self, div, base_url: str) -> str:
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
                    domain = base_url.split("/")[2]
                    return f"https://facebook.com{href}"
                return href
        return base_url

    def _has_bangla(self, text: str) -> bool:
        return sum(1 for c in text if "\u0980" <= c <= "\u09FF") >= 5
