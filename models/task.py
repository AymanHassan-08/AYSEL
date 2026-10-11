"""Task persistence tables.

Notes vs. the original design doc:
- Timestamps default to timezone-aware UTC (datetime.utcnow is deprecated).
- Status enum is stored as VARCHAR via native_enum=False for SQLite portability.
- TaskStatus reuses the wire enum from schemas.a2a so storage and protocol
  can never drift apart.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from models.base import Base
from schemas.a2a import TaskState

# Storage-level status: same values as the A2A wire protocol.
TaskStatus = TaskState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskORM(Base):
    __tablename__ = "a2a_tasks"

    id = Column(String(64), primary_key=True)  # UUIDv4
    session_id = Column(String(64), nullable=False, index=True)
    status = Column(
        SQLEnum(TaskStatus, values_callable=lambda e: [s.value for s in e], native_enum=False),
        default=TaskStatus.SUBMITTED,
        nullable=False,
    )

    # A2A protocol fields
    system_instruction = Column(Text, nullable=True)
    # SQLAlchemy reserves `.metadata` on declarative classes, so the Python
    # attribute is `metadata_` while the DB column keeps the name "metadata".
    metadata_ = Column("metadata", JSON, default=dict)

    # Timestamps (timezone-aware UTC)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    messages = relationship(
        "MessageORM",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="MessageORM.id",
    )
    artifacts = relationship(
        "ArtifactORM",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ArtifactORM.id",
    )


class MessageRole:
    USER = "user"
    AGENT = "agent"


class MessageORM(Base):
    __tablename__ = "a2a_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), ForeignKey("a2a_tasks.id"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    parts = Column(JSON, nullable=False)  # list[Part] as JSON
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    task = relationship("TaskORM", back_populates="messages")


class ArtifactORM(Base):
    __tablename__ = "a2a_artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), ForeignKey("a2a_tasks.id"), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    parts = Column(JSON, nullable=False)  # list[Part] as JSON
    index = Column(Integer, nullable=True)  # for appendable artifacts
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    task = relationship("TaskORM", back_populates="artifacts")
