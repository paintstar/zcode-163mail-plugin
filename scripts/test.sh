#!/usr/bin/env bash
# 验证 163 邮箱连接与授权（bash + openssl，无需 Python）。
# 同时验证 IMAP（登录 + ID 命令 + INBOX 状态）与 SMTP（AUTH LOGIN 授权）。
set -uo pipefail

CONFIG="${MAIL_163_CONFIG:-$HOME/.zcode/mail-plugin/config.json}"
IMAP_HOST=imap.163.com IMAP_PORT=993
SMTP_HOST=smtp.163.com SMTP_PORT=465

user="${MAIL_163_USER:-}"
code="${MAIL_163_AUTH_CODE:-}"
if { [[ -z "$user" ]] || [[ -z "$code" ]]; } && [[ -f "$CONFIG" ]]; then
  [[ -z "$user" ]] && user=$(sed -n 's/.*"user"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$CONFIG" | head -1)
  [[ -z "$code" ]] && code=$(sed -n 's/.*"auth_code"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$CONFIG" | head -1)
fi
if [[ -z "$user" || -z "$code" ]]; then
  echo "未找到凭据。先运行 bash setup.sh 写入 ${CONFIG}，或设置环境变量 MAIL_163_USER / MAIL_163_AUTH_CODE。" >&2
  exit 1
fi

command -v openssl >/dev/null 2>&1 || { echo "需要 openssl（macOS/Linux 系统一般自带）。" >&2; exit 1; }

# ---- IMAP：登录 → 网易要求的 ID 命令 → INBOX 状态 → 退出 ----
imap_out=$(printf 'a1 LOGIN "%s" "%s"\na2 ID ("name" "zcode-mail-plugin" "version" "0.1" "vendor" "personal")\na3 STATUS INBOX (MESSAGES UNSEEN)\na4 LOGOUT\n' \
  "$user" "$code" \
  | openssl s_client -crlf -quiet -connect "$IMAP_HOST:$IMAP_PORT" 2>/dev/null) || true

if [[ -z "$imap_out" ]]; then
  echo "无法连接 $IMAP_HOST:${IMAP_PORT}，请检查网络。" >&2
  exit 1
fi
if grep -q '^a1 NO' <<<"$imap_out"; then
  echo "IMAP 登录失败：$(grep '^a1 NO' <<<"$imap_out" | head -1)"
  echo "请检查：① 网页版已开启 IMAP/SMTP 服务；② 填写的是 16 位客户端授权码而非登录密码；③ 授权码是否已重新生成导致旧码失效。"
  exit 1
fi
if ! grep -q '^a1 OK' <<<"$imap_out"; then
  echo "IMAP 会话异常结束，请稍后重试。" >&2
  exit 1
fi
status=$(grep 'STATUS' <<<"$imap_out" | head -1)
msgs=$(sed -n 's/.*MESSAGES \([0-9][0-9]*\).*/\1/p' <<<"$status")
unseen=$(sed -n 's/.*UNSEEN \([0-9][0-9]*\).*/\1/p' <<<"$status")
echo "IMAP 连接成功：${user}（INBOX 共 ${msgs:-?} 封，未读 ${unseen:-?} 封）"

# ---- SMTP：AUTH LOGIN 授权验证（不发信） ----
smtp_out=$(printf 'EHLO zcode-mail-plugin\nAUTH LOGIN\n%s\n%s\nQUIT\n' \
  "$(printf '%s' "$user" | base64)" \
  "$(printf '%s' "$code" | base64)" \
  | openssl s_client -crlf -quiet -connect "$SMTP_HOST:$SMTP_PORT" 2>/dev/null) || true

if [[ -z "$smtp_out" ]]; then
  echo "警告：无法连接 SMTP $SMTP_HOST:${SMTP_PORT}，发信功能暂不可用（收件不受影响）。"
  exit 1
fi
if grep -q '^235' <<<"$smtp_out"; then
  echo "SMTP 授权成功：可以发送邮件。"
else
  echo "警告：SMTP 授权失败（$(grep -E '^(5[0-9][0-9])' <<<"$smtp_out" | head -1)），收件可用但发信不可用。"
  exit 1
fi
echo "全部通过 ✅"
