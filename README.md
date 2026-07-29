# Codex 账号日报

每天从 new-api 拉取两个 Codex 渠道的账户用量（5 小时窗口 / 每周窗口使用百分比、套餐、credits 等），推送到微信（Server酱 / PushPlus）。

数据来源：new-api 管理端接口 `GET /api/channel/{id}/codex/usage`（即网页上「账户信息」按钮调用的接口，会自动刷新 OAuth token）。

## 准备（密钥获取方式）

所有密钥只填写在本地 `auth.json` 中（已在 `.gitignore` 里，不会上传 GitHub）。

1. **new-api 访问令牌**（需要管理员账号）：
   1. 浏览器登录 <https://napi.zq.cuiyong.net:44443>
   2. 右上角头像 → **个人设置**
   3. 找到 **系统访问令牌** → 生成新令牌并复制
   4. 填入 `config.json` 的 `newapi_access_token`
2. **推送渠道**（三选一或都填）：
   - **企业微信自建应用**（推荐，成员可在微信里接收，见下文「企业微信推送配置」）：填入 `push.wecom`
   - **Server酱**：打开 <https://sct.ftqq.com> → 微信扫码登录 → 复制 **SendKey** → 填入 `push.serverchan_sendkey`
   - **PushPlus**：打开 <https://www.pushplus.plus> → 微信扫码登录 → 复制 **token** → 填入 `push.pushplus_token`

## 企业微信推送配置

让朋友在微信里直接收到日报（无需常驻企业微信 App）：

1. **注册企业微信**：下载企业微信 App → 创建企业（个人即可，名字随意，无需认证）
2. **创建自建应用**：电脑登录管理后台 <https://work.weixin.qq.com> → 「应用管理」→「自建」→「创建应用」→ 可见范围选全部成员。创建后得到 **AgentId** 和 **Secret**
3. **拿企业 ID**：管理后台「我的企业」→ 最下方「企业 ID」
4. **配置可信 IP**：自建应用详情页 →「企业可信 IP」→ 填入脚本运行机器的公网 IP（`curl ifconfig.me` 查询；家庭宽带 IP 变动后需更新，否则会报 60020 错误）
5. **把三个值填入 `auth.json`** 的 `push.wecom`：`corpid` / `corpsecret` / `agentid`
6. **邀请成员 + 微信插件**：
   - 「通讯录」→ 添加成员（朋友的手机号/微信）
   - 「我的企业」→「微信插件」→ 把插件二维码发给朋友，用**微信**扫码关注
   - 朋友关注后即使在微信里也能收到应用消息，可以卸载企业微信 App

## 配置

```bash
cp config.example.json config.json   # 普通配置（base_url、渠道 ID）
cp auth.example.json auth.json       # 密钥（令牌、推送 key）
# 编辑 auth.json，填入令牌和推送 key
```

**密钥只放在 `auth.json`**，该文件已被 `.gitignore` 排除，且项目内置了 Claude Code hook（`.claude/hooks/protect_auth.py`）阻止 AI 读取它。旧版 `config.json` 里的密钥会被脚本自动迁移到 `auth.json`。

- `channel_ids`：渠道 ID 列表。不知道 ID 的话先运行 `python3 codex_daily_report.py --list-channels` 查看；留空则自动匹配名称含 `channel_keyword` 的所有渠道。
- `newapi_user_id`：访问令牌对应的用户 ID（管理员一般是 `1`，个人设置页面可见）。部分 new-api 版本要求随令牌一起发送 `New-Api-User` 请求头。
- 推送渠道填一个即可，两个都填会各推一份。

## 测试

```bash
python3 codex_daily_report.py --dry-run   # 只打印消息
python3 codex_daily_report.py             # 实际推送
```

## 定时部署

只需要 Python 3（标准库，无第三方依赖）。

### macOS（launchd，本项目当前方式）

plist 已安装在 `~/Library/LaunchAgents/com.dushibo.codex-daily-report.plist`，每天 14:00 运行：

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dushibo.codex-daily-report.plist   # 加载
launchctl kickstart gui/$(id -u)/com.dushibo.codex-daily-report                                # 手动触发一次
launchctl bootout gui/$(id -u)/com.dushibo.codex-daily-report                                  # 卸载
```

注意：电脑在 14:00 时需处于开机状态；睡眠中的 Mac 会在唤醒后补跑错过的任务。运行日志见 `report.log`。

### Linux 服务器（cron）

```cron
# crontab -e，每天下午 2 点推送
0 14 * * * cd /opt/AccountMonitor && /usr/bin/python3 codex_daily_report.py >> report.log 2>&1
```

注意：`auth.json` 含有访问令牌和推送 key，不要提交到公开仓库。
