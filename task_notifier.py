#!/usr/bin/env python3
"""Task Notifier — execute a command and send an email notification on completion.

Usage:
    python task_notifier.py --order "python main.py" --task-name "Data Pipeline" --to "me@example.com"
    python task_notifier.py --script train.sh --to "me@example.com"

    # Daemon mode — runs in background, immune to Ctrl+C / terminal close:
    python task_notifier.py --daemon --order "python main.py" -n "Big Job"
"""

import argparse
import os
import sys

from notifier.config import load_config, validate_config
from notifier.mailer import send_notification
from notifier.runner import run_command, set_daemonized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute a command and send an email notification when done.",
    )

    exec_group = parser.add_argument_group("Execution (choose one)").add_mutually_exclusive_group()
    exec_group.add_argument(
        "-o", "--order",
        default=None,
        help="Shell command to execute (e.g. \"python main.py\"). "
             "Mutually exclusive with --script.",
    )
    exec_group.add_argument(
        "-s", "--script",
        default=None,
        help="Path to a bash script file to execute. "
             "Mutually exclusive with --order.",
    )

    parser.add_argument(
        "-n", "--task-name",
        default=None,
        help="Name of the task (used in email subject and log filename).",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="Recipient email address (overrides config default).",
    )
    parser.add_argument(
        "--attach",
        dest="attach_files",
        action="append",
        default=None,
        help="Extra files to attach (supports glob patterns, "
             "e.g. \"output/*.csv\"). Can be specified multiple times.",
    )
    parser.add_argument(
        "-d", "--daemon",
        action="store_true",
        help="Daemonize — fork to background, detach from terminal. "
             "The process will survive Ctrl+C, terminal close, "
             "and SSH disconnect. Check logs/ for output.",
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to the YAML configuration file (default: config.yaml).",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    # 1. Load config
    try:
        cfg = load_config(args.config)
        validate_config(cfg)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Daemonize early if requested (POSIX only)
    if args.daemon:
        if os.name != "posix":
            print("[ERROR] --daemon is only supported on Linux/macOS.", file=sys.stderr)
            sys.exit(1)

        pid = os.fork()
        if pid > 0:
            # Parent exits immediately — shell prompt returns
            print(f"[Task Notifier] Daemon started (PID {pid}). "
                  f"Task will run in background. Check logs/ for output.")
            sys.exit(0)

        # Child: new session, detach from terminal
        os.setsid()
        pid2 = os.fork()
        if pid2 > 0:
            sys.exit(0)

        # Redirect stdio to /dev/null
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)

        set_daemonized()

    # 3. Determine task name
    task_name = args.task_name or cfg.defaults.task_name

    # 4. Determine command / script
    script_path = args.script or cfg.script
    command_str = args.order or ""

    if script_path:
        if not os.path.isfile(script_path):
            msg = f"Script file not found: {script_path}"
            if args.daemon:
                _die_silent(msg)
            print(f"[ERROR] {msg}", file=sys.stderr)
            sys.exit(1)
        final_command = script_path
        # Read script content for the email body
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                command_text = f.read().strip()
        except Exception:
            command_text = script_path
    elif command_str:
        final_command = command_str
        command_text = command_str
    else:
        msg = ("No command or script specified. "
               "Use --order or --script, or set 'script' in config.yaml.")
        if args.daemon:
            _die_silent(msg)
        print(f"[ERROR] {msg}", file=sys.stderr)
        sys.exit(1)

    # 5. Run the command
    if not args.daemon:
        print(f"[Task Notifier] Running task: {task_name}")
        print(f"[Task Notifier] Command: {final_command}")
        print(f"[Task Notifier] Logging to: {cfg.log_dir}")
        print("-" * 60)

    exit_code, log_path, elapsed, start_time, end_time, resource_info = run_command(
        command=final_command,
        task_name=task_name,
        log_dir=cfg.log_dir,
    )

    if not args.daemon:
        print("-" * 60)
        status = "Completed" if exit_code == 0 else f"Failed (exit code: {exit_code})"
        print(f"[Task Notifier] Task '{task_name}' {status}")
        print(f"[Task Notifier] Elapsed: {_fmt(elapsed)}")
        print(f"[Task Notifier] Log: {log_path}")

    # 6. Extra attachments
    extra_attachments = args.attach_files if args.attach_files is not None else cfg.attach_files

    # 7. Send notification
    try:
        if not args.daemon:
            print("[Task Notifier] Sending email notification...")
        send_notification(
            config=cfg,
            task_name=task_name,
            exit_code=exit_code,
            elapsed=elapsed,
            command_text=command_text,
            start_time=start_time,
            end_time=end_time,
            log_file_path=log_path,
            to_address=args.to,
            extra_attachments=extra_attachments,
            resource_info=resource_info,
        )
        if not args.daemon:
            print("[Task Notifier] Email sent successfully.")
    except Exception as e:
        if args.daemon:
            _die_silent(f"Failed to send email: {e}")
        print(f"[ERROR] Failed to send email: {e}", file=sys.stderr)
        sys.exit(1)


def _die_silent(msg: str) -> None:
    """Write error to log and exit (for daemon mode where stderr is /dev/null)."""
    log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "logs",
        "_daemon_error.log",
    )
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{msg}\n")
    sys.exit(1)


def _fmt(seconds: float) -> str:
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


if __name__ == "__main__":
    main()
