"""missed calls; clinic Exotel number and plan

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-20

DDL frozen from the models at this revision (scripts/dump_ddl.py).
"""

from collections.abc import Sequence

from alembic import op
from rls import enable_rls_sql, grant_dml_sql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
CREATE TABLE missed_calls (
    clinic_id UUID NOT NULL,
    caller_phone VARCHAR(16) NOT NULL,
    first_call_sid VARCHAR(64),
    called_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_called_at TIMESTAMP WITH TIME ZONE NOT NULL,
    repeat_count SMALLINT DEFAULT '0' NOT NULL,
    status VARCHAR(16) DEFAULT 'pending' NOT NULL,
    source VARCHAR(10) DEFAULT 'exotel' NOT NULL,
    offer_sent_at TIMESTAMP WITH TIME ZONE,
    appointment_id UUID,
    resolution VARCHAR(20),
    resolved_by UUID,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_missed_calls PRIMARY KEY (id),
    CONSTRAINT ck_missed_calls_status CHECK (status IN ('pending', 'recovered', 'call_back_needed', 'resolved')),
    CONSTRAINT ck_missed_calls_source CHECK (source IN ('exotel','manual')),
    CONSTRAINT fk_missed_calls_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id)
);

CREATE INDEX ix_missed_calls_clinic_called ON missed_calls (clinic_id, called_at);

CREATE INDEX ix_missed_calls_clinic_phone ON missed_calls (clinic_id, caller_phone, last_called_at);
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE clinics ADD COLUMN exotel_number VARCHAR(16);"
        "ALTER TABLE clinics ADD CONSTRAINT uq_clinics_exotel_number UNIQUE (exotel_number);"
        "ALTER TABLE clinics ADD COLUMN plan VARCHAR(10) DEFAULT 'pilot' NOT NULL;"
        "ALTER TABLE clinics ADD CONSTRAINT ck_clinics_plan CHECK (plan IN ('pilot','basic','pro'));"
    )
    op.execute(DDL)
    op.execute(enable_rls_sql("missed_calls"))
    op.execute(grant_dml_sql("missed_calls"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS missed_calls CASCADE")
    op.execute(
        "ALTER TABLE clinics DROP CONSTRAINT IF EXISTS ck_clinics_plan;"
        "ALTER TABLE clinics DROP COLUMN IF EXISTS plan;"
        "ALTER TABLE clinics DROP COLUMN IF EXISTS exotel_number;"
    )
