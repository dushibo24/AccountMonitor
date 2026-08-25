# Codex / Kimi 账号日报

每天从 new-api 拉取 Codex 渠道的账户用量，并可直接从 Kimi 官网官方接口拉取 Kimi Coding Plan 用量，推送到微信（企业微信 / Server酱 / PushPlus）。

数据来源：new-api 管理端接口 `GET /api/channel/{id}/codex/usage`（即网页上「账户信息」按钮调用的接口，会自动刷新 OAuth token）。

new-api 的只读请求遇到网络超时、连接中断或上游 5xx 时会自动尝试最多 3 次（间隔 1 秒、2 秒）；认证、权限等 4xx 错误不会重试。

## 准备（密钥获取方式）

所有密钥只填写在本地 `auth.json` 中（已在 `.gitignore` 里，不会上传 GitHub）。

1. **new-api 访问令牌**（需要管理员账号）：
   1. 浏览器登录 <https://napi.zq.cuiyong.net:44443>
   2. 右上角头像 → **个人设置**
   3. 找到 **系统访问令牌** → 生成新令牌并复制
   4. 填入 `auth.json` 的 `newapi_access_token`
2. **推送渠道**（三选一或都填）：
   - **企业微信自建应用**（推荐，成员可在微信里接收，见下文「企业微信推送配置」）：填入 `push.wecom`
   - **Server酱**：打开 <https://sct.ftqq.com> → 微信扫码登录 → 复制 **SendKey** → 填入 `push.serverchan_sendkey`
   - **PushPlus**：打开 <https://www.pushplus.plus> → 微信扫码登录 → 复制 **token** → 填入 `push.pushplus_token`

## 企业微信推送配置（按此顺序）

让朋友在微信里直接收到日报（无需常驻企业微信 App）：

1. **注册企业微信**：下载企业微信 App → 创建企业（个人即可，无需认证）。
2. **添加成员**：管理后台「通讯录」→ 添加成员；成员必须处于正常状态。
3. **创建自建应用**：管理后台「应用管理」→「自建」→「创建应用」，可见范围包含上一步的成员。保存页面里的 **AgentId** 和该应用的 **Secret**；不要使用通讯录 Secret。
4. **取得企业 ID**：管理后台「我的企业」→「企业信息」→ **企业 ID**。
5. **填写 `auth.json`**：

   ```json
   {
     "newapi_access_token": "你的 new-api 系统访问令牌",
     "push": {
       "wecom": {
         "corpid": "ww 开头的企业 ID",
         "corpsecret": "自建应用 Secret",
         "agentid": 1000002,
         "touser": "@all"
       }
     }
   }
   ```

6. **配置企业可信 IP**：在运行日报的机器执行 `curl -4 ifconfig.me`，将输出的公网 IPv4 填入自建应用详情页的「企业可信 IP」。家庭宽带 IP 变化后要同步更新，否则推送会返回 `60020`。
7. **单独试发企业微信**（不访问 new-api）：

   ```bash
   python3 codex_daily_report.py --test-wecom
   ```

   看到“企业微信测试消息发送成功”才表示凭据、可信 IP、应用范围和接收人均已打通。脚本会把 `40001`、`40013`、`60020`、`81013` 等错误翻译成具体处理建议。
8. **让成员在个人微信接收**：
   - 「通讯录」→ 添加成员（朋友的手机号/微信）
   - 「我的企业」→「微信插件」→ 把插件二维码发给朋友，用**微信**扫码关注
   - 朋友关注后即使在微信里也能收到应用消息，可以卸载企业微信 App

### 出现“配置企业可信 IP 前，请先设置可信域名或接收消息服务器 URL”时

选择 **设置接收消息服务器 URL**，不需要购买或备案域名。本项目通过本机验证服务和 cloudflared 临时 HTTPS 地址完成一次验证。验证成功并保存可信 IP 后，这两个进程都可以关闭，不需要常驻。

#### 1. 在企业微信后台生成回调参数

进入「应用管理 → 自建 → Codex 账号日报 → 接收消息 → 设置 API 接收」。页面需要填写：

- `URL`
- `Token`
- `EncodingAESKey`

点击页面按钮随机生成 `Token` 和 `EncodingAESKey`。先保留这个页面，不要点击保存。

#### 2. 把回调参数写入 auth.json

将刚才生成的值原样填入 `push.wecom`。不要把真实值发送给其他人或提交到 Git：

```json
"wecom": {
  "corpid": "你的企业 ID",
  "corpsecret": "你的自建应用 Secret",
  "agentid": 1000002,
  "touser": "@all",
  "callback_token": "企业微信页面中的 Token",
  "callback_aeskey": "企业微信页面中的 EncodingAESKey"
}
```

后台、`auth.json` 两处的 Token 和 EncodingAESKey 必须逐字一致。

#### 3. 安装一次性验证工具

在项目目录执行：

```bash
cd /Users/throneway/Desktop/learn/research/codeshop/AccountMonitor
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-wecom.txt
brew install cloudflared  # 没有安装 cloudflared 时执行一次
```

日报主脚本仍然只使用 Python 标准库；这些依赖只用于本次 URL 验证。

#### 4. 在第一个终端启动验证服务器

```bash
cd /Users/throneway/Desktop/learn/research/codeshop/AccountMonitor
.venv/bin/python tools/wecom_verify_server.py
```

正常输出：

```text
监听 0.0.0.0:8787，等待企业微信验证请求...
```

保持这个终端运行。可另开终端检查本地服务：

```bash
curl http://127.0.0.1:8787/healthz
```

应返回 `ok`。

#### 5. 在第二个终端建立临时 HTTPS 隧道

```bash
cloudflared tunnel --url http://127.0.0.1:8787
```

等待输出类似下面的公网地址：

```text
https://something-random.trycloudflare.com
```

复制完整地址，并保持第二个终端运行。

#### 6. 回到企业微信页面保存

填写并点击保存：

- URL：cloudflared 输出的完整 `https://...trycloudflare.com` 地址
- Token：第 1 步生成的 Token
- EncodingAESKey：第 1 步生成的 EncodingAESKey

第一个终端应显示：

```text
[成功] 验证通过，回显: ...
```

如果显示“签名不匹配”，检查 Token；如果显示“解密失败”，检查 EncodingAESKey。修改后重新保存。

#### 7. 设置企业可信 IP 并试发

URL 验证成功后，回到应用的「企业可信 IP → 配置」。在运行日报的 Mac 上获取公网 IPv4：

```bash
curl -4 ifconfig.me
```

把输出的 IP 填入并保存。此时可以按 `Ctrl+C` 关闭 cloudflared 和验证服务器；它们只负责一次性 URL 验证，不影响后续主动推送。

最后执行：

```bash
python3 codex_daily_report.py --test-wecom
```

看到“企业微信测试消息发送成功”才表示完整推送链路已经打通。

## 配置

```bash
cp config.example.json config.json   # 普通配置（base_url、渠道 ID）
cp auth.example.json auth.json       # 密钥（令牌、推送 key）
chmod 600 auth.json                  # 仅允许当前用户读取
# 编辑 auth.json，填入令牌和推送 key
```

**密钥只放在 `auth.json`**，该文件已被 `.gitignore` 排除，且项目内置了 Claude Code hook（`.claude/hooks/protect_auth.py`）阻止 AI 读取它。旧版 `config.json` 里的密钥会被脚本自动迁移到 `auth.json`。

### Kimi Coding Plan（可选）

Kimi 监测不经过 new-api，而是调用 Kimi 官网当前使用的官方接口：
`POST https://www.kimi.com/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats`。
接口返回 Kimi Code 专属 5 小时 / 7 天限额以及订阅额度使用情况。

1. 在浏览器登录 <https://www.kimi.com>，打开开发者工具 → **Network**，刷新「订阅 / 用量」页面。
2. 找到请求路径包含 `kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats` 的请求：如果请求头有完整 `Cookie`，原样复制；如果使用 `Authorization: Bearer kimi-auth...`，则复制 Bearer 后面的完整令牌。
3. 在 `config.json` 中按 **new-api 里的 Kimi 渠道名称** 配置一一对应关系；名称会直接用于日报标题：

   ```json
   "kimi": {
     "enabled": true,
     "base_url": "https://www.kimi.com/apiv2"
   },
   "kimi_accounts": [
     {"channel_name": "Kimi 渠道名称 1"},
     {"channel_name": "Kimi 渠道名称 2"}
   ]
   ```

   ```json
   "kimi_cookies": {
     "Kimi 渠道名称 1": "账号 1 的完整 Cookie 或 kimi-auth 令牌",
     "Kimi 渠道名称 2": "账号 2 的完整 Cookie 或 kimi-auth 令牌"
   }
   ```

每个 `channel_name` 必须唯一，并且在 `kimi_cookies` 中有同名键；这样一个 new-api Kimi 渠道就对应一个独立 Cookie。某个 Cookie 失效只会让对应渠道显示失败，不影响其他账号。Cookie 只通过 `auth.json` 只读挂载注入 Docker，不会写入镜像或日志。Cookie 过期后，重新复制并替换本机 `auth.json`，然后执行 `docker compose restart`。

- `channel_ids`：渠道 ID 列表。不知道 ID 的话先运行 `python3 codex_daily_report.py --list-channels` 查看；留空则自动匹配名称含 `channel_keyword` 的所有渠道。
- `newapi_user_id`：访问令牌对应的用户 ID（管理员一般是 `1`，个人设置页面可见）。部分 new-api 版本要求随令牌一起发送 `New-Api-User` 请求头。
- 推送渠道填一个即可，多个都填会各推一份；未使用的字段保持空字符串。

## 测试

```bash
python3 codex_daily_report.py --dry-run   # 只打印消息
python3 codex_daily_report.py --test-wecom # 只测试企业微信推送
python3 codex_daily_report.py --test-kimi  # 逐个测试 Kimi 官方用量接口
python3 codex_daily_report.py             # 实际推送
```

## 定时部署

日报主脚本只需要 Python 3（标准库，无第三方依赖）。`requirements-wecom.txt` 只供企业微信回调 URL 的一次性验证工具使用。

### macOS（launchd）

先确认 `python3 codex_daily_report.py --dry-run` 和正式推送都成功，再安装定时任务。仓库提供安装脚本，默认每天 13:00 运行：

```bash
./tools/install_launchd.sh
launchctl kickstart gui/$(id -u)/com.dushibo.codex-daily-report                                # 手动触发一次
launchctl bootout gui/$(id -u)/com.dushibo.codex-daily-report                                  # 卸载
```

注意：电脑在 13:00 时需处于开机状态；睡眠中的 Mac 会在唤醒后补跑错过的任务。运行日志见 `report.log`。

### Linux 服务器（cron）

```cron
# crontab -e，每天下午 1 点推送
0 13 * * * cd /opt/AccountMonitor && /usr/bin/python3 codex_daily_report.py >> report.log 2>&1
```

注意：`auth.json` 含有访问令牌和推送 key，不要提交到公开仓库。

### Docker（Ubuntu，推荐用于 pktgen）

镜像基于 Ubuntu 22.04。容器启动时立即执行一次日报，之后常驻并按北京时间
每天 13:00 执行。`config.json` 和 `auth.json` 通过只读挂载提供，不会写入镜像层。

```bash
# config.json、auth.json 已放在项目目录后：
docker compose up -d --build
docker compose logs -f account-monitor
```

修改时间或取消启动时立即执行，可编辑 `compose.yaml` 中的环境变量：

- `REPORT_TIME`：`HH:MM` 格式，默认 `13:00`
- `RUN_ON_START`：默认 `true`；设为 `false` 时仅等待定时执行

手动试发企业微信或只拉取数据检查：

```bash
docker compose exec account-monitor \
  python3 codex_daily_report.py -c /app/config/config.json --test-wecom
docker compose exec account-monitor \
  python3 codex_daily_report.py -c /app/config/config.json --dry-run
docker compose exec account-monitor \
  python3 codex_daily_report.py -c /app/config/config.json --test-kimi
```

直接使用 `docker run` 时：

```bash
docker build -t account-monitor:latest .
docker run -d --name account-monitor --restart unless-stopped \
  --dns 223.5.5.5 --dns 1.1.1.1 \
  -e TZ=Asia/Shanghai -e REPORT_TIME=13:00 \
  -v "$PWD/config.json:/app/config/config.json:ro" \
  -v "$PWD/auth.json:/app/config/auth.json:ro" \
  account-monitor:latest
```
