from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_release_builds_match_declared_architectures() -> None:
    manifest = yaml.safe_load((ROOT / "platform.yaml").read_text(encoding="utf-8"))
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    declared = set(manifest["images"]["api"]["platforms"])
    assert declared == {"linux/amd64", "linux/arm64"}

    publish = workflow["jobs"]["publish"]
    assert {entry["component"] for entry in publish["strategy"]["matrix"]["include"]} == {"api", "web"}
    steps = publish["steps"]
    qemu_index = next(
        i for i, step in enumerate(steps) if step.get("uses", "").startswith("docker/setup-qemu-action@")
    )
    buildx_index = next(
        i for i, step in enumerate(steps) if step.get("uses", "").startswith("docker/setup-buildx-action@")
    )
    build_index = next(
        i for i, step in enumerate(steps) if step.get("uses", "").startswith("docker/build-push-action@")
    )
    assert qemu_index < buildx_index < build_index
    assert "arm64" in steps[qemu_index]["with"]["platforms"].split(",")
    build = steps[build_index]["with"]
    assert set(build["platforms"].split(",")) == declared
    assert build["push"] is True
    assert build["sbom"] is True
    assert build["provenance"] == "mode=max"
    assert any("trivy-action@" in step.get("uses", "") for step in steps)
    assert any("actions/attest@" in step.get("uses", "") for step in steps)
