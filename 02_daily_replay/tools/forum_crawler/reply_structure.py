from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag


NGA_QUOTE_HEADER = re.compile(
    r"^(?:Reply\s+to\s+)?\+R\s+by\s+\[(?P<author>.+?)\]\s*"
    r"\((?P<time>[^)]+)\)\s*",
    flags=re.IGNORECASE,
)


def clean_html_text(value: Any) -> str:
    soup = BeautifulSoup(str(value or ""), "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("")
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def reply_result(
    body: str,
    raw_text: str,
    reply_chain: list[dict[str, str]] | None = None,
    status: str = "none",
    error: str = "",
) -> dict[str, Any]:
    chain = reply_chain or []
    return {
        "body": body.strip(),
        "rawText": raw_text.strip(),
        "quote": chain[0] if chain else None,
        "replyChain": chain,
        "quoteParseStatus": status,
        "quoteParseError": error,
    }


def apply_reply_structure(record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    record["content"] = str(result.get("body") or "").strip()
    record.update(
        {
            "rawText": str(result.get("rawText") or "").strip(),
            "quote": result.get("quote"),
            "replyChain": list(result.get("replyChain") or []),
            "quoteParseStatus": str(result.get("quoteParseStatus") or "none"),
            "quoteParseError": str(result.get("quoteParseError") or ""),
        }
    )
    return record


def stored_reply_structure(raw_json: str | dict[str, Any] | None, fallback_body: str) -> dict[str, Any]:
    if isinstance(raw_json, dict):
        payload = raw_json
    else:
        try:
            payload = json.loads(raw_json or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
    has_structure = any(
        key in payload
        for key in ("rawText", "quote", "replyChain", "quoteParseStatus", "quoteParseError")
    )
    return {
        "body": str(payload.get("content") or fallback_body or "").strip(),
        "rawText": str(payload.get("rawText") or fallback_body or "").strip(),
        "quote": payload.get("quote"),
        "replyChain": list(payload.get("replyChain") or []),
        "quoteParseStatus": str(payload.get("quoteParseStatus") or ("legacy" if not has_structure else "none")),
        "quoteParseError": str(payload.get("quoteParseError") or ""),
    }


def structured_markdown_lines(body: str, author: str, structure: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for entry in structure.get("replyChain") or []:
        quote_author = str(entry.get("author") or "引用内容").strip()
        quote_time = str(entry.get("time") or "").strip()
        label = f"{quote_author} · {quote_time}" if quote_time else quote_author
        lines.extend(["> [!QUOTE]", f"> **{label}**", ">"])
        quote_body = str(entry.get("body") or "").strip()
        for quote_line in quote_body.splitlines() or [""]:
            lines.append(f"> {quote_line}" if quote_line else ">")
        lines.append("")
    if structure.get("replyChain"):
        lines.extend([f"**{author} 回复：**", ""])
    elif structure.get("quoteParseStatus") == "failed":
        error = str(structure.get("quoteParseError") or "未知结构错误")
        lines.extend([f"> [!WARNING] 引用结构解析失败：{error}", ""])
    lines.append(body.strip())
    return lines


def _nga_quote_entry(quote_node: Tag) -> dict[str, str] | None:
    clone = BeautifulSoup(str(quote_node), "lxml").select_one(".quote")
    if clone is None:
        return None
    for nested in list(clone.select(".quote .quote")):
        nested.decompose()
    text = clean_html_text(clone)
    match = NGA_QUOTE_HEADER.match(text)
    if not match:
        return None
    return {
        "author": match.group("author").strip(),
        "time": match.group("time").strip(),
        "body": text[match.end() :].strip(),
    }


def parse_nga_content(raw_html: str) -> dict[str, Any]:
    soup = BeautifulSoup(raw_html or "", "lxml")
    raw_text = clean_html_text(soup)
    quote_nodes = list(soup.select(".quote"))
    if not quote_nodes:
        if NGA_QUOTE_HEADER.match(raw_text):
            return reply_result(
                raw_text,
                raw_text,
                status="failed",
                error="发现引用标记，但原始内容没有可识别的引用容器边界",
            )
        return reply_result(raw_text, raw_text)

    chain: list[dict[str, str]] = []
    failures = 0
    for node in quote_nodes:
        entry = _nga_quote_entry(node)
        if entry is None:
            failures += 1
        else:
            chain.append(entry)

    body_soup = BeautifulSoup(raw_html or "", "lxml")
    for node in list(body_soup.select(".quote")):
        node.decompose()
    body = clean_html_text(body_soup)
    if failures:
        return reply_result(
            body,
            raw_text,
            status="failed",
            error=f"{failures} 个引用容器缺少可识别的作者或时间元数据",
        )
    return reply_result(body, raw_text, chain, status="parsed")


def _xueqiu_segment_text(segment_html: str) -> str:
    return clean_html_text(segment_html).strip()


def _xueqiu_chain_entry(segment: str) -> dict[str, str] | None:
    match = re.match(r"^@(?P<author>[^:：\n]+)\s*[:：]\s*(?P<body>[\s\S]*)$", segment)
    if not match:
        return None
    return {
        "author": match.group("author").strip(),
        "time": "",
        "body": match.group("body").strip(),
    }


def parse_xueqiu_content(raw_html: str) -> dict[str, Any]:
    soup = BeautifulSoup(raw_html or "", "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    raw_text = clean_html_text(soup)
    text = soup.get_text("")
    segments = [_xueqiu_segment_text(part) for part in text.split("//")]
    segments = [segment for segment in segments if segment]
    if not segments:
        return reply_result("", raw_text)

    body = segments[0]
    body_match = re.match(r"^回复\s*@[^:：\n]+\s*[:：]\s*(?P<body>[\s\S]*)$", body)
    if body_match:
        body = body_match.group("body").strip()

    if len(segments) == 1:
        return reply_result(body, raw_text)

    chain: list[dict[str, str]] = []
    for segment in segments[1:]:
        entry = _xueqiu_chain_entry(segment)
        if entry is None:
            return reply_result(
                body,
                raw_text,
                status="failed",
                error="雪球回复链存在无法按平台分隔结构解析的片段",
            )
        chain.append(entry)
    return reply_result(body, raw_text, chain, status="parsed")


def parse_hupu_content(reply_node: Tag, quote_node: Tag | None) -> dict[str, Any]:
    body = clean_html_text(reply_node)
    raw_parts = [body]
    if quote_node is None:
        return reply_result(body, body)

    quote_text = clean_html_text(quote_node)
    raw_parts.append(quote_text)
    author_node = quote_node.select_one("a[href], a")
    author = clean_html_text(author_node) if author_node else ""
    author = author.lstrip("@").strip()

    quote_body = quote_text
    quote_body = re.sub(r"^引用(?:内容)?\s*", "", quote_body).strip()
    if author:
        quote_body = re.sub(rf"^@?{re.escape(author)}\s*[:：]?\s*", "", quote_body).strip()
    if not quote_body:
        return reply_result(
            body,
            "\n".join(raw_parts),
            status="failed",
            error="虎扑引用容器存在，但引用正文为空",
        )

    chain = [{"author": author, "time": "", "body": quote_body}]
    return reply_result(body, "\n".join(raw_parts), chain, status="parsed")
