#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codex 账号日报：从 new-api 拉取 Codex 渠道的账户用量，推送到微信（Server酱 / PushPlus）。

用法:
    python3 codex_daily_report.py                 # 生成并推送日报
    python3 codex_daily_report.py --dry-run       # 只打印消息，不推送
    python3 codex_daily_report.py --list-channels # 列出渠道，帮助找到 channel id
    python3 codex_daily_report.py -c config.json  # 指定配置文件
"""
import argparse
import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_CONFIG = "config.json"


def http_json(url, method="GET", headers=None, data=None, timeout=20):
    """发送 HTTP 请求并解析 JSON 响应。"""
    body = None
    hdrs = {"User-Agent": "codex-daily-report/1.0"}
    if headers:
        hdrs.update(headers)
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code} {url}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"请求失败 {url}: {e.reason}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"响应不是 JSON {url}: {raw[:300]}")


class NewApiClient:
    def __init__(self, base_url, access_token):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def get(self, path, params=None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return http_json(url, headers=self.headers)

    def list_channels(self, keyword=""):
        # 管理端渠道列表（分页），按关键字过滤名称
        resp = self.get("/api/channel/search", {"keyword": keyword, "p": 0, "page_size": 100})
        if not resp.get("success"):
            raise RuntimeError(f"查询渠道失败: {resp.get('message')}")
        data = resp.get("data") or {}
        return data.get("items") or data.get("records") or []

    def get_channel(self, channel_id):
        resp = self.get(f"/api/channel/{channel_id}")
        if not resp.get("success"):
            raise RuntimeError(f"查询渠道 {channel_id} 失败: {resp.get('message')}")
        return resp.get("data") or {}

    def get_codex_usage(self, channel_id):
        resp = self.get(f"/api/channel/{channel_id}/codex/usage")
        if not resp.get("success"):
            raise RuntimeError(f"获取渠道 {channel_id} 用量失败: {resp.get('message')}")
        return resp.get("data") or {}


# ---------- 消息格式化 ----------

def fmt_reset_time(ts):
    """把 unix 秒时间戳转成本地可读时间。"""
    if not ts:
        return "未知"
    try:
        dt = datetime.datetime.fromtimestamp(int(ts)).astimezone()
        now = datetime.datetime.now().astimezone()
        if dt.date() == now.date():
            return dt.strftime("今天 %H:%M")
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return "未知"


def fmt_window(name, window):
    if not isinstance(window, dict):
        return None
    used = window.get("used_percent")
    if used is None:
        return None
    reset = fmt_reset_time(window.get("reset_at"))
    bar_len = 10
    filled = round(min(max(float(used), 0), 100) / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    return f"- {name}: {bar} {float(used):.0f}%（{reset} 重置）"


def format_account(channel, usage):
    name = channel.get("name") or f"渠道 {channel.get('id')}"
    lines = [f"### {name}"]
    if isinstance(usage, dict):
        email = usage.get("email") or (usage.get("account") or {}).get("email")
        plan = usage.get("plan_type")
        if email:
            lines.append(f"- 账号: {email}")
        if plan:
            lines.append(f"- 套餐: {plan}")
        rl = usage.get("rate_limit") or {}
        w = fmt_window("5小时窗口", rl.get("primary_window"))
        if w:
            lines.append(w)
        w = fmt_window("每周窗口", rl.get("secondary_window"))
        if w:
            lines.append(w)
        if rl.get("limit_reached"):
            lines.append("- ⚠️ 限额已用尽")
        credits = usage.get("credits") or {}
        if credits.get("unlimited"):
            lines.append("- 额度: 不限量")
        elif credits.get("balance") not in (None, ""):
            lines.append(f"- 额度余额: {credits['balance']}")
        elif credits.get("has_credits") is False:
            lines.append("- 额度: 无额外 credits")
    return "\n".join(lines)


def build_report(client, channel_ids):
    today = datetime.date.today().isoformat()
    sections, errors = [], []
    for cid in channel_ids:
        try:
            channel = client.get_channel(cid)
            usage = client.get_codex_usage(cid)
            sections.append(format_account(channel, usage))
        except Exception as e:  # noqa: BLE001 - 单个账号失败不影响其他账号
            errors.append(f"### 渠道 {cid}\n- ❌ 获取失败: {e}")
    title = f"Codex 账号日报 {today}"
    content = "\n\n".join(sections + errors)
    return title, content


# ---------- 推送 ----------

def push_serverchan(sendkey, title, content):
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    resp = http_json(url, method="POST", data={"title": title, "desp": content})
    if resp.get("code") != 0:
        raise RuntimeError(f"Server酱推送失败: {resp}")


def push_pushplus(token, title, content):
    url = "http://www.pushplus.plus/send"
    resp = http_json(url, method="POST",
                     data={"token": token, "title": title, "content": content,
                           "template": "markdown"})
    if resp.get("code") != 200:
        raise RuntimeError(f"PushPlus 推送失败: {resp}")


# ---------- 入口 ----------

def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Codex 账号日报推送")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印不推送")
    parser.add_argument("--list-channels", action="store_true", help="列出渠道后退出")
    args = parser.parse_args()

    cfg = load_config(args.config)
    token = cfg.get("newapi_access_token", "")
    if not token or not token.isascii():
        print("请先在配置文件中填入有效的 newapi_access_token"
              "（new-api 个人设置 → 系统访问令牌）", file=sys.stderr)
        return 1
    client = NewApiClient(cfg["newapi_base_url"], token)

    if args.list_channels:
        for ch in client.list_channels(cfg.get("channel_keyword", "codex")):
            print(f"id={ch.get('id')}\ttype={ch.get('type')}\tname={ch.get('name')}")
        return 0

    channel_ids = cfg.get("channel_ids")
    if not channel_ids:
        keyword = cfg.get("channel_keyword", "codex")
        channel_ids = [ch["id"] for ch in client.list_channels(keyword)]
        if not channel_ids:
            print(f"未找到名称含「{keyword}」的渠道", file=sys.stderr)
            return 1

    title, content = build_report(client, channel_ids)
    print(title)
    print(content)

    if args.dry_run:
        return 0

    ok = True
    push = cfg.get("push") or {}
    if push.get("serverchan_sendkey"):
        try:
            push_serverchan(push["serverchan_sendkey"], title, content)
            print("Server酱 推送成功")
        except Exception as e:  # noqa: BLE001
            print(f"Server酱 {e}", file=sys.stderr)
            ok = False
    if push.get("pushplus_token"):
        try:
            push_pushplus(push["pushplus_token"], title, content)
            print("PushPlus 推送成功")
        except Exception as e:  # noqa: BLE001
            print(f"PushPlus {e}", file=sys.stderr)
            ok = False
    if not (push.get("serverchan_sendkey") or push.get("pushplus_token")):
        print("未配置任何推送渠道（push.serverchan_sendkey / push.pushplus_token）", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
