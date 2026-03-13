"""
Scheduled Tasks Router
----------------------
Allows admins (and VM owners) to schedule one-off actions on VMs:
  - start / stop / restart
  - snapshot (create a named snapshot)

The scheduler runs as a background asyncio loop started in main.py's lifespan.
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.core.database import engine
from app.models.vm import VM
from app.models.audit import AuditLog
from app.models.scheduled_task import ScheduledTask, TaskAction, TaskStatus
from app.models.user import User, Role
from app.schemas import ScheduledTaskCreate, ScheduledTaskRead, ScheduledTaskUpdate
from app.routers.auth import get_current_active_user, get_current_admin_user, get_session
from app.services.vm_service import vm_service

router = APIRouter(prefix="/scheduled-tasks", tags=["scheduled-tasks"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _owns_vm(user: User, vm: VM) -> bool:
    return user.role == Role.ADMIN or vm.owner_id == user.id


def _log(session: Session, user_id: int, action: str, vm_id: int, details: str = None):
    log = AuditLog(
        user_id=user_id,
        action=action,
        vm_id=vm_id,
        details=details,
        timestamp=datetime.utcnow(),
    )
    session.add(log)
    session.commit()


# ── CRUD endpoints ─────────────────────────────────────────────────────────────

@router.post("", response_model=ScheduledTaskRead, status_code=status.HTTP_201_CREATED)
async def create_scheduled_task(
    task_in: ScheduledTaskCreate,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session),
):
    """Create a new scheduled task for a VM."""
    vm = session.get(VM, task_in.vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if not _owns_vm(current_user, vm):
        raise HTTPException(status_code=403, detail="Not authorised to schedule tasks for this VM")

    run_at_naive = (task_in.run_at.astimezone(timezone.utc).replace(tzinfo=None)
                    if task_in.run_at.tzinfo else task_in.run_at)
    if run_at_naive <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="run_at must be in the future")

    if task_in.action == TaskAction.SNAPSHOT and not task_in.snapshot_name:
        raise HTTPException(status_code=400, detail="snapshot_name is required for snapshot action")

    task = ScheduledTask(
        vm_id=task_in.vm_id,
        created_by=current_user.id,
        action=task_in.action,
        snapshot_name=task_in.snapshot_name,
        run_at=run_at_naive,
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    _log(session, current_user.id, f"schedule_{task.action}", vm.id,
         f"Scheduled '{task.action}' for {task.run_at.strftime('%Y-%m-%d %H:%M UTC')}")

    return task


@router.get("", response_model=List[ScheduledTaskRead])
async def list_scheduled_tasks(
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session),
):
    """List scheduled tasks.  Admins see all; users see only their own VMs' tasks."""
    if current_user.role == Role.ADMIN:
        tasks = session.exec(
            select(ScheduledTask).order_by(ScheduledTask.run_at)
        ).all()
    else:
        # Find VM ids owned by this user
        owned_vm_ids = [
            vm.id for vm in session.exec(select(VM).where(VM.owner_id == current_user.id)).all()
        ]
        if not owned_vm_ids:
            return []
        tasks = session.exec(
            select(ScheduledTask)
            .where(ScheduledTask.vm_id.in_(owned_vm_ids))
            .order_by(ScheduledTask.run_at)
        ).all()
    return tasks


@router.get("/{task_id}", response_model=ScheduledTaskRead)
async def get_scheduled_task(
    task_id: int,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session),
):
    task = session.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    vm = session.get(VM, task.vm_id)
    if not _owns_vm(current_user, vm):
        raise HTTPException(status_code=403, detail="Not authorised")
    return task


@router.put("/{task_id}", response_model=ScheduledTaskRead)
async def update_scheduled_task(
    task_id: int,
    task_update: ScheduledTaskUpdate,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session),
):
    """Reschedule a pending task (cannot modify running/completed/failed tasks)."""
    task = session.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    vm = session.get(VM, task.vm_id)
    if not _owns_vm(current_user, vm):
        raise HTTPException(status_code=403, detail="Not authorised")

    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit a task with status '{task.status}'. Only pending tasks can be modified.",
        )

    if task_update.run_at:
        run_at_u = (task_update.run_at.astimezone(timezone.utc).replace(tzinfo=None)
                    if task_update.run_at.tzinfo else task_update.run_at)
        if run_at_u <= datetime.utcnow():
            raise HTTPException(status_code=400, detail="run_at must be in the future")
        task.run_at = run_at_u

    if task_update.snapshot_name is not None:
        task.snapshot_name = task_update.snapshot_name

    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_scheduled_task(
    task_id: int,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session),
):
    """Cancel (delete) a pending scheduled task."""
    task = session.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    vm = session.get(VM, task.vm_id)
    if not _owns_vm(current_user, vm):
        raise HTTPException(status_code=403, detail="Not authorised")

    if task.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Cannot cancel a task that is currently running")

    task.status = TaskStatus.CANCELLED
    session.add(task)
    session.commit()

    _log(session, current_user.id, f"cancel_schedule_{task.action}", vm.id,
         f"Cancelled scheduled '{task.action}' that was due {task.run_at.strftime('%Y-%m-%d %H:%M UTC')}")
    return None


# ── Background scheduler loop ─────────────────────────────────────────────────

async def _execute_task(task_id: int):
    """Run a single scheduled task. Called by the scheduler loop."""
    vmx_path = task_action = task_snap = task_creator = task_vm_id = None
    error: Optional[str] = None

    try:
        # Step 1: load + mark running — copy all values inside the session
        with Session(engine) as session:
            task = session.get(ScheduledTask, task_id)
            if not task or task.status != TaskStatus.PENDING:
                return

            vm = session.get(VM, task.vm_id)
            if not vm:
                task.status = TaskStatus.FAILED
                task.result_message = "VM no longer exists"
                task.executed_at = datetime.utcnow()
                session.add(task)
                session.commit()
                return

            # Read every attribute we need while still inside the session
            vmx_path     = str(vm.vmx_path)
            task_action  = task.action
            task_snap    = str(task.snapshot_name) if task.snapshot_name else None
            task_creator = int(task.created_by)
            task_vm_id   = int(task.vm_id)

            task.status = TaskStatus.RUNNING
            task.executed_at = datetime.utcnow()
            session.add(task)
            session.commit()

        # Step 2: run the vmrun command (session closed, only plain vars used)
        if task_action == TaskAction.START:
            await run_in_threadpool(vm_service.start_vm, vmx_path)

        elif task_action == TaskAction.STOP:
            await run_in_threadpool(vm_service.stop_vm, vmx_path)

        elif task_action == TaskAction.RESTART:
            await run_in_threadpool(vm_service.restart_vm, vmx_path)

        elif task_action == TaskAction.SNAPSHOT:
            snap_name = task_snap or f"auto-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"
            await run_in_threadpool(vm_service.create_snapshot, vmx_path, snap_name)

    except Exception as exc:
        error = str(exc)
        print(f"[Scheduler] Task {task_id} failed: {error}")

    # Step 3: always write final result — even if we crashed
    if task_vm_id is None:
        return  # never got past the initial load, nothing to update
    try:
        with Session(engine) as session:
            task = session.get(ScheduledTask, task_id)
            if task:
                task.status = TaskStatus.FAILED if error else TaskStatus.COMPLETED
                task.result_message = error or "Completed successfully"
                session.add(task)
                log = AuditLog(
                    user_id=task_creator,
                    action=f"scheduled_{task_action.value}",
                    vm_id=task_vm_id,
                    details=task.result_message,
                    timestamp=datetime.utcnow(),
                )
                session.add(log)
                session.commit()
    except Exception as exc:
        print(f"[Scheduler] Failed to write result for task {task_id}: {exc}")


async def run_scheduler():
    """
    Background loop: checks every 30 seconds for tasks that are due and runs them.
    Registered in main.py lifespan via asyncio.create_task().
    """
    print("Scheduled task runner started.")
    while True:
        try:
            now = datetime.utcnow()
            with Session(engine) as session:
                due_tasks = session.exec(
                    select(ScheduledTask)
                    .where(ScheduledTask.status == TaskStatus.PENDING)
                    .where(ScheduledTask.run_at <= now)
                ).all()
                due_ids = [t.id for t in due_tasks]

            for task_id in due_ids:
                asyncio.create_task(_execute_task(task_id))

        except Exception as exc:
            print(f"[Scheduler] Error in scheduler loop: {exc}")

        await asyncio.sleep(30)
