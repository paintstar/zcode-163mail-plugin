---
name: mail-163
description: 操作用户的 163 邮箱（网易邮箱）：查收/列出/搜索/阅读邮件及附件、发送邮件。当用户要求"查收邮件、看有没有新邮件/未读、找某人的邮件、读一下这封邮件、回复/转发/发封邮件、把附件存下来"等涉及邮箱的操作时使用。
---

# 163 邮箱操作

## 工具

脚本位于本技能目录的 `../../scripts/`（即插件根目录的 `scripts/`，以 SKILL 加载时给出的 base directory 为准）：

- `setup.sh` — 写入凭据，纯 bash，零依赖
- `test.sh` — 验证 IMAP/SMTP 连接与授权，bash + openssl（系统自带）
- `mail.py` — 列邮件/搜索/读信/发件，纯 Python 3 标准库，无第三方依赖

下文用 `$SCRIPTS` 代指该目录的绝对路径，`$MAIL` 代指 `$SCRIPTS/mail.py`。

## 凭据

- 存放于 `~/.zcode/mail-plugin/config.json`（权限 600），由用户通过 `bash $SCRIPTS/setup.sh` 写入（交互式，授权码不回显）；也可用环境变量 `MAIL_163_USER` / `MAIL_163_AUTH_CODE` 覆盖。
- 验证连接优先用 `bash $SCRIPTS/test.sh`（同时验证 IMAP 登录与 SMTP 授权，无需 Python）；等价的 `python3 $MAIL test` 只验 IMAP。
- 如果 test 报登录失败，引导用户：登录网页版 https://mail.163.com → 设置 → POP3/SMTP/IMAP → 开启 IMAP/SMTP 服务（需手机短信验证）→ 生成 16 位客户端授权码 → 重新 setup。授权码不是邮箱登录密码。
- 若运行 `$MAIL` 时提示找不到 python3：引导安装（macOS `xcode-select --install` 或 `brew install python3`；Debian/Ubuntu `sudo apt install python3`）。配置与验证不受影响（纯 bash）。

## 命令速查

```bash
# 配置凭据（纯 bash）与验证连接（bash + openssl，含 SMTP 授权检查）
bash $SCRIPTS/setup.sh
bash $SCRIPTS/test.sh

# 验证连接与授权，看未读数（Python 版，只验 IMAP）
python3 $MAIL test

# 列出收件箱最近 20 封（新→旧，首列是 UID）
python3 $MAIL list
python3 $MAIL list --folder INBOX --limit 50

# 搜索（在最近 scan 封里过滤；均为子串匹配）
python3 $MAIL search --sender zhang --subject 报价 --since 2026-09-01
python3 $MAIL search --unread

# 读某封邮件（UID 来自 list/search 输出首列；默认不标记已读）
python3 $MAIL read 123
python3 $MAIL read 123 --save-attachments ~/Downloads/att
python3 $MAIL read 123 --mark-read          # 用户明确要求才用
python3 $MAIL read 123 --raw                # 需要看原始 MIME 时

# 发送（正文用 --body / --body-file / 管道；附件可多个 --attach）
python3 $MAIL send --to a@example.com --subject 标题 --body "正文"
echo "正文" | python3 $MAIL send --to a@example.com --subject 标题
python3 $MAIL send --to a@example.com --subject 标题 --body-file msg.txt --attach ./file.pdf

# 列出所有文件夹（垃圾邮件、已删除等中文名会给出显示名和 --folder 用的原名）
python3 $MAIL folders
```

## 操作规范

- **发送前必须向用户确认**收件人、主题、正文（有附件时一并确认）。用户没有明确要求发邮件时，不要主动发。
- `read` 默认**不**改变已读状态；只在用户明确要求"标为已读"时加 `--mark-read`。
- 不要把授权码、config.json 内容输出到对话或写入任何文件。
- 本插件 v0.1 不提供删除/移动邮件功能；用户要求删除时如实说明，不要用其他方式（如手写 IMAP 命令）代替。
- 列表只显示摘要。要回答"这封说了什么"必须先 `read` 对应 UID，不要凭主题猜内容。
- 中文文件夹：`--folder` 参数用 `folders` 命令输出的 IMAP 名称（引号内原样）。
