# Codex 账号日报

每天从 new-api 拉取两个 Codex 渠道的账户用量（5 小时窗口 / 每周窗口使用百分比、套餐、credits 等），推送到微信（Server酱 / PushPlus）。

数据来源：new-api 管理端接口 `GET /api/channel/{id}/codex/usage`（即网页上「账户信息」按钮调用的接口，会自动刷新 OAuth token）。

## 准备（密钥获取方式）

所有密钥只填写在本地 `config.json` 中（已在 `.gitignore` 里，不会上传 GitHub）。

1. **new-api 访问令牌**（需要管理员账号）：
   1. 浏览器登录 <https://napi.zq.cuiyong.net:44443>
   2. 右上角头像 → **个人设置**
   3. 找到 **系统访问令牌** → 生成新令牌并复制
   4. 填入 `config.json` 的 `newapi_access_token`
2. **推送渠道**（二选一或都填，微信扫码登录即可）：
   - **Server酱**：打开 <https://sct.ftqq.com> → 微信扫码登录 → 复制 **SendKey** → 填入 `push.serverchan_sendkey`
   - **PushPlus**：打开 <https://www.pushplus.plus> → 微信扫码登录 → 复制 **token** → 填入 `push.pushplus_token`

## 配置

```bash
cp config.example.json config.json
# 编辑 config.json，填入令牌和推送 key
```

- `channel_ids`：渠道 ID 列表。不知道 ID 的话先运行 `python3 codex_daily_report.py --list-channels` 查看；留空则自动匹配名称含 `channel_keyword` 的所有渠道。
- 推送渠道填一个即可，两个都填会各推一份。

## 测试

```bash
python3 codex_daily_report.py --dry-run   # 只打印消息
python3 codex_daily_report.py             # 实际推送
```

## 服务器定时部署

只需要 Python 3（标准库，无第三方依赖）。把本目录上传到服务器后：

```cron
# crontab -e，每天早上 9 点推送
0 9 * * * cd /opt/AccountMonitor && /usr/bin/python3 codex_daily_report.py >> report.log 2>&1
```

注意：`config.json` 含有访问令牌和推送 key，不要提交到公开仓库。
