"""Configuration for Zhihu MCP server."""

from dataclasses import dataclass
from pathlib import Path

import os


@dataclass(frozen=True)
class ZhihuConfig:
    """Immutable configuration loaded from environment variables."""

    state_file: Path
    headless: bool
    request_delay: float
    user_agent: str

    @classmethod
    def from_env(cls) -> "ZhihuConfig":
        """Create config from environment variables with sensible defaults."""
        state_dir = Path(
            os.getenv("ZHIHU_STATE_DIR", "~/.zhihu-mcp")
        ).expanduser()
        state_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            state_file=state_dir / "auth.json",
            headless=os.getenv("ZHIHU_HEADLESS", "true").lower() == "true",
            request_delay=float(
                os.getenv("ZHIHU_REQUEST_DELAY", "2.0")
            ),
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
