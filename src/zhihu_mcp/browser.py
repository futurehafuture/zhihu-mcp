"""Zhihu browser client using Playwright for authentication and data extraction."""

import asyncio
import json
import logging
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

from markdownify import markdownify as md

from zhihu_mcp.config import ZhihuConfig
from zhihu_mcp.models import (
    SearchOutput,
    SearchResultItem,
    QuestionOutput,
    AnswerItem,
    ArticleOutput,
)

logger = logging.getLogger(__name__)

ZHIHU_BASE = "https://www.zhihu.com"
ZHIHU_ZHUANLAN_BASE = "https://zhuanlan.zhihu.com"
LOGIN_URL = f"{ZHIHU_BASE}/signin"
LOGIN_TIMEOUT_MS = 300_000  # 5 minutes


class ZhihuBrowser:
    """Manages Playwright browser for Zhihu interactions."""

    def __init__(self, config: ZhihuConfig) -> None:
        self._config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._last_request: float = 0.0

    async def start(self) -> None:
        """Launch Playwright and browser."""
        if self._playwright is not None:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._config.headless
        )
        logger.info("Browser launched (headless=%s)", self._config.headless)

    async def stop(self) -> None:
        """Close browser and Playwright."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Browser closed")

    def has_auth(self) -> bool:
        """Check if saved authentication state exists."""
        return self._config.state_file.exists()

    async def login(self) -> str:
        """Interactive login via headed browser. User handles CAPTCHA etc."""
        # Launch headed browser for login
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=self._config.user_agent,
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        await page.goto(LOGIN_URL)
        logger.info("Login page opened. Waiting for user to login...")

        try:
            await page.wait_for_url(
                f"{ZHIHU_BASE}/",
                timeout=LOGIN_TIMEOUT_MS,
            )
        except Exception:
            # Also accept if redirected to explore or hot
            current_url = page.url
            if "zhihu.com" in current_url and "signin" not in current_url:
                pass
            else:
                await context.close()
                await browser.close()
                await pw.stop()
                return "Error: Login timed out after 5 minutes."

        # Save authentication state
        await context.storage_state(path=str(self._config.state_file))
        await context.close()
        await browser.close()
        await pw.stop()

        logger.info("Login successful. State saved to %s", self._config.state_file)
        return "Login successful! Authentication state saved."

    async def _ensure_context(self) -> BrowserContext:
        """Get or create browser context with saved auth state."""
        if self._context is not None:
            return self._context

        await self.start()

        kwargs: dict = {
            "user_agent": self._config.user_agent,
            "viewport": {"width": 1280, "height": 800},
        }
        if self._config.state_file.exists():
            kwargs["storage_state"] = str(self._config.state_file)

        self._context = await self._browser.new_context(**kwargs)
        return self._context

    async def _navigate(self, url: str) -> Page:
        """Navigate to URL and return page with content loaded."""
        await self._rate_limit()
        ctx = await self._ensure_context()

        if self._page is None or self._page.is_closed():
            self._page = await ctx.new_page()

        await self._page.goto(url, wait_until="networkidle", timeout=30_000)
        await self._page.wait_for_timeout(1000)
        return self._page

    async def _rate_limit(self) -> None:
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request
        delay = self._config.request_delay
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self._last_request = time.time()

    async def _extract_initial_state(self, page: Page) -> Optional[dict]:
        """Extract __INITIAL_STATE__ JSON from Zhihu page."""
        result = await page.evaluate(
            """() => {
                // Method 1: js-initialData script tag
                const el = document.getElementById('js-initialData');
                if (el) {
                    try { return JSON.parse(el.textContent); }
                    catch { /* fall through */ }
                }
                // Method 2: window.__INITIAL_STATE__
                if (window.__INITIAL_STATE__) {
                    const s = window.__INITIAL_STATE__;
                    return typeof s === 'string' ? JSON.parse(s) : s;
                }
                return null;
            }"""
        )
        return result

    async def _check_login_required(self, page: Page) -> bool:
        """Check if the page shows a login wall."""
        login_modal = await page.query_selector(
            '[class*="signFlow"], [class*="LoginModal"], button[data-za-detail-view-name="登录"]'
        )
        return login_modal is not None

    # --- Public API ---

    async def search(
        self,
        keyword: str,
        search_type: str = "content",
        limit: int = 10,
        offset: int = 0,
    ) -> SearchOutput:
        """Search Zhihu and return structured results."""
        query = urlencode({"type": search_type, "q": keyword})
        url = f"{ZHIHU_BASE}/search?{query}"
        page = await self._navigate(url)

        if await self._check_login_required(page):
            return SearchOutput(
                keyword=keyword, total=0, items=[], has_more=False
            )

        # Scroll to load more results if needed
        requested = offset + limit
        for _ in range(max(0, (requested - 5) // 5)):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)

        state = await self._extract_initial_state(page)
        if state:
            items = self._parse_search_from_state(state, requested)
            if items:
                page_items = items[offset:requested]
                return SearchOutput(
                    keyword=keyword,
                    total=len(items),
                    items=page_items,
                    has_more=len(items) > requested,
                    next_offset=requested if len(items) > requested else None,
                )

        # Fallback: parse from HTML
        return await self._parse_search_from_html(page, keyword, limit, offset)

    def _parse_search_from_state(
        self, state: dict, limit: int
    ) -> list[SearchResultItem]:
        """Parse search results from __INITIAL_STATE__."""
        items: list[SearchResultItem] = []
        entities = state.get("initialState", state).get("entities", {})

        # Get result IDs from search section
        search_data = state.get("initialState", state).get("search", {})
        result_ids: list[str] = []

        # Navigate various possible structures
        for key in ("topSearch", "hashSearch", "generalSearch"):
            section = search_data.get(key, {})
            result = section.get("result", section.get("resultList", {}))
            if isinstance(result, dict):
                result_ids = result.get("ids", [])
            elif isinstance(result, list):
                result_ids = [r.get("id", "") for r in result if isinstance(r, dict)]
            if result_ids:
                break

        search_results = entities.get("searchResults", {})

        for rid in result_ids[:limit]:
            item = search_results.get(str(rid))
            if not item:
                continue

            obj = item.get("object", item)
            highlight = item.get("highlight", {})
            author_info = obj.get("author", {})

            item_type = obj.get("type", "unknown")
            obj_id = obj.get("id", "")

            url = self._build_url(item_type, obj_id)
            title = (
                highlight.get("title", "")
                or obj.get("title", obj.get("name", ""))
            ).strip()
            if not title:
                continue

            items.append(
                SearchResultItem(
                    title=title,
                    excerpt=highlight.get("description", "")
                    or obj.get("excerpt", obj.get("content", ""))[:300],
                    url=url,
                    item_type=item_type,
                    author=author_info.get("name", "")
                    if isinstance(author_info, dict)
                    else str(author_info),
                    vote_count=obj.get("voteupCount", obj.get("voteup_count", 0)),
                    comment_count=obj.get(
                        "commentCount", obj.get("comment_count", 0)
                    ),
                )
            )

        return items

    async def _parse_search_from_html(
        self, page: Page, keyword: str, limit: int, offset: int = 0
    ) -> SearchOutput:
        """Fallback: parse search results from rendered HTML."""
        cards = await page.query_selector_all(
            '[class*="SearchResult"], [class*="Card SearchResult"]'
        )

        items: list[SearchResultItem] = []
        for card in cards[offset : offset + limit]:
            title_el = await card.query_selector(
                'h2 a, [class*="Title"] a, a[data-za-detail-view-name="Title"]'
            )
            excerpt_el = await card.query_selector(
                '[class*="excerpt"], [class*="RichContent-inner"] span'
            )
            author_el = await card.query_selector(
                '[class*="AuthorInfo"] meta[itemprop="name"]'
            )
            vote_el = await card.query_selector(
                '[class*="VoteButton--up"] button, button[class*="Vote"]'
            )

            title = (await title_el.inner_text()) if title_el else ""
            url = await title_el.get_attribute("href") if title_el else ""
            excerpt = (await excerpt_el.inner_text()) if excerpt_el else ""
            author = (
                await author_el.get_attribute("content") if author_el else ""
            )
            vote_text = (await vote_el.inner_text()) if vote_el else "0"

            if url and not url.startswith("http"):
                url = f"{ZHIHU_BASE}{url}"
            if not title.strip():
                continue

            items.append(
                SearchResultItem(
                    title=title.strip(),
                    excerpt=excerpt.strip()[:300],
                    url=url,
                    item_type="unknown",
                    author=author,
                    vote_count=self._parse_count(vote_text),
                )
            )

        return SearchOutput(
            keyword=keyword,
            total=len(items),
            items=items,
            has_more=len(cards) > offset + limit,
            next_offset=offset + limit if len(cards) > offset + limit else None,
        )

    async def get_question(
        self, question_id: str, answer_limit: int = 5
    ) -> QuestionOutput:
        """Get question details with top answers."""
        api_output = await self._get_question_from_api(
            question_id=question_id,
            answer_limit=answer_limit,
        )
        if api_output and (api_output.title or api_output.answers):
            return api_output

        url = f"{ZHIHU_BASE}/question/{question_id}"
        page = await self._navigate(url)

        if await self._check_login_required(page):
            return QuestionOutput(title="Login required", detail="")

        state = await self._extract_initial_state(page)
        if state:
            return self._parse_question_from_state(state, answer_limit)

        return await self._parse_question_from_html(page, answer_limit)

    def _load_auth_cookies(self) -> dict[str, str]:
        """Load Zhihu cookies from Playwright storage state."""
        if not self._config.state_file.exists():
            return {}

        try:
            state = json.loads(self._config.state_file.read_text())
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to read auth state from %s", self._config.state_file)
            return {}

        return {
            cookie["name"]: cookie["value"]
            for cookie in state.get("cookies", [])
            if "name" in cookie
            and "value" in cookie
            and "zhihu" in cookie.get("domain", "")
        }

    async def _get_question_from_api(
        self, question_id: str, answer_limit: int
    ) -> Optional[QuestionOutput]:
        """Fetch question answers through Zhihu's JSON API."""
        cookies = self._load_auth_cookies()
        if not cookies:
            return None

        include = (
            "data[*].content,excerpt,voteup_count,comment_count,question.title"
        )
        headers = {
            "User-Agent": self._config.user_agent,
            "Referer": f"{ZHIHU_BASE}/question/{question_id}",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        params = {
            "include": include,
            "limit": str(answer_limit),
            "offset": "0",
            "platform": "desktop",
            "sort_by": "default",
        }
        url = f"{ZHIHU_BASE}/api/v4/questions/{question_id}/answers"

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers=headers,
                    cookies=cookies,
                )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("Question API fetch failed: %s", exc)
            return None

        raw_answers = payload.get("data", [])
        if not isinstance(raw_answers, list):
            return None

        title = ""
        parsed_answers: list[AnswerItem] = []
        for raw in raw_answers[:answer_limit]:
            if not isinstance(raw, dict):
                continue

            question = raw.get("question", {})
            if isinstance(question, dict) and not title:
                title = question.get("title", "")

            author_info = raw.get("author", {})
            content_html = raw.get("content") or raw.get("excerpt", "")
            content_md = md(content_html) if content_html else ""
            answer_id = str(raw.get("id", ""))

            parsed_answers.append(
                AnswerItem(
                    author=author_info.get("name", "Anonymous")
                    if isinstance(author_info, dict)
                    else str(author_info),
                    content=content_md.strip()[:2000],
                    vote_count=raw.get("voteup_count", 0),
                    comment_count=raw.get("comment_count", 0),
                    url=f"{ZHIHU_BASE}/question/{question_id}/answer/{answer_id}"
                    if answer_id
                    else "",
                )
            )

        paging = payload.get("paging", {})
        answer_count = (
            paging.get("totals", 0)
            if isinstance(paging, dict)
            else 0
        )

        return QuestionOutput(
            title=title or f"Question {question_id}",
            detail="",
            answer_count=answer_count,
            answers=parsed_answers,
        )

    def _parse_question_from_state(
        self, state: dict, answer_limit: int
    ) -> QuestionOutput:
        """Parse question page from __INITIAL_STATE__."""
        entities = state.get("initialState", state).get("entities", {})
        questions = entities.get("questions", {})
        answers = entities.get("answers", {})

        if not questions:
            return QuestionOutput(title="Question not found", detail="")

        qid = next(iter(questions))
        q = questions[qid]

        answer_ids: list[str] = []
        question_section = (
            state.get("initialState", state)
            .get("question", {})
            .get("answers", {})
        )
        if isinstance(question_section, dict):
            answer_ids = question_section.get("ids", [])
        elif isinstance(question_section, list):
            answer_ids = [str(a.get("id", "")) for a in question_section]

        parsed_answers: list[AnswerItem] = []
        for aid in answer_ids[:answer_limit]:
            a = answers.get(str(aid), {})
            author_info = a.get("author", {})
            content_html = a.get("content", a.get("excerpt", ""))
            content_md = md(content_html) if content_html else ""

            parsed_answers.append(
                AnswerItem(
                    author=author_info.get("name", "Anonymous")
                    if isinstance(author_info, dict)
                    else str(author_info),
                    content=content_md.strip()[:2000],
                    vote_count=a.get("voteupCount", a.get("voteup_count", 0)),
                    comment_count=a.get(
                        "commentCount", a.get("comment_count", 0)
                    ),
                    url=f"{ZHIHU_BASE}/question/{qid}/answer/{aid}",
                )
            )

        tags = [t.get("name", "") for t in q.get("topics", []) if isinstance(t, dict)]

        return QuestionOutput(
            title=q.get("title", ""),
            detail=q.get("detail", q.get("excerpt", "")),
            answer_count=q.get("answerCount", q.get("answer_count", 0)),
            follower_count=q.get(
                "followerCount", q.get("follower_count", 0)
            ),
            tags=tags,
            answers=parsed_answers,
        )

    async def _parse_question_from_html(
        self, page: Page, answer_limit: int
    ) -> QuestionOutput:
        """Fallback: parse question from HTML."""
        title_el = await page.query_selector(
            "h1.QuestionHeader-title, h1[class*='QuestionHeader']"
        )
        detail_el = await page.query_selector(
            "[class*='QuestionRichText-inner'], [itemprop='text']"
        )

        title = (await title_el.inner_text()) if title_el else "Unknown"
        detail = (await detail_el.inner_text()) if detail_el else ""

        answer_els = await page.query_selector_all(
            "[class*='AnswerItem'], [class*='List-item']"
        )

        answers: list[AnswerItem] = []
        for ans_el in answer_els[:answer_limit]:
            author_el = await ans_el.query_selector(
                "[class*='AuthorInfo'] meta[itemprop='name']"
            )
            content_el = await ans_el.query_selector(
                "[class*='RichContent-inner']"
            )
            vote_el = await ans_el.query_selector(
                "button[class*='Vote']"
            )

            author = (
                await author_el.get_attribute("content") if author_el else "Anonymous"
            )
            content = (await content_el.inner_text()) if content_el else ""
            vote_text = (await vote_el.inner_text()) if vote_el else "0"

            answers.append(
                AnswerItem(
                    author=author,
                    content=content.strip()[:2000],
                    vote_count=self._parse_count(vote_text),
                )
            )

        return QuestionOutput(title=title.strip(), detail=detail.strip(), answers=answers)

    async def get_article(self, article_id: str) -> ArticleOutput:
        """Get article content."""
        api_output = await self._get_article_from_api(article_id)
        if api_output and (api_output.title or api_output.content):
            return api_output

        url = f"{ZHIHU_ZHUANLAN_BASE}/p/{article_id}"
        page = await self._navigate(url)

        if await self._check_login_required(page):
            return ArticleOutput(title="Login required", content="")

        state = await self._extract_initial_state(page)
        if state:
            return self._parse_article_from_state(state, article_id)

        return await self._parse_article_from_html(page, article_id)

    async def _get_article_from_api(
        self, article_id: str
    ) -> Optional[ArticleOutput]:
        """Fetch article content through Zhihu column's JSON API."""
        cookies = self._load_auth_cookies()
        if not cookies:
            return None

        article_url = f"{ZHIHU_ZHUANLAN_BASE}/p/{article_id}"
        headers = {
            "User-Agent": self._config.user_agent,
            "Referer": article_url,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        api_url = f"{ZHIHU_ZHUANLAN_BASE}/api/articles/{article_id}"

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                response = await client.get(
                    api_url,
                    headers=headers,
                    cookies=cookies,
                )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("Article API fetch failed: %s", exc)
            return None

        content_html = payload.get("content") or payload.get("excerpt", "")
        content_md = md(content_html) if content_html else ""
        author_info = payload.get("author", {})

        return ArticleOutput(
            title=payload.get("title", ""),
            author=author_info.get("name", "")
            if isinstance(author_info, dict)
            else str(author_info),
            content=content_md.strip()[:5000],
            vote_count=payload.get("voteup_count", payload.get("liked_count", 0)),
            comment_count=payload.get("comment_count", 0),
            url=payload.get("url") or article_url,
        )

    def _parse_article_from_state(
        self, state: dict, article_id: str
    ) -> ArticleOutput:
        """Parse article from __INITIAL_STATE__."""
        entities = state.get("initialState", state).get("entities", {})
        articles = entities.get("articles", {})

        if not articles:
            return ArticleOutput(title="Article not found", content="")

        aid = next(iter(articles))
        a = articles[aid]
        author_info = a.get("author", {})
        content_html = a.get("content", "")
        content_md = md(content_html) if content_html else ""

        return ArticleOutput(
            title=a.get("title", ""),
            author=author_info.get("name", "")
            if isinstance(author_info, dict)
            else str(author_info),
            content=content_md.strip()[:5000],
            vote_count=a.get("voteupCount", a.get("voteup_count", 0)),
            comment_count=a.get("commentCount", a.get("comment_count", 0)),
            url=f"{ZHIHU_ZHUANLAN_BASE}/p/{article_id}",
        )

    async def _parse_article_from_html(
        self, page: Page, article_id: str
    ) -> ArticleOutput:
        """Fallback: parse article from HTML."""
        title_el = await page.query_selector(
            "h1.Post-Title, h1[class*='PostTitle'], h1"
        )
        author_el = await page.query_selector(
            "[class*='AuthorInfo'] meta[itemprop='name']"
        )
        content_el = await page.query_selector(
            "[class*='Post-RichTextContainer'], [class*='RichText'], article"
        )
        vote_el = await page.query_selector(
            "button[class*='VoteButton--up']"
        )

        title = (await title_el.inner_text()) if title_el else "Unknown"
        author = (
            await author_el.get_attribute("content") if author_el else ""
        )
        content_html = (await content_el.inner_html()) if content_el else ""
        content_md = md(content_html) if content_html else ""
        vote_text = (await vote_el.inner_text()) if vote_el else "0"

        return ArticleOutput(
            title=title.strip(),
            author=author,
            content=content_md.strip()[:5000],
            vote_count=self._parse_count(vote_text),
            url=f"{ZHIHU_ZHUANLAN_BASE}/p/{article_id}",
        )

    @staticmethod
    def _build_url(item_type: str, obj_id: str) -> str:
        """Build Zhihu URL from item type and ID."""
        type_routes = {
            "answer": f"{ZHIHU_BASE}/question/{{}}",
            "question": f"{ZHIHU_BASE}/question/{{}}",
            "article": f"{ZHIHU_ZHUANLAN_BASE}/p/{{}}",
            "zvideo": f"{ZHIHU_BASE}/zvideo/{{}}",
        }
        template = type_routes.get(item_type, f"{ZHIHU_BASE}/search?q={{}}")
        return template.format(obj_id)

    @staticmethod
    def _parse_count(text: str) -> int:
        """Parse count text like '1.2 万' or '350' to integer."""
        text = text.strip().replace(",", "")
        try:
            if "万" in text:
                return int(float(text.replace("万", "")) * 10_000)
            if "K" in text.upper():
                return int(float(text.upper().replace("K", "")) * 1_000)
            return int(text)
        except (ValueError, TypeError):
            return 0
