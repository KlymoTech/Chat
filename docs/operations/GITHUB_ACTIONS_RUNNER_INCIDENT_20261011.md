# GitHub Actions runner-allocation incident — 2026-10-11

## Observed evidence

For commit `eaa70adf6886b1e1963dd63455f5558572577fe0`, GitHub Actions run `38080025975` (Education Runtime Authorization) reports its backend job as failed after approximately two seconds, with an empty runner name and **zero steps**.

Run `38080025981` (CI) likewise reports failed frontend, backend, deployment configuration, and source/security jobs, each with an empty runner name and zero executed steps. Its integration job was skipped because prerequisites did not succeed.

**Conclusion:** these specific runs did not execute their test commands. Their results are not evidence that tests passed or failed. The underlying runner-allocation/account configuration issue must be resolved before meaningful release qualification.

## GitHub administrator checks

1. Open the failed workflow run and inspect the job's GitHub UI annotation/error banner (not merely its conclusion).
2. Inspect repository and organization **Settings → Actions → General** for policy restrictions, permitted actions, workflow permissions, and runner eligibility.
3. Inspect **Settings → Actions → Runners** and verify that the requested GitHub-hosted `ubuntu-24.04` runners are allowed and available.
4. Check account billing, Actions spending limits, usage quota and any payment or service restrictions. Do not assume which one caused the failure without the actual GitHub error.
5. Run a minimal workflow on an approved runner and confirm that a job is assigned a runner and executes at least one step.
6. Rerun the full mandatory CI, CodeQL, education authorization and audit workflows on the **same candidate commit**. Investigate any actual code failures exposed once jobs execute.
7. Keep release promotion blocked until full topology integration, security and migration checks pass.

## Release status

**BLOCKED — runner allocation not established.** Do not disable or bypass quality gates to make this status green. After restoring runner execution, use actual logs to repair application issues and continue the frontend/backend/website consolidation.
