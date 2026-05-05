import unittest

from zhihu_mcp.browser import ZhihuBrowser
from zhihu_mcp.models import QuestionOutput, SearchInput, SearchType


class SearchInputTests(unittest.TestCase):
    def test_accepts_content_type_alias(self) -> None:
        payload = {
            "keyword": "agent",
            "content_type": "article",
            "limit": 5,
            "offset": 10,
        }

        parsed = SearchInput.model_validate(payload)

        self.assertEqual(parsed.search_type, SearchType.ARTICLE)
        self.assertEqual(parsed.limit, 5)
        self.assertEqual(parsed.offset, 10)

    def test_question_output_lists_are_independent(self) -> None:
        first = QuestionOutput(title="first", detail="")
        second = QuestionOutput(title="second", detail="")

        first.tags.append("AI")

        self.assertEqual(second.tags, [])


class HelperTests(unittest.TestCase):
    def test_parse_count_supports_common_units(self) -> None:
        self.assertEqual(ZhihuBrowser._parse_count("1.2 万"), 12000)
        self.assertEqual(ZhihuBrowser._parse_count("3K"), 3000)
        self.assertEqual(ZhihuBrowser._parse_count("350"), 350)
        self.assertEqual(ZhihuBrowser._parse_count("赞同"), 0)


if __name__ == "__main__":
    unittest.main()
