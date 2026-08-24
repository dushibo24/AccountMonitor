#!/usr/bin/env python3
"""Run the report immediately and then once a day inside Docker."""

import datetime
import os
import signal
import subprocess
import sys
import threading


APP_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_SCRIPT = os.path.join(APP_PATH, "codex_daily_report.py")
STOP_EVENT = threading.Event()


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_report_time(value):
    try:
        parsed = datetime.datetime.strptime(value, "%H:%M")
    except ValueError:
        raise RuntimeError(
            f"REPORT_TIME 必须是 24 小时制 HH:MM，当前值为 {value!r}"
        ) from None
    return parsed.hour, parsed.minute


def next_run_at(now, hour, minute):
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


def log(message):
    timestamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{timestamp}] {message}", flush=True)


def run_report(config_path):
    log("开始执行账号日报")
    result = subprocess.run(
        [sys.executable, "-u", REPORT_SCRIPT, "--config", config_path],
        check=False,
    )
    if result.returncode == 0:
        log("账号日报执行成功")
    else:
        log(f"账号日报执行失败，退出码 {result.returncode}；调度器将继续运行")
    return result.returncode


def stop(_signum, _frame):
    STOP_EVENT.set()


def validate_runtime_files(config_path):
    auth_path = os.path.join(os.path.dirname(os.path.abspath(config_path)), "auth.json")
    for path in (config_path, auth_path):
        if not os.path.isfile(path):
            raise RuntimeError(f"缺少运行文件: {path}")
        if not os.access(path, os.R_OK):
            raise RuntimeError(f"运行文件不可读: {path}")


def main():
    config_path = os.environ.get("CONFIG_PATH", "/app/config/config.json")
    report_time = os.environ.get("REPORT_TIME", "13:00")
    try:
        validate_runtime_files(config_path)
        hour, minute = parse_report_time(report_time)
    except RuntimeError as exc:
        print(f"容器配置错误: {exc}", file=sys.stderr)
        return 2

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    log(
        f"调度器启动：每天 {hour:02d}:{minute:02d} 执行，"
        f"时区 {datetime.datetime.now().astimezone().tzname()}"
    )
    if env_flag("RUN_ON_START", default=True):
        run_report(config_path)

    while not STOP_EVENT.is_set():
        now = datetime.datetime.now().astimezone()
        target = next_run_at(now, hour, minute)
        wait_seconds = max(0, (target - now).total_seconds())
        log(f"下次执行时间：{target:%Y-%m-%d %H:%M:%S %Z}")
        if STOP_EVENT.wait(wait_seconds):
            break
        run_report(config_path)

    log("调度器已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
