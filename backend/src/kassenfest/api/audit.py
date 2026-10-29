"""The auditor agent from the API: after every upload (`api.inbox`) and on demand for one bill.

Which bills it is attacking right now lives in memory, like the inbox's runs; what it
concluded is stored (`db.Audit`) and served with each claim (`api.live`).
"""

import asyncio
from collections.abc import Collection

from fastapi import APIRouter, HTTPException

from kassenfest.agents.auditor import AuditSummary, audit_month, clean, due
from kassenfest.api.deps import Deps, RunDeps
from kassenfest.api.models import AuditStatus
from kassenfest.pipeline.month import evaluate_month

router = APIRouter(prefix="/api")


class Auditing:
    def __init__(self) -> None:
        self.running: set[str] = set()
        self.tasks: set[asyncio.Task[AuditSummary]] = set()
        self._lock = asyncio.Lock()

    async def run(self, deps: Deps, claim_ids: Collection[str] | None = None) -> AuditSummary:
        """Attack every clean bill that is due (or just these), one pass at a time."""
        if deps.records is None:
            return AuditSummary()
        async with self._lock:  # a bill is never attacked twice at once
            month = evaluate_month(deps.engine, deps.records, deps.records.month)
            dossiers = due(month, deps.engine, deps.client.settings.as_of(), claim_ids)
            ids = {d.bill.claim.id for d in dossiers}
            self.running |= ids
            try:
                return await audit_month(
                    deps.client, deps.engine, deps.blobs, deps.records, dossiers=dossiers
                )
            finally:
                self.running -= ids

    def start(self, deps: Deps, claim_ids: Collection[str]) -> None:
        """Run in the background; the bills show as running from now on."""
        ids = set(claim_ids)
        self.running |= ids
        task = asyncio.create_task(self.run(deps, ids))
        self.tasks.add(task)

        def finished(t: asyncio.Task[AuditSummary]) -> None:
            self.tasks.discard(t)
            self.running -= ids

        task.add_done_callback(finished)


auditing = Auditing()


@router.post("/claims/{claim_id}/audit", status_code=202)
async def audit_claim(claim_id: str, deps: RunDeps) -> AuditStatus:
    """Let the auditor attack a clean bill that has no audit of its current state yet."""
    if deps.records is None:
        raise HTTPException(404, "No records: the pipeline has no claims")
    month = evaluate_month(deps.engine, deps.records, deps.records.month)
    claim = month.claims.get(claim_id)
    if claim is None:
        raise HTTPException(404, f"No pipeline claim {claim_id}")
    if not clean(month, claim):
        raise HTTPException(409, "The rules already object to this bill: fix it first")
    if claim_id in auditing.running:
        return AuditStatus(state="running")
    if not due(month, deps.engine, deps.client.settings.as_of(), [claim_id]):
        return AuditStatus(state="done")  # nothing new for the auditor to see
    auditing.start(deps, [claim_id])
    return AuditStatus(state="running")
