# zcode-163mail-plugin

一个 ZCode 插件：让 AI 助手直接帮你**查收、搜索、阅读 163 邮箱邮件**，并在**你确认后发送邮件**。

基于 IMAP/SMTP + 网易「客户端授权码」接入，纯 Python 3 标准库，**零第三方依赖**。

## 功能特性

- 📥 **查收邮件**：列收件箱、看未读、按发件人/主题/日期/未读搜索
- 📖 **阅读邮件**：正文提取（纯文本与 HTML 自动处理）、附件保存到本地
- 📤 **发送邮件**：多收件人、抄送、附件（支持中文文件名）
- 🛡️ **安全设计**：读信默认不标已读；发信前助手必须向你确认；授权码只存本机（权限 600）
- 🧩 **即装即用**：装成 ZCode 插件后，用自然语言即可操作邮箱

## 快速开始

环境要求：ZCode 客户端 + 一个 163 邮箱。**安装、配置、验证只用到系统自带的 bash，零额外依赖**；收信/发信等完整功能运行在 python3 上（零第三方包——macOS 首次使用会自动引导安装命令行工具，Linux 发行版一般自带）。

只需两步：

### 1️⃣ 在插件市场添加本仓库

ZCode 插件市场 → **新建** → 填入本仓库地址：

```
https://github.com/paintstar/zcode-163mail-plugin.git
```

在列表中安装 **mail-163**。

### 2️⃣ 对 ZCode 说「帮我配置 163 邮箱」

开一个新会话，对 ZCode 说「帮我配置 163 邮箱」

按照提示完成：

1. 浏览器登录 [mail.163.com](https://mail.163.com)
2. 设置 → POP3/SMTP/IMAP → 开启「**IMAP/SMTP 服务**」（需手机短信验证）
3. 生成 **16 位客户端授权码**并记下来（只显示一次）

配置完成后，对 ZCode 说句「**看下我 163 有没有未读邮件**」——能列出来就说明一切就绪 🎉

之后就可以用自然语言操作邮箱了，比如：

> 「找一下米哈游发来的邮件」
> 「读一下最新那封，有附件就存到 ~/Downloads」
> 「给 a@example.com 发封邮件，说明天下午三点开会」（发送前助手会先给你确认）

## 手动配置（可选）

不想走对话引导，也可以全手动：

```bash
git clone https://github.com/paintstar/zcode-163mail-plugin.git
cd zcode-163mail-plugin
bash scripts/setup.sh    # 写入邮箱地址与授权码（纯 bash，授权码不回显）
bash scripts/test.sh     # 验证 IMAP/SMTP 连接（bash + openssl，无需 Python）
```

> 偏好 Python 或在 Windows 上：`python3 scripts/mail.py setup` 与 `python3 scripts/mail.py test` 效果相同。

凭据保存在 `~/.zcode/mail-plugin/config.json`（自动 chmod 600，已被 .gitignore 排除）；也可以不改文件，直接用环境变量：

```bash
export MAIL_163_USER=you@163.com
export MAIL_163_AUTH_CODE=你的16位授权码
```

**其他安装方式**：

- **本地目录安装**：克隆本仓库后，插件市场 → 新建 → 选择克隆出的目录 → 安装。适合想改代码再装的情况。
- **只装技能试用**：把 `skills/mail` 复制到 `~/.zcode/skills/mail-163`，并把 SKILL.md 中的 `../../scripts/mail.py` 改成脚本绝对路径。

> 注意：市场安装的是缓存副本，仓库更新后需要在插件管理里更新/重装才会生效。安装后插件标识为 `mail-163@zcode-163mail-plugin`。

## 命令行用法

配置与验证（纯 bash，无需 Python）：

```bash
bash scripts/setup.sh
bash scripts/test.sh
```

收信/搜索/读信/发件（需要 python3）：

```bash
python3 scripts/mail.py test                          # 验证连接与授权
python3 scripts/mail.py folders                       # 列出所有文件夹
python3 scripts/mail.py list --limit 20               # 列出最近 20 封
python3 scripts/mail.py search --unread               # 只看未读
python3 scripts/mail.py search --sender zhang --subject 报价 --since 2026-09-01
python3 scripts/mail.py read 1718421959               # 读指定 UID（默认不标已读）
python3 scripts/mail.py read 1718421959 --save-attachments ~/Downloads/att
python3 scripts/mail.py send --to a@example.com --subject 标题 --body "正文"
python3 scripts/mail.py send --to a@example.com --cc b@example.com \
    --subject 标题 --body-file msg.txt --attach ./报价单.pdf
```

`list` / `search` 输出的首列是邮件 UID，`read` 用它定位邮件。

## 配置

配置文件 `~/.zcode/mail-plugin/config.json`（`setup` 自动生成）：

```json
{
  "user": "you@163.com",
  "auth_code": "你的16位客户端授权码"
}
```

| 方式 | 优先级 | 适用场景 |
|---|---|---|
| 环境变量 `MAIL_163_USER` / `MAIL_163_AUTH_CODE` | 最高 | 临时切换账号、CI |
| 配置文件 | 其次 | 日常使用 |
| `--config /path/to/other.json` | 指定文件 | 多账号并存 |

## 常见问题

**登录失败？**
① 检查填的是 16 位授权码而非邮箱登录密码；② 确认网页版已开启 IMAP/SMTP 服务；③ 授权码重新生成后旧码立即作废。

**提示找不到 python3？**
macOS 终端输入 `python3` 会引导安装命令行工具（或 `brew install python3`）；Debian/Ubuntu 用 `sudo apt install python3`。配置与验证步骤不受影响（纯 bash）。

**会报 `Unsafe Login` 吗？**
网易要求客户端登录后、SELECT 之前发送 IMAP `ID` 命令声明身份，本插件已内置处理。如果你要改造脚本，请保留 `IMAP_ID_ARGS`。

**连接被频繁拒绝？**
网易对 IMAP 有连接频控。插件设计为短连接、用完即断；请勿在外层写高频轮询。

**读信时显示「收件人： None」？**
该邮件本身没有 To 头（密送群发常见），不是 bug。

## 隐私与安全

- 授权码仅保存在本机，不随仓库分发，`config.json` 已列入 `.gitignore`
- `read` 默认**不改变**已读状态，需要时显式加 `--mark-read`
- v0.1 刻意不提供删除/移动邮件功能，防止 AI 误操作；发送邮件需人工确认
- 本插件的所有网络通信只发生在你本机与 `imap.163.com` / `smtp.163.com` 之间

## Roadmap

- [ ] Outlook / Microsoft 365 支持（OAuth2 XOAUTH2，复用现有协议层）
- [ ] 删除/移动/标记（带二次确认机制）
- [ ] MCP server 形态
- [ ] 多账号管理

## License

[MIT](LICENSE)
