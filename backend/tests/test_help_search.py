from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from northstar_api.database import SessionFactory
from northstar_api.help_models import HelpArticle
from northstar_api.models import Role
from northstar_api.services.help_search import help_search_service


async def test_postgres_help_search_filters_role_before_limit() -> None:
    """Restricted hits must not consume the SQL top-K window for another role."""

    class EmptyRows:
        def all(self) -> list[Any]:
            return []

    class RecordingSession:
        statement: Any = None

        async def execute(self, statement: Any) -> EmptyRows:
            self.statement = statement
            return EmptyRows()

    for role in (Role.ANALYST, Role.OWNER):
        session = RecordingSession()
        hits = await help_search_service._postgres_lexical(
            session, role=role, query="create agent", category="agents"
        )
        assert hits == []
        assert session.statement is not None

        compiled = session.statement.compile(dialect=postgresql.dialect())
        statement = str(compiled)
        assert "CAST(help_articles.audience_roles_json AS JSONB) @>" in statement
        assert statement.index("@>") < statement.index("LIMIT")
        assert [role.value] in compiled.params.values()
        assert "agents" in compiled.params.values()


async def test_help_search_respects_role_before_ranking(client) -> None:
    # client starts the lifespan and idempotently syncs docs-as-code content.
    await client.get('/health/live')
    async with SessionFactory() as session:
        owner_hits = await help_search_service.search(session, role=Role.OWNER, query='create agent')
        analyst_hits = await help_search_service.search(session, role=Role.ANALYST, query='create agent')
        assert any(hit.article.slug == 'create-agent' for hit in owner_hits)
        assert all(hit.article.slug != 'create-agent' for hit in analyst_hits)


async def test_help_search_exact_title_and_content_sync_are_stable(client) -> None:
    await client.get('/health/live')
    async with SessionFactory() as session:
        before = len((await session.scalars(select(HelpArticle))).all())
        hits = await help_search_service.search(session, role=Role.OWNER, query='Understand the Analytics dashboard')
        assert hits
        assert hits[0].article.slug == 'analytics-dashboard'
        after = len((await session.scalars(select(HelpArticle))).all())
        assert before == after
