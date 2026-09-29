#!/usr/bin/env python3
"""Tests for fetch_archive.py."""

import gzip
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from fetch_archive import decode_json_bytes  # noqa: E402


class TestDecodeJsonBytes(unittest.TestCase):
    def test_decode_plain_utf8(self):
        """Plain UTF-8 JSON should decode correctly."""
        data = {"key": "value"}
        raw = json.dumps(data).encode("utf-8")
        result = decode_json_bytes(raw)
        self.assertEqual(result, data)

    def test_decode_gzipped(self):
        """Gzipped JSON should be decompressed and decoded."""
        data = {"key": "value"}
        json_text = json.dumps(data)
        raw = gzip.compress(json_text.encode("utf-8"))
        result = decode_json_bytes(raw)
        self.assertEqual(result, data)

    def test_decode_utf16_le_bom(self):
        """UTF-16 LE with BOM should be decoded correctly."""
        data = {"key": "value"}
        json_text = json.dumps(data)
        # UTF-16 LE with BOM
        raw = b"\xff\xfe" + json_text.encode("utf-16-le")
        result = decode_json_bytes(raw)
        self.assertEqual(result, data)

    def test_decode_utf16_be_bom(self):
        """UTF-16 BE with BOM should be decoded correctly."""
        data = {"key": "value"}
        json_text = json.dumps(data)
        # UTF-16 BE with BOM
        raw = b"\xfe\xff" + json_text.encode("utf-16-be")
        result = decode_json_bytes(raw)
        self.assertEqual(result, data)

    def test_decode_utf8_bom(self):
        """UTF-8 with BOM should have BOM stripped."""
        data = {"key": "value"}
        json_text = json.dumps(data)
        # UTF-8 with BOM
        raw = b"\xef\xbb\xbf" + json_text.encode("utf-8")
        result = decode_json_bytes(raw)
        self.assertEqual(result, data)

    def test_decode_gzip_then_utf16(self):
        """Gzipped UTF-16 should be decompressed then decoded."""
        data = {"key": "value"}
        json_text = json.dumps(data)
        # UTF-16 LE with BOM, then gzipped
        utf16_with_bom = b"\xff\xfe" + json_text.encode("utf-16-le")
        raw = gzip.compress(utf16_with_bom)
        result = decode_json_bytes(raw)
        self.assertEqual(result, data)

    def test_decode_gzip_utf8_bom(self):
        """Gzipped UTF-8 with BOM should work."""
        data = {"key": "value"}
        json_text = json.dumps(data)
        # UTF-8 with BOM, then gzipped
        utf8_with_bom = b"\xef\xbb\xbf" + json_text.encode("utf-8")
        raw = gzip.compress(utf8_with_bom)
        result = decode_json_bytes(raw)
        self.assertEqual(result, data)

    def test_decode_list(self):
        """JSON arrays should also decode correctly."""
        data = [{"id": 1}, {"id": 2}]
        raw = json.dumps(data).encode("utf-8")
        result = decode_json_bytes(raw)
        self.assertEqual(result, data)

    def test_decode_invalid_json_raises(self):
        """Invalid JSON should raise JSONDecodeError."""
        raw = b"not valid json"
        with self.assertRaises(json.JSONDecodeError):
            decode_json_bytes(raw)


if __name__ == "__main__":
    unittest.main()
