from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from ulid import ULID


def new_id() -> str:
    return str(ULID())


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String, unique=True)
    path: Mapped[str] = mapped_column(String)
    kg_status: Mapped[str] = mapped_column(String, default="none")
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class Pack(Base):
    __tablename__ = "packs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String, unique=True)
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"))
    playbook_ref: Mapped[str] = mapped_column(String)
    pack_version_pin: Mapped[str] = mapped_column(String, default="local")
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")
    created_by: Mapped[str] = mapped_column(String, default="cli")
    token_budget: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)


class WorkUnit(Base):
    __tablename__ = "work_units"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"))
    step_id: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)  # task|gate|human_task|session|convoy
    status: Mapped[str] = mapped_column(String, default="open")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    owner_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    convoy_id: Mapped[str | None] = mapped_column(String, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class UnitDep(Base):
    __tablename__ = "unit_deps"
    unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"), primary_key=True)
    needs_unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"), primary_key=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"))
    work_unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"))
    kind: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    produced_by_role: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    schema_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class Gate(Base):
    __tablename__ = "gates"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    work_unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"))
    artifact_id: Mapped[str | None] = mapped_column(String, ForeignKey("artifacts.id"), nullable=True)
    gate_type: Mapped[str] = mapped_column(String)  # human|agent|derived
    decision: Mapped[str] = mapped_column(String, default="pending")  # pending|approved|rejected
    feedback_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    work_unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"))
    driver: Mapped[str] = mapped_column(String)
    provider_session_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="intent")
    started_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ended_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    __tablename__ = "events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"))
    unit_id: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class Memory(Base):
    __tablename__ = "memory"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    pack_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[str] = mapped_column(String)  # pack|project|role
    kind: Mapped[str] = mapped_column(String)  # lesson|pattern|pitfall
    title: Mapped[str] = mapped_column(String)
    body_md: Mapped[str] = mapped_column(String)
    source_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
