"""recall rules, treatment plans, recalls, recovery attributions; appointments.visit_type

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20

DDL frozen from the models at this revision (scripts/dump_ddl.py).
"""

from collections.abc import Sequence

from alembic import op
from rls import enable_rls_sql, grant_dml_sql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
CREATE TABLE recall_rules (
    clinic_id UUID NOT NULL,
    visit_type VARCHAR(40) NOT NULL,
    label VARCHAR(80) NOT NULL,
    delay_days INTEGER NOT NULL,
    followup_days SMALLINT[] NOT NULL,
    plan_based BOOLEAN DEFAULT 'false' NOT NULL,
    is_active BOOLEAN DEFAULT 'true' NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_recall_rules PRIMARY KEY (id),
    CONSTRAINT uq_recall_rules_clinic_id_visit_type UNIQUE (clinic_id, visit_type),
    CONSTRAINT ck_recall_rules_delay CHECK (delay_days BETWEEN 1 AND 730),
    CONSTRAINT ck_recall_rules_max_two_followups CHECK (cardinality(followup_days) <= 2),
    CONSTRAINT fk_recall_rules_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id)
);

CREATE TABLE recovery_attributions (
    clinic_id UUID NOT NULL,
    appointment_id UUID NOT NULL,
    doctor_id UUID NOT NULL,
    source VARCHAR(16) NOT NULL,
    source_ref_id UUID,
    fee_paise INTEGER NOT NULL,
    recovered_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_recovery_attributions PRIMARY KEY (id),
    CONSTRAINT ck_recovery_attributions_source CHECK (source IN ('missed_call','recall','noshow_rebook')),
    CONSTRAINT ck_recovery_attributions_fee CHECK (fee_paise >= 0),
    CONSTRAINT fk_recovery_attributions_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id),
    CONSTRAINT uq_recovery_attributions_appointment_id UNIQUE (appointment_id)
);

CREATE INDEX ix_recovery_clinic_at ON recovery_attributions (clinic_id, recovered_at);

CREATE TABLE recalls (
    clinic_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    doctor_id UUID NOT NULL,
    rule_id UUID,
    plan_id UUID,
    source_appointment_id UUID,
    visit_type VARCHAR(40),
    label VARCHAR(80) NOT NULL,
    due_date DATE NOT NULL,
    followup_days SMALLINT[] NOT NULL,
    status VARCHAR(10) DEFAULT 'scheduled' NOT NULL,
    sends SMALLINT DEFAULT '0' NOT NULL,
    first_sent_at TIMESTAMP WITH TIME ZONE,
    last_sent_at TIMESTAMP WITH TIME ZONE,
    booked_appointment_id UUID,
    closed_reason VARCHAR(40),
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_recalls PRIMARY KEY (id),
    CONSTRAINT fk_recalls_clinic_id_patient_id_patients FOREIGN KEY(clinic_id, patient_id) REFERENCES patients (clinic_id, id),
    CONSTRAINT fk_recalls_clinic_id_doctor_id_doctors FOREIGN KEY(clinic_id, doctor_id) REFERENCES doctors (clinic_id, id),
    CONSTRAINT ck_recalls_status CHECK (status IN ('scheduled', 'sent', 'booked', 'declined', 'lapsed', 'cancelled', 'skipped')),
    CONSTRAINT ck_recalls_sends CHECK (sends BETWEEN 0 AND 3)
);

CREATE INDEX ix_recalls_clinic_status_due ON recalls (clinic_id, status, due_date);

CREATE UNIQUE INDEX uq_recall_source_appt ON recalls (source_appointment_id) WHERE source_appointment_id IS NOT NULL;

CREATE TABLE treatment_plans (
    clinic_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    doctor_id UUID NOT NULL,
    visit_type VARCHAR(40) NOT NULL,
    sessions_planned SMALLINT NOT NULL,
    sessions_done SMALLINT DEFAULT '0' NOT NULL,
    interval_days SMALLINT NOT NULL,
    status VARCHAR(10) DEFAULT 'active' NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_treatment_plans PRIMARY KEY (id),
    CONSTRAINT uq_treatment_plans_clinic_id_id UNIQUE (clinic_id, id),
    CONSTRAINT fk_treatment_plans_clinic_id_patient_id_patients FOREIGN KEY(clinic_id, patient_id) REFERENCES patients (clinic_id, id),
    CONSTRAINT fk_treatment_plans_clinic_id_doctor_id_doctors FOREIGN KEY(clinic_id, doctor_id) REFERENCES doctors (clinic_id, id),
    CONSTRAINT ck_treatment_plans_planned CHECK (sessions_planned BETWEEN 1 AND 100),
    CONSTRAINT ck_treatment_plans_done CHECK (sessions_done >= 0),
    CONSTRAINT ck_treatment_plans_interval CHECK (interval_days BETWEEN 1 AND 60),
    CONSTRAINT ck_treatment_plans_status CHECK (status IN ('active','completed','dropped','cancelled'))
);

CREATE UNIQUE INDEX uq_active_plan ON treatment_plans (patient_id, doctor_id) WHERE status = 'active';
"""

TABLES = ["recall_rules", "treatment_plans", "recalls", "recovery_attributions"]


def upgrade() -> None:
    op.execute("ALTER TABLE appointments ADD COLUMN visit_type VARCHAR(40)")
    op.execute(
        "ALTER TABLE outbox_messages ADD COLUMN seq BIGINT GENERATED BY DEFAULT AS IDENTITY;"
        "ALTER TABLE outbox_messages ADD CONSTRAINT uq_outbox_messages_seq UNIQUE (seq);"
        "ALTER TABLE scheduled_jobs ADD COLUMN seq BIGINT GENERATED BY DEFAULT AS IDENTITY;"
        "ALTER TABLE scheduled_jobs ADD CONSTRAINT uq_scheduled_jobs_seq UNIQUE (seq);"
    )
    op.execute(DDL)
    for t in TABLES:
        op.execute(enable_rls_sql(t))
        op.execute(grant_dml_sql(t))


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS visit_type")
    op.execute("ALTER TABLE outbox_messages DROP COLUMN IF EXISTS seq")
    op.execute("ALTER TABLE scheduled_jobs DROP COLUMN IF EXISTS seq")
