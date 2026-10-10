"""Tests for the production configuration preflight."""

import tempfile
import unittest
from pathlib import Path

from scripts.production_env_preflight import load_env, validate


class ProductionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.valid = {
            "APP_ENV": "production",
            "JWT_SECRET": "N6p9!aB2xQ7#vR4kL8@tY5mZ1wC3sD0eF",
            "MFA_ENCRYPTION_KEY": "R8v2@pL6tH4!cK9qD5#sW1zY7mN3fA0bG",
            "DATABASE_URL": "postgresql://user:password@db.internal:5432/app",
            "APP_CORS_ORIGINS": '["https://app.company.test"]',
            "APP_AUTO_CREATE_SCHEMA": "false",
            "ALLOW_PRODUCTION_SEED": "false",
            "SEED_DEMO_AGENT": "false",
        }

    def test_valid(self):
        self.assertEqual(validate(self.valid), [])

    def test_placeholder_secret_rejected(self):
        self.valid["JWT_SECRET"] = "replace-with-at-least-32-random-characters"
        self.assertTrue(validate(self.valid))

    def test_insecure_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["http://localhost:3100"]'
        self.assertTrue(validate(self.valid))

    def test_shared_keys_rejected(self):
        self.valid["MFA_ENCRYPTION_KEY"] = self.valid["JWT_SECRET"]
        self.assertTrue(validate(self.valid))


    def test_origin_with_credentials_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://user:pass@app.company.test"]'
        self.assertTrue(validate(self.valid))

    def test_origin_with_path_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://app.company.test/admin"]'
        self.assertTrue(validate(self.valid))

    def test_invalid_port_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://app.company.test:invalid"]'
        self.assertTrue(validate(self.valid))

    def test_sqlite_rejected_for_production(self):
        self.valid["DATABASE_URL"] = "sqlite:///./app.db"
        self.assertTrue(validate(self.valid))


    def test_missing_database_credentials_rejected(self):
        self.valid["DATABASE_URL"] = "postgresql://db.internal/app"
        self.assertTrue(validate(self.valid))

    def test_invalid_database_port_rejected(self):
        self.valid["DATABASE_URL"] = "postgresql://user:password@db.internal:invalid/app"
        self.assertTrue(validate(self.valid))

    def test_placeholder_database_password_rejected(self):
        self.valid["DATABASE_URL"] = "postgresql://user:replace-password@db.internal/app"
        self.assertTrue(validate(self.valid))


    def test_duplicate_env_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("APP_ENV=production\nAPP_ENV=development\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_env(path)

    def test_invalid_env_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("INVALID-KEY=value\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_env(path)

    def test_unterminated_quote_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("JWT_SECRET='unterminated\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_env(path)


    def test_database_password_containing_example_word_allowed(self):
        self.valid["DATABASE_URL"] = "postgresql://user:myexamplepassword@db.internal/app"
        self.assertEqual(validate(self.valid), [])


    def test_wildcard_interface_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://0.0.0.0"]'
        self.assertTrue(validate(self.valid))

    def test_loopback_ipv6_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://[::1]"]'
        self.assertTrue(validate(self.valid))


    def test_private_ipv4_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://192.168.1.5"]'
        self.assertTrue(validate(self.valid))

    def test_private_ipv6_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://[fc00::1]"]'
        self.assertTrue(validate(self.valid))

    def test_repeated_jwt_secret_rejected(self):
        self.valid["JWT_SECRET"] = "a" * 40
        self.assertTrue(validate(self.valid))

    def test_repeated_mfa_secret_rejected(self):
        self.valid["MFA_ENCRYPTION_KEY"] = "b" * 40
        self.assertTrue(validate(self.valid))


    def test_internal_hostname_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://admin.internal"]'
        self.assertTrue(validate(self.valid))

    def test_local_hostname_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://service.local"]'
        self.assertTrue(validate(self.valid))


    def test_single_label_hostname_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://intranet"]'
        self.assertTrue(validate(self.valid))

    def test_invalid_dns_label_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://-bad.company.test"]'
        self.assertTrue(validate(self.valid))


    def test_numeric_tld_origin_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://app.123"]'
        self.assertTrue(validate(self.valid))


    def test_dotted_numeric_hostname_rejected(self):
        self.valid["APP_CORS_ORIGINS"] = '["https://192.168.1.999"]'
        self.assertTrue(validate(self.valid))


    def test_postgres_sslmode_require_allowed(self):
        self.valid["DATABASE_URL"] += "?sslmode=require"
        self.assertEqual(validate(self.valid), [])

    def test_postgres_sslmode_disable_rejected(self):
        self.valid["DATABASE_URL"] += "?sslmode=disable"
        self.assertTrue(validate(self.valid))

    def test_postgres_unexpected_query_option_rejected(self):
        self.valid["DATABASE_URL"] += "?application_name=debug"
        self.assertTrue(validate(self.valid))

    def test_postgres_duplicate_tls_option_rejected(self):
        self.valid["DATABASE_URL"] += "?sslmode=require&sslmode=disable"
        self.assertTrue(validate(self.valid))


    def test_postgres_ambiguous_tls_options_rejected(self):
        self.valid["DATABASE_URL"] += "?ssl=true&sslmode=require"
        self.assertTrue(validate(self.valid))


if __name__ == "__main__":
    unittest.main()
