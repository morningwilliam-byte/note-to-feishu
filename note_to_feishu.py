#!/usr/bin/env python3
"""
Apple Notes / 剪贴板 → 飞书文档
用法：
  echo "HTML" | python3 note_to_feishu.py "标题"   # Apple Notes 管道
  python3 note_to_feishu.py "标题" --clipboard      # 剪贴板
"""
import os
import re
import sys
import json
import subprocess
import urllib.request
from html.parser import HTMLParser

# ── Config (secrets loaded from ~/.config/note_to_feishu/config.json or env vars) ──
_CONFIG_FILE = os.path.expanduser("~/.config/note_to_feishu/config.json")

def _load_config():
    cfg = {}
    try:
        with open(_CONFIG_FILE) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        pass  # fall through to env vars
    except Exception as e:
        sys.exit(f"❌ 配置文件解析失败 ({_CONFIG_FILE}): {e}")
    # Env vars override file values
    cfg.setdefault("app_id",       os.environ.get("FEISHU_APP_ID", ""))
    cfg.setdefault("app_secret",   os.environ.get("FEISHU_APP_SECRET", ""))
    cfg.setdefault("folder_token", os.environ.get("FEISHU_FOLDER_TOKEN", ""))
    missing = [k for k in ("app_id", "app_secret", "folder_token") if not cfg.get(k)]
    if missing:
        sys.exit(
            f"❌ 缺少配置项: {missing}\n"
            f"   请复制 config.example.json 到 {_CONFIG_FILE} 并填入实际值。\n"
            f"   或设置环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_FOLDER_TOKEN"
        )
    return cfg

_cfg = _load_config()
APP_ID       = _cfg["app_id"]
APP_SECRET   = _cfg["app_secret"]
FOLDER_TOKEN = _cfg["folder_token"]

# OAuth — user_access_token (so documents are created as the user, not the bot)
TOKEN_STORE    = os.path.expanduser("~/.config/note_to_feishu/user_token.json")
OAUTH_REDIRECT = "http://localhost:9988/callback"


def http_post(url, data, token=None):
    import urllib.error
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise Exception(f"HTTP {e.code}: {detail}") from None


def http_patch(url, data, token):
    import urllib.error
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="PATCH")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise Exception(f"HTTP {e.code}: {detail}") from None


def http_get(url, token):
    import urllib.error
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise Exception(f"HTTP {e.code}: {detail}") from None


def get_token():
    result = http_post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": APP_ID, "app_secret": APP_SECRET}
    )
    return result["tenant_access_token"]


# ── HTML → Feishu blocks ──────────────────────────────────────────────────────

class HTMLToBlocks(HTMLParser):
    # Word class → Feishu block type
    WORD_HEADING = {
        "MsoHeading1": 3, "MsoHeading2": 4, "MsoHeading3": 5,
        "MsoTitle": 3, "MsoSubtitle": 4,
    }
    WORD_LIST = {
        "MsoListParagraph", "MsoListParagraphCxSpFirst",
        "MsoListParagraphCxSpMiddle", "MsoListParagraphCxSpLast",
    }
    # HTML tag → Feishu block type
    TAG_HEADING = {"h1": 3, "h2": 4, "h3": 5, "h4": 5}
    # Fonts used for Word bullet/symbol characters (should be skipped)
    SKIP_FONTS = {"symbol", "wingdings", "wingdings2"}

    def __init__(self):
        super().__init__()
        self._blocks = []
        self._runs = []
        self._style_stack = []
        self._block_type = 2
        self._list_stack = []
        self._skip = False       # inside <style>/<script>
        self._skip_depth = 0     # inside <o:p> / <w:*> etc.
        self._span_stack = []    # (kind: "skip"|"style"|"plain", pushed_style: bool)
        # table state
        self._in_table = False
        self._table_rows = []
        self._cur_row = []
        self._cur_cell_text = []
        self._in_cell = False
        # CSS class → font size map (extracted from <style> block)
        # Used to detect headings in textutil-generated HTML
        self._css_class_fontsize = {}   # "p1" → 22.0  (float, px)
        self._style_buf = []            # accumulate <style> text
        self._indent_level = 1          # current block indent level (1-based)
        self._list_margins = []         # sorted unique margin-left (pt) values for dynamic level mapping

    def _skip_active(self):
        return self._skip or self._skip_depth > 0

    def _parse_css_classes(self, css_text):
        """Parse <style> block to extract font sizes for p.pN classes.
        e.g. 'p.p1 {font: 22.0px Times; ...}' → {'p1': 22.0}
        """
        # Match rules like: p.p1 { ... font: 14px ... }  or  p.p1 { font-size: 14px }
        for rule_m in re.finditer(r'p\.(\w+)\s*\{([^}]*)\}', css_text):
            cls = rule_m.group(1)
            body = rule_m.group(2)
            # font shorthand: "font: 22.0px Arial" or "font: bold 22.0px Arial"
            m = re.search(r'\bfont\s*:[^;]*?([\d.]+)px\b', body)
            if not m:
                # font-size: 22.0px
                m = re.search(r'font-size\s*:\s*([\d.]+)px', body)
            if m:
                self._css_class_fontsize[cls] = float(m.group(1))

    def _block_type_from_css_class(self, cls_name):
        """Heuristic: map CSS class → block type based on font size.
        Uses both absolute thresholds and relative ranking within the document.
        Returns None if no match / size is body-text range.
        """
        size = self._css_class_fontsize.get(cls_name)
        if size is None:
            return None
        sizes = sorted(set(self._css_class_fontsize.values()), reverse=True)
        body_size = min(sizes) if sizes else 11.0
        # Don't treat body-size text as a heading
        if size <= body_size:
            return None
        # Absolute lower bound: must be visibly larger than typical body (>= 11px)
        if size < 11.5:
            return None
        # Find rank among distinct sizes larger than body
        larger = [s for s in sizes if s > body_size]
        if not larger:
            return None
        rank = larger.index(size) if size in larger else len(larger)
        if rank == 0:
            return 3   # H1 – largest
        if rank == 1:
            return 4   # H2 – second largest
        return 5       # H3 – third or smaller

    def _merged_style(self):
        merged = {}
        for d in self._style_stack:
            merged.update(d)
        return merged

    BULLET_CHARS = set("•·◦▪○–￮◉◌◍●◎")

    # Map block_type → content key name required by Feishu API
    BLOCK_TYPE_KEY = {
        2: "text",
        3: "heading1",
        4: "heading2",
        5: "heading3",
        6: "heading4",
        7: "heading5",
        8: "heading6",
        9: "heading7",
        10: "heading8",
        11: "heading9",
        12: "bullet",
        13: "ordered",
    }

    def _flush(self):
        if self._runs:
            # Drop whitespace-only runs
            runs = [r for r in self._runs
                    if r.get("text_run", {}).get("content", "").strip()]
            block_type = self._block_type
            indent = self._indent_level
            # Detect/strip inline bullet characters
            if runs:
                first = runs[0].get("text_run", {}).get("content", "").strip()
                if first in self.BULLET_CHARS:
                    if block_type == 2:
                        block_type = 12
                    runs = runs[1:]  # drop bullet run
                    if runs:
                        first_content = runs[0].get("text_run", {}).get("content", "")
                        stripped = first_content.lstrip()
                        if stripped != first_content:
                            runs[0] = dict(runs[0])
                            runs[0]["text_run"] = dict(runs[0]["text_run"])
                            runs[0]["text_run"]["content"] = stripped
            if runs:
                content_key = self.BLOCK_TYPE_KEY.get(block_type, "text")
                block = {
                    "block_type": block_type,
                    content_key: {"elements": runs, "style": {}}
                }
                if indent > 1 and block_type in (12, 13):
                    # Store indent hint; consumed by _build_block_tree during upload.
                    # Feishu nests indented bullets as child blocks of their parent.
                    block["_indent"] = indent
                self._blocks.append(block)
        self._runs = []
        self._block_type = 2
        self._indent_level = 1

    def _make_run(self, text):
        s = self._merged_style()
        el_style = {}
        for k in ("bold", "italic", "underline", "strikethrough"):
            if s.get(k):
                el_style[k] = True
        if s.get("link"):
            el_style["link"] = s["link"]
        tr = {"content": text}
        if el_style:
            tr["text_element_style"] = el_style
        return {"text_run": tr}

    @staticmethod
    def _parse_style(css):
        """Parse inline CSS string into a style dict."""
        result = {}
        if re.search(r'font-weight\s*:\s*bold', css, re.I):
            result["bold"] = True
        if re.search(r'font-style\s*:\s*italic', css, re.I):
            result["italic"] = True
        if re.search(r'text-decoration\s*:[^;]*underline', css, re.I):
            result["underline"] = True
        if re.search(r'text-decoration\s*:[^;]*line-through', css, re.I):
            result["strikethrough"] = True
        return result

    @staticmethod
    def _margin_to_pt(style):
        """Extract margin-left in points from inline CSS."""
        m = re.search(r'margin-left\s*:\s*([\d.]+)(pt|cm|in)', style, re.I)
        if not m:
            return 0.0
        val, unit = float(m.group(1)), m.group(2).lower()
        return val * (28.35 if unit == "cm" else 72 if unit == "in" else 1)

    def _indent_for_margin(self, margin_pt):
        """1-based indent level derived from margin-left (dynamic ranking)."""
        import bisect
        if margin_pt not in self._list_margins:
            bisect.insort(self._list_margins, margin_pt)
        return self._list_margins.index(margin_pt) + 1

    @staticmethod
    def _is_symbol_font(css):
        """Check if style uses a symbol/dingbat font (Word bullet characters)."""
        m = re.search(r'font-family\s*:\s*[\'"]?([^\'";\s,]+)', css, re.I)
        return bool(m and m.group(1).lower().replace(" ", "") in HTMLToBlocks.SKIP_FONTS)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag in ("style", "script"):
            self._skip = True
            if tag == "style":
                self._style_buf = []
            return

        # Skip Office XML tags like <o:p>, <w:*>, <m:*>
        if ":" in tag and tag.split(":")[0] in ("o", "w", "m"):
            self._skip_depth += 1; return

        if self._skip_active(): return

        if self._in_table:
            if tag == "tr":   self._cur_row = []
            elif tag in ("td", "th"):
                self._in_cell = True; self._cur_cell_text = []
            elif self._in_cell and tag in ("p", "li", "br"):
                # Paragraph/item start within a cell — add separator
                if self._cur_cell_text:
                    self._cur_cell_text.append("\n")
            return

        if tag == "span":
            style = attrs.get("style", "")
            if self._is_symbol_font(style):
                self._span_stack.append(("skip", False))
            else:
                sp = self._parse_style(style)
                if sp:
                    self._style_stack.append(sp)
                self._span_stack.append(("style", bool(sp)))
            return

        if tag == "p":
            self._flush()
            cls = attrs.get("class", "")
            inline_style = attrs.get("style", "")
            self._block_type = 2
            self._indent_level = 1
            for hcls, bt in self.WORD_HEADING.items():
                if hcls in cls:
                    self._block_type = bt; break
            else:
                # Word clipboard HTML encodes heading level via mso-outline-level in style
                ol_m = re.search(r'mso-outline-level\s*:\s*(\d+)', inline_style, re.I)
                if ol_m:
                    level = int(ol_m.group(1))
                    # mso-outline-level 1→H1(3), 2→H2(4), 3→H3(5), …
                    self._block_type = min(2 + level, 11)
                else:
                    is_list = any(lc in cls for lc in self.WORD_LIST)
                    if not is_list and "mso-list" in inline_style:
                        is_list = True  # MsoNormal with mso-list (Word uses margin-left for indent)
                    if is_list:
                        self._block_type = 12
                        # Try mso-list levelN (works when class is MsoListParagraph)
                        m = re.search(r'mso-list\s*:[^;]*\blevel(\d+)\b', inline_style, re.I)
                        if m and int(m.group(1)) > 1:
                            self._indent_level = int(m.group(1))
                        else:
                            # Fall back to margin-left for indent (works for MsoNormal + mso-list)
                            margin_pt = self._margin_to_pt(inline_style)
                            self._indent_level = self._indent_for_margin(margin_pt)
                    else:
                        # textutil-generated HTML: infer heading level from CSS font size
                        # cls may be "p1", "p2", etc.
                        css_bt = self._block_type_from_css_class(cls)
                        if css_bt is not None:
                            self._block_type = css_bt
        elif tag == "div":
            self._flush()
        elif tag in self.TAG_HEADING:
            self._flush(); self._block_type = self.TAG_HEADING[tag]
        elif tag == "hr":
            self._flush(); self._blocks.append({"block_type": 22, "divider": {}})
        elif tag == "ul":
            self._list_stack.append(["ul", 0])
        elif tag == "ol":
            self._list_stack.append(["ol", 0])
        elif tag == "li":
            self._flush()
            self._block_type = 12 if (self._list_stack and self._list_stack[-1][0] == "ul") else 13
            # Use nesting depth for indent level (1-based)
            self._indent_level = len(self._list_stack)
        elif tag == "br":
            self._flush()
        elif tag in ("b", "strong"):
            self._style_stack.append({"bold": True})
        elif tag in ("i", "em"):
            self._style_stack.append({"italic": True})
        elif tag == "u":
            self._style_stack.append({"underline": True})
        elif tag in ("s", "del", "strike"):
            self._style_stack.append({"strikethrough": True})
        elif tag == "a":
            href = attrs.get("href", "")
            self._style_stack.append({"link": {"url": href}} if href else {})
        elif tag == "table":
            self._flush(); self._in_table = True; self._table_rows = []

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            if tag == "style" and self._style_buf:
                self._parse_css_classes("".join(self._style_buf))
                self._style_buf = []
            self._skip = False; return

        if ":" in tag and tag.split(":")[0] in ("o", "w", "m"):
            self._skip_depth = max(0, self._skip_depth - 1); return

        if self._skip_active(): return

        if self._in_table:
            if tag in ("td", "th"):
                self._in_cell = False
                raw = "".join(self._cur_cell_text)
                # Collapse \n-separated segments into " / " joined string
                parts = [p.strip() for p in raw.split("\n") if p.strip()]
                cell = " / ".join(parts).replace("|", "\\|")
                self._cur_row.append(cell)
                self._cur_cell_text = []
            elif tag == "tr":
                self._table_rows.append(self._cur_row)
            elif tag == "table":
                self._in_table = False; self._render_table()
            return

        if tag == "span":
            if self._span_stack:
                kind, had_style = self._span_stack.pop()
                if kind == "style" and had_style and self._style_stack:
                    self._style_stack.pop()
            return

        if tag in ("b", "strong", "i", "em", "u", "s", "del", "strike", "a"):
            if self._style_stack: self._style_stack.pop()
        elif tag in ("p", "li") or tag in self.TAG_HEADING:
            self._flush()
        elif tag in ("ul", "ol"):
            if self._list_stack: self._list_stack.pop()

    def _render_table(self):
        if not self._table_rows: return
        rows = self._table_rows
        cols = max(len(r) for r in rows) if rows else 0
        if cols == 0: return
        # Pad rows to uniform column count
        for row in rows:
            while len(row) < cols:
                row.append("")
        # Emit a sentinel block that create_doc will replace with a real table block
        self._blocks.append({
            "block_type": "__table__",
            "__rows__": rows,
            "__cols__": cols,
        })

    def handle_data(self, data):
        if self._skip:
            # Accumulate style block text for CSS parsing
            if self._style_buf is not None:
                self._style_buf.append(data)
            return
        if self._skip_depth > 0: return
        if self._in_cell:
            # Normalize newlines in cell content
            data = data.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
            self._cur_cell_text.append(data); return
        if self._span_stack and self._span_stack[-1][0] == "skip":
            return  # skip Word bullet/symbol characters
        # Replace newlines with spaces (Word HTML source formatting artifact)
        data = data.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        if data.strip() or (self._runs and data.strip()):
            self._runs.append(self._make_run(data))

    def get_blocks(self):
        self._flush()
        return self._blocks


def html_to_blocks(html):
    p = HTMLToBlocks()
    p.feed(html)
    return p.get_blocks()


def plain_to_blocks(text):
    blocks = []
    prev_empty = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if not prev_empty:
                blocks.append({"block_type": 2, "text": {
                    "elements": [{"text_run": {"content": ""}}], "style": {}}})
            prev_empty = True
        else:
            blocks.append({"block_type": 2, "text": {
                "elements": [{"text_run": {"content": stripped}}], "style": {}}})
            prev_empty = False
    return blocks


# ── Clipboard ─────────────────────────────────────────────────────────────────

def get_clipboard():
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e",
         'ObjC.import("AppKit"); var pb = $.NSPasteboard.generalPasteboard; '
         'var s = pb.stringForType("public.html"); s && s.js ? s.js : ""'],
        capture_output=True, text=True
    )
    html = result.stdout.strip()
    if html and "<" in html:
        return "html", html
    text = subprocess.run(
        ["osascript", "-e", "the clipboard"],
        capture_output=True, text=True
    ).stdout.strip()
    return "text", text or "(空剪贴板)"


# ── OAuth user token ─────────────────────────────────────────────────────────

def _save_user_token(data):
    os.makedirs(os.path.dirname(TOKEN_STORE), exist_ok=True)
    with open(TOKEN_STORE, "w") as f:
        json.dump({"access_token": data["access_token"],
                   "refresh_token": data["refresh_token"]}, f)


def _refresh_user_token(refresh_token):
    """Exchange refresh_token for a new user_access_token. Returns token or None."""
    try:
        result = http_post(
            "https://open.feishu.cn/open-apis/authen/v1/oidc/refresh_access_token",
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
            get_token()
        )
        if result.get("code") == 0:
            _save_user_token(result["data"])
            return result["data"]["access_token"]
    except Exception:
        pass
    return None


def _oauth_flow():
    """One-time browser OAuth. Returns user_access_token."""
    import webbrowser, threading
    import http.server as _hs
    import urllib.parse as _up

    code_box = [None]

    class _Handler(_hs.BaseHTTPRequestHandler):
        def do_GET(self):
            q = _up.parse_qs(_up.urlparse(self.path).query)
            code_box[0] = q.get("code", [None])[0]
            self.send_response(200); self.end_headers()
            msg = "✅ 授权成功，可以关闭此窗口。" if code_box[0] else "❌ 未获取到授权码"
            self.wfile.write(msg.encode())
        def log_message(self, *a): pass

    srv = _hs.HTTPServer(("localhost", 9988), _Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    url = (f"https://open.feishu.cn/open-apis/authen/v1/authorize"
           f"?app_id={APP_ID}&redirect_uri={_up.quote(OAUTH_REDIRECT)}&scope=offline_access")
    print("  正在打开飞书授权页面，请在浏览器中完成授权...", file=sys.stderr)
    webbrowser.open(url)

    import time
    for _ in range(120):
        time.sleep(1)
        if code_box[0]:
            break
    srv.server_close()

    if not code_box[0]:
        raise Exception("OAuth 授权超时（120秒）")

    result = http_post(
        "https://open.feishu.cn/open-apis/authen/v1/oidc/access_token",
        {"grant_type": "authorization_code", "code": code_box[0]},
        get_token()
    )
    if result.get("code") != 0:
        raise Exception(f"授权码换取 token 失败: {result}")

    _save_user_token(result["data"])
    print(f"  ✅ 授权成功，token 已保存", file=sys.stderr)
    return result["data"]["access_token"]


def get_user_token():
    """Return a valid user_access_token, refreshing or re-authorizing as needed."""
    try:
        with open(TOKEN_STORE) as f:
            stored = json.load(f)
        tok = _refresh_user_token(stored["refresh_token"])
        if tok:
            return tok
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        pass
    return _oauth_flow()


# ── Feishu doc creation ───────────────────────────────────────────────────────

def _write_table_block(doc_id, table_block, index, token):
    """Create a real Feishu table block (block_type=31) and fill cell content.

    table_block is the sentinel dict produced by _render_table:
      {"block_type": "__table__", "__rows__": [[...], ...], "__cols__": N}

    Returns the number of logical positions consumed (always 1).
    """
    rows_data = table_block["__rows__"]
    num_rows = len(rows_data)
    num_cols = table_block["__cols__"]

    # Step 1: create empty table block
    r = http_post(
        f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
        {"children": [{"block_type": 31, "table": {"property": {"column_size": num_cols, "row_size": num_rows}}}],
         "index": index},
        token
    )
    if r.get("code") != 0:
        print(f"  创建 table block 失败: {r}", file=sys.stderr)
        return 1

    # cell_ids are returned in row-major order (row0col0, row0col1, ..., row1col0, ...)
    cell_ids = r["data"]["children"][0]["table"]["cells"]

    # Step 2: fetch ALL blocks (paginated) to get each cell's inner text block id
    all_items = []
    page_token = None
    while True:
        url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks?page_size=200"
        if page_token:
            url += f"&page_token={page_token}"
        resp = http_get(url, token)
        all_items.extend(resp["data"].get("items", []))
        if not resp["data"].get("has_more"):
            break
        page_token = resp["data"]["page_token"]
    blocks_by_id = {b["block_id"]: b for b in all_items}

    # Step 3: batch_update all cells
    requests = []
    for flat_idx, cell_id in enumerate(cell_ids):
        row_idx = flat_idx // num_cols
        col_idx = flat_idx % num_cols
        if row_idx >= num_rows:
            break
        cell_text = rows_data[row_idx][col_idx] if col_idx < len(rows_data[row_idx]) else ""
        cell_block = blocks_by_id.get(cell_id, {})
        text_block_id = (cell_block.get("children") or [None])[0]
        if not text_block_id:
            continue
        # First row = header: bold
        if row_idx == 0:
            el = {"text_run": {"content": cell_text, "text_element_style": {"bold": True}}}
        else:
            el = {"text_run": {"content": cell_text}}
        requests.append({"block_id": text_block_id, "update_text_elements": {"elements": [el]}})

    if requests:
        batch_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/batch_update"
        # batch_update has a limit; send in chunks of 50
        CHUNK = 50
        for i in range(0, len(requests), CHUNK):
            rb = http_patch(batch_url, {"requests": requests[i:i + CHUNK]}, token)
            if rb.get("code") != 0:
                print(f"  batch_update 写入失败: {rb}", file=sys.stderr)

    return 1


def _build_block_tree(blocks):
    """Convert flat block list to nested [(block, children), ...] tree.

    List blocks with _indent > 1 become children of the nearest preceding
    list block at a lower indent level.  Non-list blocks always go to root
    and reset the list context.
    """
    root = []
    list_stack = []   # [(indent_level, children_list)]

    for block in blocks:
        bt = block.get("block_type")

        if bt not in (12, 13):
            list_stack.clear()
            root.append((block, []))
        else:
            indent = block.pop("_indent", 1)
            children = []

            if not list_stack or indent <= 1:
                list_stack.clear()
                root.append((block, children))
                list_stack.append((indent, children))
            else:
                # Pop deeper levels; find closest ancestor at lower indent
                while list_stack and list_stack[-1][0] >= indent:
                    list_stack.pop()
                parent_list = list_stack[-1][1] if list_stack else root
                parent_list.append((block, children))
                list_stack.append((indent, children))

    return root


def _upload_block_tree(doc_id, parent_id, nodes, token, start_index=0):
    """Upload a (block, children) tree under parent_id. Returns count of root-level blocks created."""
    if not nodes:
        return 0

    BATCH = 50
    written = 0
    pending = []          # (block, children) pairs awaiting batch write
    id_children = []      # (created_block_id, children_list) for recursive upload

    def flush_pending():
        nonlocal written
        for j in range(0, len(pending), BATCH):
            batch = pending[j:j + BATCH]
            r = http_post(
                f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{parent_id}/children",
                {"children": [b for b, _ in batch], "index": start_index + written},
                token
            )
            if r.get("code") != 0:
                print(f"  写入错误 (parent={parent_id}): {r}", file=sys.stderr)
                pending.clear()
                return
            for k, (_, children) in enumerate(batch):
                bid = r["data"]["children"][k]["block_id"]
                id_children.append((bid, children))
            written += len(batch)
        pending.clear()

    for block, children in nodes:
        if block.get("block_type") == "__table__":
            flush_pending()
            _write_table_block(doc_id, block, start_index + written, token)
            written += 1
        else:
            pending.append((block, children))
    flush_pending()

    for bid, children in id_children:
        if children:
            _upload_block_tree(doc_id, bid, children, token, 0)

    return written


def create_doc(title, blocks, token, user_token=None):
    # Create document as the user (so they are the owner/author), fall back to bot
    create_token = user_token or token
    result = http_post(
        "https://open.feishu.cn/open-apis/docx/v1/documents",
        {"title": title, "folder_token": FOLDER_TOKEN},
        create_token
    )
    if result.get("code") != 0:
        raise Exception(f"创建文档失败: {result}")

    doc_id = result["data"]["document"]["document_id"]
    print(f"  文档已创建: {doc_id}，共 {len(blocks)} 个 blocks", file=sys.stderr)

    # Write blocks using bot token (has admin access to all workspace docs)
    tree = _build_block_tree(blocks)
    written = _upload_block_tree(doc_id, doc_id, tree, token)
    print(f"  写入结果: code=0 ({written} root blocks)", file=sys.stderr)

    return doc_id, f"https://feishu.cn/docx/{doc_id}"


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "来自 Apple Notes"

    debug = "--debug" in sys.argv

    if "--clipboard" in sys.argv or sys.stdin.isatty():
        content_type, content = get_clipboard()
        if content_type == "html":
            if debug:
                print(f"[HTML 前 1000 字符]\n{content[:1000]}\n", file=sys.stderr)
            blocks = html_to_blocks(content)
        else:
            if debug:
                print(f"[纯文本]\n{content[:500]}\n", file=sys.stderr)
            blocks = plain_to_blocks(content or "(空剪贴板)")
    else:
        html_content = sys.stdin.read()
        if debug:
            print(f"[HTML 前 1000 字符]\n{html_content[:1000]}\n", file=sys.stderr)
        blocks = html_to_blocks(html_content) or plain_to_blocks("(空笔记)")

    if debug:
        print(f"[生成 blocks]\n{json.dumps(blocks[:10], ensure_ascii=False, indent=2)}\n", file=sys.stderr)

    try:
        token = get_token()
        try:
            user_token = get_user_token()
        except Exception as e:
            print(f"  ⚠️ 用户 token 获取失败，将用机器人身份创建: {e}", file=sys.stderr)
            user_token = None
        doc_id, url = create_doc(title, blocks, token, user_token)
        print(f"✅ 飞书文档已创建：{url}")
        subprocess.run(["open", url])
    except Exception as e:
        print(f"❌ 失败: {e}", file=sys.stderr)
        sys.exit(1)
