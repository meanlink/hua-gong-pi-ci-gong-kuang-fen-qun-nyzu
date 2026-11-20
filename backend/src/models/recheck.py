from sqlalchemy import String, JSON, Double, ForeignKey, BigInteger, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Recheck(Base):
    __tablename__ = 'rechecks'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    error_pct: Mapped[float] = mapped_column(Double)
    trials_total: Mapped[int] = mapped_column(Integer)
    base_seed: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
class RecheckTrial(Base):
    __tablename__ = 'recheck_trials'
    __table_args__ = (UniqueConstraint('recheck_id', 'trial_index', name='uq_recheck_trial'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    recheck_id: Mapped[int] = mapped_column(ForeignKey('rechecks.id'))
    trial_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='running')
    switched: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(String(500), default='')
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
