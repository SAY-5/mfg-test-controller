"""SQLAlchemy persistence for test-run history.

Three tables: ``device`` records the devices a run touched, ``test_run`` is one
execution of a plan, and ``step_result`` is one step within a run. The store is
used by the CLI to record runs and to look up prior runs for ``replay`` and
``--only-failed``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from mfg_test_controller.controller.sequencer import StationReport


class Base(DeclarativeBase):
    """Declarative base for the persistence models."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DeviceRow(Base):
    """A device referenced by a test run."""

    __tablename__ = "device"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_run.id"))
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))

    run: Mapped[TestRun] = relationship(back_populates="devices")


class TestRun(Base):
    """One execution of a test plan."""

    __tablename__ = "test_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_name: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    passed_steps: Mapped[int] = mapped_column(Integer, default=0)
    failed_steps: Mapped[int] = mapped_column(Integer, default=0)

    steps: Mapped[list[StepResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    devices: Mapped[list[DeviceRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class StepResult(Base):
    """One step result within a test run."""

    __tablename__ = "step_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_run.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    device: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))
    register: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean)
    measured: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str] = mapped_column(String(256))
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)

    run: Mapped[TestRun] = relationship(back_populates="steps")


class RunStore:
    """A SQLite-backed store for test runs."""

    def __init__(self, url: str = "sqlite:///test-runs.db") -> None:
        self.engine = create_engine(url)
        Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session inside a transaction."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_report(self, report: StationReport, device_kinds: Mapping[str, str]) -> int:
        """Persist a :class:`StationReport`, returning the new run id."""
        with self.session() as session:
            run = TestRun(
                plan_name=report.plan_name,
                duration_s=report.duration_s,
                total_steps=report.total,
                passed_steps=report.passed,
                failed_steps=report.failed,
            )
            for name, kind in sorted(device_kinds.items()):
                run.devices.append(DeviceRow(name=name, kind=kind))
            for ordinal, outcome in enumerate(report.outcomes):
                run.steps.append(
                    StepResult(
                        ordinal=ordinal,
                        name=outcome.name,
                        device=outcome.device,
                        action=outcome.action,
                        register=outcome.register,
                        passed=outcome.passed,
                        measured=outcome.measured,
                        detail=outcome.detail,
                        duration_s=outcome.duration_s,
                    )
                )
            session.add(run)
            session.flush()
            return run.id

    def get_run(self, run_id: int) -> TestRun | None:
        """Fetch one run with its steps eagerly loaded."""
        with self.session() as session:
            run = session.get(TestRun, run_id)
            if run is not None:
                _ = run.steps, run.devices
                session.expunge_all()
            return run

    def list_runs(self, limit: int = 20) -> list[TestRun]:
        """Return the most recent runs, newest first."""
        with self.session() as session:
            runs = session.query(TestRun).order_by(TestRun.started_at.desc()).limit(limit).all()
            session.expunge_all()
            return runs

    def register_history(
        self,
        register: str,
        station: str | None = None,
        device: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return ``(device, measured)`` pairs for ``register``, oldest first.

        Only read steps that recorded a measurement are returned. ``station``
        filters by plan name and ``device`` filters by device name; rows are
        ordered by run start time so the result is a time series.
        """
        with self.session() as session:
            query = (
                session.query(StepResult.device, StepResult.measured)
                .join(TestRun, StepResult.run_id == TestRun.id)
                .filter(StepResult.register == register)
                .filter(StepResult.action == "read")
                .filter(StepResult.measured.isnot(None))
            )
            if station is not None:
                query = query.filter(TestRun.plan_name == station)
            if device is not None:
                query = query.filter(StepResult.device == device)
            rows = query.order_by(TestRun.started_at, StepResult.run_id).all()
            return [(dev, float(measured)) for dev, measured in rows]

    def measured_registers(self, station: str | None = None) -> list[tuple[str, str]]:
        """Return the distinct ``(device, register)`` pairs with read history."""
        with self.session() as session:
            query = (
                session.query(StepResult.device, StepResult.register)
                .join(TestRun, StepResult.run_id == TestRun.id)
                .filter(StepResult.action == "read")
                .filter(StepResult.measured.isnot(None))
            )
            if station is not None:
                query = query.filter(TestRun.plan_name == station)
            pairs: set[tuple[str, str]] = set()
            for dev, reg in query.distinct().all():
                pairs.add((dev, reg))
            return sorted(pairs)
