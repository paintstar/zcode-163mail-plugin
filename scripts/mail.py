#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""163 邮箱命令行工具（ZCode mail-163 插件）。

子命令：
  test     验证连接与授权
  folders  列出所有文件夹
  list     列出文件夹内最近的邮件
  search   按发件人/主题/日期/未读在最近邮件中过滤
  read     读取指定 UID 的邮件正文与附件
  send     发送邮件（可带附件）
  setup    写入账号与客户端授权码配置

凭据读取顺序：环境变量 MAIL_163_USER / MAIL_163_AUTH_CODE > 配置文件
（默认 ~/.zcode/mail-plugin/config.json，可用 --config 指定）。

仅依赖 Python 3 标准库。
"""

import argparse
import base64
import email
import email.header
import email.policy
import html as html_mod
import imaplib
import json
import os
import re
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, parseaddr, parsedate_to_datetime
from getpass import getpass
from pathlib import Path

IMAP_HOST = "imap.163.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.163.com"
SMTP_PORT = 465
DEFAULT_CONFIG = Path.home() / ".zcode" / "mail-plugin" / "config.json"

# 网易要求客户端在登录后（SELECT 之前）发送 ID 命令声明身份，
# 否则后续操作一律报 "Unsafe Login"。字段值无校验，但不可缺失。
IMAP_ID_ARGS = ('("name" "zcode-mail-plugin" "version" "0.1.0" '
                '"vendor" "personal" "support-email" "none@example.com")')


def fail(msg):
    sys.exit(msg)


def load_credentials(args):
    user = os.environ.get("MAIL_163_USER")
    code = os.environ.get("MAIL_163_AUTH_CODE")
    path = Path(args.config).expanduser()
    if not (user and code) and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            fail("配置文件 {} 读取失败：{}".format(path, exc))
        user = user or data.get("user")
        code = code or data.get("auth_code")
    if not (user and code):
        fail("未找到凭据。请先运行 setup 写入配置（{}），或设置环境变量 "
             "MAIL_163_USER / MAIL_163_AUTH_CODE。".format(path))
    return user, code


def imap_connect(user, code):
    imaplib.Commands["ID"] = ("AUTH", "SELECTED")  # imaplib 默认不认识 ID
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    except OSError as exc:
        fail("无法连接 {}:{}：{}".format(IMAP_HOST, IMAP_PORT, exc))
    try:
        conn.login(user, code)
    except imaplib.IMAP4.error as exc:
        fail("登录失败：{}\n请检查：① 网页版邮箱已开启 IMAP/SMTP 服务；"
             "② 填写的是 16 位客户端授权码而非登录密码；③ 授权码是否已被重新生成导致旧码失效。"
             .format(exc))
    typ, _ = conn._simple_command("ID", IMAP_ID_ARGS)  # noqa: SLF001 标准库无公开接口
    if typ != "OK":
        fail("ID 命令被拒绝：{}".format(typ))
    return conn


def select_folder(conn, folder, readonly=True):
    typ, data = conn.select(utf7_encode(folder), readonly)
    if typ != "OK":
        fail("无法打开文件夹 {!r}。先用 folders 子命令查看可用文件夹。"
             .format(folder))
    return int(data[0])


# ---------- IMAP modified UTF-7（RFC 3501 §5.1.3，文件夹中文名需要） ----------

def utf7_decode(name):
    out, i = [], 0
    while i < len(name):
        ch = name[i]
        if ch != "&":
            out.append(ch)
            i += 1
            continue
        end = name.find("-", i + 1)
        if end < 0:
            out.append(ch)
            break
        b64 = name[i + 1:end].replace(",", "/")
        if not b64:
            out.append("&")
        else:
            b64 += "=" * (-len(b64) % 4)
            out.append(base64.b64decode(b64).decode("utf-16-be"))
        i = end + 1
    return "".join(out)


def utf7_encode(name):
    out = []
    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E and ch != "&":
            out.append(ch)
        elif ch == "&":
            out.append("&-")
        else:
            b64 = base64.b64encode(ch.encode("utf-16-be")).decode("ascii")
            out.append("&" + b64.rstrip("=").replace("/", ",") + "-")
    return "".join(out)


# ---------- 邮件解析 ----------

def norm_date(value):
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return value


def short_from(value):
    if not value:
        return ""
    return parseaddr(str(value))[1] or str(value)


def parse_flags(fetch_data):
    for item in fetch_data:
        if isinstance(item, tuple) and b"FLAGS" in item[0]:
            m = re.search(rb"FLAGS \(([^)]*)\)", item[0])
            if m:
                return m.group(1).decode("ascii", "replace")
    return ""


def iter_parts(msg):
    """产出 (part, is_attachment)。兼容 multipart 与单段消息。"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            cd = str(part.get("Content-Disposition") or "")
            yield part, "attachment" in cd
    else:
        yield msg, "attachment" in str(msg.get("Content-Disposition") or "")


def part_text(part):
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    for enc in (charset, "utf-8", "gbk"):
        try:
            return payload.decode(enc, "strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", "replace")


def html_to_text(html):
    html = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", "", html)
    return html_mod.unescape(text).strip()


def extract_body(msg):
    """返回 (正文文本, 说明)。优先 text/plain，仅 HTML 时做尽力转换。"""
    plain, html_body = None, None
    for part, is_att in iter_parts(msg):
        if is_att:
            continue
        maintype, subtype = part.get_content_type().split("/", 1)
        if maintype != "text":
            continue
        try:
            text = part_text(part)
        except Exception as exc:  # 畸形编码也要能继续
            text = "(该段正文解码失败: {})".format(exc)
        if subtype == "plain" and plain is None:
            plain = text
        elif subtype == "html" and html_body is None:
            html_body = text
    if plain and plain.strip():
        return plain.strip(), ""
    if html_body:
        return html_to_text(html_body), "(原邮件为 HTML，以下为转换后的纯文本；--raw 查看原文)\n"
    return "(无文本正文)", ""


def list_attachments(msg):
    out = []
    for part, is_att in iter_parts(msg):
        if not is_att:
            continue
        fname = part.get_filename() or "(未命名)"
        size = len(part.get_payload(decode=True) or b"")
        out.append((fname, size, part))
    return out


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "{:.0f}{}".format(n, unit) if unit == "B" else "{:.1f}{}".format(n, unit)
        n /= 1024.0


# ---------- 子命令 ----------

def cmd_setup(args):
    user = (args.user or input("163 邮箱地址: ")).strip()
    code = (args.code or getpass("16 位客户端授权码（输入不回显）: ")).strip()
    if "@" not in user or not code:
        fail("邮箱地址或授权码为空/格式不对，未写入任何文件。")
    path = Path(args.config).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"user": user, "auth_code": code}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    path.chmod(0o600)
    print("已写入 {}（权限 600）。运行 `mail.py test` 验证。".format(path))


def cmd_test(args):
    user, code = load_credentials(args)
    conn = imap_connect(user, code)
    try:
        total = select_folder(conn, "INBOX")
        typ, data = conn.search(None, "UNSEEN")
        unread = len(data[0].split())
        print("连接成功：{}".format(user))
        print("INBOX 共 {} 封，未读 {} 封。收发均可用（SMTP 在发送时验证）。".format(total, unread))
    finally:
        try:
            conn.logout()
        except imaplib.IMAP4.error:
            pass


def cmd_folders(args):
    user, code = load_credentials(args)
    conn = imap_connect(user, code)
    try:
        typ, data = conn.list()
        print("{:<24} {}".format("显示名", "IMAP 名称（--folder 参数用引号原样传入）"))
        for line in data:
            if not line:
                continue
            text = line.decode("latin-1")
            m = re.match(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"[^"]*"|NIL)\s+(?P<name>.+)$', text)
            if not m:
                print(text)
                continue
            raw = m.group("name").strip('"')
            shown = utf7_decode(raw)
            label = shown if shown != raw else ""
            print("{:<24} {}".format(label or raw, raw))
    finally:
        try:
            conn.logout()
        except imaplib.IMAP4.error:
            pass


def fetch_summaries(conn, limit, folder):
    select_folder(conn, folder)
    typ, data = conn.uid("search", None, "ALL")
    if typ != "OK":
        fail("搜索失败：{}".format(data))
    uids = data[0].split()
    return uids, uids[-limit:][::-1]


def print_summary(uid, header_bytes, flags):
    msg = email.message_from_bytes(header_bytes, policy=email.policy.default)
    unread = "" if "\\Seen" in flags else " [未读]"
    att_hint = ""
    print("{} | {} | {} | {}{}".format(
        uid.decode(),
        norm_date(msg["Date"]),
        short_from(msg["From"]),
        (str(msg["Subject"]) or "(无主题)").replace("\n", " "),
        unread,
    ) + att_hint)


def scan_headers(conn, uids):
    """逐封取头部，返回 [(uid, header_bytes, flags)]，保持传入顺序。"""
    out = []
    for uid in uids:
        typ, data = conn.uid(
            "fetch", uid,
            "(FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
        if typ != "OK" or not data or data[0] is None:
            continue
        header_bytes = data[0][1] if isinstance(data[0], tuple) else b""
        out.append((uid, header_bytes, parse_flags(data)))
    return out


def cmd_list(args):
    user, code = load_credentials(args)
    conn = imap_connect(user, code)
    try:
        uids, picks = fetch_summaries(conn, args.limit, args.folder)
        print("文件夹 {} 共 {} 封，显示最近 {} 封（新→旧）：".format(args.folder, len(uids), len(picks)))
        for uid, header_bytes, flags in scan_headers(conn, picks):
            print_summary(uid, header_bytes, flags)
    finally:
        try:
            conn.logout()
        except imaplib.IMAP4.error:
            pass


def cmd_search(args):
    user, code = load_credentials(args)
    conn = imap_connect(user, code)
    try:
        uids, picks = fetch_summaries(conn, args.scan, args.folder)
        since = None
        if args.since:
            try:
                from datetime import date as _date
                since = _date.fromisoformat(args.since)
            except ValueError:
                fail("--since 需要 YYYY-MM-DD 格式")
        hits = 0
        for uid, header_bytes, flags in scan_headers(conn, picks):
            msg = email.message_from_bytes(header_bytes, policy=email.policy.default)
            subject = str(msg["Subject"] or "")
            sender = str(msg["From"] or "")
            if args.subject and args.subject.lower() not in subject.lower():
                continue
            if args.sender and args.sender.lower() not in sender.lower():
                continue
            if args.unread and "\\Seen" in flags:
                continue
            if since is not None:
                try:
                    if parsedate_to_datetime(msg["Date"]).date() < since:
                        continue
                except (TypeError, ValueError):
                    continue
            hits += 1
            print_summary(uid, header_bytes, flags)
        print("— 在最近 {} 封中命中 {} 封。".format(len(picks), hits))
    finally:
        try:
            conn.logout()
        except imaplib.IMAP4.error:
            pass


def cmd_read(args):
    user, code = load_credentials(args)
    conn = imap_connect(user, code)
    try:
        select_folder(conn, args.folder, readonly=False)  # 可能需要标记已读
        typ, data = conn.uid("fetch", args.uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            fail("读取 UID {} 失败，先用 list/search 确认该 UID 存在于 {}。"
                 .format(args.uid, args.folder))
        raw = data[0][1]
        if args.mark_read:
            conn.uid("store", args.uid, "+FLAGS", "(\\Seen)")
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        print("主题: {}".format(msg["Subject"]))
        print("发件人: {}".format(msg["From"]))
        print("收件人: {}".format(msg["To"]))
        if msg["Cc"]:
            print("抄送: {}".format(msg["Cc"]))
        print("日期: {}".format(msg["Date"]))
        atts = list_attachments(msg)
        if atts:
            print("附件 {} 个: {}".format(
                len(atts), ", ".join("{}({})".format(n, human_size(s)) for n, s, _ in atts)))
            if args.save_attachments:
                dest = Path(args.save_attachments).expanduser()
                dest.mkdir(parents=True, exist_ok=True)
                for name, _, part in atts:
                    payload = part.get_payload(decode=True) or b""
                    safe = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name)
                    (dest / safe).write_bytes(payload)
                print("附件已保存到 {}".format(dest.resolve()))
        else:
            print("附件: 无")
        print("-" * 60)
        if args.raw:
            print(raw.decode("utf-8", "replace"))
        else:
            note, body = extract_body(msg)
            if note:
                print(note)
            print(body)
    finally:
        try:
            conn.logout()
        except imaplib.IMAP4.error:
            pass


def build_message(user, to_list, cc_list, subject, body, attachments):
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = email.header.Header(subject, "utf-8").encode()
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for att in attachments or []:
        path = Path(att).expanduser()
        if not path.is_file():
            fail("附件不存在：{}".format(path))
        part = MIMEApplication(path.read_bytes())
        part.add_header("Content-Disposition", "attachment", filename=path.name)
        msg.attach(part)
    return msg


def cmd_send(args):
    user, code = load_credentials(args)
    to_list = [a.strip() for a in re.split(r"[,;，；]", args.to) if a.strip()]
    cc_list = [a.strip() for a in re.split(r"[,;，；]", args.cc)] if args.cc else []
    for addr in to_list + cc_list:
        if "@" not in addr:
            fail("收件人地址不合法：{}".format(addr))
    body = args.body
    if args.body_file:
        body = Path(args.body_file).expanduser().read_text(encoding="utf-8")
    if body is None and not sys.stdin.isatty():
        body = sys.stdin.read()
    if not body:
        fail("缺少正文：用 --body、--body-file 或管道传入。")
    msg = build_message(user, to_list, cc_list, args.subject, body, args.attach)
    smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
    try:
        smtp.login(user, code)
        smtp.sendmail(user, to_list + cc_list, msg.as_string().encode("utf-8"))
    finally:
        smtp.quit()
    print("已发送：{} → {}{}".format(
        user, ", ".join(to_list), "（抄送 {}）".format(", ".join(cc_list)) if cc_list else ""))


# ---------- 入口 ----------

def main():
    parser = argparse.ArgumentParser(
        prog="mail.py", description="163 邮箱命令行工具（IMAP/SMTP + 客户端授权码）")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="配置文件路径（默认 ~/.zcode/mail-plugin/config.json）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="写入账号与授权码配置")
    p.add_argument("--user", help="163 邮箱地址")
    p.add_argument("--code", help="16 位客户端授权码（不传则交互式输入）")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("test", help="验证连接与授权")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("folders", help="列出所有文件夹")
    p.set_defaults(func=cmd_folders)

    p = sub.add_parser("list", help="列出最近邮件")
    p.add_argument("--folder", default="INBOX", help="文件夹名（默认 INBOX）")
    p.add_argument("--limit", type=int, default=20, help="显示条数（默认 20）")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="按发件人/主题/日期/未读过滤最近邮件")
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--sender", help="按发件人过滤（不区分大小写的子串）")
    p.add_argument("--subject", help="按主题过滤（不区分大小写的子串）")
    p.add_argument("--since", help="只看此日期之后，YYYY-MM-DD")
    p.add_argument("--unread", action="store_true", help="只看未读")
    p.add_argument("--scan", type=int, default=100, help="向后扫描的封数（默认 100）")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("read", help="读取指定 UID 的邮件")
    p.add_argument("uid", help="邮件 UID（来自 list/search 输出首列）")
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--raw", action="store_true", help="输出原始 MIME 报文")
    p.add_argument("--mark-read", action="store_true", help="顺带标记为已读")
    p.add_argument("--save-attachments", metavar="DIR", help="保存附件到目录")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("send", help="发送邮件")
    p.add_argument("--to", required=True, help="收件人，逗号分隔可多个")
    p.add_argument("--cc", help="抄送")
    p.add_argument("--subject", required=True, help="主题")
    p.add_argument("--body", help="正文文本")
    p.add_argument("--body-file", help="从文件读正文")
    p.add_argument("--attach", action="append", help="附件路径，可重复")
    p.set_defaults(func=cmd_send)

    args = parser.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    args.func(args)


if __name__ == "__main__":
    main()
