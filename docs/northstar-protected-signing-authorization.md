# Protected Jenkins signing authorization (offline foundation)

Module: `queue_notification_signing_authorization.py`.

The module independently verifies a signed, canonical Ed25519 operation authorization against a **pinned, separately provisioned issuer public key**. The exact issuer, audience, operation purpose, release, run, branch, environment, source SHA and source/target digests are checked. Authorization IDs must be well formed, and expiry is limited to five minutes. Unknown fields, duplicate JSON keys, malformed signatures and wrong keys fail closed.

**Status: standalone verification library and tests only.** It is not yet called by the custody-first signer, does not authenticate transport/workload identity or provide a replay ledger for authorization IDs, and cannot confer production signing authority on its own.

## Next integration gates

1. Authenticate the isolated workload independently (approved private ingress and IAM/mTLS); callers must not set trusted issuer keys or expected build coordinates.
2. Require the authorization verifier in a private orchestrator **before** immutable custody readback and before the irreversible signing claim.
3. Store the authorization ID in a distinct, committed, append-only replay register. An unknown commit result must block signing; never retry blindly.
4. Require the existing custody signing claim and reverified immutable S3/JUnit evidence before retrieving the Ed25519 signer key.
5. Verify against disposable PostgreSQL with concurrent requests, CI, and independently authenticated Jenkins witness-producing job before any production activation.

AWS IAM, Jenkins agent authentication, Secrets Manager, customer integrations, and deployment approvals remain explicitly deferred; no live credentials or AWS resources are required to validate this offline module.
