"""queue sessions/entries and durable scheduled jobs + RLS

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20

DDL frozen from the models at this revision (scripts/dump_ddl.py).
"""

from collections.abc import Sequence

from alembic import op
from rls import enable_rls_sql, grant_dml_sql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
CREATE TABLE scheduled_jobs (
    clinic_id UUID,
    kind VARCHAR(40) NOT NULL,
    run_at TIMESTAMP WITH TIME ZONE NOT NULL,
    payload JSONB DEFAULT '{}' NOT NULL,
    dedup_key VARCHAR(160) NOT NULL,
    status VARCHAR(10) DEFAULT 'pending' NOT NULL,
    attempts SMALLINT DEFAULT '0' NOT NULL,
    max_attempts SMALLINT DEFAULT '6' NOT NULL,
    locked_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_scheduled_jobs PRIMARY KEY (id),
    CONSTRAINT ck_scheduled_jobs_status CHECK (status IN ('pending','running','done','failed','cancelled')),
    CONSTRAINT fk_scheduled_jobs_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id),
    CONSTRAINT uq_scheduled_jobs_dedup_key UNIQUE (dedup_key)
);

CREATE INDEX ix_jobs_due ON scheduled_jobs (run_at) WHERE status = 'pending';

CREATE INDEX ix_jobs_running ON scheduled_jobs (locked_at) WHERE status = 'running';

CREATE TABLE queue_sessions (
    clinic_id UUID NOT NULL,
    doctor_id UUID NOT NULL,
    session_date DATE NOT NULL,
    start_time TIME WITHOUT TIME ZONE NOT NULL,
    end_time TIME WITHOUT TIME ZONE NOT NULL,
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ends_at TIMESTAMP WITH TIME ZONE NOT NULL,
    max_tokens SMALLINT NOT NULL,
    last_token_no INTEGER DEFAULT '0' NOT NULL,
    current_entry_id UUID,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_queue_sessions PRIMARY KEY (id),
    CONSTRAINT uq_queue_sessions_clinic_id_id UNIQUE (clinic_id, id),
    CONSTRAINT uq_queue_sessions_doctor_id_session_date_start_time UNIQUE (doctor_id, session_date, start_time),
    CONSTRAINT fk_queue_sessions_clinic_id_doctor_id_doctors FOREIGN KEY(clinic_id, doctor_id) REFERENCES doctors (clinic_id, id),
    CONSTRAINT fk_queue_sessions_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id)
);

CREATE INDEX ix_queue_sessions_clinic_date ON queue_sessions (clinic_id, session_date);

CREATE TABLE queue_entries (
    clinic_id UUID NOT NULL,
    queue_session_id UUID NOT NULL,
    token_no INTEGER NOT NULL,
    kind VARCHAR(8) NOT NULL,
    status VARCHAR(10) NOT NULL,
    priority BOOLEAN DEFAULT 'false' NOT NULL,
    appointment_id UUID,
    patient_id UUID,
    phone VARCHAR(16),
    slot_start TIMESTAMP WITH TIME ZONE,
    channel VARCHAR(10) NOT NULL,
    public_code VARCHAR(32) NOT NULL,
    issued_at TIMESTAMP WITH TIME ZONE NOT NULL,
    called_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    alert_sent_at TIMESTAMP WITH TIME ZONE,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_queue_entries PRIMARY KEY (id),
    CONSTRAINT uq_queue_entries_queue_session_id_token_no UNIQUE (queue_session_id, token_no),
    CONSTRAINT fk_queue_entries_clinic_id_queue_session_id_queue_sessions FOREIGN KEY(clinic_id, queue_session_id) REFERENCES queue_sessions (clinic_id, id),
    CONSTRAINT fk_queue_entries_clinic_id_patient_id_patients FOREIGN KEY(clinic_id, patient_id) REFERENCES patients (clinic_id, id),
    CONSTRAINT ck_queue_entries_kind CHECK (kind IN ('booked','walk_in')),
    CONSTRAINT ck_queue_entries_status CHECK (status IN ('waiting', 'called', 'skipped', 'completed', 'cancelled')),
    CONSTRAINT ck_queue_entries_channel CHECK (channel IN ('dashboard','qr','whatsapp')),
    CONSTRAINT ck_queue_entries_booked_has_appt CHECK ((kind = 'booked') = (appointment_id IS NOT NULL)),
    CONSTRAINT uq_queue_entries_public_code UNIQUE (public_code)
);

CREATE INDEX ix_queue_entries_session_status ON queue_entries (queue_session_id, status);

CREATE UNIQUE INDEX uq_queue_entries_appointment ON queue_entries (appointment_id);
"""

TABLES = ["queue_sessions", "queue_entries", "scheduled_jobs"]


def upgrade() -> None:
    op.execute(DDL)
    op.execute(enable_rls_sql("queue_sessions"))
    op.execute(enable_rls_sql("queue_entries"))
    # Jobs: tenant code may enqueue for its own clinic; platform jobs (clinic_id NULL) need bypass.
    op.execute(enable_rls_sql("scheduled_jobs"))
    for t in TABLES:
        op.execute(grant_dml_sql(t))


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
