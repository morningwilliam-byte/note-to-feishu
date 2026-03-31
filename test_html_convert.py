#!/usr/bin/env python3
"""
本地测试：把 HTML 文件转成飞书 blocks，打印可读预览，不上传飞书。
用法：python3 test_html_convert.py input.html
"""
import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from note_to_feishu import HTMLToBlocks

BLOCK_TYPE_NAME = {
    2: "段落", 3: "H1", 4: "H2", 5: "H3",
    12: "列表●", 13: "列表1.", 22: "分割线",
}

def preview(blocks):
    for i, b in enumerate(blocks):
        bt = b.get("block_type", "?")
        name = BLOCK_TYPE_NAME.get(bt, f"type{bt}")
        if bt == 22:
            print(f"[{i:02d}] {name}: ───────────────")
            continue
        elements = b.get("text", {}).get("elements", [])
        text = "".join(e.get("text_run", {}).get("content", "") for e in elements)
        styles = []
        for e in elements:
            s = e.get("text_run", {}).get("text_element_style", {})
            for k in ("bold", "italic", "underline", "strikethrough"):
                if s.get(k) and k not in styles:
                    styles.append(k)
        style_str = f" [{','.join(styles)}]" if styles else ""
        print(f"[{i:02d}] {name}{style_str}: {text[:120]}")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("用法: python3 test_html_convert.py input.html")
        sys.exit(1)
    with open(path, encoding="utf-8", errors="replace") as f:
        html = f.read()
    parser = HTMLToBlocks()
    parser.feed(html)
    blocks = parser.get_blocks()
    print(f"共 {len(blocks)} 个 blocks\n")
    preview(blocks)
    print(f"\n--- 完整 JSON (前5个) ---")
    print(json.dumps(blocks[:5], ensure_ascii=False, indent=2))
