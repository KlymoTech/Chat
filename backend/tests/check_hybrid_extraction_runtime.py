"""Run the current isolated extraction contracts without app startup or credentials."""
from pathlib import Path

import pytest

if __name__ == "__main__":
    tests = Path(__file__).parent
    raise SystemExit(pytest.main(["--noconftest", "-q", *[str(tests / name) for name in (
        "test_extraction_fidelity.py", "test_extraction_pipeline.py", "test_extraction_storage.py",
    )]]))
