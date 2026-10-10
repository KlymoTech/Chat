"""SQLite contract tests for cross-request desired-state uniqueness.

PostgreSQL concurrency and Alembic migration tests are still required in CI.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex

from northstar_api.modules.platform_runtime.persistence import PlatformConfigVersion


def test_partial_index_enforces_one_active_configuration_per_environment() -> None:
    index = next(
        idx for idx in PlatformConfigVersion.__table__.indexes
        if idx.name == "uq_platform_config_versions_one_active_per_environment"
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE platform_config_versions "
            "(id TEXT PRIMARY KEY, environment TEXT NOT NULL, active BOOLEAN NOT NULL)"
        ))
        connection.execute(CreateIndex(index))
        connection.execute(text(
            "INSERT INTO platform_config_versions(id, environment, active) "
            "VALUES ('a','production',1), ('b','production',0), ('c','staging',1)"
        ))
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO platform_config_versions(id, environment, active) "
                "VALUES ('d','production',1)"
            ))
        # Inactive rollback revisions remain available; other environments
        # have an independent active slot.
        connection.execute(text(
            "INSERT INTO platform_config_versions(id, environment, active) "
            "VALUES ('e','production',0), ('f','test',1)"
        ))
