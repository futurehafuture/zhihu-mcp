# Zhihu MCP

[中文](README.zh-CN.md) | English

An MCP server for searching Zhihu and retrieving question/article content.

The server uses Playwright for browser-based login and page extraction, with
HTTP API fallbacks for question answers and column articles when saved Zhihu
cookies are available.

## Features

- `zhihu_login`: open a browser window and save Zhihu authentication state.
- `zhihu_search`: search Zhihu content, questions, or articles by keyword.
- `zhihu_get_question`: fetch a question and top answers.
- `zhihu_get_article`: fetch a Zhihu column article.

## Privacy

Login state is stored locally in `~/.zhihu-mcp/auth.json` by default. That file
contains cookies and must not be shared. This repository ignores local auth
state, `.env`, virtual environments, caches, and local agent/editor logs.

You can change the auth state location with:

```bash
ZHIHU_STATE_DIR=/path/to/local/private/state
```

## Installation

Requires Python 3.11+.

```bash
git clone https://github.com/futurehafuture/zhihu-mcp.git
cd zhihu-mcp
uv sync
uv run playwright install chromium
```

## MCP Configuration

Example configuration for an MCP client:

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "uv",
      "args": ["run", "zhihu-mcp"],
      "cwd": "/absolute/path/to/zhihu-mcp",
      "env": {
        "ZHIHU_HEADLESS": "true"
      }
    }
  }
}
```

For the first login, run with a visible browser:

```json
{
  "env": {
    "ZHIHU_HEADLESS": "false"
  }
}
```

Then call `zhihu_login` from your MCP client and complete login in the opened
browser window.

## Tool Inputs

### `zhihu_search`

```json
{
  "keyword": "agent",
  "search_type": "article",
  "limit": 10,
  "offset": 0
}
```

`search_type` can be `content`, `question`, or `article`. The server also
accepts `content_type` as a compatibility alias for `search_type`.

### `zhihu_get_question`

```json
{
  "question_id": "123456789",
  "answer_limit": 5
}
```

### `zhihu_get_article`

```json
{
  "article_id": "676544930"
}
```

## Development Checks

```bash
uv run python -m compileall src
uv run python -m unittest discover -s tests
```

`ruff` and `mypy` are optional local checks if you install them in your
environment.

## Notes

Zhihu changes its web UI and anti-bot behavior over time. Search results may
differ from the Zhihu mobile app because this server uses the desktop web
search page and saved browser cookies.
