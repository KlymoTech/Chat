"""Safe internal-only website journey contracts.

Adapted from the existing website/src/lib/automation-contract.ts design, but
implemented in the canonical FastAPI runtime. No provider URLs, arbitrary
expressions, customer messages, dynamic code or database commands.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeType = Literal["trigger", "condition", "delay", "task", "exit"]
SourceCategory = Literal["form", "subscription"]
InternalAction = Literal["review_lead", "notify_owner"]


class AutomationNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    type: NodeType
    event: Literal["lead_accepted", "subscription_confirmed"] | None = None
    field: Literal["marketing_consent", "source_category"] | None = None
    equals: str | None = Field(default=None, max_length=20)
    minutes: int | None = Field(default=None, ge=1, le=10080)
    action: InternalAction | None = None
    next: str | None = Field(default=None, max_length=40)
    on_true: str | None = Field(default=None, max_length=40)
    on_false: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def valid_shape(self) -> "AutomationNode":
        values = {
            "event": self.event, "field": self.field, "equals": self.equals,
            "minutes": self.minutes, "action": self.action, "next": self.next,
            "on_true": self.on_true, "on_false": self.on_false,
        }
        allowed: dict[str, set[str]] = {
            "trigger": {"event", "next"},
            "condition": {"field", "equals", "on_true", "on_false"},
            "delay": {"minutes", "next"},
            "task": {"action", "next"},
            "exit": set(),
        }
        fields = allowed[self.type]
        if any((v is None) == (k in fields) for k, v in values.items()):
            raise ValueError("Automation node fields do not match its type")
        if self.type == "condition":
            options = {"marketing_consent": {"true", "false"},
                       "source_category": {"form", "subscription"}}
            if self.equals not in options[self.field or "marketing_consent"]:
                raise ValueError("Invalid allowlisted condition value")
        return self

    def successors(self) -> tuple[str, ...]:
        if self.type == "condition":
            return (self.on_true or "", self.on_false or "")
        return (self.next,) if self.next else ()


class AutomationGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(min_length=1, max_length=120)
    nodes: tuple[AutomationNode, ...] = Field(min_length=2, max_length=30)

    @model_validator(mode="after")
    def graph_is_bounded_acyclic_and_complete(self) -> "AutomationGraph":
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Automation node IDs must be unique")
        by_id = {node.id: node for node in self.nodes}
        starts = [node for node in self.nodes if node.type == "trigger"]
        if len(starts) != 1 or not any(node.type == "exit" for node in self.nodes):
            raise ValueError("Exactly one trigger and at least one exit are required")
        stack: set[str] = set()
        visited: set[str] = set()

        def visit(identifier: str) -> None:
            if identifier not in by_id:
                raise ValueError("Automation target does not exist")
            if identifier in stack:
                raise ValueError("Automation cycles are not permitted")
            if identifier in visited:
                return
            stack.add(identifier)
            for successor in by_id[identifier].successors():
                visit(successor)
            stack.remove(identifier)
            visited.add(identifier)

        visit(starts[0].id)
        if len(visited) != len(ids):
            raise ValueError("Automation contains unreachable nodes")
        return self

    def first_node(self) -> AutomationNode:
        return next(node for node in self.nodes if node.type == "trigger")

    def by_id(self, identifier: str) -> AutomationNode:
        return next(node for node in self.nodes if node.id == identifier)


class AutomationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=120)
    document: AutomationGraph


class AutomationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    document: AutomationGraph


class AutomationVersionGuard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class AutomationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_category: SourceCategory
    marketing_consent: bool = False
    at: datetime | None = None


class SimulationStep(BaseModel):
    node_id: str
    type: NodeType
    result: Literal["advanced", "waiting", "task", "completed"]
    at: datetime
    task: InternalAction | None = None
    decision: str | None = None


def plan_step(
    graph: AutomationGraph,
    node_id: str,
    *,
    source_category: SourceCategory,
    marketing_consent: bool,
    at: datetime,
) -> tuple[str | None, datetime, InternalAction | None, str | None]:
    """Pure transition; the durable worker owns DB locking and notifications."""
    node = graph.by_id(node_id)
    if node.type == "exit":
        return None, at, None, None
    if node.type == "condition":
        actual = str(marketing_consent).lower() if node.field == "marketing_consent" else source_category
        matched = actual == node.equals
        return (node.on_true if matched else node.on_false), at, None, (
            "matched" if matched else "not_matched"
        )
    if node.type == "delay":
        return node.next, at + timedelta(minutes=node.minutes or 0), None, None
    if node.type == "task":
        return node.next, at, node.action, None
    return node.next, at, None, None


def simulate(graph: AutomationGraph, fixture: AutomationFixture) -> list[SimulationStep]:
    """Bounded synthetic preview. No lead, provider or customer mutation."""
    clock = fixture.at or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    identifier: str | None = graph.first_node().id
    result: list[SimulationStep] = []
    while identifier is not None and len(result) < 60:
        node = graph.by_id(identifier)
        nxt, due, task, decision = plan_step(
            graph, identifier, source_category=fixture.source_category,
            marketing_consent=fixture.marketing_consent, at=clock,
        )
        result.append(SimulationStep(
            node_id=identifier, type=node.type,
            result=("completed" if node.type == "exit" else
                    "waiting" if node.type == "delay" else
                    "task" if task is not None else "advanced"),
            at=clock, task=task, decision=decision,
        ))
        identifier, clock = nxt, due
    return result
