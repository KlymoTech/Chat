"""Public extraction API; implementation is separated into evidence-focused modules.

The NVIDIA client and every model setting remain in the existing vision.py/config.py.
No model download, replacement, Qwen adapter, embedding or RAG policy is introduced here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from northstar_api.services.extraction_checkpoint import PageCheckpoint as PageCheckpoint
from northstar_api.services.extraction_checkpoint import decode_page_checkpoint as decode_page_checkpoint
from northstar_api.services.extraction_checkpoint import encode_page_checkpoint as encode_page_checkpoint
from northstar_api.services.extraction_native import configuration as configuration
from northstar_api.services.extraction_native import native_pdf as native_pdf
from northstar_api.services.extraction_native import text_unit as text_unit
from northstar_api.services.extraction_package import ExtractionPackage as ExtractionPackage
from northstar_api.services.extraction_pipeline import extract_document as extract_document
from northstar_api.services.extraction_validation import same_text

if TYPE_CHECKING:
    from northstar_api.config import Settings


def _compare(native: str, visual: str) -> bool:
    return same_text(native, visual)


async def _read_image(image: bytes, settings: Settings) -> str:
    """Backward-compatible direct reader; structured extraction uses region evidence."""
    from northstar_api.services.vision import read_image

    return await read_image(image, settings)
