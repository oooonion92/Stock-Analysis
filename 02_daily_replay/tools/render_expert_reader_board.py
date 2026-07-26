from __future__ import annotations

import argparse
import html
import json
import re
from collections import OrderedDict
from pathlib import Path


META_RE = re.compile(
    r"^>\s*(?P<time>[^｜]+)\s*｜\s*(?P<site>[^｜]+)\s*｜\s*(?P<author>[^｜]+?)(?:\s*｜\s*(?P<thread>.*?))?\s*｜\s*\[查看原帖\]\((?P<url>https?://[^)]+)\)\s*$"
)
HEADER_RE = re.compile(r"^>\s*更新时间：(?P<updated>[^｜]+)\s*｜\s*records:\s*(?P<records>\d+)\s*$")


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value.strip().lower())
    return cleaned.strip("-") or "item"


def parse_markdown(text: str) -> dict:
    lines = text.splitlines()
    title = "高手发言阅读看板"
    updated_at = ""
    total_records = 0
    current_style = None
    current_source = None
    posts: list[dict] = []
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("# "):
            title = line[2:].strip() or title
            index += 1
            continue
        header_match = HEADER_RE.match(line)
        if header_match:
            updated_at = header_match.group("updated").strip()
            total_records = int(header_match.group("records"))
            index += 1
            continue
        if line.startswith("## "):
            current_style = line[3:].strip()
            index += 1
            continue
        if line.startswith("### "):
            current_source = line[4:].strip()
            index += 1
            continue
        if line.startswith("#### "):
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            meta_parts: list[str] = []
            while index < len(lines):
                meta_raw = lines[index].strip()
                if not meta_raw:
                    break
                if not meta_parts and not meta_raw.startswith(">"):
                    break
                if meta_raw.startswith(">"):
                    meta_raw = meta_raw[1:].strip()
                meta_parts.append(meta_raw)
                index += 1
                if "[查看原帖](" in meta_raw:
                    break
            meta_line = "> " + " ".join(meta_parts).strip()
            meta_match = META_RE.match(meta_line)
            if not meta_match:
                raise ValueError(f"无法解析发言元信息：{meta_line}")

            preview = ""
            while index < len(lines) and not lines[index].strip():
                index += 1
            if index < len(lines) and lines[index].startswith("**速览：**"):
                preview = lines[index].split("**速览：**", 1)[1].strip()
                index += 1

            if index < len(lines) and not lines[index].strip():
                index += 1

            content_lines: list[str] = []
            while index < len(lines):
                raw = lines[index]
                stripped = raw.strip()
                if stripped == "---":
                    index += 1
                    break
                if stripped.startswith("#### ") or stripped.startswith("## ") or stripped.startswith("### "):
                    break
                content_lines.append(raw.rstrip())
                index += 1

            content = "\n".join(content_lines).strip()
            time_text = meta_match.group("time").strip()
            date_text = time_text[:10]
            posts.append(
                {
                    "date": date_text,
                    "time": time_text,
                    "style": current_style or "未分类",
                    "source": current_source or f"{meta_match.group('site').strip()} / {meta_match.group('author').strip()}",
                    "site": meta_match.group("site").strip(),
                    "author": meta_match.group("author").strip(),
                    "thread": (meta_match.group("thread") or "").strip(),
                    "url": meta_match.group("url").strip(),
                    "preview": preview,
                    "content": content,
                }
            )
            continue
        index += 1

    grouped: OrderedDict[str, OrderedDict[str, OrderedDict[str, list[dict]]]] = OrderedDict()
    for post in posts:
        grouped.setdefault(post["date"], OrderedDict()).setdefault(post["style"], OrderedDict()).setdefault(
            post["source"], []
        ).append(post)

    dates = []
    for date, styles_map in grouped.items():
        styles = []
        date_count = 0
        for style, sources_map in styles_map.items():
            authors = []
            for source, source_posts in sources_map.items():
                author_id = "-".join(
                    [
                        slugify(date),
                        slugify(style),
                        slugify(source),
                    ]
                )
                authors.append(
                    {
                        "id": author_id,
                        "source": source,
                        "count": len(source_posts),
                        "posts": source_posts,
                    }
                )
                date_count += len(source_posts)
            styles.append({"style": style, "authors": authors})
        dates.append({"date": date, "count": date_count, "styles": styles})

    dates.sort(key=lambda item: item["date"], reverse=True)
    return {
        "title": title.replace("汇总", "阅读看板"),
        "updatedAt": updated_at,
        "totalRecords": total_records or len(posts),
        "dates": dates,
    }


def render_html(board: dict) -> str:
    board_json = json.dumps(board, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(board["title"])}</title>
  <style>
    :root {{
      --bg: #f5f6f2;
      --panel: #ffffff;
      --ink: #20242a;
      --muted: #68707a;
      --line: #dfe3e6;
      --accent: #1f6feb;
      --accent-soft: #eaf2ff;
      --green: #2f7d57;
      --warn: #8a5a00;
      --warn-bg: #fff7e6;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
      line-height: 1.72;
    }}
    .sidebar {{
      position: fixed;
      inset: 0 auto 0 0;
      width: 340px;
      padding: 22px 18px;
      overflow-y: auto;
      background: #fbfcfa;
      border-right: 1px solid var(--line);
    }}
    .brand h1 {{
      margin: 0 0 6px;
      font-size: 22px;
      line-height: 1.25;
    }}
    .brand p {{
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .helper {{
      margin: 0 0 18px;
      padding: 10px 12px;
      border: 1px solid #f0d8a8;
      border-radius: 8px;
      background: var(--warn-bg);
      color: var(--warn);
      font-size: 12px;
    }}
    .controls {{
      display: grid;
      gap: 10px;
      margin-bottom: 18px;
    }}
    .button {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--panel);
      color: var(--ink);
      padding: 9px 12px;
      font-size: 14px;
      cursor: pointer;
      text-align: left;
    }}
    .button:hover {{
      border-color: var(--accent);
      background: var(--accent-soft);
      color: #0b4fb3;
    }}
    .nav-title {{
      margin: 18px 0 10px;
      font-size: 13px;
      color: var(--muted);
      font-weight: 700;
    }}
    .author-nav {{
      display: grid;
      gap: 8px;
    }}
    .author-nav a {{
      display: block;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--panel);
      color: var(--ink);
      text-decoration: none;
      font-size: 14px;
    }}
    .author-nav a:hover,
    .author-nav a.active {{
      border-color: var(--accent);
      background: var(--accent-soft);
      color: #0b4fb3;
    }}
    .author-nav .style-label {{
      margin: 10px 0 2px;
      color: var(--green);
      font-size: 12px;
      font-weight: 800;
    }}
    .date-control {{
      margin-top: 22px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
    }}
    label {{
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    select {{
      width: 100%;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 0 10px;
      font-size: 15px;
    }}
    .meta {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 12px;
    }}
    main {{
      margin-left: 340px;
      padding: 30px 44px 80px;
    }}
    .reader {{
      width: min(1180px, 100%);
    }}
    .date-section {{
      margin-bottom: 26px;
    }}
    .date-heading {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 16px;
      margin-bottom: 18px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--line);
    }}
    .date-heading span {{
      font-size: 28px;
      font-weight: 800;
    }}
    .date-heading em {{
      color: var(--muted);
      font-style: normal;
    }}
    .style-heading {{
      margin: 28px 0 12px;
      font-size: 22px;
    }}
    .author-section {{
      scroll-margin-top: 18px;
      margin-bottom: 34px;
    }}
    .author-section h3 {{
      margin: 0 0 12px;
      font-size: 19px;
    }}
    .author-section h3 span {{
      margin-left: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 500;
    }}
    .post {{
      margin: 0 0 16px;
      padding: 18px 20px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .post-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .post-meta a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .preview {{
      margin: 12px 0 10px;
      color: #0f3d2c;
      font-weight: 700;
    }}
    .content {{
      white-space: normal;
      font-size: 16px;
    }}
    .empty {{
      padding: 24px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      background: var(--panel);
    }}
    @media (max-width: 860px) {{
      .sidebar {{
        position: static;
        width: auto;
        max-height: none;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      main {{
        margin-left: 0;
        padding: 22px 16px 60px;
      }}
      .date-heading {{
        display: block;
      }}
      .date-heading span {{
        font-size: 23px;
      }}
    }}
  </style>
</head>
<body>
  <aside class="sidebar">
    <div class="brand">
      <h1 id="boardTitle"></h1>
      <p id="boardMeta"></p>
    </div>
    <div class="helper" id="helperText">当前先显示内置快照；如果你后面又更新了 `今日汇总.md`，可以点下面按钮重新导入。</div>
    <div class="controls">
      <button id="importButton" class="button" type="button">导入最新的 今日汇总.md</button>
      <input id="fileInput" type="file" accept=".md,text/markdown" hidden>
    </div>
    <div class="nav-title">作者导航</div>
    <nav id="authorNav" class="author-nav"></nav>
    <div class="date-control">
      <label for="dateSelect">日期选择</label>
      <select id="dateSelect"></select>
    </div>
    <div class="meta">点击作者名后，右侧阅读区会跳到对应位置。</div>
  </aside>
  <main>
    <div class="reader" id="reader"></div>
  </main>
  <script>
    const initialBoard = {board_json};
    const dateSelect = document.getElementById('dateSelect');
    const authorNav = document.getElementById('authorNav');
    const reader = document.getElementById('reader');
    const boardTitle = document.getElementById('boardTitle');
    const boardMeta = document.getElementById('boardMeta');
    const helperText = document.getElementById('helperText');
    const importButton = document.getElementById('importButton');
    const fileInput = document.getElementById('fileInput');
    let boardState = initialBoard;

    function escapeHtml(value) {{
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }}

    function renderContent(text) {{
      return escapeHtml(text).replace(/\\n/g, '<br>');
    }}

    function buildDateOptions(dates, selectedDate) {{
      dateSelect.innerHTML = dates.map(item => {{
        const selected = item.date === selectedDate ? ' selected' : '';
        return `<option value="${{escapeHtml(item.date)}}"${{selected}}>${{escapeHtml(item.date)}}</option>`;
      }}).join('');
    }}

    function renderBoard(board, preferredDate) {{
      boardState = board;
      boardTitle.textContent = board.title || '高手发言阅读看板';
      boardMeta.textContent = `${{board.updatedAt || '未记录更新时间'}} ｜ ${{board.totalRecords || 0}} records`;

      if (!board.dates || !board.dates.length) {{
        dateSelect.innerHTML = '';
        reader.innerHTML = '<div class="empty">没有可显示的数据。</div>';
        authorNav.innerHTML = '';
        return;
      }}

      const selectedDate = preferredDate && board.dates.some(item => item.date === preferredDate)
        ? preferredDate
        : board.dates[0].date;

      buildDateOptions(board.dates, selectedDate);
      reader.innerHTML = board.dates.map(dateBlock => {{
        const styleHtml = dateBlock.styles.map(styleBlock => {{
          const authorHtml = styleBlock.authors.map(authorBlock => {{
            const postsHtml = authorBlock.posts.map(post => `
              <article class="post">
                <div class="post-meta">
                  <span>${{escapeHtml(post.time)}}</span>
                  <span>${{escapeHtml(post.author)}}</span>
                  <span>${{escapeHtml(post.thread)}}</span>
                  <a href="${{escapeHtml(post.url)}}" target="_blank" rel="noopener">查看原帖</a>
                </div>
                ${{post.preview ? `<div class="preview">速览：${{escapeHtml(post.preview)}}</div>` : ''}}
                <div class="content">${{renderContent(post.content)}}</div>
              </article>
            `).join('');
            return `
              <section
                class="author-section"
                id="${{escapeHtml(authorBlock.id)}}"
                data-date="${{escapeHtml(dateBlock.date)}}"
                data-style="${{escapeHtml(styleBlock.style)}}"
                data-source="${{escapeHtml(authorBlock.source)}}"
                data-count="${{authorBlock.count}}">
                <h3>${{escapeHtml(authorBlock.source)}} <span>${{authorBlock.count}}</span></h3>
                ${{postsHtml}}
              </section>
            `;
          }}).join('');
          return `<h2 class="style-heading">${{escapeHtml(styleBlock.style)}}</h2>${{authorHtml}}`;
        }}).join('');
        return `
          <section class="date-section" data-date="${{escapeHtml(dateBlock.date)}}">
            <div class="date-heading"><span>${{escapeHtml(dateBlock.date)}}</span><em>${{dateBlock.count}} records</em></div>
            ${{styleHtml}}
          </section>
        `;
      }}).join('');

      dateSelect.value = selectedDate;
      showDate(selectedDate, false);
    }}

    function showDate(date, shouldScroll = true) {{
      document.querySelectorAll('.date-section').forEach(section => {{
        section.hidden = section.dataset.date !== date;
      }});
      renderAuthorNav(date);
      const activeSection = document.querySelector(`.date-section[data-date="${{CSS.escape(date)}}"]`);
      if (activeSection && shouldScroll) {{
        window.scrollTo({{ top: activeSection.offsetTop - 16, behavior: 'smooth' }});
      }}
    }}

    function renderAuthorNav(date) {{
      authorNav.innerHTML = '';
      const sections = Array.from(document.querySelectorAll(`.author-section[data-date="${{CSS.escape(date)}}"]`));
      let lastStyle = '';
      sections.forEach(section => {{
        if (section.dataset.style !== lastStyle) {{
          const label = document.createElement('div');
          label.className = 'style-label';
          label.textContent = section.dataset.style;
          authorNav.appendChild(label);
          lastStyle = section.dataset.style;
        }}
        const link = document.createElement('a');
        link.href = `#${{section.id}}`;
        link.textContent = `${{section.dataset.source}} (${{section.dataset.count}})`;
        link.addEventListener('click', () => {{
          authorNav.querySelectorAll('a').forEach(item => item.classList.remove('active'));
          link.classList.add('active');
        }});
        authorNav.appendChild(link);
      }});
    }}

    function parseMarkdown(text) {{
      const lines = text.split(/\\r?\\n/);
      const board = {{
        title: '高手发言阅读看板',
        updatedAt: '',
        totalRecords: 0,
        dates: []
      }};
      let currentStyle = '未分类';
      let currentSource = '';
      const rawPosts = [];

      for (let i = 0; i < lines.length; i += 1) {{
        const line = lines[i].trim();
        if (!line) continue;
        if (line.startsWith('# ')) {{
          board.title = line.slice(2).trim().replace('汇总', '阅读看板') || board.title;
          continue;
        }}
        const headerMatch = line.match(/^>\\s*更新时间：([^｜]+)\\s*｜\\s*records:\\s*(\\d+)\\s*$/);
        if (headerMatch) {{
          board.updatedAt = headerMatch[1].trim();
          board.totalRecords = Number(headerMatch[2]);
          continue;
        }}
        if (line.startsWith('## ')) {{
          currentStyle = line.slice(3).trim() || '未分类';
          continue;
        }}
        if (line.startsWith('### ')) {{
          currentSource = line.slice(4).trim();
          continue;
        }}
        if (!line.startsWith('#### ')) continue;

        i += 1;
        while (i < lines.length && !(lines[i] || '').trim()) {{
          i += 1;
        }}
        const metaParts = [];
        while (i < lines.length) {{
          const rawMeta = (lines[i] || '').trim();
          if (!rawMeta) break;
          if (!metaParts.length && !rawMeta.startsWith('>')) break;
          const normalizedMeta = rawMeta.startsWith('>') ? rawMeta.slice(1).trim() : rawMeta;
          metaParts.push(normalizedMeta);
          if (normalizedMeta.includes('[查看原帖](')) {{
            i += 1;
            break;
          }}
          i += 1;
        }}
        const metaLine = `> ${{metaParts.join(' ').trim()}}`;
        const metaMatch = metaLine.match(/^>\\s*([^｜]+)\\s*｜\\s*([^｜]+)\\s*｜\\s*([^｜]+?)(?:\\s*｜\\s*(.*?))?\\s*｜\\s*\\[查看原帖\\]\\((https?:\\/\\/[^)]+)\\)\\s*$/);
        if (!metaMatch) continue;

        let preview = '';
        while (i < lines.length && !(lines[i] || '').trim()) {{
          i += 1;
        }}
        if ((lines[i] || '').startsWith('**速览：**')) {{
          preview = (lines[i] || '').split('**速览：**')[1].trim();
          i += 1;
        }}
        if (!(lines[i] || '').trim()) i += 1;

        const contentLines = [];
        while (i < lines.length) {{
          const next = lines[i];
          const trimmed = next.trim();
          if (trimmed === '---') {{
            i += 1;
            break;
          }}
          if (trimmed.startsWith('#### ') || trimmed.startsWith('## ') || trimmed.startsWith('### ')) {{
            break;
          }}
          contentLines.push(next.replace(/\\s+$/, ''));
          i += 1;
        }}

        const time = metaMatch[1].trim();
        rawPosts.push({{
          date: time.slice(0, 10),
          time,
          style: currentStyle,
          source: currentSource || `${{metaMatch[2].trim()}} / ${{metaMatch[3].trim()}}`,
          site: metaMatch[2].trim(),
          author: metaMatch[3].trim(),
          thread: (metaMatch[4] || '').trim(),
          url: metaMatch[5].trim(),
          preview,
          content: contentLines.join('\\n').trim()
        }});
      }}

      const grouped = new Map();
      rawPosts.forEach(post => {{
        if (!grouped.has(post.date)) grouped.set(post.date, new Map());
        const styleMap = grouped.get(post.date);
        if (!styleMap.has(post.style)) styleMap.set(post.style, new Map());
        const sourceMap = styleMap.get(post.style);
        if (!sourceMap.has(post.source)) sourceMap.set(post.source, []);
        sourceMap.get(post.source).push(post);
      }});

      board.dates = Array.from(grouped.entries())
        .sort((a, b) => b[0].localeCompare(a[0]))
        .map(([date, styleMap]) => {{
          let dateCount = 0;
          const styles = Array.from(styleMap.entries()).map(([style, sourceMap]) => {{
            const authors = Array.from(sourceMap.entries()).map(([source, posts]) => {{
              dateCount += posts.length;
              const authorId = [date, style, source]
                .join('-')
                .toLowerCase()
                .replace(/[^0-9a-z\\u4e00-\\u9fff]+/g, '-')
                .replace(/^-+|-+$/g, '') || 'item';
              return {{
                id: authorId,
                source,
                count: posts.length,
                posts
              }};
            }});
            return {{ style, authors }};
          }});
          return {{ date, count: dateCount, styles }};
        }});
      if (!board.totalRecords) {{
        board.totalRecords = rawPosts.length;
      }}
      return board;
    }}

    async function tryFetchLatest() {{
      if (!location.protocol.startsWith('http')) {{
        helperText.textContent = '当前是本地文件模式，所以浏览器不能自动读取同目录 markdown；看板已内置今天的快照，后续可点按钮手动导入最新的 今日汇总.md。';
        return;
      }}
      try {{
        const response = await fetch(`./今日汇总.md?ts=${{Date.now()}}`, {{ cache: 'no-store' }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const text = await response.text();
        const latestBoard = parseMarkdown(text);
        renderBoard(latestBoard, dateSelect.value);
        helperText.textContent = '已自动读取同目录最新的 今日汇总.md。';
      }} catch (error) {{
        helperText.textContent = `自动读取同目录 markdown 失败，当前仍显示内置快照。可手动导入最新文件。`;
      }}
    }}

    importButton.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async event => {{
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      const text = await file.text();
      const importedBoard = parseMarkdown(text);
      renderBoard(importedBoard);
      helperText.textContent = `已导入：${{file.name}}`;
      fileInput.value = '';
    }});

    dateSelect.addEventListener('change', event => showDate(event.target.value));
    renderBoard(initialBoard);
    tryFetchLatest();
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="根据今日汇总 markdown 生成高手发言阅读看板。")
    parser.add_argument("input", type=Path, help="输入 markdown 路径")
    parser.add_argument("output", type=Path, help="输出 html 路径")
    args = parser.parse_args()

    text = args.input.read_text(encoding="utf-8-sig")
    board = parse_markdown(text)
    args.output.write_text(render_html(board), encoding="utf-8")
    print(f"已生成：{args.output}")


if __name__ == "__main__":
    main()
