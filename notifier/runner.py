"""Command runner — executes a shell command and captures output to a log file."""

import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional, Tuple

# 固定北京时间（UTC+8），不受服务器本地时区影响
CST = timezone(timedelta(hours=8), "CST")

try:
    import psutil as _psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def run_command(
    command: str,
    task_name: str,
    log_dir: str = "./logs",
) -> Tuple[int, str, float, str, str, Optional[dict[str, Any]]]:
    """Execute `command`, write real-time output to `log_dir/<task_name>.log`.

    Returns:
        Tuple of (exit_code, log_file_path, elapsed_seconds,
                  start_time_iso, end_time_iso, resource_info).
        ``resource_info`` is a dict with keys:
          peak_memory_mb, cpu_percent_avg (or None if psutil unavailable).
    """
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in task_name)
    log_file = log_dir_path / f"{safe_name}.log"

    start_time = time.time()
    start_time_iso = datetime.now(CST).isoformat()

    resource_info: Optional[dict[str, Any]] = None

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"=== Task: {task_name} ===\n")
        f.write(f"=== Command: {command} ===\n")
        f.write(f"=== Started at: {start_time_iso} ===\n\n")
        f.flush()

        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            # Start resource monitoring in background
            monitor_stop = threading.Event()
            monitor_result: dict[str, Any] = {}
            monitor_thread = threading.Thread(
                target=_monitor_resources,
                args=(process.pid, monitor_stop, monitor_result),
                daemon=True,
            )
            monitor_thread.start()

            for line in iter(process.stdout.readline, ""):
                f.write(line)
                f.flush()
                if not _DAEMONIZED:
                    sys.stdout.write(line)
                    sys.stdout.flush()

            process.wait()
            exit_code = process.returncode

            # Stop monitor and collect results
            monitor_stop.set()
            monitor_thread.join(timeout=3)
            if monitor_result.get("peak_rss") is not None:
                peak_mb = monitor_result["peak_rss"] / 1024 / 1024
                cpu_avg = monitor_result.get("cpu_percent_avg")
                resource_info = {
                    "peak_memory_mb": round(peak_mb, 1),
                    "cpu_percent_avg": round(cpu_avg, 1) if cpu_avg is not None else None,
                }

        except Exception as e:
            exit_code = -1
            error_msg = f"Failed to execute command: {e}\n"
            f.write(error_msg)
            sys.stderr.write(error_msg)
            sys.stderr.flush()

    end_time = time.time()
    elapsed = end_time - start_time
    end_time_iso = datetime.now(CST).isoformat()

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n=== Finished at: {end_time_iso} ===\n")
        f.write(f"=== Exit code: {exit_code} ===\n")
        f.write(f"=== Elapsed: {_format_duration(elapsed)} ===\n")
        if resource_info:
            f.write(f"=== Peak memory: {resource_info['peak_memory_mb']} MB ===\n")
            if resource_info["cpu_percent_avg"] is not None:
                f.write(f"=== Avg CPU: {resource_info['cpu_percent_avg']}% ===\n")

    return exit_code, str(log_file.absolute()), elapsed, start_time_iso, end_time_iso, resource_info


def _monitor_resources(
    pid: int,
    stop_event: threading.Event,
    result: dict[str, Any],
) -> None:
    """Background thread: sample RSS (peak) and CPU %% every 5 seconds."""
    if not HAS_PSUTIL:
        return
    try:
        proc = _psutil.Process(pid)
    except (_psutil.NoSuchProcess, _psutil.AccessDenied):
        return

    peak_rss = 0
    cpu_samples: list[float] = []

    while not stop_event.is_set():
        try:
            with proc.oneshot():
                mem = proc.memory_info()
                cpu = proc.cpu_percent()
            peak_rss = max(peak_rss, mem.rss)
            cpu_samples.append(cpu)
        except (_psutil.NoSuchProcess, _psutil.AccessDenied):
            break
        stop_event.wait(5)

    result["peak_rss"] = peak_rss
    result["cpu_percent_avg"] = (
        sum(cpu_samples) / len(cpu_samples) if cpu_samples else None
    )


# Global flag: set to True when daemonized to suppress console output
_DAEMONIZED = False


def set_daemonized() -> None:
    """Mark the process as daemonized (suppresses real-time console output)."""
    global _DAEMONIZED
    _DAEMONIZED = True


def _format_duration(seconds: float) -> str:
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
