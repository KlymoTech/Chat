"""Contract tests for safe Help Center support links."""

import unittest

from northstar_api.services.help_links import safe_support_url


class SupportLinkTests(unittest.TestCase):
    def test_valid_support_links(self):
        for value in (
            "https://support.company.example/help",
            "https://support.company.example:8443/tickets?from=app",
            " https://support.company.example/faq ",
        ):
            with self.subTest(value=value):
                self.assertEqual(safe_support_url(value), value.strip())

    def test_reject_unsafe_support_links(self):
        for value in (
            "http://support.company.example/",
            "javascript:alert(1)",
            "https://user:password@support.company.example/",
            "https://@support.company.example/",
            "https://localhost/help",
            "https://admin.internal/help",
            "https://127.0.0.1/help",
            "https://192.168.1.9/help",
            "https://[::1]/help",
            "https://support.company.example:99999/",
            "https://support.company.example/hello\\world",
            "https://support.company.example/%0aevil",
            "https://support.company.example/hello world",
            "https://support.company.example\nevil",
            "https:///missing-host",
            "https://example.com.",
            None,
            42,
        ):
            with self.subTest(value=value):
                self.assertEqual(safe_support_url(value), "")
