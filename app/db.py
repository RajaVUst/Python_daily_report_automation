"""Application database (separate from the Oracle source). SQLite by default."""
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import APP_DB_URL

_is_sqlite = APP_DB_URL.startswith("sqlite")
engine = create_engine(
    APP_DB_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(300), nullable=False)


class JobState(Base):
    """Whether the schedule is switched on (survives restarts)."""
    __tablename__ = "job_state"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    enabled = Column(Boolean, default=False, nullable=False)


class JobRun(Base):
    __tablename__ = "job_runs"
    id = Column(Integer, primary_key=True)
    job_name = Column(String(100), nullable=False)
    trigger = Column(String(20), nullable=False)  # scheduled | manual
    status = Column(String(20), nullable=False)  # queued|running|success|failed|killed
    pid = Column(Integer)
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime)
    report_path = Column(String(500))
    data_path = Column(String(500))
    results_json = Column(Text)
    llm_summary = Column(Text)
    email_status = Column(Text)
    error = Column(Text)


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
