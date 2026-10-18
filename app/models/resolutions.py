"""Approval records, simulated payments, and append-only workflow events."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.entities import utcnow


class CaseReview(Base):
    __tablename__ = "case_reviews"
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), primary_key=True)
    reviewer_id: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(2000))
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SimulatedRefund(Base):
    __tablename__ = "simulated_refunds"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseEvent(Base):
    __tablename__ = "case_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
