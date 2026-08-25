#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codex / Kimi Coding Plan 账号日报，推送到微信（Server酱 / PushPlus）。

用法:
    python3 codex_daily_report.py                 # 生成并推送日报
    python3 codex_daily_report.py --dry-run       # 只打印消息，不推送
    python3 codex_daily_report.py --list-channels # 列出渠道，帮助找到 channel id
    python3 codex_daily_report.py -c config.json  # 指定配置文件
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_CONFIG = "config.json"

SENSITIVE_QUERY_KEYS = {
    "access_token", "corpsecret", "secret", "sendkey", "token",
}

NEWAPI_MAX_ATTEMPTS = 3
NEWAPI_RETRY_DELAYS = (1, 2)
KIMI_DEFAULT_BASE_URL = "https://www.kimi.com/apiv2"


class HttpRequestError(RuntimeError):
    """带有是否适合重试标记的 HTTP 请求错误。"""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def safe_url_for_log(url):
    """隐藏 URL 中可能出现的推送密钥，避免错误日志泄密。"""
    try:
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        safe_query = urllib.parse.urlencode([
            (key, "***" if key.lower() in SENSITIVE_QUERY_KEYS else value)
            for key, value in query
        ])
        path = parts.path
        if (parts.hostname or "").lower() == "sctapi.ftqq.com":
            path = re.sub(r"/[^/]+\.send$", "/***.send", path)
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, path, safe_query, parts.fragment)
        )
    except (TypeError, ValueError):
        return "<invalid-url>"


def http_json(url, method="GET", headers=None, data=None, json_body=None, timeout=20):
    """发送 HTTP 请求并解析 JSON 响应。data 为表单，json_body 为 JSON。"""
    body = None
    hdrs = {"User-Agent": "codex-daily-report/1.0"}
    if headers:
        hdrs.update(headers)
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    safe_url = safe_url_for_log(url)
    request_has_secret = safe_url != url or any(
        str(key).lower() in SENSITIVE_QUERY_KEYS
        for payload in (data, json_body)
        if isinstance(payload, dict)
        for key in payload
    ) or any(str(key).lower() in {"authorization", "cookie", "set-cookie"}
             for key in hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        if request_has_secret:
            detail = "<已隐藏含凭据请求的响应正文>"
        raise HttpRequestError(
            f"HTTP {e.code} {safe_url}: {detail}",
            retryable=500 <= e.code < 600,
        ) from None
    except urllib.error.URLError as e:
        raise HttpRequestError(
            f"请求失败 {safe_url}: {e.reason}", retryable=True
        ) from None
    except (TimeoutError, ConnectionError) as e:
        raise HttpRequestError(
            f"请求失败 {safe_url}: {e}", retryable=True
        ) from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        detail = "<已隐藏含凭据请求的响应正文>" if request_has_secret else raw[:300]
        raise RuntimeError(f"响应不是 JSON {safe_url}: {detail}")


class NewApiClient:
    def __init__(self, base_url, access_token, user_id=None,
                 max_attempts=NEWAPI_MAX_ATTEMPTS):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {access_token}"}
        self.max_attempts = max(1, int(max_attempts))
        if user_id:
            self.headers["New-Api-User"] = str(user_id)

    def get(self, path, params=None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = http_json(url, headers=self.headers)
                upstream_status = resp.get("upstream_status") if isinstance(resp, dict) else None
                if (isinstance(upstream_status, int) and upstream_status >= 500
                        and resp.get("success") is False):
                    raise HttpRequestError(
                        f"new-api 上游 HTTP {upstream_status}: "
                        f"{resp.get('message') or '服务暂时不可用'}",
                        retryable=True,
                    )
                return resp
            except HttpRequestError as e:
                if not e.retryable or attempt >= self.max_attempts:
                    raise
                delay = NEWAPI_RETRY_DELAYS[min(attempt - 1, len(NEWAPI_RETRY_DELAYS) - 1)]
                print(
                    f"new-api 请求失败（第 {attempt}/{self.max_attempts} 次）: {e}；"
                    f"{delay} 秒后重试",
                    file=sys.stderr,
                )
                time.sleep(delay)

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


class KimiClient:
    """Kimi 官网 Coding Plan 用量客户端。

    该接口是 Kimi 官网当前使用的 Connect JSON API；Cookie 由调用方从浏览器
    复制后原样传入，不在日志或镜像中保存。
    """

    def __init__(self, cookie, base_url=KIMI_DEFAULT_BASE_URL):
        cookie = str(cookie or "").strip()
        if not cookie:
            raise RuntimeError("Kimi 配置缺少 cookie")
        self.base_url = str(base_url or KIMI_DEFAULT_BASE_URL).rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://www.kimi.com",
            "Referer": "https://www.kimi.com/",
            "X-Language": "zh-CN",
            "x-msh-platform": "web",
        }
        # 浏览器复制出来的通常是完整 Cookie；Kimi Code 新版也可能提供
        # 形如 kimi-auth... 的 access token（官网前端以 Bearer 发送）。
        if "=" in cookie or ";" in cookie:
            self.headers["Cookie"] = cookie
        else:
            self.headers["Authorization"] = f"Bearer {cookie}"

    def get_subscription_stats(self):
        path = "/kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats"
        resp = http_json(
            self.base_url + path,
            method="POST",
            headers=self.headers,
            json_body={},
        )
        if not isinstance(resp, dict):
            raise RuntimeError("Kimi 用量接口返回格式异常")
        if resp.get("code") or resp.get("error_type") or resp.get("error"):
            message = resp.get("message") or resp.get("error_type") or resp.get("error")
            raise RuntimeError(f"Kimi 用量接口失败: {message}")
        return resp

# ---------- 消息格式化 ----------

def fmt_reset_time(ts):
    """把 unix 秒时间戳转成本地可读时间。"""
    if not ts:
        return "未知"
    try:
        if isinstance(ts, str) and not ts.strip().isdigit():
            normalized = ts.strip().replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.datetime.now().astimezone().tzinfo)
            dt = dt.astimezone()
        else:
            dt = datetime.datetime.fromtimestamp(int(ts)).astimezone()
        now = datetime.datetime.now().astimezone()
        if dt.date() == now.date():
            return dt.strftime("今天 %H:%M")
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return "未知"


def _field(obj, *names):
    if not isinstance(obj, dict):
        return None
    for name in names:
        if name in obj and obj[name] is not None:
            return obj[name]
    return None


def _ratio_percent(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # Kimi 返回 ratio（0~1）；兼容已经是百分数的测试/代理响应。
    if 0 <= number <= 1:
        number *= 100
    return number


def fmt_kimi_window(name, window):
    if not isinstance(window, dict):
        return None
    ratio = _field(window, "ratio", "used_ratio", "usedRatio")
    used = _ratio_percent(ratio)
    if used is None:
        return None
    reset = _field(window, "reset_time", "resetTime")
    if isinstance(reset, dict):
        reset = _field(reset, "seconds", "unix_seconds", "unixSeconds")
    return fmt_window(name, {"used_percent": used, "reset_at": reset})


def format_kimi_account(usage, name="Kimi Coding Plan"):
    """格式化 Kimi 官方订阅统计，优先展示 Kimi Code 专属限额。"""
    lines = [f"### {name}"]
    subscriptions = _field(usage, "subscriptions") or []
    if isinstance(subscriptions, list) and subscriptions:
        sub = subscriptions[0] if isinstance(subscriptions[0], dict) else {}
        plan = _field(sub, "display_name", "displayName", "name", "title")
        if plan:
            lines.append(f"- 套餐: {plan}")
    five_hour = _field(usage, "ratelimit_code_5h", "ratelimitCode5h")
    weekly = _field(usage, "ratelimit_code_7d", "ratelimitCode7d")
    # 某些地区/版本只返回通用限额，作为兼容回退。
    five_hour = five_hour or _field(usage, "ratelimit_5h", "ratelimit5h")
    weekly = weekly or _field(usage, "ratelimit_7d", "ratelimit7d")
    formatted = fmt_kimi_window("5小时窗口（Kimi Code）", five_hour)
    if formatted:
        lines.append(formatted)
    formatted = fmt_kimi_window("每周窗口（Kimi Code）", weekly)
    if formatted:
        lines.append(formatted)
    balance = _field(usage, "subscription_balance", "subscriptionBalance")
    code_ratio = _field(balance, "kimi_code_used_ratio", "kimiCodeUsedRatio")
    if code_ratio is not None:
        percent = _ratio_percent(code_ratio)
        if percent is not None:
            lines.append(f"- 订阅额度已用: {percent:.0f}%")
    if len(lines) == 1:
        raise RuntimeError("Kimi 响应中没有可识别的 Coding Plan 用量字段")
    return "\n".join(lines)


def build_kimi_report(client, name="Kimi Coding Plan"):
    try:
        return format_kimi_account(client.get_subscription_stats(), name), 1, 0
    except Exception as e:  # noqa: BLE001 - 与单个 new-api 渠道一致，继续其他来源
        return f"### {name}\n- ❌ 获取失败: {e}", 0, 1


def resolve_kimi_accounts(cfg):
    """读取 Kimi 账号映射；Cookie 只从 auth.json 的 kimi_cookies 获取。"""
    kimi_cfg = cfg.get("kimi") or {}
    raw_accounts = cfg.get("kimi_accounts") or kimi_cfg.get("accounts") or []
    raw_cookies = cfg.get("kimi_cookies") or {}
    if not isinstance(raw_cookies, dict):
        return [], "auth.json 的 kimi_cookies 必须是以渠道 ID 为键的 JSON 对象"

    # 兼容旧版单账号配置；新配置应使用 channel_id 显式映射。
    if not raw_accounts and (cfg.get("kimi_cookie") or kimi_cfg.get("cookie")):
        raw_accounts = [{
            "channel_id": kimi_cfg.get("channel_id", "default"),
            "name": kimi_cfg.get("name", "Kimi Coding Plan"),
            "base_url": kimi_cfg.get("base_url", KIMI_DEFAULT_BASE_URL),
            "_legacy_cookie": cfg.get("kimi_cookie") or kimi_cfg.get("cookie"),
        }]
    if not isinstance(raw_accounts, list):
        return [], "config.json 的 kimi_accounts 必须是数组"

    accounts, seen = [], set()
    for index, raw in enumerate(raw_accounts, 1):
        if not isinstance(raw, dict):
            return [], f"kimi_accounts 第 {index} 项必须是 JSON 对象"
        channel_id = str(raw.get("channel_id")) if raw.get("channel_id") not in (None, "") else ""
        channel_name = str(raw.get("channel_name") or raw.get("name") or "").strip()
        if not channel_id and not channel_name:
            return [], f"kimi_accounts 第 {index} 项缺少 channel_name"
        identity = channel_name or channel_id
        if identity in seen:
            return [], f"kimi_accounts 存在重复渠道: {identity}"
        seen.add(identity)
        cookie = (raw.get("_legacy_cookie") or raw_cookies.get(channel_name)
                  or raw_cookies.get(channel_id))
        if isinstance(cookie, dict):
            cookie = cookie.get("cookie")
        accounts.append({
            "channel_id": channel_id,
            "name": channel_name or f"Kimi Coding Plan（渠道 {channel_id}）",
            "base_url": raw.get("base_url") or kimi_cfg.get("base_url", KIMI_DEFAULT_BASE_URL),
            "cookie": cookie,
        })
    return accounts, None


def fmt_window(name, window):
    if not isinstance(window, dict):
        return None
    used = window.get("used_percent")
    if used is None:
        return None
    try:
        used_number = float(used)
    except (TypeError, ValueError):
        return None
    reset = fmt_reset_time(window.get("reset_at"))
    bar_len = 10
    filled = round(min(max(used_number, 0), 100) / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    return f"- {name}: {bar} {used_number:.0f}%（{reset} 重置）"


def _window_kind(window):
    if not isinstance(window, dict):
        return None
    try:
        seconds = float(window.get("limit_window_seconds"))
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return "weekly" if seconds >= 24 * 60 * 60 else "five_hour"


def resolve_rate_limit_windows(usage):
    """按窗口时长识别 5 小时/每周窗口，兼容 Free 套餐只有周窗口的情况。"""
    rate_limit = usage.get("rate_limit") or {}
    primary = rate_limit.get("primary_window")
    secondary = rate_limit.get("secondary_window")
    windows = [item for item in (primary, secondary) if isinstance(item, dict)]
    plan_type = str(usage.get("plan_type") or rate_limit.get("plan_type") or "").lower()

    five_hour = next((item for item in windows if _window_kind(item) == "five_hour"), None)
    weekly = next((item for item in windows if _window_kind(item) == "weekly"), None)

    if plan_type == "free":
        return None, weekly or primary or secondary
    if five_hour is None and weekly is None:
        return primary, secondary
    if five_hour is None:
        five_hour = next((item for item in windows if item is not weekly), None)
    if weekly is None:
        weekly = next((item for item in windows if item is not five_hour), None)
    return five_hour, weekly


def format_account(channel, usage):
    name = channel.get("name") or f"渠道 {channel.get('id')}"
    lines = [f"### {name}"]
    if isinstance(usage, dict):
        account = usage.get("account")
        email = usage.get("email") or (
            account.get("email") if isinstance(account, dict) else None
        )
        rl = usage.get("rate_limit") or {}
        plan = usage.get("plan_type") or rl.get("plan_type")
        if email:
            lines.append(f"- 账号: {email}")
        if plan:
            lines.append(f"- 套餐: {plan}")
        five_hour, weekly = resolve_rate_limit_windows(usage)
        w = fmt_window("5小时窗口", five_hour)
        if w:
            lines.append(w)
        w = fmt_window("每周窗口", weekly)
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
        if credits.get("overage_limit_reached"):
            lines.append("- ⚠️ 超额额度已受限")
        if (usage.get("spend_control") or {}).get("reached"):
            lines.append("- ⚠️ 消费额度已受限")
        reset_credits = (usage.get("rate_limit_reset_credits") or {}).get("available_count")
        if reset_credits not in (None, ""):
            lines.append(f"- 可用重置次数: {reset_credits}")
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
    return title, content, len(sections), len(errors)


# ---------- 推送 ----------

def push_serverchan(sendkey, title, content):
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    resp = http_json(url, method="POST", data={"title": title, "desp": content})
    if resp.get("code") != 0:
        raise RuntimeError(
            f"Server酱推送失败: code={resp.get('code')}, "
            f"message={resp.get('message') or resp.get('msg') or '未知错误'}"
        )


def push_pushplus(token, title, content):
    url = "https://www.pushplus.plus/send"
    resp = http_json(url, method="POST",
                     data={"token": token, "title": title, "content": content,
                           "template": "markdown"})
    if resp.get("code") != 200:
        raise RuntimeError(
            f"PushPlus 推送失败: code={resp.get('code')}, "
            f"message={resp.get('msg') or resp.get('message') or '未知错误'}"
        )


WECOM_ERROR_HINTS = {
    40001: "corpsecret 不正确，确认使用的是自建应用 Secret，而不是通讯录 Secret",
    40013: "corpid 不正确，请从「我的企业 → 企业信息」复制企业 ID",
    40014: "access_token 无效，请稍后重试",
    41001: "请求缺少 access_token",
    60011: "应用不可见或成员不在应用可见范围内",
    60020: "当前公网 IP 不在应用可信 IP 中；请更新可信 IP 后重试",
    81013: "touser 不存在或不在应用可见范围内",
}


def _wecom_error(stage, resp):
    code = resp.get("errcode")
    message = resp.get("errmsg") or resp.get("message") or "未知错误"
    try:
        normalized_code = int(code)
    except (TypeError, ValueError):
        normalized_code = code
    hint = WECOM_ERROR_HINTS.get(
        normalized_code, "请按 errcode 查询企业微信开发文档"
    )
    return RuntimeError(f"企业微信{stage}失败: errcode={code}, errmsg={message}；{hint}")


def validate_wecom_config(wecom):
    if not isinstance(wecom, dict):
        raise RuntimeError("企业微信配置 push.wecom 必须是 JSON 对象")
    missing = [key for key in ("corpid", "corpsecret", "agentid") if not wecom.get(key)]
    if missing:
        raise RuntimeError(f"企业微信配置缺少: {', '.join(missing)}")
    try:
        agentid = int(wecom["agentid"])
    except (TypeError, ValueError):
        raise RuntimeError("企业微信 agentid 必须是数字") from None
    return agentid


def push_wecom_app(wecom, title, content):
    """企业微信自建应用推送（成员可在微信插件中接收）。

    wecom: {"corpid": ..., "corpsecret": ..., "agentid": ..., "touser": "@all"(可选)}
    """
    agentid = validate_wecom_config(wecom)
    qs = urllib.parse.urlencode({
        "corpid": wecom["corpid"],
        "corpsecret": wecom["corpsecret"],
    })
    token_resp = http_json(f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?{qs}")
    if token_resp.get("errcode"):
        raise _wecom_error("获取 access_token", token_resp)
    access_token = token_resp.get("access_token")
    if not access_token:
        raise RuntimeError("企业微信获取 access_token 失败: 响应中缺少 access_token")

    url = ("https://qyapi.weixin.qq.com/cgi-bin/message/send"
           f"?access_token={access_token}")
    payload = {
        "touser": wecom.get("touser") or "@all",
        "msgtype": "markdown",
        "agentid": agentid,
        "markdown": {"content": f"## {title}\n\n{content}"},
    }
    resp = http_json(url, method="POST", json_body=payload)
    if resp.get("errcode"):
        raise _wecom_error("推送", resp)
    invalid_users = resp.get("invaliduser")
    if invalid_users:
        raise RuntimeError(
            f"企业微信返回成功但以下接收人无效: {invalid_users}；"
            "请检查 touser、应用可见范围和成员状态"
        )


# ---------- 入口 ----------

# 密钥只允许放在 auth.json 中
SECRET_KEYS = ("newapi_access_token", "push")


def load_config(path):
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            f"找不到配置文件 {path}；先执行 cp config.example.json config.json"
        ) from None
    except json.JSONDecodeError as e:
        raise RuntimeError(f"配置文件 {path} 不是有效 JSON: 第 {e.lineno} 行") from None
    if not isinstance(cfg, dict):
        raise RuntimeError(f"配置文件 {path} 的顶层必须是 JSON 对象")
    auth_path = os.path.join(os.path.dirname(os.path.abspath(path)), "auth.json")

    # 旧版 config.json 里遗留的密钥自动迁移到 auth.json
    moved = {k: cfg.pop(k) for k in SECRET_KEYS if cfg.get(k)}
    auth = {}
    if os.path.exists(auth_path):
        try:
            with open(auth_path, encoding="utf-8") as f:
                auth = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"auth.json 不是有效 JSON: 第 {e.lineno} 行") from None
        if not isinstance(auth, dict):
            raise RuntimeError("auth.json 的顶层必须是 JSON 对象")
    if moved:
        auth = {**moved, **auth}  # auth.json 中已有的值优先
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump(auth, f, ensure_ascii=False, indent=2)
        os.chmod(auth_path, 0o600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"已将 {', '.join(moved)} 从配置迁移到 auth.json")

    cfg.update(auth)
    return cfg


def main():
    parser = argparse.ArgumentParser(description="Codex 账号日报推送")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印不推送")
    parser.add_argument("--list-channels", action="store_true", help="列出渠道后退出")
    parser.add_argument("--test-wecom", action="store_true",
                        help="跳过 new-api，向企业微信发送一条测试消息")
    parser.add_argument("--test-kimi", action="store_true",
                        help="只请求 Kimi 官方用量接口并打印结果，不推送")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except (OSError, RuntimeError) as e:
        print(f"配置错误: {e}", file=sys.stderr)
        return 1

    if args.test_kimi:
        kimi_cfg = cfg.get("kimi") or {}
        kimi_accounts, accounts_error = resolve_kimi_accounts(cfg)
        if accounts_error:
            print(accounts_error, file=sys.stderr)
            return 1
        if not kimi_accounts:
            print("请先在 config.json 中配置 kimi_accounts 和 auth.json 中的 kimi_cookies",
                  file=sys.stderr)
            return 1
        failed = False
        for account in kimi_accounts:
            if not account["cookie"]:
                print(f"### {account['name']}\n- ❌ 未配置该渠道的 Cookie")
                failed = True
                continue
            try:
                usage = KimiClient(
                    account["cookie"], account["base_url"]
                ).get_subscription_stats()
                print(format_kimi_account(usage, account["name"]))
            except Exception as e:  # noqa: BLE001 - CLI 需要给出可操作的诊断
                print(f"### {account['name']}\n- ❌ 获取失败: {e}")
                failed = True
        return 1 if failed else 0

    if args.test_wecom:
        wecom = (cfg.get("push") or {}).get("wecom")
        try:
            push_wecom_app(
                wecom,
                "AccountMonitor 企业微信测试",
                f"测试时间：{datetime.datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}\n\n"
                "如果你看到这条消息，企业微信凭据、可信 IP、应用可见范围和接收人均已打通。",
            )
        except Exception as e:  # noqa: BLE001 - CLI 需要给出可操作的诊断
            print(str(e), file=sys.stderr)
            return 1
        print("企业微信测试消息发送成功")
        return 0

    token = cfg.get("newapi_access_token", "")
    base_url = cfg.get("newapi_base_url")
    kimi_cfg = cfg.get("kimi") or {}
    kimi_cookie = cfg.get("kimi_cookie") or kimi_cfg.get("cookie")
    kimi_accounts, kimi_accounts_error = resolve_kimi_accounts(cfg)
    kimi_enabled = bool(kimi_cfg.get("enabled", bool(kimi_accounts)))
    newapi_enabled = bool(token and isinstance(token, str) and token.isascii() and base_url)

    if args.list_channels:
        if not newapi_enabled:
            print("--list-channels 需要 auth.json 中有效的 newapi_access_token 和 newapi_base_url",
                  file=sys.stderr)
            return 1
        client = NewApiClient(base_url, token, cfg.get("newapi_user_id"))
        try:
            channels = client.list_channels(cfg.get("channel_keyword", "codex"))
        except Exception as e:  # noqa: BLE001 - CLI 统一输出简洁错误
            print(f"列出渠道失败: {e}", file=sys.stderr)
            return 1
        for ch in channels:
            print(f"id={ch.get('id')}\ttype={ch.get('type')}\tname={ch.get('name')}")
        return 0

    sections = []
    success_count = failure_count = 0
    if newapi_enabled:
        client = NewApiClient(base_url, token, cfg.get("newapi_user_id"))
        channel_ids = cfg.get("channel_ids")
        if not channel_ids:
            keyword = cfg.get("channel_keyword", "codex")
            try:
                channel_ids = [ch["id"] for ch in client.list_channels(keyword)]
            except Exception as e:  # noqa: BLE001 - CLI 统一输出简洁错误
                sections.append(f"### new-api Codex\n- ❌ 自动查找渠道失败: {e}")
                channel_ids = []
            if not channel_ids and not sections:
                sections.append(f"### new-api Codex\n- ❌ 未找到名称含「{keyword}」的渠道")
        if channel_ids:
            _, report_content, succeeded, failed = build_report(client, channel_ids)
            sections.append(report_content)
            success_count += succeeded
            failure_count += failed
        elif sections:
            failure_count += 1

    if kimi_enabled:
        if kimi_accounts_error:
            sections.append(f"### Kimi Coding Plan\n- ❌ 配置错误: {kimi_accounts_error}")
            failure_count += 1
        elif not kimi_accounts:
            sections.append("### Kimi Coding Plan\n- ❌ 配置已启用但没有 kimi_accounts")
            failure_count += 1
        else:
            for account in kimi_accounts:
                if not account["cookie"]:
                    kimi_section, succeeded, failed = (
                        f"### {account['name']}\n- ❌ 获取失败: 未配置该渠道的 Cookie",
                        0,
                        1,
                    )
                else:
                    kimi_section, succeeded, failed = build_kimi_report(
                        KimiClient(account["cookie"], account["base_url"]),
                        account["name"],
                    )
                sections.append(kimi_section)
                success_count += succeeded
                failure_count += failed

    if not sections:
        print("请在 auth.json 中配置 newapi_access_token，或配置 kimi.cookie（并启用 Kimi）",
              file=sys.stderr)
        return 1

    title = f"Codex / Kimi 账号日报 {datetime.date.today().isoformat()}"
    content = "\n\n".join(sections)
    print(title)
    print(content)

    if args.dry_run:
        return 0 if success_count > 0 and failure_count == 0 else 1

    ok = success_count > 0 and failure_count == 0
    push = cfg.get("push") or {}
    pushers = []
    if push.get("serverchan_sendkey"):
        pushers.append(("Server酱", lambda: push_serverchan(push["serverchan_sendkey"], title, content)))
    if push.get("pushplus_token"):
        pushers.append(("PushPlus", lambda: push_pushplus(push["pushplus_token"], title, content)))
    wecom = push.get("wecom")
    if isinstance(wecom, dict) and any(
            wecom.get(key) for key in ("corpid", "corpsecret", "agentid")):
        pushers.append(("企业微信", lambda: push_wecom_app(wecom, title, content)))
    if not pushers:
        print("未配置任何推送渠道（push.serverchan_sendkey / push.pushplus_token / push.wecom）",
              file=sys.stderr)
        return 1
    for name, do_push in pushers:
        try:
            do_push()
            print(f"{name} 推送成功")
        except Exception as e:  # noqa: BLE001
            print(f"{name} {e}", file=sys.stderr)
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
