# note-to-feishu

把 Word / Apple Notes / 任意剪贴板内容一键转成飞书文档，完整保留格式。

## 功能

- **剪贴板 → 飞书文档**：从 Word 复制内容，一键生成飞书文档
- **Apple Notes → 飞书文档**：通过 Automator 工作流自动转换
- 格式保留：标题层级（H1–H9）、多级 bullet 缩进（4 级）、粗体/斜体/下划线、表格、分割线
- 文档以**你自己的身份**创建（OAuth user token），你拥有完整的分享权限控制

## 系统要求

- macOS（剪贴板访问依赖 osascript）
- Python 3.9+
- 飞书企业版账号 + 自建应用

## 快速开始

### 1. 配置飞书应用

见 [SETUP.md](SETUP.md) 完整指引。

### 2. 安装配置文件

```bash
mkdir -p ~/.config/note_to_feishu
cp config.example.json ~/.config/note_to_feishu/config.json
# 编辑 config.json，填入你的飞书应用 app_id、app_secret、folder_token
```

### 3. 首次授权（OAuth）

运行一次触发浏览器授权，之后自动续期：

```bash
echo "test" | python3 note_to_feishu.py "测试"
```

浏览器会打开飞书授权页面，授权后 token 自动保存到 `~/.config/note_to_feishu/user_token.json`。

### 4. 配置 macOS Spotlight 快捷方式

见 [SETUP.md](SETUP.md) → Automator 部分。

## 使用方法

### 剪贴板模式（推荐）

1. 在 Word 中全选复制（⌘A → ⌘C）
2. 运行：

```bash
python3 note_to_feishu.py "文档标题" --clipboard
```

或通过 Spotlight 调用 `ClipToFeishu` Automator 应用。

### Apple Notes 模式

通过 `NotesToFeishu` Automator 应用，将 Apple Notes 内容通过管道传入：

```bash
echo "<html>...</html>" | python3 note_to_feishu.py "文档标题"
```

## 配置

所有敏感配置存放在 `~/.config/note_to_feishu/config.json`（不在项目目录内，不会提交到 git）。

| 字段 | 说明 |
|------|------|
| `app_id` | 飞书自建应用的 App ID |
| `app_secret` | 飞书自建应用的 App Secret |
| `folder_token` | 文档存放的云空间文件夹 token |

也可通过环境变量覆盖：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_FOLDER_TOKEN`

OAuth token 自动保存在 `~/.config/note_to_feishu/user_token.json`，无需手动管理。

## 项目结构

```
note_to_feishu.py          # 主程序
test_html_convert.py       # 本地测试工具（不上传飞书，只预览转换结果）
config.example.json        # 配置文件模板
SETUP.md                   # 飞书应用配置 + Automator 配置完整指引
developer_agent_experience.md  # 开发经验记录
```

## 本地测试

不上传飞书，仅预览 HTML 转换结果：

```bash
python3 test_html_convert.py input.html
```
