"""The fixer agent from the API: after every upload (`api.inbox`) and on demand for the month.

Which patients it is drafting for right now lives in memory, like the auditor's runs; what it
filed is stored (`db.Fix`) and served as the month's actions (`api.live`).
"""

import asyncio
from collections.abc import Collection

from fastapi import APIRouter, HTTPException

from kassenfest.agents.fixer import FixSummary, due, fix_month
from kassenfest.api.deps import Deps, RunDeps
from kassenfest.api.models import FixerStatus
from kassenfest.pipeline.month import evaluate_month

router = APIRouter(prefix="/api")


class Fixing:
    def __init__(self) -> None:
        self.running: set[str] = set()
        self.tasks: set[asyncio.Task[FixSummary]] = set()
        self._lock = asyncio.Lock()

    async def run(self, deps: Deps, patient_ids: Collection[str] | None = None) -> FixSummary:
        """Draft for every patient who is due (or just these), one pass at a time."""
        if deps.records is None:
            return FixSummary()
        async with self._lock:  # a patient is never drafted twice at once
            month = evaluate_month(deps.engine, deps.records, deps.records.month)
            pending = due(month, deps.engine, deps.client.settings.as_of(), patient_ids)
            ids = {b.patient_id for b in pending}
            self.running |= ids
            try:
                return await fix_month(deps.client, deps.engine, deps.records, pending=pending)
            finally:
                self.running -= ids

    def start(self, deps: Deps, patient_ids: Collection[str]) -> None:
        """Run in the background; the patients show as running from now on."""
        ids = set(patient_ids)
        self.running |= ids
        task = asyncio.create_task(self.run(deps, ids))
        self.tasks.add(task)

        def finished(t: asyncio.Task[FixSummary]) -> None:
            self.tasks.discard(t)
            self.running -= ids

        task.add_done_callback(finished)


fixing = Fixing()


@router.post("/months/{month}/actions/draft", status_code=202)
async def draft_actions(month: str, deps: RunDeps) -> FixerStatus:
    """Let the fixer draft the actions of every patient whose findings have no current draft."""
    if deps.records is None:
        raise HTTPException(404, "No records: the pipeline has no claims")
    if month != deps.records.month:
        raise HTTPException(404, f"No bills for {month}: the month on file is {deps.records.month}")
    evaluated = evaluate_month(deps.engine, deps.records, month)
    pending = due(evaluated, deps.engine, deps.client.settings.as_of())
    names = [b.case.patient.name for b in pending]
    if not pending:
        return FixerStatus(state="done")
    fixing.start(deps, [b.patient_id for b in pending])
    return FixerStatus(state="running", running=names)
