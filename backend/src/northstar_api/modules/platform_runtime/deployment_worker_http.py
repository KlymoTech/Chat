"""Isolated, opt-in deployment-worker HTTP contract.

IMPORTANT: This is NOT registered by the public northstar_api.main application.
Deploy only in a separate workload via a private Unix socket or certified
mTLS ingress with network policy; enable only after security qualification.
The API has no cloud mutation endpoint, arbitrary plan input or key-issuance API.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from .deployment_leases import DeploymentClaim
from .deployment_machine_identity import MachineAuthenticationError
from .deployment_worker_audit import DeploymentAuditBlocked
from .deployment_worker_operations import DeploymentWorkerOperations

T = TypeVar("T")


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimBody(_StrictBody):
    change_id: UUID


class LeaseBody(_StrictBody):
    change_id: UUID
    lease_token: UUID
    owner: str = Field(min_length=3, max_length=160)
    expires_at: datetime
    environment: str = Field(min_length=1, max_length=32)

    def as_claim(self) -> DeploymentClaim:
        return DeploymentClaim(
            self.change_id, self.lease_token, self.owner,
            self.expires_at, self.environment,
        )


class LeaseOperationBody(_StrictBody):
    claim: LeaseBody


class StepOperationBody(LeaseOperationBody):
    index: int = Field(ge=0)


class StepVerifyBody(StepOperationBody):
    signed_attestation: str = Field(min_length=10, max_length=8192)


class StepUnknownBody(StepOperationBody):
    reason: str = Field(min_length=5, max_length=500)


def create_deployment_worker_app(
    operations: DeploymentWorkerOperations,
    *,
    private_ingress_enabled: bool = False,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    """Create a standalone, OFF-by-default ASGI app (never public-router mounted)."""
    if operations is None:
        raise ValueError("machine-authorized operations are required")

    app = FastAPI(
        title="Northstar private deployment worker",
        docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=lifespan,
    )

    def require_machine_token(
        authorization: str | None = Header(default=None),
    ) -> str:
        # This flag is NOT a network control; external deployment must enforce
        # private ingress or mTLS independently. Fail closed if not provisioned.
        if not private_ingress_enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail="private worker ingress not enabled")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="machine authorization required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization[7:]
        if not token or any(c.isspace() for c in token) or len(token) > 8192:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="invalid machine authorization")
        return token

    async def apply(call: Callable[[], Awaitable[T]]) -> T:
        try:
            return await call()
        except MachineAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="machine authorization denied",
            ) from exc
        except DeploymentAuditBlocked as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="deployment requires reconciliation",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid deployment operation",
            ) from exc
        except Exception as exc:
            # Never expose SQL, identity, attestation, or implementation errors.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="deployment operation could not be completed",
            ) from exc

    @app.post("/internal/deployment/claims", status_code=200)
    async def claim(body: ClaimBody, token: str = Depends(require_machine_token)) -> dict:
        result = await apply(lambda: operations.claim(token, body.change_id))
        if result is None:
            raise HTTPException(status_code=409, detail="deployment claim not available")
        return {"claim": {
            "change_id": str(result.change_id),
            "lease_token": str(result.lease_token),
            "owner": result.owner,
            "expires_at": result.expires_at.isoformat(),
            "environment": result.environment,
        }}

    @app.post("/internal/deployment/leases/renew")
    async def renew(body: LeaseOperationBody, token: str = Depends(require_machine_token)) -> dict:
        accepted = await apply(lambda: operations.renew(token, body.claim.as_claim()))
        if not accepted:
            raise HTTPException(status_code=409, detail="deployment lease not renewable")
        return {"accepted": True}

    @app.post("/internal/deployment/steps/begin")
    async def begin(body: StepOperationBody, token: str = Depends(require_machine_token)) -> dict:
        step = await apply(lambda: operations.begin_step(
            token, body.claim.as_claim(), body.index,
        ))
        if step is None:
            raise HTTPException(status_code=409, detail="deployment step cannot begin")
        return {
            "change_id": str(step.change_id),
            "lease_token": str(step.lease_token),
            "step_index": step.step_index,
            "step_name": step.step_name,
        }

    @app.post("/internal/deployment/steps/verify")
    async def verify(body: StepVerifyBody, token: str = Depends(require_machine_token)) -> dict:
        accepted = await apply(lambda: operations.verify_step(
            token, body.claim.as_claim(), body.index,
            signed_attestation=body.signed_attestation,
        ))
        if not accepted:
            raise HTTPException(status_code=409, detail="deployment step not verified")
        return {"verified": True}

    @app.post("/internal/deployment/steps/unknown")
    async def mark_unknown(
        body: StepUnknownBody, token: str = Depends(require_machine_token),
    ) -> dict:
        accepted = await apply(lambda: operations.mark_unknown(
            token, body.claim.as_claim(), body.index, reason=body.reason,
        ))
        if not accepted:
            raise HTTPException(status_code=409, detail="deployment step not marked unknown")
        return {"requires_reconciliation": True}

    @app.post("/internal/deployment/leases/close")
    async def close(body: LeaseOperationBody, token: str = Depends(require_machine_token)) -> dict:
        accepted = await apply(lambda: operations.close(token, body.claim.as_claim()))
        if not accepted:
            raise HTTPException(status_code=409, detail="deployment lease cannot close")
        return {"closed": True}

    return app
