"""Pydantic models for Zhihu MCP tool inputs and outputs."""

from enum import Enum
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class SearchType(str, Enum):
    """Type of Zhihu content to search."""

    CONTENT = "content"
    QUESTION = "question"
    ARTICLE = "article"


class SearchInput(BaseModel):
    """Input for zhihu_search tool."""

    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    keyword: str = Field(
        ...,
        description="Search keyword (e.g. 'machine learning', 'deep learning')",
        min_length=1,
        max_length=200,
    )
    search_type: SearchType = Field(
        default=SearchType.CONTENT,
        validation_alias=AliasChoices("search_type", "content_type"),
        description="Content type: 'content' (all), 'question', or 'article'",
    )
    limit: int = Field(
        default=10,
        description="Maximum number of results to return",
        ge=1,
        le=50,
    )
    offset: int = Field(
        default=0,
        description="Number of results to skip for pagination",
        ge=0,
    )


class QuestionInput(BaseModel):
    """Input for zhihu_get_question tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question_id: str = Field(
        ...,
        description="Zhihu question ID (from URL: zhihu.com/question/{id})",
        min_length=1,
    )
    answer_limit: int = Field(
        default=5,
        description="Maximum number of top answers to include",
        ge=1,
        le=20,
    )


class ArticleInput(BaseModel):
    """Input for zhihu_get_article tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    article_id: str = Field(
        ...,
        description="Zhihu article ID (from URL: zhuanlan.zhihu.com/p/{id})",
        min_length=1,
    )


class SearchResultItem(BaseModel):
    """A single search result."""

    title: str
    excerpt: str
    url: str
    item_type: str
    author: str = ""
    vote_count: int = 0
    comment_count: int = 0


class SearchOutput(BaseModel):
    """Output of zhihu_search tool."""

    keyword: str
    total: int
    items: List[SearchResultItem]
    has_more: bool
    next_offset: Optional[int] = None


class AnswerItem(BaseModel):
    """A single answer in a question."""

    author: str
    content: str
    vote_count: int = 0
    comment_count: int = 0
    url: str = ""


class QuestionOutput(BaseModel):
    """Output of zhihu_get_question tool."""

    title: str
    detail: str
    answer_count: int = 0
    follower_count: int = 0
    tags: List[str] = Field(default_factory=list)
    answers: List[AnswerItem] = Field(default_factory=list)


class ArticleOutput(BaseModel):
    """Output of zhihu_get_article tool."""

    title: str
    author: str
    content: str
    vote_count: int = 0
    comment_count: int = 0
    url: str = ""
