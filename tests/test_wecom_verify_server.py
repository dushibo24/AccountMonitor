import base64
import hashlib
import struct
import unittest

from tools import wecom_verify_server as verify


class WecomVerifyTests(unittest.TestCase):
    def test_decode_aes_key(self):
        raw = bytes(range(32))
        encoded = base64.b64encode(raw).decode("ascii").rstrip("=")
        self.assertEqual(verify.decode_aes_key(encoded), raw)

    def test_decode_aes_key_rejects_wrong_length(self):
        encoded = base64.b64encode(b"too short").decode("ascii").rstrip("=")
        with self.assertRaisesRegex(RuntimeError, "32 字节"):
            verify.decode_aes_key(encoded)

    def test_verify_signature(self):
        values = ["token", "123", "nonce", "echo"]
        signature = hashlib.sha1("".join(sorted(values)).encode("utf-8")).hexdigest()
        self.assertTrue(verify.verify_signature(*values, signature))
        self.assertFalse(verify.verify_signature(*values, "bad-signature"))

    @unittest.skipIf(verify.AES is None, "pycryptodome is not installed")
    def test_decrypt_echostr_round_trip(self):
        key = bytes(range(32))
        message = "wecom-callback-ok"
        corpid = "ww123456"
        plain = (
            b"0123456789abcdef"
            + struct.pack(">I", len(message.encode("utf-8")))
            + message.encode("utf-8")
            + corpid.encode("utf-8")
        )
        pad_len = 32 - (len(plain) % 32)
        padded = plain + bytes([pad_len]) * pad_len
        encrypted = verify.AES.new(key, verify.AES.MODE_CBC, key[:16]).encrypt(padded)

        old_key, old_corpid = verify.AES_KEY, verify.CORP_ID
        try:
            verify.AES_KEY, verify.CORP_ID = key, corpid
            self.assertEqual(
                verify.decrypt_echostr(base64.b64encode(encrypted).decode("ascii")),
                message,
            )
        finally:
            verify.AES_KEY, verify.CORP_ID = old_key, old_corpid


if __name__ == "__main__":
    unittest.main()
