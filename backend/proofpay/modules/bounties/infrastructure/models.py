"""SQLAlchemy models of the bounties module (schema `bounty`)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from proofpay.modules.bounties.domain.entities import (
    BountyStatus,
    ClaimStatus,
    SolverKind,
)
from proofpay.shared.db.base import Base

SCHEMA = "bounty"


def _in_list(column: str, values: type[BountyStatus | ClaimStatus | SolverKind]) -> str:
    """SQL `column IN (...)` over the values of an enum."""
    return f"{column} IN ({', '.join(repr(member.value) for member in values)})"


class BountyRow(Base):
    __tablename__ = "bounties"
    __table_args__ = (
        CheckConstraint(_in_list("status", BountyStatus), name="status"),
        CheckConstraint("amount > 0", name="amount_positive"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    repo_owner: Mapped[str] = mapped_column(String(100))
    repo_name: Mapped[str] = mapped_column(String(100))
    issue_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    done_when: Mapped[str] = mapped_column(Text)
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), index=True)
    funder_key_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    auth_id: Mapped[str | None] = mapped_column(String(64))
    auth_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    capture_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))


class ClaimRow(Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(_in_list("status", ClaimStatus), name="status"),
        CheckConstraint(_in_list("solver_kind", SolverKind), name="solver_kind"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    bounty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.bounties.id"), index=True
    )
    solver_name: Mapped[str] = mapped_column(String(100))
    solver_kind: Mapped[str] = mapped_column(String(16))
    paypal_email: Mapped[str] = mapped_column(String(254))
    pr_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    verdict: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payout_batch_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_bounty_id_id", "bounty_id", "id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.bounties.id"))
    at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    kind: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB)
