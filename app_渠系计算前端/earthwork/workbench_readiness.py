"""Project the adopted scope into the next action and the ranges it can measure."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .section_preparation import PreparationRow, PreparationSnapshot, PreparationTask


_CALCULATION_ACTIONS = frozenset({"calculate", "partial_bore", "partial_ready"})


@dataclass(frozen=True, slots=True)
class ReadinessRow:
    row: PreparationRow
    ready_spans: tuple[str, ...]
    pending_spans: tuple[str, ...]
    excluded_spans: tuple[str, ...]
    terrain_spans: tuple[str, ...]
    bore_spans: tuple[str, ...]
    blocked_by_task: bool

    @property
    def status(self) -> str:
        if self.ready_spans:
            return "partial" if self.pending_spans or self.excluded_spans else "ready"
        return "pending" if self.pending_spans else "excluded"

    @property
    def awaiting_terrain(self) -> bool:
        return bool(self.terrain_spans)

    @property
    def ready_parts(self) -> int:
        return len(self.ready_spans)

    @property
    def pending_parts(self) -> int:
        return len(self.pending_spans)

    @property
    def excluded_parts(self) -> int:
        return len(self.excluded_spans)


@dataclass(frozen=True, slots=True)
class WorkbenchReadiness:
    snapshot: PreparationSnapshot
    rows: tuple[ReadinessRow, ...]
    action: str
    terrain_ready: bool
    terrain_action: str | None
    priority_task: PreparationTask | None
    design_stale: bool
    has_draft: bool

    @property
    def has_design(self) -> bool:
        return bool(self.rows)

    @property
    def can_calculate(self) -> bool:
        return self.action in _CALCULATION_ACTIONS

    @property
    def ready_count(self) -> int:
        return sum(bool(entry.ready_spans) for entry in self.rows)

    @property
    def pending_count(self) -> int:
        return sum(bool(entry.pending_spans) for entry in self.rows)

    @property
    def excluded_count(self) -> int:
        return sum(entry.status == "excluded" for entry in self.rows)


def _readiness_row(row: PreparationRow, *, terrain_ready: bool, hold_bores_for_terrain: bool,
                   blocking_task: bool, design_stale: bool) -> ReadinessRow:
    ready, pending, excluded, terrain, bores = [], [], [], [], []
    blocked_by_task = False
    if row.parts:
        ranges = ((part.span, part.status, part.is_bore, part.requires_terrain and not part.is_bore)
                  for part in row.parts)
    else:
        # Legacy bore records are separate from the active assets. Pending
        # connection candidates also have no parts until their settings are applied.
        ranges = ((row.span, row.status, row.is_bore, False),)
    for span, status, bore, requires_terrain in ranges:
        if status == "excluded":
            excluded.append(span)
            continue
        waiting_for_terrain = not terrain_ready and (requires_terrain or bore and hold_bores_for_terrain)
        if waiting_for_terrain:
            terrain.append(span)
        if status == "pending" or waiting_for_terrain or design_stale:
            pending.append(span)
        elif blocking_task:
            pending.append(span)
            blocked_by_task = True
        else:
            ready.append(span)
            if bore:
                bores.append(span)
    return ReadinessRow(row, tuple(ready), tuple(pending), tuple(excluded), tuple(terrain),
                        tuple(bores), blocked_by_task)


def workbench_readiness(snapshot: PreparationSnapshot, *, terrain_ready: bool, terrain_failed: bool = False,
                        has_draft: bool = False, design_stale: bool = False) -> WorkbenchReadiness:
    """Reuse preparation findings and the calculator's partial-scope policy.

    The snapshot already validates bore diameter and length and marks disabled
    ranges. Terrain readiness is separate from construction-data readiness.
    """
    needs_terrain = any(part.status != "excluded" and part.requires_terrain and not part.is_bore
                        for row in snapshot.rows for part in row.parts)
    terrain_action = ("retry_terrain" if terrain_failed else "terrain") if needs_terrain and not terrain_ready else None
    task = None if design_stale else snapshot.priority_task
    if terrain_action and task and task.action not in {"source", "bore_source"}:
        task = None
    rows = tuple(_readiness_row(row, terrain_ready=terrain_ready, blocking_task=task is not None,
                                hold_bores_for_terrain=needs_terrain and not snapshot.allow_partial,
                                design_stale=design_stale)
                 for row in snapshot.rows)
    available = tuple(entry for entry in rows if entry.ready_spans)
    pending = any(entry.pending_spans for entry in rows)
    if has_draft:
        action = "draft"
    elif not rows or design_stale:
        action = "design"
    elif task is not None:
        action = "task"
    elif available:
        if not pending:
            action = "calculate"
        elif all(entry.ready_spans == entry.bore_spans for entry in available):
            action = "partial_bore"
        else:
            action = "partial_ready"
    elif terrain_action:
        action = terrain_action
    elif any(part.editable and not part.enabled for row in snapshot.rows for part in row.parts):
        action = "scope"
    else:
        action = "design"
    return WorkbenchReadiness(snapshot, rows, action, terrain_ready, terrain_action, task, design_stale, has_draft)
