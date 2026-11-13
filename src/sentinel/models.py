"""SQLAlchemy models and session setup for the Sentinel CCTV anomaly agent.

Implements local goal L1: cameras, events, incidents and entities tables plus
the session factory. The database URL is taken from ``SENTINEL_DB_URL`` so the
test suite can point at a throwaway SQLite file.
"""
from __future__ import annotations

import datetime
import os

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, index=True)
    rtsp_url = Column(String)
    enabled = Column(Boolean, default=True)
    zones = Column(JSON, nullable=True)
    schedule = Column(JSON, nullable=True)
    sensitivity = Column(Float, default=0.5)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"))
    started_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    ended_at = Column(DateTime, nullable=True)
    tier0_signal = Column(JSON, nullable=True)
    burst_paths = Column(JSON, nullable=True)
    severity = Column(Integer, default=0)
    anomaly_type = Column(String, nullable=True)
    vlm_json = Column(JSON, nullable=True)
    confidence = Column(Float, default=0.0)
    status = Column(String, default="pending")
    alert_sent_at = Column(DateTime, nullable=True)
    owner_feedback = Column(String, nullable=True)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"))
    window_start = Column(DateTime)
    window_end = Column(DateTime)
    event_ids = Column(JSON)
    max_severity = Column(Integer)
    alert_sent_at = Column(DateTime, nullable=True)


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String)
    label = Column(String)
    face_embedding_placeholder = Column(String, nullable=True)
    whitelisted = Column(Boolean, default=False)


DATABASE_URL = os.environ.get("SENTINEL_DB_URL", "sqlite:///sentinel.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(bind=engine)