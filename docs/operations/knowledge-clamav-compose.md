# Optional local ClamAV sidecar for knowledge uploads

The Northstar backend already requires a clean ClamAV INSTREAM verdict
before promoting staged knowledge uploads in `staging` and `production`.
This additive Compose override supplies a same-network-namespace scanner
for local integration tests. It does **not** deploy AWS/ECS infrastructure.

## Start and stop (operator-initiated)

From the repository root:

```bash
docker compose -f compose.yaml -f compose.knowledge-clamav.yaml config
docker compose -f compose.yaml -f compose.knowledge-clamav.yaml up -d --build
docker compose -f compose.yaml -f compose.knowledge-clamav.yaml ps
```

The override changes only `api.environment` and adds
`knowledge-clamav` with a persistent signature volume.
It does not alter the default `docker compose up` workflow.

The scanner shares the API's network namespace so the backend's existing
client reaches `127.0.0.1:3310`. Clamd itself must bind only
`127.0.0.1`, not `0.0.0.0`. There are **no published scanner ports**.
The official ClamAV image supports the `CLAMD_CONF_*` environment
configuration; FreshClam maintains signatures in the persistent volume.

The first scan may fail closed while FreshClam downloads signatures or
Clamd initializes. Retry after the scanner is healthy, not by disabling
the scanner. If a scan exceeds configured limits, Clamd is configured
to flag it instead of reporting a clean verdict. The server uses a
500 MiB maximum stream for the current maximum upload size.

To stop without deleting signatures:

```bash
docker compose -f compose.yaml -f compose.knowledge-clamav.yaml stop knowledge-clamav
```

Avoid `down --volumes` if signature and other persistent data must be
retained. Stop or disable only in a non-production environment; an
enabled API refuses promotion when the scanner is offline.

## Required before production

- Pin a qualified ClamAV image by immutable digest and scan the image.
- Qualify the actual container startup and TCP binding; record the
  `docker compose config` output, health and version, and EICAR
  detection/rejection evidence.
- Verify scanner signature age, automatic updates, RAM/CPU budgets,
  throughput/timeouts, and detection of scan-size-limit events.
- Validate that bad/unknown scan replies never promote an object, and
  that staging does not accumulate unbounded files.
- For ECS/EKS use a task/pod-local scanner and production workload
  networking; this Compose override is **not** an AWS deployment model.
- Restore exact-commit CI and verify PostgreSQL, MinIO/S3, upload,
  operational logging and rollback tests before signing a release.

This configuration preserves the existing API and object-store contract.
No production AWS service is provisioned by this patch.

## Live scanner qualification command

Run the following only when the optional Compose scanner is running:

```bash
docker compose -f compose.yaml -f compose.knowledge-clamav.yaml \
  exec api python -m northstar_api.workers.knowledge_clamav_qualification --test-eicar
```

This CLI checks loopback PING/VERSION, a clean INSTREAM payload, and whether
the daemon rejects the harmless industry-standard EICAR signature. It
exits nonzero if anything fails and emits no uploaded file content.
Without `--test-eicar` it performs only partial connectivity checks and exits
with code 2, which **must not** be used as a release gate.

A successful live CLI output is one necessary local piece of evidence;
it is not sufficient proof of signature freshness, image provenance,
per-tenant isolation, production runtime behavior, restore readiness or
release authorization. Capture and review the output during a real operator
qualification run. No live daemon has been tested merely by merging this code.
