#!/usr/bin/env bash
# 写入 163 邮箱凭据（纯 bash，无任何依赖）。
# 用法：bash setup.sh [--user 邮箱] [--code 授权码] [--config 路径]
# 缺省交互式输入；授权码输入不回显。凭据写入 ~/.zcode/mail-plugin/config.json（600）。
set -euo pipefail

CONFIG="${MAIL_163_CONFIG:-$HOME/.zcode/mail-plugin/config.json}"
user="${MAIL_163_USER:-}"
code="${MAIL_163_AUTH_CODE:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)   user="$2"; shift 2 ;;
    --code)   code="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$1（--user/--code/--config）" >&2; exit 1 ;;
  esac
done

if [[ -z "$user" ]]; then
  read -rp "163 邮箱地址: " user || { echo "输入为空，未写入。"; exit 1; }
fi
if [[ -z "$code" ]]; then
  read -rsp "16 位客户端授权码（输入不回显）: " code || { echo; echo "输入为空，未写入。"; exit 1; }
  echo
fi

user="${user//[[:space:]]/}"
code="${code//[[:space:]]/}"
[[ "$user" == *@* ]] || { echo "邮箱地址格式不对：${user}，未写入任何文件。" >&2; exit 1; }
[[ "$code" != *'"'* && "$code" != *'\'* ]] || { echo "授权码含有非法字符，未写入任何文件。" >&2; exit 1; }
[[ ${#code} -eq 16 ]] || echo "提示：163 授权码通常是 16 位，你输入的是 ${#code} 位，请确认。"

mkdir -p "$(dirname "$CONFIG")"
umask 177
printf '{\n  "user": "%s",\n  "auth_code": "%s"\n}\n' "$user" "$code" > "$CONFIG"
chmod 600 "$CONFIG"
echo "已写入 ${CONFIG}（权限 600）。运行 bash test.sh 验证连接。"
