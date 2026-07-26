from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from crawl_hupu_user_replies import parse_items
from crawl_nga_author_replies import extract_html_records
from crawl_xueqiu_user_posts import normalize_status
from forum_db import connect, insert_posts, upsert_site, upsert_target
from reply_structure import (
    parse_hupu_content,
    parse_nga_content,
    parse_xueqiu_content,
    stored_reply_structure,
    structured_markdown_lines,
)


class NgaReplyStructureTests(unittest.TestCase):
    def test_issue_zippo578_example(self) -> None:
        raw_html = (
            '<div class="quote"><a>+</a><a>R</a> by <a class="userlink">[茶茶番]</a> '
            '<span class="xtxt silver">(2026-07-13 15:21)</span><br><br>'
            '可是平隔日是正常价格 平今是10倍价格啊<br>'
            '一般不是买多买空 买多买空这样平的么</div>'
            '底仓单子没那么多的，做几次就只能做隔日了<br>'
            '另外这个只能做单向<br>'
            '比如看多，那多就是底仓<br>'
            '如果多空一起做，很容易日内大亏，超级大那种'
        )

        result = parse_nga_content(raw_html)

        self.assertEqual(result["quoteParseStatus"], "parsed")
        self.assertEqual(
            result["quote"],
            {
                "author": "茶茶番",
                "time": "2026-07-13 15:21",
                "body": "可是平隔日是正常价格 平今是10倍价格啊\n一般不是买多买空 买多买空这样平的么",
            },
        )
        self.assertEqual(
            result["body"],
            "底仓单子没那么多的，做几次就只能做隔日了\n另外这个只能做单向\n比如看多，那多就是底仓\n如果多空一起做，很容易日内大亏，超级大那种",
        )

    def test_reply_to_r_header(self) -> None:
        result = parse_nga_content(
            '<div class="quote">Reply to +R by [前作者] (2026-07-13 09:00)<br>旧内容</div>新回复'
        )
        self.assertEqual(result["quoteParseStatus"], "parsed")
        self.assertEqual(result["quote"]["author"], "前作者")
        self.assertEqual(result["quote"]["body"], "旧内容")
        self.assertEqual(result["body"], "新回复")

    def test_no_quote(self) -> None:
        result = parse_nga_content("第一段<br>第二段")
        self.assertEqual(result["quoteParseStatus"], "none")
        self.assertIsNone(result["quote"])
        self.assertEqual(result["body"], "第一段\n第二段")

    def test_nested_quotes_keep_order(self) -> None:
        result = parse_nga_content(
            '<div class="quote">+R by [直接回复对象] (2026-07-13 10:00)<br>'
            '<div class="quote">+R by [更早作者] (2026-07-13 09:00)<br>更早内容</div>'
            '直接回复对象的内容</div>当前作者内容'
        )
        self.assertEqual(result["quoteParseStatus"], "parsed")
        self.assertEqual(
            [entry["author"] for entry in result["replyChain"]],
            ["直接回复对象", "更早作者"],
        )
        self.assertEqual(result["body"], "当前作者内容")

    def test_flattened_quote_marker_is_not_guessed(self) -> None:
        raw = "+R by [前作者] (2026-07-13 09:00)\n旧内容\n新回复"
        result = parse_nga_content(raw)
        self.assertEqual(result["quoteParseStatus"], "failed")
        self.assertEqual(result["body"], raw)
        self.assertEqual(result["replyChain"], [])


class XueqiuReplyStructureTests(unittest.TestCase):
    def test_reply_chain(self) -> None:
        raw_html = (
            '回复<a href="/n/茶茶番">@茶茶番</a>: 当前作者回复第一行<br>当前作者回复第二行'
            '//<a href="/n/茶茶番">@茶茶番</a>:回复<a href="/n/当前作者">@当前作者</a>: 被引用回复'
        )
        result = parse_xueqiu_content(raw_html)
        self.assertEqual(result["quoteParseStatus"], "parsed")
        self.assertEqual(result["body"], "当前作者回复第一行\n当前作者回复第二行")
        self.assertEqual(result["replyChain"][0]["author"], "茶茶番")
        self.assertEqual(result["replyChain"][0]["body"], "回复@当前作者: 被引用回复")

    def test_normalized_status_stores_current_body_and_chain(self) -> None:
        record = normalize_status(
            {
                "id": 100,
                "created_at": 1783929517000,
                "text": "回复<a>@前作者</a>: 当前回复//<a>@前作者</a>:被引用内容",
                "user": {"id": 200, "screen_name": "当前作者"},
            },
            "following",
            "关注流",
            "https://xueqiu.com/",
        )
        self.assertEqual(record["content"], "当前回复")
        self.assertEqual(record["replyChain"][0]["body"], "被引用内容")
        self.assertEqual(record["quoteParseStatus"], "parsed")


class HupuReplyStructureTests(unittest.TestCase):
    def test_quote_container(self) -> None:
        soup = BeautifulSoup(
            """
            <div class="list-item-reply">当前作者回复<br>第二行</div>
            <div class="hasImgContent">引用内容<a href="/user">@前作者</a>：引用第一行<br>引用第二行</div>
            """,
            "lxml",
        )
        result = parse_hupu_content(
            soup.select_one(".list-item-reply"),
            soup.select_one(".hasImgContent"),
        )
        self.assertEqual(result["quoteParseStatus"], "parsed")
        self.assertEqual(result["body"], "当前作者回复\n第二行")
        self.assertEqual(result["quote"]["author"], "前作者")
        self.assertEqual(result["quote"]["body"], "引用第一行\n引用第二行")

    def test_profile_item_keeps_quote_out_of_content(self) -> None:
        html = """
        <div class="list-item">
          <div class="list-item-reply">当前回复</div>
          <div class="hasImgContent">引用内容<a href="/user">@前作者</a>：引用正文</div>
          <div class="shoImgWarp"><a>主题标题</a></div>
          <div class="hasTopicName">股票区</div>
          <span>发布于 2026-07-13 16:11:37</span>
        </div>
        """
        records = parse_items(html, "https://my.hupu.com/123?tabKey=2", "123", "当前作者")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content"], "当前回复")
        self.assertEqual(records[0]["quote"]["body"], "引用正文")
        self.assertNotIn("引用正文", records[0]["content"])


class NgaCrawlerIntegrationTests(unittest.TestCase):
    def test_author_search_record_keeps_quote_out_of_content(self) -> None:
        html = """
        <table><tr>
          <td><a class="author">当前作者</a><span class="postdate">2026-07-13 10:00</span></td>
          <td class="c2"><a class="topic">主题</a>
            <span id="postcontent459_456"><div class="quote">+R by [前作者] (2026-07-13 09:00)<br>引用正文</div>当前回复</span>
          </td>
        </tr></table>
        """
        records = extract_html_records(html, "123", "当前作者", 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content"], "当前回复")
        self.assertEqual(records[0]["quote"]["body"], "引用正文")


class OutputStructureTests(unittest.TestCase):
    def test_structured_fields_survive_storage_and_markdown(self) -> None:
        payload = {
            "content": "作者自己的回复",
            "rawText": "引用正文\n作者自己的回复",
            "quote": {"author": "前作者", "time": "2026-07-13 09:00", "body": "引用正文"},
            "replyChain": [
                {"author": "前作者", "time": "2026-07-13 09:00", "body": "引用正文"}
            ],
            "quoteParseStatus": "parsed",
            "quoteParseError": "",
        }
        structure = stored_reply_structure(json.dumps(payload, ensure_ascii=False), "错误的回退正文")
        markdown = "\n".join(structured_markdown_lines(structure["body"], "当前作者", structure))

        self.assertEqual(structure["body"], "作者自己的回复")
        self.assertIn("> [!QUOTE]", markdown)
        self.assertIn("> **前作者 · 2026-07-13 09:00**", markdown)
        self.assertIn("**当前作者 回复：**", markdown)
        self.assertEqual(markdown.count("引用正文"), 1)

    def test_legacy_record_is_not_reinterpreted(self) -> None:
        body = "+R by [前作者] (2026-07-13 09:00)\n引用和正文已被压平"
        structure = stored_reply_structure("{}", body)
        self.assertEqual(structure["quoteParseStatus"], "legacy")
        self.assertEqual(structure["body"], body)
        self.assertEqual(structure["replyChain"], [])

    def test_database_keeps_structured_reply_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "forum.sqlite"
            conn = connect(db_path)
            try:
                site_id = upsert_site(conn, "NGA", "https://bbs.nga.cn", "nga")
                target_id = upsert_target(conn, "NGA", "测试作者", "123")
                record = {
                    "post_id": "456",
                    "content": "当前回复",
                    "published_at": "2026-07-13 10:00",
                    "crawl_time": "2026-07-13T10:01:00+08:00",
                    "quote": {"author": "前作者", "time": "2026-07-13 09:00", "body": "引用内容"},
                    "replyChain": [
                        {"author": "前作者", "time": "2026-07-13 09:00", "body": "引用内容"}
                    ],
                    "rawText": "引用内容\n当前回复",
                    "quoteParseStatus": "parsed",
                    "quoteParseError": "",
                }
                self.assertEqual(insert_posts(conn, site_id, target_id, [record]), 1)
                row = conn.execute("SELECT content, raw_json FROM posts").fetchone()
            finally:
                conn.close()

            stored = json.loads(row["raw_json"])
            self.assertEqual(row["content"], "当前回复")
            self.assertEqual(stored["replyChain"][0]["body"], "引用内容")
            self.assertEqual(stored["quoteParseStatus"], "parsed")


if __name__ == "__main__":
    unittest.main()
