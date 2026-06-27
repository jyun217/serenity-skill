#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产业链研究库 — 静态站点生成器（离线、零依赖）。

用法:
    python3 industryresearch/build.py

它做什么:
  1. 读取本目录下的 library.json（目录元数据）。
  2. 扫描 md/ 子目录下的 *.md（你的分析正文，只读、不修改）。
  3. 按 library.json 的 match 关键词把每个 md 匹配到一条目录元数据。
  4. 生成 index.html（按行业→类型归纳的门户）和 pages/<文件名>.html（逐篇渲染详情页）。

新增一篇分析的流程:
  a. 把新的 .md 放进 md/ 子目录。
  b. 在 library.json 的 entries 里加一条（match 填文件名里的唯一关键词）。
  c. 重新运行 python3 industryresearch/build.py。

无需联网、无需安装任何库。双击 index.html 即可在浏览器查看。
"""

import json
import re
import html
import glob
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
MD_DIR = os.path.join(HERE, "md")
PAGES_DIR = os.path.join(HERE, "pages")


# --------------------------------------------------------------------------
# 轻量 Markdown -> HTML 转换器（针对本研究库使用的 md 子集）
# 支持: # 标题 / GFM 管道表格 / 有序无序列表(含嵌套) / > 引用 / --- 分隔线
#       **加粗** / `行内代码` / [文字](链接) / 段落 / HTML 转义
# --------------------------------------------------------------------------

_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")
_HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _inline(text):
    """行内元素: 转义 -> 提取代码 -> 链接 -> 加粗 -> 还原代码。"""
    text = html.escape(text, quote=False)
    codes = []

    def _stash(m):
        codes.append("<code>" + m.group(1) + "</code>")
        return "\x00%d\x00" % (len(codes) - 1)

    text = _CODE_RE.sub(_stash, text)
    text = _LINK_RE.sub(
        lambda m: '<a href="%s" target="_blank" rel="noopener">%s</a>'
        % (html.escape(m.group(2), quote=True), m.group(1)),
        text,
    )
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)
    return text


def _split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _render_table(header, rows):
    out = ['<div class="table-wrap"><table>', "<thead><tr>"]
    for c in header:
        out.append("<th>%s</th>" % _inline(c))
    out.append("</tr></thead><tbody>")
    for r in rows:
        # pad / trim to header width
        cells = (r + [""] * len(header))[: len(header)]
        out.append("<tr>" + "".join("<td>%s</td>" % _inline(c) for c in cells) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def _render_list(items):
    """items: list of (indent, marker, text). 用缩进栈构建嵌套列表。"""
    html_out = []
    stack = []  # each: {"tag": "ul"/"ol", "indent": int}

    def close_to(indent):
        while stack and stack[-1]["indent"] >= indent:
            html_out.append("</%s>" % stack[-1]["tag"])
            stack.pop()

    for indent, marker, text in items:
        tag = "ol" if marker[0].isdigit() else "ul"
        if not stack or indent > stack[-1]["indent"]:
            html_out.append("<%s>" % tag)
            stack.append({"tag": tag, "indent": indent})
        elif indent < stack[-1]["indent"]:
            close_to(indent + 1)
            if not stack or stack[-1]["indent"] != indent:
                html_out.append("<%s>" % tag)
                stack.append({"tag": tag, "indent": indent})
        html_out.append("<li>%s</li>" % _inline(text))

    while stack:
        html_out.append("</%s>" % stack[-1]["tag"])
        stack.pop()
    return "".join(html_out)


def md_to_html(text):
    # 去掉可能存在的 YAML front-matter
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            text = text[end + 4 :]

    lines = text.split("\n")
    out = []
    i = 0
    n = len(lines)
    para = []
    list_buf = []

    def flush_para():
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(para)))
            para.clear()

    def flush_list():
        if list_buf:
            out.append(_render_list(list_buf))
            list_buf.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 空行
        if not stripped:
            flush_para()
            flush_list()
            i += 1
            continue

        # 标题
        m = _HEAD_RE.match(line)
        if m:
            flush_para()
            flush_list()
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, _inline(m.group(2)), level))
            i += 1
            continue

        # 分隔线
        if re.match(r"^\s*([-*_])\s*(\1\s*){2,}$", line):
            flush_para()
            flush_list()
            out.append("<hr>")
            i += 1
            continue

        # 表格: 当前行含 | 且下一行是分隔行
        if "|" in line and i + 1 < n and _SEP_RE.match(lines[i + 1]):
            flush_para()
            flush_list()
            header = _split_row(line)
            rows = []
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            out.append(_render_table(header, rows))
            continue

        # 引用
        if stripped.startswith(">"):
            flush_para()
            flush_list()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].lstrip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % _inline(" ".join(quote)))
            continue

        # 列表
        m = _LIST_RE.match(line)
        if m:
            flush_para()
            indent = len(m.group(1))
            list_buf.append((indent, m.group(2), m.group(3)))
            i += 1
            continue

        # 普通段落
        flush_list()
        para.append(stripped)
        i += 1

    flush_para()
    flush_list()
    return "\n".join(out)


# --------------------------------------------------------------------------
# 页面模板 / 样式
# --------------------------------------------------------------------------

CSS = """
:root{
  --bg:#0f1217; --panel:#161b22; --panel2:#1c232c; --line:#2a323c;
  --ink:#e6edf3; --muted:#9aa7b4; --faint:#6e7b8a;
  --accent:#4ea1ff; --accent2:#36c39b; --warn:#e0b341;
  --chip:#222c38; --semi:#3b82f6; --pharma:#22b07d;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  line-height:1.7;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px}

header.site{border-bottom:1px solid var(--line);background:linear-gradient(180deg,#12161c,#0f1217)}
header.site .wrap{padding:34px 22px 26px}
.site h1{margin:0 0 6px;font-size:26px;letter-spacing:.5px}
.site .sub{color:var(--muted);font-size:14px;margin:0}
.meta-row{display:flex;gap:18px;flex-wrap:wrap;margin-top:16px;color:var(--faint);font-size:12.5px}
.meta-row b{color:var(--ink);font-weight:600}

.toolbar{position:sticky;top:0;z-index:5;background:rgba(15,18,23,.92);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.toolbar .wrap{display:flex;gap:12px;align-items:center;padding:12px 22px;flex-wrap:wrap}
.search-wrap{flex:1;min-width:200px;position:relative;display:flex}
#search{flex:1;min-width:0;background:var(--panel2);border:1px solid var(--line);
  color:var(--ink);border-radius:9px;padding:9px 36px 9px 13px;font-size:14px;outline:none}
#search:focus{border-color:var(--accent)}
.search-clear{position:absolute;right:8px;top:50%;transform:translateY(-50%);cursor:pointer;
  color:var(--muted);font-size:18px;line-height:1;width:22px;height:22px;border-radius:50%;
  display:none;align-items:center;justify-content:center;user-select:none}
.search-clear:hover{background:var(--line);color:var(--ink)}
.search-clear.on{display:flex}
.filters{display:flex;gap:7px;flex-wrap:wrap}
.filt{background:var(--chip);border:1px solid var(--line);color:var(--muted);
  border-radius:999px;padding:5px 13px;font-size:12.5px;cursor:pointer;user-select:none}
.filt.on{background:var(--accent);border-color:var(--accent);color:#06101c;font-weight:600}

section.industry{margin:34px 0 8px}
.industry-head{display:flex;align-items:center;gap:12px;margin:0 0 4px}
.industry-head .dot{width:11px;height:11px;border-radius:50%;background:#6e7b8a}
.dot.半导体{background:var(--semi)} .dot.医药生物{background:var(--pharma)} .dot.化工新材料{background:#c98a3a}
.industry-head h2{font-size:20px;margin:0}
.industry-head .cnt{color:var(--faint);font-size:13px}
.type-label{color:var(--faint);font-size:12.5px;text-transform:uppercase;letter-spacing:1px;
  margin:22px 0 12px;border-left:3px solid var(--line);padding-left:10px}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 18px 16px;
  display:flex;flex-direction:column;transition:.15s;position:relative;overflow:hidden}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}
.card .badge{position:absolute;top:0;right:0;font-size:11px;padding:4px 11px;border-bottom-left-radius:10px;font-weight:600}
.badge.产业链{background:#1d3a52;color:#8fc8ff}
.badge.单公司深挖{background:#1f3d33;color:#7fe0bf}
.card h3{margin:2px 60px 8px 0;font-size:16.5px;line-height:1.4}
.card .sub{color:var(--accent2);font-size:12.5px;margin:0 0 10px;font-weight:500}
.card .crosstag{display:inline-block;font-size:11px;color:#8fc8ff;background:#13202e;
  border:1px solid #25425c;border-radius:6px;padding:2px 8px;margin:0 0 9px}
.card .summary{color:var(--muted);font-size:13.5px;margin:0 0 14px;flex:1}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.chip{background:var(--chip);border:1px solid var(--line);color:var(--faint);
  font-size:11.5px;border-radius:6px;padding:3px 8px}
.card .foot{display:flex;justify-content:space-between;align-items:center;
  border-top:1px solid var(--line);padding-top:11px;font-size:12.5px}
.card .foot .date{color:var(--faint)}
.card .foot a{font-weight:600}

footer.site{border-top:1px solid var(--line);margin-top:46px;color:var(--faint);font-size:12.5px}
footer.site .wrap{padding:24px 22px 40px}
.disclaimer{color:var(--warn);opacity:.85}
.empty{color:var(--faint);text-align:center;padding:40px;display:none}

/* ---------- 详情页 ---------- */
.doc{max-width:880px;margin:0 auto;padding:30px 22px 80px}
.backbar{position:sticky;top:0;background:rgba(15,18,23,.92);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line);z-index:5}
.backbar .wrap{max-width:880px;display:flex;justify-content:space-between;align-items:center;padding:12px 22px;font-size:13.5px}
.crumb{color:var(--faint)}
.doc h1{font-size:25px;line-height:1.35;margin:18px 0 6px;border:none}
.doc h2{font-size:20px;margin:34px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--line)}
.doc h3{font-size:16.5px;margin:24px 0 8px;color:#cfe3ff}
.doc h4{font-size:14.5px;margin:18px 0 6px;color:var(--muted)}
.doc p{margin:11px 0}
.doc strong{color:#fff}
.doc a{word-break:break-all}
.doc ul,.doc ol{padding-left:24px;margin:10px 0}
.doc li{margin:5px 0}
.doc blockquote{margin:16px 0;padding:10px 16px;background:var(--panel);
  border-left:3px solid var(--accent);border-radius:6px;color:var(--muted);font-size:13.5px}
.doc hr{border:none;border-top:1px solid var(--line);margin:28px 0}
.doc code{background:var(--panel2);border:1px solid var(--line);border-radius:5px;
  padding:1px 6px;font-size:12.5px;font-family:"SF Mono",Menlo,Consolas,monospace;color:#e8b87f}
.table-wrap{overflow-x:auto;margin:16px 0;border:1px solid var(--line);border-radius:10px}
.doc table{border-collapse:collapse;width:100%;font-size:13px}
.doc th,.doc td{border:1px solid var(--line);padding:8px 11px;text-align:left;vertical-align:top}
.doc th{background:var(--panel2);color:#cfe3ff;font-weight:600;white-space:nowrap}
.doc tbody tr:nth-child(even){background:rgba(255,255,255,.02)}
.tags{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0 6px}
.related{margin-top:40px;border-top:1px solid var(--line);padding-top:18px}
.related h3{margin:0 0 12px}
.related a{display:inline-block;background:var(--panel);border:1px solid var(--line);
  border-radius:9px;padding:8px 13px;margin:0 8px 8px 0;font-size:13px}

/* ---------- 真卡点信号（多源指向） ---------- */
.signal-banner{background:linear-gradient(180deg,#1d1a0e,#14130c);border:1px solid #5a4a1e;
  border-radius:14px;padding:17px 19px;margin:24px 0 6px}
.signal-banner .lead{display:flex;align-items:center;gap:8px;font-size:15px;color:#ffd970;font-weight:700;margin-bottom:6px}
.signal-banner .desc{color:var(--muted);font-size:12.5px;margin:0 0 13px;line-height:1.6}
.signal-list{display:flex;gap:11px;flex-wrap:wrap}
.signal-group{margin-top:13px}
.signal-group:first-of-type{margin-top:2px}
.sg-head{font-size:12px;color:#cdb96e;font-weight:700;margin:0 0 8px;display:flex;align-items:center;gap:8px;letter-spacing:.4px;border-left:3px solid #6a5722;padding-left:9px}
.sg-head .sg-cnt{background:#2e2714;color:#ffd970;border-radius:999px;padding:1px 9px;font-size:11px;font-weight:600}
.signal-item{display:flex;align-items:center;gap:10px;background:#221d10;border:1px solid #6a5722;
  border-radius:11px;padding:9px 14px;font-size:13.5px}
.signal-item .nm{color:#ffe39a;font-weight:700}
.signal-item .hit{color:#cdb96e;font-size:11.5px;background:#2e2714;border-radius:999px;padding:2px 10px}
.card.flagged{border-color:#7a6526;box-shadow:0 0 0 1px #7a6526,0 0 26px -6px rgba(201,159,46,.55)}
.pill-signal{display:inline-flex;align-items:center;gap:5px;background:#3a3115;color:#ffd970;
  border:1px solid #7a6526;border-radius:999px;font-size:11.5px;font-weight:700;padding:3px 11px;margin:0 0 9px}
.chip.hot{background:#352c12;border-color:#7a6526;color:#ffd970;font-weight:600}
.signal-callout{background:linear-gradient(180deg,#1d1a0e,#14130c);border:1px solid #6a5722;
  border-radius:12px;padding:15px 18px;margin:8px 0 20px}
.signal-callout .lead{color:#ffd970;font-weight:700;font-size:14.5px;margin-bottom:7px;display:flex;align-items:center;gap:7px}
.signal-callout .desc{color:var(--muted);font-size:13px;margin:0 0 10px;line-height:1.6}
.signal-callout a{display:inline-block;margin:0 10px 6px 0;font-size:13px;background:#221d10;
  border:1px solid #6a5722;border-radius:8px;padding:6px 12px}

/* ---------- 层内卡点(单链头号卡点,青色,区别于金色多源指向) ---------- */
.legend{display:flex;gap:20px;flex-wrap:wrap;margin:14px 0 2px;font-size:12px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.lg-gold{color:#ffd970;font-weight:600}.lg-teal{color:#5fe0cf;font-weight:600}
.card .keypick{display:inline-block;font-size:12px;color:#ffd970;background:#2a2410;
  border:1px solid #6a5722;border-radius:7px;padding:5px 10px;margin:0 0 10px}
.pill-pick{display:inline-flex;align-items:center;gap:5px;background:#10302e;color:#5fe0cf;
  border:1px solid #1f6f63;border-radius:999px;font-size:11.5px;font-weight:700;padding:3px 11px;margin:0 0 9px}
.chip.pick{background:#10302e;border-color:#1f6f63;color:#5fe0cf;font-weight:600}
.pick-callout{background:linear-gradient(180deg,#0f2624,#0d1614);border:1px solid #1f6f63;
  border-radius:12px;padding:13px 17px;margin:8px 0 18px;color:#bfeee6;font-size:13px;line-height:1.6}
.pick-callout b{color:#5fe0cf}
.pick-callout a{color:#5fe0cf;margin-left:8px}
.trow.pick{border-color:#1f6f63;box-shadow:0 0 0 1px #1f6f63}
.trow.pick .tname{color:#5fe0cf}
.trow.pick .tcode{background:#10302e;border-color:#1f6f63;color:#5fe0cf}

/* ---------- 视图切换 + 按标的反查 ---------- */
.viewnav{display:flex;gap:8px;margin-left:auto}
.viewnav a{background:var(--chip);border:1px solid var(--line);color:var(--muted);
  border-radius:999px;padding:6px 14px;font-size:12.5px}
.viewnav a:hover{text-decoration:none;border-color:var(--accent)}
.viewnav a.cur{background:var(--accent);border-color:var(--accent);color:#06101c;font-weight:600}
.trow{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:15px 17px;margin-bottom:13px}
.trow.flagged{border-color:#7a6526;box-shadow:0 0 0 1px #7a6526,0 0 22px -8px rgba(201,159,46,.5)}
.thead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:11px}
.tname{font-size:16px;font-weight:700}
.trow.flagged .tname{color:#ffd970}
.tcode{background:var(--chip);border:1px solid var(--line);color:var(--faint);font-size:11.5px;border-radius:6px;padding:2px 8px}
.trow.flagged .tcode{background:#352c12;border-color:#7a6526;color:#ffd970}
.tcount{margin-left:auto;color:var(--faint);font-size:12px;background:var(--panel2);border:1px solid var(--line);border-radius:999px;padding:3px 11px}
.trow.flagged .tcount{color:#ffd970;border-color:#7a6526;background:#2e2714}
.tlist{display:flex;flex-direction:column;gap:7px}
.tlist a{display:flex;align-items:center;gap:10px;font-size:13.5px;color:var(--ink);
  padding:8px 11px;background:var(--panel2);border:1px solid var(--line);border-radius:8px}
.tlist a:hover{border-color:var(--accent);text-decoration:none}
.tlist .ttype{font-size:11px;border-radius:5px;padding:2px 8px;white-space:nowrap}
.ttype.产业链{background:#1d3a52;color:#8fc8ff}
.ttype.单公司深挖{background:#1f3d33;color:#7fe0bf}
.tlist .tttl{flex:1}
.tlist .tind{color:var(--faint);font-size:11.5px;white-space:nowrap}
.tlist .tdate{color:var(--faint);font-size:11.5px;white-space:nowrap}
"""

PAGE_HEAD = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head><body>"""


def company_name(ticker):
    """取标的字符串里空格前的公司名（合并 A/H 同名）。"""
    return ticker.split()[0] if ticker else ticker


def chip_html(t, marks=()):
    nm = company_name(t)
    return '<span class="%s">%s</span>' % ("chip hot" if nm in marks else "chip", html.escape(t))


def build_index(entries, cfg, marks):
    parts = [PAGE_HEAD.format(title=cfg["site_title"], css=CSS)]
    total = len(entries)
    dates = [e["date"] for e in entries if e.get("date")]
    last = max(dates) if dates else ""
    parts.append('<header class="site"><div class="wrap">')
    parts.append('<h1>%s</h1>' % html.escape(cfg["site_title"]))
    parts.append('<p class="sub">%s</p>' % html.escape(cfg["site_subtitle"]))
    parts.append(
        '<div class="meta-row"><span><b>%d</b> 篇分析</span>'
        '<span>覆盖 <b>%d</b> 个行业</span>'
        '<span>最近更新 <b>%s</b></span></div>'
        % (total, len(cfg["industries_order"]), last)
    )
    parts.append("</div></header>")

    # toolbar: search + industry filters
    parts.append('<div class="toolbar"><div class="wrap">')
    parts.append('<div class="search-wrap"><input id="search" type="text" placeholder="搜索标题 / 标的 / 关键词…">'
                 '<span class="search-clear" id="clear" title="清空">×</span></div>')
    parts.append('<div class="filters"><span class="filt on" data-f="all">全部</span>')
    for ind in cfg["industries_order"]:
        parts.append('<span class="filt" data-f="%s">%s</span>' % (html.escape(ind), html.escape(ind)))
    parts.append("</div>")
    parts.append('<div class="viewnav"><a class="cur">按行业</a><a href="tickers.html">按标的反查 →</a></div>')
    parts.append("</div></div>")

    parts.append('<main class="wrap">')

    # 真卡点信号横幅(金标:被几条产业链列为头号卡点,就几颗 🎯,全部置顶)
    if marks:
        parts.append('<div class="signal-banner">')
        parts.append('<div class="lead">🎯 真卡点信号</div>')
        parts.append(
            '<p class="desc">每有一条产业链把某标的列为<b class="lg-gold">头号卡点</b>，它就多一颗 🎯。'
            '<b class="lg-gold">1 颗 = 层内卡点</b>(单条产业链的头号卡点)；'
            '<b class="lg-gold">≥2 颗 = 多源指向</b>(多条相互独立的产业链共同把它列为头号卡点，最强信号)。</p>'
        )
        # 按行业分组(行业取自把它列为头号卡点的产业链)
        by_ind_marks = {}
        for nm, info in marks.items():
            seen = []
            for ch in info["chains"]:
                ci = ch.get("industry", "")
                if ci not in seen:
                    seen.append(ci)
            for ci in seen:
                by_ind_marks.setdefault(ci, {})[nm] = info
        ind_order = [i for i in cfg["industries_order"] if i in by_ind_marks] + \
                    [i for i in by_ind_marks if i not in cfg["industries_order"]]
        for ind in ind_order:
            items = by_ind_marks[ind]
            parts.append('<div class="signal-group" data-ind="%s">' % html.escape(ind))
            parts.append('<div class="sg-head">%s<span class="sg-cnt">%d</span></div>'
                         % (html.escape(ind), len(items)))
            parts.append('<div class="signal-list">')
            for nm, info in sorted(items.items(), key=lambda kv: (-kv[1]["stars"], kv[0])):
                in_ind = [x["title"] for x in info["chains"] if x.get("industry", "") == ind]
                chains = "、".join(in_ind or [x["title"] for x in info["chains"]])
                label = "多源指向" if info["stars"] >= 2 else "层内卡点"
                shay = (nm + " " + chains).lower()
                parts.append(
                    '<div class="signal-item" data-hay="%s"><span class="nm">%s %s</span>'
                    '<span class="hit">%s · %s</span>'
                    '<a href="pages/%s.html">查看 →</a></div>'
                    % (html.escape(shay), "🎯" * info["stars"], html.escape(nm), label, html.escape(chains), html.escape(info["link_slug"]))
                )
            parts.append("</div></div>")
        parts.append("</div>")

    by_ind = {}
    for e in entries:
        by_ind.setdefault(e["industry"], []).append(e)

    ordered_inds = [i for i in cfg["industries_order"] if i in by_ind]
    ordered_inds += [i for i in by_ind if i not in ordered_inds]

    for ind in ordered_inds:
        items = by_ind[ind]
        parts.append('<section class="industry" data-ind="%s">' % html.escape(ind))
        parts.append(
            '<div class="industry-head"><span class="dot %s"></span>'
            '<h2>%s</h2><span class="cnt">%d 篇</span></div>'
            % (html.escape(ind), html.escape(ind), len(items))
        )
        for typ in cfg["type_order"]:
            tset = [e for e in items if e["type"] == typ]
            if not tset:
                continue
            parts.append('<div class="type-label">%s</div>' % html.escape(typ))
            parts.append('<div class="grid">')
            for e in sorted(tset, key=lambda x: x.get("date", ""), reverse=True):
                also = e.get("also_in", [])
                all_inds = [ind] + [a for a in also if a != ind]
                hay = " ".join([e["title"], e["subsector"], e["summary"], " ".join(e["tickers"])] + all_inds)
                subj = company_name(e["tickers"][0]) if (e["type"] == "单公司深挖" and e["tickers"]) else None
                marked = subj in marks
                parts.append(
                    '<article class="card%s" data-ind="%s" data-hay="%s">'
                    % (" flagged" if marked else "", html.escape(",".join(all_inds)), html.escape(hay))
                )
                parts.append('<span class="badge %s">%s</span>' % (html.escape(e["type"]), html.escape(e["type"])))
                parts.append('<h3>%s</h3>' % html.escape(e["title"]))
                if marked:
                    n = marks[subj]["stars"]
                    parts.append('<div class="pill-signal">%s 真卡点 · %s</div>'
                                 % ("🎯" * n, "多源指向" if n >= 2 else "层内卡点"))
                parts.append('<p class="sub">%s</p>' % html.escape(e["subsector"]))
                if also:
                    parts.append('<div class="crosstag">↳ 也属:%s</div>' % html.escape("、".join(also)))
                parts.append('<p class="summary">%s</p>' % html.escape(e["summary"]))
                if e.get("key_pick"):
                    kps = e["key_pick"]
                    kps = [kps] if isinstance(kps, str) else kps
                    parts.append('<div class="keypick">🎯 本链头号卡点：%s</div>' % html.escape("、".join(kps)))
                parts.append('<div class="chips">%s</div>' % "".join(chip_html(t, marks) for t in e["tickers"]))
                parts.append(
                    '<div class="foot"><span class="date">%s</span>'
                    '<a href="pages/%s.html">查看完整分析 →</a></div>'
                    % (html.escape(e.get("date", "")), html.escape(e["slug"]))
                )
                parts.append("</article>")
            parts.append("</div>")
        parts.append("</section>")

    parts.append('<div class="empty" id="empty">没有匹配的分析。</div>')
    parts.append("</main>")

    parts.append(
        '<footer class="site"><div class="wrap">'
        '<p class="disclaimer">免责声明：本研究库为公开资料的研究支持与排序，不构成任何买卖建议；决策与风险由使用者自行把握。</p>'
        '<p>本页由 <code>build.py</code> 自动生成。新增分析：放入 .md → 在 library.json 加一条 → 运行 '
        '<code>python3 industryresearch/build.py</code>。</p>'
        "</div></footer>"
    )

    # search + filter JS
    parts.append("""<script>
(function(){
  var q=document.getElementById('search'),empty=document.getElementById('empty');
  var clr=document.getElementById('clear');
  var cards=[].slice.call(document.querySelectorAll('.card'));
  var filts=[].slice.call(document.querySelectorAll('.filt'));
  var sgroups=[].slice.call(document.querySelectorAll('.signal-group'));
  var banner=document.querySelector('.signal-banner');
  var curF='all';
  function apply(){
    var term=(q.value||'').toLowerCase().trim();var shown=0;
    if(clr)clr.classList.toggle('on',!!(q.value||'').length);
    cards.forEach(function(c){
      var okF=curF==='all'||(c.getAttribute('data-ind')||'').split(',').indexOf(curF)>=0;
      var okT=!term||c.getAttribute('data-hay').toLowerCase().indexOf(term)>=0;
      var on=okF&&okT;c.style.display=on?'':'none';if(on)shown++;
    });
    if(banner){
      var sShown=0;
      sgroups.forEach(function(g){
        var okF=curF==='all'||(g.getAttribute('data-ind')||'')===curF;
        var iShown=0;
        [].slice.call(g.querySelectorAll('.signal-item')).forEach(function(it){
          var okT=!term||(it.getAttribute('data-hay')||'').indexOf(term)>=0;
          it.style.display=okT?'':'none';if(okT)iShown++;
        });
        var on=okF&&iShown>0;g.style.display=on?'':'none';if(on)sShown++;
      });
      banner.style.display=sShown?'':'none';
    }
    document.querySelectorAll('.industry').forEach(function(s){
      var any=[].slice.call(s.querySelectorAll('.card')).some(function(c){return c.style.display!=='none';});
      s.style.display=any?'':'none';
      s.querySelectorAll('.type-label').forEach(function(tl){
        var grid=tl.nextElementSibling;
        var vis=[].slice.call(grid.querySelectorAll('.card')).some(function(c){return c.style.display!=='none';});
        tl.style.display=vis?'':'none';grid.style.display=vis?'':'none';
      });
    });
    empty.style.display=shown?'none':'block';
  }
  q.addEventListener('input',apply);
  if(clr)clr.addEventListener('click',function(){q.value='';q.focus();apply();});
  filts.forEach(function(f){f.addEventListener('click',function(){
    filts.forEach(function(x){x.classList.remove('on');});f.classList.add('on');
    curF=f.getAttribute('data-f');apply();
  });});
})();
</script>""")
    parts.append("</body></html>")
    return "\n".join(parts)


def build_page(e, cfg, slug_to_entry, marks):
    body = md_to_html(e["_md"])
    parts = [PAGE_HEAD.format(title=e["title"], css=CSS)]
    parts.append('<div class="backbar"><div class="wrap">')
    parts.append('<a href="../index.html">← 返回研究库</a>')
    parts.append('<span class="crumb">%s · %s</span>' % (html.escape(e["industry"]), html.escape(e["subsector"])))
    parts.append("</div></div>")
    parts.append('<article class="doc">')
    parts.append('<div class="tags">%s</div>' % "".join(chip_html(t, marks) for t in e["tickers"]))

    # 产业链页:标出本篇头号卡点
    if e["type"] == "产业链" and e.get("key_pick"):
        kps = e["key_pick"]
        kps = [kps] if isinstance(kps, str) else kps
        parts.append(
            '<div class="signal-callout"><div class="lead">🎯 本篇头号卡点：%s</div>'
            '<p class="desc">该条产业链识别出的最关键卡点标的(1 颗 🎯 = 层内卡点)。'
            '若多条相互独立的产业链都把同一标的列为头号卡点，它会升级为“多源指向”(多颗 🎯)。</p></div>'
            % html.escape("、".join(kps))
        )

    # 单公司页:若该标的是某些产业链的头号卡点
    subj = company_name(e["tickers"][0]) if (e["type"] == "单公司深挖" and e["tickers"]) else None
    if subj in marks:
        info = marks[subj]
        n = info["stars"]
        links = "".join(
            '<a href="%s.html">%s →</a>' % (html.escape(x["slug"]), html.escape(x["title"]))
            for x in info["chains"] if x["slug"] != e["slug"]
        )
        parts.append('<div class="signal-callout">')
        parts.append('<div class="lead">%s 真卡点 · %s</div>' % ("🎯" * n, "多源指向" if n >= 2 else "层内卡点"))
        parts.append(
            '<p class="desc">%s 被 %d 条%s产业链列为头号卡点%s相关分析：</p>'
            % (html.escape(subj), n, "相互独立的" if n >= 2 else "",
               "——多源指向，Serenity 方法里最强的信号。" if n >= 2 else "。")
        )
        parts.append(links)
        parts.append("</div>")

    parts.append(body)

    rel = []
    for r in e.get("related", []):
        if r in slug_to_entry:
            tgt = slug_to_entry[r]
            rel.append('<a href="%s.html">%s →</a>' % (html.escape(r), html.escape(tgt["title"])))
    if rel:
        parts.append('<div class="related"><h3>相关分析</h3>%s</div>' % "".join(rel))

    parts.append("</article>")
    parts.append("</body></html>")
    return "\n".join(parts)


def build_tickers(cfg, appears, name_codes, marks):
    parts = [PAGE_HEAD.format(title="按标的反查 · " + cfg["site_title"], css=CSS)]
    parts.append('<header class="site"><div class="wrap">')
    parts.append('<h1>按标的反查</h1>')
    parts.append('<p class="sub">每只标的出现在哪些分析里 — 🎯 的数量 = 被几条产业链列为头号卡点(1 颗层内卡点，≥2 颗多源指向)。</p>')
    n_multi = sum(1 for v in marks.values() if v["stars"] >= 2)
    n_single = sum(1 for v in marks.values() if v["stars"] == 1)
    parts.append(
        '<div class="meta-row"><span>共 <b>%d</b> 只标的</span>'
        '<span>🎯🎯 <b>%d</b> 只多源指向</span>'
        '<span>🎯 <b>%d</b> 只层内卡点</span></div>' % (len(appears), n_multi, n_single)
    )
    parts.append("</div></header>")

    parts.append('<div class="toolbar"><div class="wrap">')
    parts.append('<div class="search-wrap"><input id="search" type="text" placeholder="搜索公司名 / 代码 / 分析标题…">'
                 '<span class="search-clear" id="clear" title="清空">×</span></div>')
    parts.append('<div class="viewnav"><a href="index.html">← 按行业</a><a class="cur">按标的反查</a></div>')
    parts.append("</div></div>")

    parts.append('<main class="wrap" style="padding-top:22px">')

    # 排序：头号卡点星数多 → 出现篇数多 → 名称
    def starcount(n):
        return marks[n]["stars"] if n in marks else 0

    names = sorted(appears.keys(), key=lambda n: (-starcount(n), -len(appears[n]), n))
    for nm in names:
        es = sorted(appears[nm], key=lambda x: x.get("date", ""), reverse=True)
        codes = sorted(name_codes.get(nm, []))
        n = starcount(nm)
        marked = nm in marks
        prefix = ("🎯" * n + " ") if marked else ""
        hay = " ".join([nm] + codes + [e["title"] for e in es])
        parts.append('<div class="trow%s" data-hay="%s">' % (" flagged" if marked else "", html.escape(hay)))
        parts.append('<div class="thead">')
        parts.append('<span class="tname">%s%s</span>' % (prefix, html.escape(nm)))
        for c in codes:
            code_only = c[len(nm):].strip() if c.startswith(nm) else c
            parts.append('<span class="tcode">%s</span>' % html.escape(code_only or c))
        if marked:
            kp = "、".join(x["title"] for x in marks[nm]["chains"])
            parts.append('<span class="tcode">%s · %s</span>'
                         % ("多源指向" if n >= 2 else "层内卡点", html.escape(kp)))
        parts.append('<span class="tcount">被 %d 篇指向</span>' % len(es))
        parts.append("</div>")
        parts.append('<div class="tlist">')
        for e in es:
            parts.append(
                '<a href="pages/%s.html"><span class="ttype %s">%s</span>'
                '<span class="tttl">%s</span>'
                '<span class="tind">%s</span><span class="tdate">%s</span></a>'
                % (
                    html.escape(e["slug"]), html.escape(e["type"]), html.escape(e["type"]),
                    html.escape(e["title"]), html.escape(e["subsector"]), html.escape(e.get("date", "")),
                )
            )
        parts.append("</div></div>")

    parts.append('<div class="empty" id="empty">没有匹配的标的。</div>')
    parts.append("</main>")
    parts.append(
        '<footer class="site"><div class="wrap">'
        '<p class="disclaimer">免责声明：本研究库为公开资料的研究支持与排序，不构成任何买卖建议；决策与风险由使用者自行把握。</p>'
        "</div></footer>"
    )
    parts.append("""<script>
(function(){
  var q=document.getElementById('search'),empty=document.getElementById('empty');
  var clr=document.getElementById('clear');
  var rows=[].slice.call(document.querySelectorAll('.trow'));
  function apply(){
    var t=(q.value||'').toLowerCase().trim();var shown=0;
    if(clr)clr.classList.toggle('on',!!(q.value||'').length);
    rows.forEach(function(r){
      var on=!t||r.getAttribute('data-hay').toLowerCase().indexOf(t)>=0;
      r.style.display=on?'':'none';if(on)shown++;
    });
    empty.style.display=shown?'none':'block';
  }
  q.addEventListener('input',apply);
  if(clr)clr.addEventListener('click',function(){q.value='';q.focus();apply();});
})();
</script>""")
    parts.append("</body></html>")
    return "\n".join(parts)


def main():
    with open(os.path.join(HERE, "library.json"), encoding="utf-8") as f:
        cfg = json.load(f)

    md_files = sorted(glob.glob(os.path.join(MD_DIR, "*.md")))
    entries = []
    used = set()

    for path in md_files:
        fname = os.path.basename(path)
        stem = fname[:-3]
        match_entry = None
        for ent in cfg["entries"]:
            if ent["match"] in fname and ent["match"] not in used:
                match_entry = ent
                used.add(ent["match"])
                break
        if not match_entry:
            print("  [warn] 未在 library.json 找到匹配: %s （已跳过，请补一条 entry）" % fname)
            continue
        with open(path, encoding="utf-8") as f:
            md = f.read()
        e = dict(match_entry)
        e["slug"] = stem
        e["_md"] = md
        entries.append(e)

    for ent in cfg["entries"]:
        if ent["match"] not in used:
            print("  [warn] library.json 里的 entry 没有对应 md 文件: match=%s" % ent["match"])

    slug_to_entry = {e["slug"]: e for e in entries}

    # ---- 标的索引(用于"按标的反查") ----
    appears = {}        # 公司名 -> [entry,...]
    deepdive_slug = {}  # 公司名 -> 其单公司深挖页 slug
    name_codes = {}     # 公司名 -> {完整标的串,...}
    for e in entries:
        for t in e["tickers"]:
            name_codes.setdefault(company_name(t), set()).add(t)
        for nm in {company_name(t) for t in e["tickers"]}:
            appears.setdefault(nm, []).append(e)
        if e["type"] == "单公司深挖" and e["tickers"]:
            deepdive_slug[company_name(e["tickers"][0])] = e["slug"]

    # ---- 真卡点信号(统一金标)：被几条产业链列为头号卡点(key_pick),就几颗 🎯 ----
    #   1 颗 = 层内卡点(单链头号)；≥2 颗 = 多源指向(多条独立产业链共同指向,最强)。
    pick_of = {}  # 公司名 -> [把它列为头号卡点的产业链 entry,...]
    for e in entries:
        kp = e.get("key_pick")
        if kp:
            for nm in ([kp] if isinstance(kp, str) else kp):
                pick_of.setdefault(nm, []).append(e)
    marks = {}
    for nm, chains in pick_of.items():
        marks[nm] = {
            "stars": len(chains),
            "chains": chains,
            "link_slug": deepdive_slug.get(nm, chains[0]["slug"]),
        }
    if marks:
        print("  🎯 真卡点信号：" + "，".join(
            "%s%s(%d链)" % ("🎯" * v["stars"], n, v["stars"])
            for n, v in sorted(marks.items(), key=lambda kv: -kv[1]["stars"])))

    os.makedirs(PAGES_DIR, exist_ok=True)
    for e in entries:
        out = build_page(e, cfg, slug_to_entry, marks)
        with open(os.path.join(PAGES_DIR, e["slug"] + ".html"), "w", encoding="utf-8") as f:
            f.write(out)

    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_index(entries, cfg, marks))

    with open(os.path.join(HERE, "tickers.html"), "w", encoding="utf-8") as f:
        f.write(build_tickers(cfg, appears, {k: sorted(v) for k, v in name_codes.items()}, marks))

    print("✓ 生成完成：%d 篇 → index.html + tickers.html + pages/（共 %d 个详情页，%d 只标的）"
          % (len(entries), len(entries), len(appears)))


if __name__ == "__main__":
    main()
