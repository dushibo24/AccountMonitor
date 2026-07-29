#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信「接收消息服务器 URL」一次性验证服务器。

用途：新版企业微信后台要求先设置「可信域名」或「接收消息服务器 URL」
才能配置「企业可信 IP」。本脚本实现官方回调验证协议，配合内网穿透
（如 cloudflared）在本地完成一次性验证，验证通过后即可关掉。

用法：
    1. 后台「接收消息 → 设置 API 接收」里随机生成 Token 和 EncodingAESKey，
       填入 auth.json:
           "push": { "wecom": { "callback_token": "...", "callback_aeskey": "..." } }
    2. python3 tools/wecom_verify_server.py          # 监听 8787 端口
    3. cloudflared tunnel --url http://localhost:8787 # 得到公网 https 地址
    4. 把地址填进后台 URL 栏，点保存触发验证
"""
import base64
import hashlib
import json
import os
import struct
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from Crypto.Cipher import AES

PORT = 8787
AUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "auth.json")


def load_credentials():
    # 环境变量优先（便于测试），否则读 auth.json
    token = os.environ.get("WECOM_CALLBACK_TOKEN", "")
    aeskey = os.environ.get("WECOM_CALLBACK_AESKEY", "")
    if not token or not aeskey:
        with open(AUTH_PATH, encoding="utf-8") as f:
            auth = json.load(f)
        wecom = (auth.get("push") or {}).get("wecom") or {}
        token = wecom.get("callback_token", "")
        aeskey = wecom.get("callback_aeskey", "")
    if not token or not aeskey:
        sys.exit("请先设置 callback_token / callback_aeskey（auth.json 的 push.wecom 里，"
                 "或 WECOM_CALLBACK_TOKEN / WECOM_CALLBACK_AESKEY 环境变量）")
    return token, base64.b64decode(aeskey + "=")


TOKEN, AES_KEY = None, None  # main() 里初始化


def verify_signature(token, timestamp, nonce, echostr, msg_signature):
    raw = "".join(sorted([token, timestamp, nonce, echostr]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest() == msg_signature


def decrypt_echostr(echostr):
    """按 WXBizMsgCrypt 协议解密 echostr，返回明文消息。"""
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY[:16])
    plain = cipher.decrypt(base64.b64decode(echostr))
    # 结构: 16字节随机串 + 4字节消息长度(网络序) + 消息 + receiveid
    msg_len = struct.unpack(">I", plain[16:20])[0]
    return plain[20:20 + msg_len].decode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        get = lambda k: (q.get(k) or [""])[0]
        msg_signature, timestamp, nonce, echostr = (
            get("msg_signature"), get("timestamp"), get("nonce"), get("echostr"))
        if not all([msg_signature, timestamp, nonce, echostr]):
            self._reply(400, "bad request")
            return
        if not verify_signature(TOKEN, timestamp, nonce, echostr, msg_signature):
            print(f"[拒绝] 签名不匹配: {self.path}")
            self._reply(403, "invalid signature")
            return
        try:
            msg = decrypt_echostr(echostr)
        except Exception as e:  # noqa: BLE001
            print(f"[错误] 解密失败: {e}（检查 callback_aeskey 是否与后台一致）")
            self._reply(500, "decrypt failed")
            return
        print(f"[成功] 验证通过，回显: {msg}")
        self._reply(200, msg)

    def do_POST(self):
        # 企业微信实际推送的消息，本项目用不到，返回 success 即可
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        print(f"[消息] 收到 POST（忽略，仅做验证用途）")
        self._reply(200, "success")

    def _reply(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # 用自己的 print


def main():
    global TOKEN, AES_KEY
    TOKEN, AES_KEY = load_credentials()
    print(f"监听 0.0.0.0:{PORT}，等待企业微信验证请求...")
    print(f"公网暴露: cloudflared tunnel --url http://localhost:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
