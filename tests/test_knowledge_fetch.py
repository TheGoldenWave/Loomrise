from __future__ import annotations

from unittest.mock import patch
import unittest

from loomrise.knowledge_fetch import fetch_https_text


class KnowledgeFetchTests(unittest.TestCase):
    @patch("loomrise.knowledge_fetch._read_once")
    @patch("loomrise.knowledge_fetch.socket.getaddrinfo")
    def test_non_public_dns_results_are_rejected_before_connect(self, resolve, read_once):
        resolve.return_value = [(None, None, None, None, ("127.0.0.1", 443))]
        with self.assertRaisesRegex(ValueError, "非公网"):
            fetch_https_text("https://example.test/faq")
        read_once.assert_not_called()

    @patch("loomrise.knowledge_fetch._read_once")
    @patch("loomrise.knowledge_fetch.socket.getaddrinfo")
    def test_html_extracts_visible_text_and_discards_script_content(self, resolve, read_once):
        resolve.return_value = [(None, None, None, None, ("93.184.216.34", 443))]
        read_once.return_value = (
            200, None,
            b"<html><body><h1>Courses &amp; fees</h1><script>private()</script>"
            b"<p>Contact us</p></body></html>",
            "text/html; charset=utf-8", None,
        )
        text = fetch_https_text("https://example.test/faq")
        self.assertEqual(text, "Courses & fees\nContact us")
        read_once.assert_called_once_with("example.test", "93.184.216.34", "/faq")

    @patch("loomrise.knowledge_fetch._read_once")
    @patch("loomrise.knowledge_fetch.socket.getaddrinfo")
    def test_redirects_are_revalidated_before_following(self, resolve, read_once):
        resolve.return_value = [(None, None, None, None, ("93.184.216.34", 443))]
        read_once.return_value = (302, "http://127.0.0.1/admin", b"", "text/html", None)
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            fetch_https_text("https://example.test/faq")
        read_once.assert_called_once()

    def test_url_credentials_and_non_default_port_are_rejected(self):
        for url in ("https://user:pass@example.test/faq", "https://example.test:8443/faq"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                fetch_https_text(url)


if __name__ == "__main__":
    unittest.main()
