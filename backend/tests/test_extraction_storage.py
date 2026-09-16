"""Actual archive and worker-function tests with in-memory external dependencies."""
from __future__ import annotations

import ast
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from northstar_api.services.extraction_checkpoint import encode_page_checkpoint
from northstar_api.services.extraction_package import ExtractionPackage
from northstar_api.services.extraction_pipeline import extract_document
from northstar_api.services.extraction_storage import approved_content, load_archive, recover_checkpoints
from test_extraction_fidelity import approve, text_package
from test_extraction_pipeline import pdf_bytes, provider, settings


def test_stored_release_is_revalidated_after_loading() -> None:
    package = text_package()
    package.record['extraction_revision'] = 3
    package.record['review_status'] = 'verified_release'
    loaded = load_archive(package.archive(), package.record['source_sha256'], revision=3)
    assert not loaded.record['release_eligible']
    with pytest.raises(ValueError, match='review before indexing'):
        approved_content(loaded, 'source.txt')
    approve(package)
    package.record['review_status'] = 'verified_release'
    loaded = load_archive(package.archive(), package.record['source_sha256'], revision=3)
    assert approved_content(loaded, 'source.txt') == package.record['pages'][0]['native_text']


def test_archive_tampering_and_wrong_source_revision_are_rejected() -> None:
    package = text_package()
    package.record['extraction_revision'] = 1
    archive = package.archive()
    for identity, revision in [('0' * 64, 1), (package.record['source_sha256'], 2)]:
        with pytest.raises(ValueError):
            load_archive(archive, identity, revision=revision)
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(output, 'w') as target:
        for name in source.namelist():
            target.writestr(name, b'changed' if name == 'source/original.txt' else source.read(name))
    with pytest.raises(ValueError, match='checksum'):
        load_archive(output.getvalue(), package.record['source_sha256'])


@pytest.mark.asyncio
async def test_sparse_completed_checkpoints_survive_corrupt_earlier_page(monkeypatch: pytest.MonkeyPatch) -> None:
    provider(monkeypatch)
    data = pdf_bytes(2)
    package = await extract_document(data, 'source.pdf', settings())
    page = package.record['pages'][1]
    checkpoint = encode_page_checkpoint(page, package.images[page['image']], [], source_sha256=package.record['source_sha256'], model='config', version=1)
    valid, invalid = recover_checkpoints({1: b'bad zip', 2: checkpoint}, source_sha256=package.record['source_sha256'], configuration_identity='config', revision=1)
    assert list(valid) == [2]
    assert invalid == [1]


def worker_functions(store: object) -> dict:
    # Compile the real worker functions, isolating DB, object store and model services.
    # This does not claim a full ASGI/PostgreSQL integration test.
    path = Path(__file__).parents[1] / 'src/northstar_api/services/ingestion.py'
    tree = ast.parse(path.read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in {'_existing_evidence', '_prepare_file'}]
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    from northstar_api.services.extraction_native import configuration
    namespace = {'object_store': store, 'get_settings': settings, 'logger': Mock(), 'load_archive': load_archive,
                 'approved_content': approved_content, 'recover_checkpoints': recover_checkpoints, 'extract_document': extract_document,
                 'configuration': configuration, 'encode_page_checkpoint': encode_page_checkpoint, 'hashlib': hashlib,
                 'json': json, 'zipfile': zipfile, 'KnowledgeStatus': SimpleNamespace(NEEDS_REVIEW='needs_review'),
                 'JobStatus': SimpleNamespace(SUCCEEDED='succeeded')}
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    return namespace


@pytest.mark.asyncio
async def test_worker_does_not_trust_supplied_file_content() -> None:
    raw = b'Preserved exact source.\n'
    store = SimpleNamespace(download=AsyncMock(return_value=(raw, {})), load_extraction_pages=AsyncMock(return_value={}),
                            put_extraction=AsyncMock(return_value='extractions/tenant/source/v0001.zip'))
    source = SimpleNamespace(id='source', tenant_id='tenant', name='source.txt', revision=1,
                             extraction_key=None, object_key='knowledge/tenant/source.txt',
                             content='unreviewed injected content', checksum=hashlib.sha256(raw).hexdigest())
    session = SimpleNamespace(commit=AsyncMock())
    result = await worker_functions(store)['_prepare_file'](session, source, None)
    assert result is None and source.content is None and source.status == 'needs_review'
    assert store.put_extraction.await_count == 1
    archive = store.put_extraction.await_args.args[2]
    assert isinstance(load_archive(archive, source.checksum), ExtractionPackage)


@pytest.mark.asyncio
async def test_worker_reuses_verified_archive_not_client_text() -> None:
    package = text_package()
    approve(package)
    package.record.update(extraction_revision=2, review_status='verified_release')
    store = SimpleNamespace(download=AsyncMock(return_value=(package.archive(), {})))
    source = SimpleNamespace(id='source', tenant_id='tenant', name='source.txt', revision=2,
                             extraction_key='extractions/tenant/source/v0002.zip', object_key='original',
                             content='attacker supplied', checksum=package.record['source_sha256'])
    result = await worker_functions(store)['_prepare_file'](SimpleNamespace(), source, None)
    assert result == source.content == package.record['pages'][0]['selected_text']
    assert store.download.await_count == 1


@pytest.mark.asyncio
async def test_worker_rejects_file_without_preserved_original() -> None:
    with pytest.raises(ValueError, match='preserved uploaded original'):
        await worker_functions(SimpleNamespace())['_prepare_file'](SimpleNamespace(), SimpleNamespace(object_key=None), None)


def test_benchmark_uses_only_adjudicated_matching_source_annotations() -> None:
    from northstar_api.services.extraction_benchmark import benchmark
    from test_extraction_fidelity import image_package
    package = image_package()
    truth = {'adjudicated': True, 'reviewer': 'human-reviewer', 'source_sha256': package.record['source_sha256'],
             'blocks': [{'id': 'P1-R1', 'text': 'Source fragment'}]}
    measured = benchmark(package.record, truth)
    assert measured['metrics']['text_exact_match']['rate'] == 1.0
    assert measured['metrics']['equation_exact_match']['status'] == 'NOT_MEASURED'
    truth['blocks'][0]['text'] = 'Do NOT change -12.50'
    measured = benchmark(package.record, truth)
    assert measured['metrics']['critical_token_fidelity']['rate'] == 0.0
    with pytest.raises(ValueError):
        benchmark(package.record, {**truth, 'adjudicated': False})
    with pytest.raises(ValueError):
        benchmark(package.record, {**truth, 'source_sha256': 'wrong'})
