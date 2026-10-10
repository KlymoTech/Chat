# Adaptive governed-switch implementation (isolated branch)

This increment adds `platform_runtime/governed_switches.py` as a **pure,
advisory** classification and evidence-gate module. It does not modify the
existing runtime, deployment profiles, AWS resources, or change executor.

## Contract

- A: reversible runtime configuration; health snapshot and rollback config.
- B: redeploy/restart; reviewed deploy plan and canary evidence.
- C: stateful provider transition; backup/restore proof, dual-run
  reconciliation, cutover and forward-repair.
- D: placement/topology transition; routing epoch, capacity, canary and
  recovery plan.
- L: protected security invariants (never independently toggle).
- E: unqualified automatic stateful switching requiring manual review.

Validation still runs against both source and target specs. No planner output
is authorization to mutate AWS, and the adapter/executor remains separate.

## Outstanding before production use

1. Connect classification to the persisted control-plane change record and
   policy API, including independently authenticated approvals.
2. Prove real AWS adapters, rollback and recovery in staging.
3. Add Terraform/Jenkins/observability/autoscaling integrations and
   benchmark representative workloads before making capacity claims.
4. Run backend tests in CI, including the governed-switch contract tests.

## Checks

From the repository's configured backend environment run the existing
Python test suite and the targeted module test:
`pytest backend/tests/test_governed_switches.py`

This branch has not been load-certified or deployed.
