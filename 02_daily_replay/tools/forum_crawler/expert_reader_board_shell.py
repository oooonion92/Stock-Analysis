from __future__ import annotations


DEFAULT_API_BASE = "http://127.0.0.1:8768"


def render_shell_html(api_base: str = DEFAULT_API_BASE) -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>高手发言阅读看板</title>
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
      margin: 0 0 16px;
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
    .mode-row {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
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
    .button.active,
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
      <h1 id="boardTitle">高手发言阅读看板</h1>
      <p id="boardMeta">等待本地阅读服务...</p>
    </div>
    <div class="helper" id="helperText">这版看板直接读取本地数据库。若提示连接失败，请先运行一次一键收集，或手动启动本地阅读服务。</div>
    <div class="controls">
      <div class="mode-row">
        <button class="button active" type="button" data-mode="today">今天</button>
        <button class="button" type="button" data-mode="recent7">最近7天</button>
        <button class="button" type="button" data-mode="all">全部日期</button>
      </div>
      <button id="refreshButton" class="button" type="button">刷新数据库内容</button>
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
    <div class="reader" id="reader">
      <div class="empty">等待加载数据...</div>
    </div>
  </main>
  <script>
    const API_BASE = __API_BASE__;
    const API_OVERVIEW = `${{API_BASE}}/api/reader/overview`;
    const API_POSTS = `${{API_BASE}}/api/reader/posts`;
    const boardMeta = document.getElementById('boardMeta');
    const helperText = document.getElementById('helperText');
    const dateSelect = document.getElementById('dateSelect');
    const authorNav = document.getElementById('authorNav');
    const reader = document.getElementById('reader');
    const refreshButton = document.getElementById('refreshButton');
    const modeButtons = Array.from(document.querySelectorAll('[data-mode]'));
    let allDates = [];
    let currentMode = 'today';

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

    function filteredDates(mode) {{
      if (mode === 'today') return allDates.slice(0, 1);
      if (mode === 'recent7') return allDates.slice(0, 7);
      return allDates.slice();
    }}

    function rebuildDateSelect(preferredDate) {{
      const dates = filteredDates(currentMode);
      dateSelect.innerHTML = dates.map(item => {{
        const selected = item.date === preferredDate ? ' selected' : '';
        return `<option value="${{escapeHtml(item.date)}}"${{selected}}>${{escapeHtml(item.date)}} (${{item.count}})</option>`;
      }}).join('');
      return dates;
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

    function renderBoard(payload) {{
      const date = payload.date || '';
      const grouped = payload.grouped || [];
      boardMeta.textContent = `${{payload.updatedAt || '未记录更新时间'}} ｜ 数据库记录 ${{payload.totalPosts || 0}} 条`;
      if (!grouped.length) {{
        reader.innerHTML = '<div class="empty">这一天没有可显示的数据。</div>';
        authorNav.innerHTML = '';
        return;
      }}
      reader.innerHTML = `
        <section class="date-section" data-date="${{escapeHtml(date)}}">
          <div class="date-heading"><span>${{escapeHtml(date)}}</span><em>${{payload.dateCount || 0}} records</em></div>
          ${{
            grouped.map(styleBlock => `
              <h2 class="style-heading">${{escapeHtml(styleBlock.style)}}</h2>
              ${{
                styleBlock.authors.map(authorBlock => `
                  <section
                    class="author-section"
                    id="${{escapeHtml(authorBlock.id)}}"
                    data-date="${{escapeHtml(date)}}"
                    data-style="${{escapeHtml(styleBlock.style)}}"
                    data-source="${{escapeHtml(authorBlock.source)}}"
                    data-count="${{authorBlock.count}}">
                    <h3>${{escapeHtml(authorBlock.source)}} <span>${{authorBlock.count}}</span></h3>
                    ${{
                      authorBlock.posts.map(post => `
                        <article class="post">
                          <div class="post-meta">
                            <span>${{escapeHtml(post.time)}}</span>
                            <span>${{escapeHtml(post.author)}}</span>
                            ${{post.thread ? `<span>${{escapeHtml(post.thread)}}</span>` : ''}}
                            ${{post.url ? `<a href="${{escapeHtml(post.url)}}" target="_blank" rel="noopener">查看原帖</a>` : ''}}
                          </div>
                          ${{post.preview ? `<div class="preview">速览：${{escapeHtml(post.preview)}}</div>` : ''}}
                          <div class="content">${{renderContent(post.content)}}</div>
                        </article>
                      `).join('')}
                    }}
                  </section>
                `).join('')}
              }}
            `).join('')
          }}
        </section>
      `;
      renderAuthorNav(date);
    }}

    async function loadOverview(preferredDate) {{
      const response = await fetch(`${{API_OVERVIEW}}?ts=${{Date.now()}}`);
      if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
      const payload = await response.json();
      allDates = payload.dates || [];
      const dates = rebuildDateSelect(preferredDate);
      if (!dates.length) {{
        boardMeta.textContent = `${{payload.updatedAt || '未记录更新时间'}} ｜ 数据库暂无可显示记录`;
        reader.innerHTML = '<div class="empty">数据库暂无可显示记录。</div>';
        authorNav.innerHTML = '';
        return '';
      }}
      return preferredDate && dates.some(item => item.date === preferredDate) ? preferredDate : dates[0].date;
    }}

    async function loadDate(date) {{
      const response = await fetch(`${{API_POSTS}}?date=${{encodeURIComponent(date)}}&ts=${{Date.now()}}`);
      if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
      const payload = await response.json();
      renderBoard(payload);
      dateSelect.value = date;
      helperText.textContent = `已连接本地数据库服务：${{API_BASE}}`;
    }}

    async function refresh(preferredDate) {{
      try {{
        const selectedDate = await loadOverview(preferredDate || dateSelect.value);
        if (selectedDate) {{
          await loadDate(selectedDate);
        }}
      }} catch (error) {{
        reader.innerHTML = '<div class="empty">无法连接本地阅读服务。请先运行一键收集，或检查阅读服务是否启动。</div>';
        helperText.textContent = `连接失败：${{error.message}}`;
      }}
    }}

    dateSelect.addEventListener('change', event => loadDate(event.target.value).catch(error => {{
      helperText.textContent = `加载失败：${{error.message}}`;
    }}));
    refreshButton.addEventListener('click', () => refresh());
    modeButtons.forEach(button => {{
      button.addEventListener('click', () => {{
        modeButtons.forEach(item => item.classList.toggle('active', item === button));
        currentMode = button.dataset.mode;
        const dates = rebuildDateSelect();
        if (dates.length) {{
          loadDate(dates[0].date).catch(error => {{
            helperText.textContent = `加载失败：${{error.message}}`;
          }});
        }} else {{
          reader.innerHTML = '<div class="empty">当前模式下没有可显示日期。</div>';
          authorNav.innerHTML = '';
        }}
      }});
    }});

    refresh();
  </script>
</body>
</html>
""".replace("__API_BASE__", repr(api_base)).replace("{{", "{").replace("}}", "}")
