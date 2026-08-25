import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import codex_daily_report as report


class FakeClient:
    def __init__(self, failed_ids=()):
        self.failed_ids = set(failed_ids)

    def get_channel(self, channel_id):
        if channel_id in self.failed_ids:
            raise RuntimeError("upstream unavailable")
        return {"id": channel_id, "name": f"Codex-{channel_id}"}

    def get_codex_usage(self, channel_id):
        return {
            "email": f"user-{channel_id}@example.com",
            "plan_type": "pro",
            "rate_limit": {
                "primary_window": {
                    "used_percent": 20,
                    "limit_window_seconds": 5 * 60 * 60,
                },
                "secondary_window": {
                    "used_percent": 60,
                    "limit_window_seconds": 7 * 24 * 60 * 60,
                },
            },
        }


class ReportTests(unittest.TestCase):
    def test_kimi_formats_code_limits_and_subscription_usage(self):
        content = report.format_kimi_account({
            "ratelimit_code_5h": {"ratio": 0.25, "reset_time": "2026-08-25T20:00:00Z"},
            "ratelimit_code_7d": {"ratio": 0.5, "reset_time": "2026-08-30T20:00:00Z"},
            "subscription_balance": {"kimi_code_used_ratio": 0.75},
        })
        self.assertIn("5小时窗口（Kimi Code）", content)
        self.assertIn("25%", content)
        self.assertIn("每周窗口（Kimi Code）", content)
        self.assertIn("订阅额度已用: 75%", content)

    def test_kimi_accounts_are_mapped_by_channel_name(self):
        accounts, error = report.resolve_kimi_accounts({
            "kimi": {"enabled": True},
            "kimi_accounts": [
                {"channel_name": "Kimi 主账号"},
                {"channel_name": "Kimi 备用账号", "channel_id": 22},
            ],
            "kimi_cookies": {
                "Kimi 主账号": "cookie-one",
                "Kimi 备用账号": "cookie-two",
            },
        })
        self.assertIsNone(error)
        self.assertEqual([item["name"] for item in accounts], ["Kimi 主账号", "Kimi 备用账号"])
        self.assertEqual([item["cookie"] for item in accounts], ["cookie-one", "cookie-two"])

    def test_kimi_client_uses_official_connect_endpoint_and_cookie(self):
        client = report.KimiClient("session=secret")
        with mock.patch.object(report, "http_json", return_value={"ratelimit_code_5h": {"ratio": 0.1}}) as request:
            self.assertEqual(client.get_subscription_stats()["ratelimit_code_5h"]["ratio"], 0.1)
        args = request.call_args
        self.assertEqual(
            args.args[0],
            "https://www.kimi.com/apiv2/"
            "kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats",
        )
        self.assertEqual(args.kwargs["headers"]["Cookie"], "session=secret")

    def test_kimi_client_accepts_kimi_auth_bearer_token(self):
        client = report.KimiClient("kimi-auth.example.token")
        self.assertNotIn("Cookie", client.headers)
        self.assertEqual(client.headers["Authorization"], "Bearer kimi-auth.example.token")

    def test_kimi_only_dry_run_does_not_require_newapi_token(self):
        config = {
            "newapi_base_url": "https://example.com",
            "kimi": {"enabled": True},
            "kimi_cookie": "session=secret",
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            auth_path = os.path.join(tmp, "auth.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            with open(auth_path, "w", encoding="utf-8") as f:
                json.dump({"kimi_cookie": "session=secret"}, f)
            with mock.patch.object(
                report.sys, "argv", ["codex_daily_report.py", "-c", config_path, "--dry-run"]
            ), mock.patch.object(
                report.KimiClient,
                "get_subscription_stats",
                return_value={"ratelimit_code_5h": {"ratio": 0.1}},
            ):
                self.assertEqual(report.main(), 0)

    def test_kimi_test_path_does_not_require_newapi_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            auth_path = os.path.join(tmp, "auth.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"kimi": {"enabled": True}}, f)
            with open(auth_path, "w", encoding="utf-8") as f:
                json.dump({"kimi_cookie": "session=secret"}, f)
            with mock.patch.object(
                report.sys, "argv", ["codex_daily_report.py", "-c", config_path, "--test-kimi"]
            ), mock.patch.object(
                report.KimiClient,
                "get_subscription_stats",
                return_value={"ratelimit_code_5h": {"ratio": 0.1}},
            ):
                self.assertEqual(report.main(), 0)

    def test_newapi_retries_transient_timeout_then_succeeds(self):
        client = report.NewApiClient("https://example.com", "token")
        transient = report.HttpRequestError("read timed out", retryable=True)
        with mock.patch.object(
            report, "http_json", side_effect=[transient, transient, {"success": True}]
        ) as request, mock.patch.object(report.time, "sleep") as sleep:
            self.assertEqual(client.get("/api/test"), {"success": True})
        self.assertEqual(request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_newapi_does_not_retry_non_retryable_error(self):
        client = report.NewApiClient("https://example.com", "token")
        unauthorized = report.HttpRequestError("HTTP 401", retryable=False)
        with mock.patch.object(
            report, "http_json", side_effect=unauthorized
        ) as request, mock.patch.object(report.time, "sleep") as sleep:
            with self.assertRaises(report.HttpRequestError):
                client.get("/api/test")
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    def test_newapi_retries_upstream_5xx_response(self):
        client = report.NewApiClient("https://example.com", "token")
        with mock.patch.object(report, "http_json", side_effect=[
            {"success": False, "upstream_status": 502, "message": "bad gateway"},
            {"success": True, "data": {}},
        ]) as request, mock.patch.object(report.time, "sleep") as sleep:
            self.assertTrue(client.get("/api/test")["success"])
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_free_plan_primary_window_is_weekly(self):
        usage = {
            "plan_type": "free",
            "rate_limit": {
                "primary_window": {
                    "used_percent": 40,
                    "limit_window_seconds": 7 * 24 * 60 * 60,
                }
            },
        }
        content = report.format_account({"name": "Free"}, usage)
        self.assertIn("每周窗口", content)
        self.assertNotIn("5小时窗口", content)

    def test_current_credit_and_limit_fields_are_reported(self):
        usage = {
            "credits": {"overage_limit_reached": True},
            "spend_control": {"reached": True},
            "rate_limit_reset_credits": {"available_count": 2},
        }
        content = report.format_account({"name": "Account"}, usage)
        self.assertIn("超额额度已受限", content)
        self.assertIn("消费额度已受限", content)
        self.assertIn("可用重置次数: 2", content)

    def test_build_report_exposes_partial_failure(self):
        _, content, succeeded, failed = report.build_report(
            FakeClient(failed_ids={2}), [1, 2]
        )
        self.assertEqual((succeeded, failed), (1, 1))
        self.assertIn("Codex-1", content)
        self.assertIn("渠道 2", content)

    def test_sensitive_urls_are_redacted(self):
        url = (
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken?"
            "corpid=ww123&corpsecret=top-secret&access_token=access-secret"
        )
        safe = report.safe_url_for_log(url)
        self.assertNotIn("top-secret", safe)
        self.assertNotIn("access-secret", safe)
        self.assertNotIn("SENDKEY", report.safe_url_for_log(
            "https://sctapi.ftqq.com/SENDKEY.send"
        ))

    def test_wecom_test_path_does_not_require_newapi_token(self):
        config = {
            "newapi_base_url": "https://example.com",
            "newapi_access_token": "",
            "push": {
                "wecom": {
                    "corpid": "ww123",
                    "corpsecret": "secret",
                    "agentid": 1000002,
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            auth_path = os.path.join(tmp, "auth.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"newapi_base_url": "https://example.com"}, f)
            with open(auth_path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            with mock.patch.object(
                report.sys, "argv", ["codex_daily_report.py", "-c", config_path, "--test-wecom"]
            ), mock.patch.object(report, "push_wecom_app") as push:
                self.assertEqual(report.main(), 0)
                push.assert_called_once()

    def test_missing_config_has_no_traceback(self):
        stderr = io.StringIO()
        with mock.patch.object(
            report.sys, "argv", ["codex_daily_report.py", "-c", "/missing/config.json"]
        ), contextlib.redirect_stderr(stderr):
            self.assertEqual(report.main(), 1)
        self.assertIn("找不到配置文件", stderr.getvalue())

    def test_dry_run_returns_failure_when_account_fetch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            auth_path = os.path.join(tmp, "auth.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "newapi_base_url": "https://example.com",
                    "channel_ids": [9],
                }, f)
            with open(auth_path, "w", encoding="utf-8") as f:
                json.dump({"newapi_access_token": "valid-ascii-token"}, f)
            with mock.patch.object(
                report.sys,
                "argv",
                ["codex_daily_report.py", "-c", config_path, "--dry-run"],
            ), mock.patch.object(
                report, "NewApiClient", return_value=FakeClient(failed_ids={9})
            ):
                self.assertEqual(report.main(), 1)


if __name__ == "__main__":
    unittest.main()
