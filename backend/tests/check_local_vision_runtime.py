"""Manual capability probe for the configured vision endpoint."""

import asyncio

import fitz
import httpx

from northstar_api.config import Settings
from northstar_api.services.hybrid_extraction import _read_image


async def main() -> None:
    document = fitz.open()
    page = document.new_page(width=500, height=140)
    page.insert_text((35, 80), "SOURCE CODE: N7Q4-271", fontsize=26)
    image = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
    document.close()
    try:
        response = await _read_image(image, Settings(_env_file=None))
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Vision endpoint rejected the request (HTTP {exc.response.status_code})") from exc
    except Exception as exc:
        raise RuntimeError(f"Vision endpoint probe failed ({type(exc).__name__})") from None
    if "N7Q4-271" not in response:
        raise AssertionError(f"Vision model did not read the image marker: {response[:200]!r}")
    print("Configured vision model read the image marker successfully")


if __name__ == "__main__":
    asyncio.run(main())
