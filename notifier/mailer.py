"""Email sender — sends task completion notifications."""

import glob
import os
import smtplib
import ssl
import urllib.parse
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from notifier.config import Config

_MAX_BODY_LINES = 200
_PREVIEW_LINES = 100


def send_notification(
    config: Config,
    task_name: str,
    exit_code: int,
    elapsed: float,
    command_text: str = "",
    start_time: str = "",
    end_time: str = "",
    log_file_path: Optional[str] = None,
    to_address: Optional[str] = None,
    extra_attachments: Optional[list[str]] = None,
    resource_info: Optional[dict[str, Any]] = None,
) -> None:
    """Send a task completion notification email.

    Log content is inlined into the email body (not attached).
    Additional files from ``extra_attachments`` are attached individually;
    missing files are noted in the body without blocking the send.
    """
    from_addr = config.defaults.from_address
    to_addr = to_address or config.defaults.to_address
    if not to_addr:
        raise ValueError("No recipient address provided")

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = (
        f"[Task Notifier] {task_name} — "
        f"{'Completed' if exit_code == 0 else 'Failed'}"
    )

    server = config.server_name
    elapsed_fmt = _format_duration(elapsed)
    start_fmt = _format_beijing_time(start_time)
    end_fmt = _format_beijing_time(end_time)

    # --- Resource info ---
    res_html = ""
    if resource_info:
        mem = resource_info.get("peak_memory_mb")
        cpu = resource_info.get("cpu_percent_avg")
        parts = []
        if mem is not None:
            parts.append(f"峰值内存 {mem} MB")
        if cpu is not None:
            parts.append(f"平均CPU {cpu}%")
        if parts:
            res_html = (
                '<p style="font-size:14px;color:#555;line-height:1.7;">'
                f"{'，'.join(parts)}</p>"
            )

    # --- Log path hint ---
    log_path_html = ""
    if log_file_path:
        log_path_html = (
            '<p style="font-size:14px;line-height:1.7;">'
            f'您可在 <code style="background:#eee;padding:2px 6px;border-radius:3px;">'
            f"{_html_escape(log_file_path)}</code> 下查看日志具体内容。</p>"
        )

    # --- Missing attachment warnings ---
    missing_warnings: list[str] = []
    attach_paths: list[str] = []

    if extra_attachments:
        for item in extra_attachments:
            # Try relative to CWD first, then as-is
            candidates = [item, os.path.abspath(item)]
            found: Optional[str] = None
            for c in candidates:
                if os.path.exists(c):
                    found = c
                    break
            if found and os.path.isfile(found):
                attach_paths.append(found)
            else:
                missing_warnings.append(item)

    missing_html = ""
    if missing_warnings:
        items_html = "<br>".join(
            f"  · {_html_escape(p)}" for p in missing_warnings
        )
        missing_html = (
            '<p style="font-size:14px;color:#b94a48;line-height:1.7;">'
            f"以下附件文件缺失：<br>{items_html}</p>"
        )

    # --- Inline log content (replaces log attachment) ---
    log_content_html = ""
    if config.log_summary.enabled and log_file_path:
        content = _extract_preview(log_file_path)
        if content is not None:
            lines = _escape_text(content)
            log_content_html = f"""
    <pre style="background:#1e1e1e;color:#d4d4d4;padding:14px;border-radius:6px;
font-size:13px;max-width:620px;white-space:pre-wrap;line-height:1.5;overflow-x:auto;">{lines}</pre>
"""

    # --- Assemble body (log content last) ---
    body_html = f"""\
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <p style="font-size: 15px; line-height: 1.7;">
        主人，来自 <strong>{_html_escape(server)}</strong> 的
        <strong>{_html_escape(task_name)}</strong> 任务已经完成，
        具体指令为：<br>
        <code style="background:#eee;padding:2px 6px;border-radius:3px;">{_html_escape(command_text)}</code>
    </p>
    <p style="font-size: 15px; line-height: 1.7;">
        这项任务开始于 {start_fmt}，
        完成于 {end_fmt}，
        共耗时 {elapsed_fmt}。
    </p>
    {res_html}
    {log_path_html}
    {missing_html}
    {log_content_html}
    <hr style="margin-top: 20px;">
    <p style="color: #888; font-size: 12px;">Sent by Task Notifier</p>
</body>
</html>"""

    msg.attach(MIMEText(body_html, "html", "utf-8"))

    # --- Attach only extra files (log is inlined, not attached) ---
    seen = set()
    for path in attach_paths:
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        with open(path, "rb") as f:
            attachment = MIMEBase("application", "octet-stream")
            attachment.set_payload(f.read())
            encoders.encode_base64(attachment)
            filename = os.path.basename(path)
            encoded = urllib.parse.quote(filename, safe="")
            attachment.add_header(
                "Content-Disposition",
                f"attachment; filename*=UTF-8''{encoded}",
            )
            msg.attach(attachment)

    # --- Send ---
    context = ssl.create_default_context()
    smtp = smtplib.SMTP(config.smtp.host, config.smtp.port)
    smtp.ehlo()
    if config.smtp.use_tls:
        smtp.starttls(context=context)
        smtp.ehlo()
    smtp.login(config.smtp.user, config.smtp.password)
    smtp.sendmail(from_addr, to_addr, msg.as_string())
    smtp.quit()


# ---------------------------------------------------------------------------
# Log preview  —  inlined in body, truncated if > 200 lines
# ---------------------------------------------------------------------------

def _extract_preview(log_file_path: str) -> Optional[str]:
    """Return log body (strip === headers), truncated at ``_MAX_BODY_LINES``."""
    if not log_file_path or not os.path.exists(log_file_path):
        return None
    try:
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.readlines()
    except Exception:
        return None

    # Keep only actual output lines (strip metadata headers)
    body = [l.rstrip("\n") for l in raw if not l.startswith("===")]
    count = len(body)

    if count <= _MAX_BODY_LINES:
        return "\n".join(body)

    head = body[:_PREVIEW_LINES]
    tail = body[-_PREVIEW_LINES:]
    skipped = count - _PREVIEW_LINES * 2
    return "\n".join(head + [f"\n... (skipped {skipped} lines) ...\n"] + tail)


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

def _format_beijing_time(iso_str: str) -> str:
    """ISO-8601 → '2026-07-04 18:19:15 (北京时间)'."""
    if not iso_str:
        return iso_str
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S (北京时间)")
    except (ValueError, TypeError):
        return iso_str


def _format_duration(seconds: float) -> str:
    """Format seconds to human-readable Chinese duration.

    Examples:
        45      → "45秒"
        125     → "2分5秒"
        3661    → "1小时1分1秒"
        90061   → "1天1小时1分1秒"
    """
    total = int(seconds)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分")
    if secs > 0 or not parts:
        parts.append(f"{secs}秒")
    return "".join(parts)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _escape_text(text: str) -> str:
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return escaped.replace("\n", "<br>")


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
