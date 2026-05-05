"""Zhihu MCP Server — FastMCP entry point."""

import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from zhihu_mcp.browser import ZhihuBrowser
from zhihu_mcp.config import ZhihuConfig
from zhihu_mcp.models import (
    SearchInput,
    QuestionInput,
    ArticleInput,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Manage browser lifecycle."""
    config = ZhihuConfig.from_env()
    browser = ZhihuBrowser(config)
    logger.info("Zhihu MCP server started (headless=%s)", config.headless)
    yield {"browser": browser, "config": config}
    await browser.stop()
    logger.info("Zhihu MCP server stopped")


mcp = FastMCP("zhihu_mcp", lifespan=lifespan)


def _get_browser(ctx: Any) -> ZhihuBrowser:
    """Extract browser instance from lifespan context."""
    request_context = ctx.request_context
    lifespan_state = getattr(request_context, "lifespan_context", None)
    if lifespan_state is None:
        lifespan_state = getattr(request_context, "lifespan_state", None)
    if lifespan_state is None:
        raise RuntimeError("MCP request context has no lifespan state")
    return lifespan_state["browser"]


def _format_search_output(output) -> str:
    """Format search results as markdown."""
    lines = [f"# Zhihu Search: \"{output.keyword}\"\n"]
    if not output.items:
        return lines[0] + "\nNo results found."

    lines.append(f"Found {output.total} results:\n")

    for i, item in enumerate(output.items, 1):
        lines.append(f"## {i}. [{item.title}]({item.url})")
        meta = [f"Type: {item.item_type}"]
        if item.author:
            meta.append(f"Author: {item.author}")
        if item.vote_count:
            meta.append(f"Votes: {item.vote_count}")
        if item.comment_count:
            meta.append(f"Comments: {item.comment_count}")
        lines.append("- " + " | ".join(meta))
        lines.append(f"\n> {item.excerpt}\n")

    if output.has_more:
        lines.append(f"\n*More results available (offset: {output.next_offset})*")

    return "\n".join(lines)


def _format_question_output(output) -> str:
    """Format question details as markdown."""
    lines = [f"# {output.title}\n"]

    if output.detail:
        lines.append(f"## Question Detail\n\n{output.detail}\n")

    stats = []
    if output.answer_count:
        stats.append(f"{output.answer_count} answers")
    if output.follower_count:
        stats.append(f"{output.follower_count} followers")
    if output.tags:
        stats.append("Tags: " + ", ".join(output.tags))
    if stats:
        lines.append(" | ".join(stats) + "\n")

    if output.answers:
        lines.append("## Top Answers\n")
        for i, ans in enumerate(output.answers, 1):
            lines.append(f"### Answer {i} by {ans.author}")
            vote_info = f" ({ans.vote_count} votes)" if ans.vote_count else ""
            lines.append(f"*{ans.author}{vote_info}*\n")
            lines.append(ans.content[:1500])
            if len(ans.content) > 1500:
                lines.append("\n... *(truncated)*")
            if ans.url:
                lines.append(f"\n[View full answer]({ans.url})")
            lines.append("")

    return "\n".join(lines)


def _format_article_output(output) -> str:
    """Format article content as markdown."""
    lines = [f"# {output.title}\n"]

    meta = []
    if output.author:
        meta.append(f"Author: {output.author}")
    if output.vote_count:
        meta.append(f"Votes: {output.vote_count}")
    if output.comment_count:
        meta.append(f"Comments: {output.comment_count}")
    if meta:
        lines.append(" | ".join(meta) + "\n")

    if output.url:
        lines.append(f"[View on Zhihu]({output.url})\n")

    if output.content:
        lines.append(output.content)

    return "\n".join(lines)


# --- Tool Definitions ---


@mcp.tool(
    name="zhihu_login",
    annotations={
        "title": "Login to Zhihu",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def zhihu_login() -> str:
    """Login to Zhihu via interactive browser window.

    Opens a headed browser to the Zhihu login page. The user completes
    login (handles CAPTCHA, 2FA, QR code, etc.). Authentication state
    is saved automatically for subsequent requests.

    Returns:
        str: Success or error message.
    """
    ctx = mcp.get_context()
    browser = _get_browser(ctx)
    return await browser.login()


@mcp.tool(
    name="zhihu_search",
    annotations={
        "title": "Search Zhihu",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def zhihu_search(params: SearchInput) -> str:
    """Search Zhihu for articles, questions, and answers by keyword.

    Args:
        params: Search parameters including keyword, content type,
                result limit, and pagination offset.

    Returns:
        str: Markdown-formatted search results.
    """
    ctx = mcp.get_context()
    browser = _get_browser(ctx)

    if not browser.has_auth():
        return (
            "Error: Not logged in. Call zhihu_login first to authenticate."
        )

    try:
        output = await browser.search(
            keyword=params.keyword,
            search_type=params.search_type.value,
            limit=params.limit,
            offset=params.offset,
        )
        return _format_search_output(output)
    except Exception as e:
        logger.error("Search failed: %s", e)
        return f"Error: Search failed — {e}. Try calling zhihu_login first."


@mcp.tool(
    name="zhihu_get_question",
    annotations={
        "title": "Get Zhihu Question",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def zhihu_get_question(params: QuestionInput) -> str:
    """Get a Zhihu question with its top answers.

    Args:
        params: Question ID and optional answer count limit.

    Returns:
        str: Markdown-formatted question detail with answers.
    """
    ctx = mcp.get_context()
    browser = _get_browser(ctx)

    if not browser.has_auth():
        return (
            "Error: Not logged in. Call zhihu_login first to authenticate."
        )

    try:
        output = await browser.get_question(
            question_id=params.question_id,
            answer_limit=params.answer_limit,
        )
        return _format_question_output(output)
    except Exception as e:
        logger.error("Get question failed: %s", e)
        return f"Error: Failed to get question — {e}"


@mcp.tool(
    name="zhihu_get_article",
    annotations={
        "title": "Get Zhihu Article",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def zhihu_get_article(params: ArticleInput) -> str:
    """Get full content of a Zhihu article (zhuanlan).

    Args:
        params: Article ID from the Zhihu URL.

    Returns:
        str: Markdown-formatted article content.
    """
    ctx = mcp.get_context()
    browser = _get_browser(ctx)

    if not browser.has_auth():
        return (
            "Error: Not logged in. Call zhihu_login first to authenticate."
        )

    try:
        output = await browser.get_article(article_id=params.article_id)
        return _format_article_output(output)
    except Exception as e:
        logger.error("Get article failed: %s", e)
        return f"Error: Failed to get article — {e}"


def main() -> None:
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
