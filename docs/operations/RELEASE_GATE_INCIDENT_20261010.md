# Release gate incident: 2026-10-10

## Observed on main

Commit `ca93f910905fd49254032a9861864e4324e307a0` has failing GitHub Actions:
- CI: source/secret security, backend quality, deployment configuration and frontend quality jobs failed; topology integration was skipped.
- Audit progress registry, Education Runtime Authorization and CodeQL also failed.

This record documents actual GitHub workflow conclusions, not assumed root causes. Job-level logs were unavailable during this review. Do not disable, skip, weaken or mark these checks optional merely to obtain a green status.

## Required incident triage

1. Recover the earliest failing step and logs from each job in GitHub Actions. Distinguish runner/account failures from lint, build, test, security and configuration failures.
2. Reproduce the failing command locally or in an isolated CI runner at the exact SHA.
3. Fix root causes in source code or CI configuration without modifying application code as a test setup workaround.
4. Execute the complete CI matrix, including Docker Compose topology and migrations, against the same immutable release candidate.
5. Confirm CodeQL is enabled or document the unavailable repository entitlement as a separate explicit release risk; do not report it as passing.
6. Obtain authorization, tenant-boundary, CRM, WhatsApp and CMS acceptance evidence before production promotion.

## Current disposition

**RELEASE BLOCKED**. No evidence yet establishes that the production deployment gates pass. Keep this incident open until linked passing runs and rollback verification exist.
