"""Tests for the production configuration preflight."""

import unittest

from scripts.production_env_preflight import validate


class ProductionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.valid = {
            "APP_ENV": "production",
            "JWT_SECRET": "a" * 40,
            "MFA_ENCRYPTION_KEY": "b" * 40,
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


if __name__ == "__main__":
    unittest.main()
