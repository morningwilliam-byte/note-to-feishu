# 配置指引

## 一、创建飞书自建应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app) → 「创建企业自建应用」
2. 记录 **App ID** 和 **App Secret**

### 必须开通的权限

在「权限管理」中开通以下权限：

| 权限 | 说明 |
|------|------|
| `docx:document` | 创建、编辑飞书文档 |
| `drive:drive` | 访问云空间（读写文件夹） |
| `offline_access` | OAuth refresh token（无需定期重新授权） |

### 安全设置

在「安全设置」→「重定向 URL」中添加：

```
http://localhost:9988/callback
```

### 发布应用

「版本管理与发布」→ 创建版本并发布（企业内部应用无需审核）。

---

## 二、获取 folder_token

1. 打开飞书「云空间」，进入你希望存放文档的文件夹
2. 浏览器地址栏：`https://feishu.cn/drive/folder/XXXXXXX`，`XXXXXXX` 即为 `folder_token`

---

## 三、写入配置文件

```bash
mkdir -p ~/.config/note_to_feishu
cp config.example.json ~/.config/note_to_feishu/config.json
```

编辑 `~/.config/note_to_feishu/config.json`：

```json
{
  "app_id": "cli_你的AppID",
  "app_secret": "你的AppSecret",
  "folder_token": "你的FolderToken"
}
```

---

## 四、OAuth 首次授权

运行一次，浏览器会自动打开飞书授权页面：

```bash
echo "hello" | python3 /path/to/note_to_feishu.py "测试"
```

授权成功后 token 保存到 `~/.config/note_to_feishu/user_token.json`，**之后无需再次授权**，refresh token 自动轮换。

---

## 五、配置 Automator 快捷方式（macOS Spotlight）

### ClipToFeishu（剪贴板 → 飞书）

1. 打开 Automator → 新建「应用程序」
2. 添加「运行 Shell 脚本」，内容：

```bash
#!/bin/bash
TITLE="$(date '+%Y-%m-%d') 剪贴板"
python3 /Users/你的用户名/Projects/note-to-feishu/note_to_feishu.py "$TITLE" --clipboard 2>/tmp/clip_to_feishu.log
```

3. 保存为 `/Applications/ClipToFeishu.app`
4. 之后在 Spotlight 输入 `clip` 即可调用

### NotesToFeishu（Apple Notes → 飞书）

1. 新建「应用程序」
2. 添加「获取所选的备忘录」
3. 添加「运行 Shell 脚本」，Shell 设为 `/bin/zsh`，「传递输入」设为「到 stdin」：

```bash
#!/bin/zsh
TITLE="$(date '+%Y-%m-%d') 来自备忘录"
textutil -convert html -stdout - | python3 /Users/你的用户名/Projects/note-to-feishu/note_to_feishu.py "$TITLE"
```

4. 保存为 `/Applications/NotesToFeishu.app`

---

## 六、文件位置总览

| 文件 | 说明 |
|------|------|
| `~/.config/note_to_feishu/config.json` | 应用密钥（**不要分享**） |
| `~/.config/note_to_feishu/user_token.json` | OAuth token（自动管理） |
| `/Applications/ClipToFeishu.app` | Spotlight 快捷方式 |
| `/Applications/NotesToFeishu.app` | Apple Notes 快捷方式 |
