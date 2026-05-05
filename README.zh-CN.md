# Zhihu MCP

中文 | [English](README.md)

一个用于搜索知乎并获取知乎问题、回答和专栏文章内容的 MCP 服务器。

本项目使用 Playwright 完成浏览器登录和页面内容提取；当本地保存的知乎
cookie 可用时，会优先尝试通过知乎的 HTTP API 获取问题回答和专栏文章。

## 功能

- `zhihu_login`：打开浏览器窗口，完成知乎登录并保存认证状态。
- `zhihu_search`：按关键词搜索知乎综合内容、问题或文章。
- `zhihu_get_question`：获取知乎问题及热门回答。
- `zhihu_get_article`：获取知乎专栏文章内容。

## 隐私

登录状态默认保存在本机 `~/.zhihu-mcp/auth.json`。这个文件包含 cookie，
不能分享给别人，也不应该提交到 GitHub。

本仓库已经忽略本地认证状态、`.env`、虚拟环境、缓存目录和本地
agent/editor 日志。

你可以用下面的环境变量修改认证状态保存位置：

```bash
ZHIHU_STATE_DIR=/path/to/local/private/state
```

## 安装

需要 Python 3.11 或更高版本。

```bash
git clone https://github.com/futurehafuture/zhihu-mcp.git
cd zhihu-mcp
uv sync
uv run playwright install chromium
```

## MCP 配置

MCP 客户端配置示例：

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

首次登录建议使用可见浏览器：

```json
{
  "env": {
    "ZHIHU_HEADLESS": "false"
  }
}
```

然后在 MCP 客户端里调用 `zhihu_login`，并在打开的浏览器窗口中完成知乎登录。

登录成功后，认证状态会保存到本机。之后可以把 `ZHIHU_HEADLESS` 改回
`true`，让浏览器在无头模式下运行。

## 工具输入

### `zhihu_search`

```json
{
  "keyword": "agent",
  "search_type": "article",
  "limit": 10,
  "offset": 0
}
```

`search_type` 可选值：

- `content`：综合内容
- `question`：问题
- `article`：文章

为了兼容旧调用方式，本工具也接受 `content_type` 作为 `search_type` 的别名。

### `zhihu_get_question`

```json
{
  "question_id": "123456789",
  "answer_limit": 5
}
```

`question_id` 来自知乎问题 URL：

```text
https://www.zhihu.com/question/123456789
```

### `zhihu_get_article`

```json
{
  "article_id": "676544930"
}
```

`article_id` 来自知乎专栏文章 URL：

```text
https://zhuanlan.zhihu.com/p/676544930
```

## 开发检查

```bash
uv run python -m compileall src
uv run python -m unittest discover -s tests
```

如果你在本地安装了 `ruff` 和 `mypy`，也可以额外运行静态检查。

## 注意事项

知乎会持续调整网页结构和反爬策略，所以本项目的解析逻辑可能需要维护。

搜索结果可能和知乎手机 App 不一致，因为本项目使用的是桌面网页版搜索页和
本地保存的浏览器 cookie；手机 App 还有独立的排序、个性化和实验分流逻辑。

请遵守知乎服务条款和相关法律法规，不要把本工具用于批量抓取、绕过权限或
传播非公开内容。
