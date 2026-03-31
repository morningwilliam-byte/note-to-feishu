# Developer Agent Experience Log

---

## 2026-03-31 — Word HTML 多级列表缩进修复

### 任务描述
修复 `note_to_feishu.py` 对从 Word 复制的 HTML 中多级列表的缩进解析，使4级缩进能正确映射到飞书 block 的 `indent_level` 1-4。

### 遇到的问题
Word 粘贴的 HTML 使用 `mso-list` CSS 属性标记列表段落，并用 `margin-left` 或 `text-indent` 的 pt 值表示缩进深度。标准 HTML 解析器只识别 `<ul>/<li>` 结构，无法正确处理 Word 的这种格式。

### 根本原因
Word 生成的 HTML 列表结构：
1. 用 `<p class="MsoListParagraph">` 或 `style` 中含 `mso-list:` 标记列表项（不是 `<li>`）
2. 用 `margin-left` 的 pt 值（如 36pt、72pt、108pt、144pt）表示缩进层级
3. 列表 bullet 字符（•、▪等）作为普通文本内嵌在 `<span style="mso-list:Ignore">` 中

### 修复方法（已在主文件实现）
1. `_margin_to_pt(style_str)` — 从 CSS style 字符串提取 `margin-left` 的 pt 值
2. `_indent_for_margin(pt)` — 将 pt 值映射到 indent_level（每36pt一级）
3. `<p>` 标签处理：检测 `mso-list` in style（不仅仅是 class="MsoListParagraph"）
4. `_flush` 方法：对 block_type=12 的 bullet block，剥离首字符如果是 bullet 字符

### 验证结果
- 首次运行测试脚本即全部通过（3/3项）
- 4个关键段落的 indent_level 全部正确：1/2/3/4
- 无 bullet 字符残留在文本内容中

### 未来类似问题的检查点
1. 从 Word/Office 复制的 HTML，优先检查 `mso-*` CSS 属性，这是 Word 特有的格式标记
2. `margin-left` pt 值是判断缩进层级的关键，通常每36pt一级（Word默认）
3. `<span style="mso-list:Ignore">` 内的内容是要剥除的 bullet 符号
4. 不要仅靠 class 名判断，Word HTML 经常同时使用 class 和内联 style
5. bullet 字符集合：`•·◦▪○–￮◉◌◍●◎`，需要在 _flush 时统一清理

---

## 2026-03-31 — 飞书多级列表缩进、标题检测、文档所有权

### 飞书 bullet 缩进 API 正确用法
- `style.indent_level` 和 `indentation_level` 字段均被飞书 API **静默忽略**，API 返回 code=0 但不生效
- 正确方法：把缩进的 bullet block 作为父 bullet 的**子 block** 上传（parent_id = 父 bullet 的 block_id）
- 嵌套上传流程：先批量创建当前层级 block → 从响应中取 block_id → 递归对有子节点的 block 上传子节点
- 实现：`_build_block_tree(blocks)` 把平铺列表转成 `(block, children)` 树，`_upload_block_tree()` 递归上传

### Word 剪贴板 HTML 标题检测
- Word 剪贴板 HTML 的标题**不用 `MsoHeading*` class**，而是在 `<p>` 的 style 里用 `mso-outline-level:N`
- 检测方式：`re.search(r'mso-outline-level\s*:\s*(\d+)', inline_style, re.I)`
- 映射：`mso-outline-level:1` → H1(block_type=3)，`2` → H2(4)，`3` → H3(5)，以此类推
- textutil 生成的 HTML 用 CSS font-size 推断标题，两种来源的检测逻辑不同，需分支处理

### textutil HTML 的多级列表限制
- textutil（`-convert html`）生成的 HTML，每个 `<li>` 独立包在一个 `<ul>` 里，**不嵌套**，多级列表信息丢失
- 无法从 textutil HTML 恢复列表缩进层级，必须用剪贴板模式（从 Word 复制）才能保留多级结构

### 飞书文档所有权（创建者显示问题）
- bot 用 `tenant_access_token` 创建的文档，创建者永远显示为机器人，**无法通过 API 修改**
- `transfer_owner` API 可以转让所有权（从成员列表角度），但 UI 的"创建者"标签不变
- 根本解法：用 `user_access_token` 创建文档，这样用户就是创建者
- OAuth 实现：首次运行触发浏览器授权 → 保存 refresh_token → 后续自动刷新，无需再次授权
- token 文件：`~/.config/note_to_feishu/user_token.json`
- 开发者后台需配置：重定向 URL `http://localhost:9988/callback` + `offline_access` scope

---
