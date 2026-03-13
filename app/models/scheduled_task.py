from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class TaskAction(str, Enum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    SNAPSHOT = "snapshot"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduledTask(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    vm_id: int = Field(foreign_key="vm.id")
    created_by: int = Field(foreign_key="user.id")

    action: TaskAction
    # For snapshot action: name of the snapshot to create
    snapshot_name: Optional[str] = Field(default=None, max_length=255)

    # When to run
    run_at: datetime

    # State
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    result_message: Optional[str] = Field(default=None, max_length=1024)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = Field(default=None)
