"""initial schema: tenancy, auth, scheduling, patients, booking, audit + RLS

Revision ID: 0001
Revises:
Create Date: 2026-11-20

DDL frozen from the models at this revision (scripts/dump_ddl.py) so later model changes never
alter what this revision creates.
"""

from collections.abc import Sequence

from alembic import op
from rls import DROP_FUNCTIONS_SQL, FUNCTIONS_SQL, enable_rls_sql, grant_dml_sql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
CREATE TABLE audit_log (
    clinic_id UUID,
    actor_type VARCHAR(12) NOT NULL,
    actor_id UUID,
    channel VARCHAR(12) NOT NULL,
    action VARCHAR(60) NOT NULL,
    entity_type VARCHAR(40) NOT NULL,
    entity_id VARCHAR(64),
    before JSONB,
    after JSONB,
    request_id VARCHAR(64),
    at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    CONSTRAINT pk_audit_log PRIMARY KEY (id),
    CONSTRAINT ck_audit_log_actor_type CHECK (actor_type IN ('user','patient','system','assistant','anonymous')),
    CONSTRAINT ck_audit_log_channel CHECK (channel IN ('dashboard','whatsapp','system','api'))
);

CREATE INDEX ix_audit_clinic_at ON audit_log (clinic_id, at);

CREATE INDEX ix_audit_entity ON audit_log (clinic_id, entity_type, entity_id);

CREATE TABLE clinics (
    name VARCHAR(160) NOT NULL,
    slug VARCHAR(40) NOT NULL,
    specialty VARCHAR(20) NOT NULL,
    timezone VARCHAR(40) DEFAULT 'Asia/Kolkata' NOT NULL,
    languages VARCHAR(5)[] NOT NULL,
    address VARCHAR(500),
    map_url VARCHAR(500),
    phone VARCHAR(16),
    default_fee_paise INTEGER DEFAULT '0' NOT NULL,
    settings JSONB DEFAULT '{}' NOT NULL,
    status VARCHAR(16) DEFAULT 'trial' NOT NULL,
    trial_ends_at TIMESTAMP WITH TIME ZONE,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_clinics PRIMARY KEY (id),
    CONSTRAINT ck_clinics_specialty CHECK (specialty IN ('dental','physio')),
    CONSTRAINT ck_clinics_status CHECK (status IN ('trial','active','suspended')),
    CONSTRAINT ck_clinics_fee_nonneg CHECK (default_fee_paise >= 0),
    CONSTRAINT uq_clinics_slug UNIQUE (slug)
);

CREATE TABLE otp_challenges (
    phone VARCHAR(16) NOT NULL,
    code_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    attempts INTEGER DEFAULT '0' NOT NULL,
    consumed_at TIMESTAMP WITH TIME ZONE,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_otp_challenges PRIMARY KEY (id)
);

CREATE INDEX ix_otp_challenges_phone ON otp_challenges (phone);

CREATE TABLE users (
    phone VARCHAR(16) NOT NULL,
    name VARCHAR(120),
    is_platform_admin BOOLEAN DEFAULT 'false' NOT NULL,
    is_active BOOLEAN DEFAULT 'true' NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT uq_users_phone UNIQUE (phone)
);

CREATE TABLE doctors (
    clinic_id UUID NOT NULL,
    name VARCHAR(120) NOT NULL,
    fee_paise INTEGER,
    slot_minutes SMALLINT NOT NULL,
    is_active BOOLEAN DEFAULT 'true' NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_doctors PRIMARY KEY (id),
    CONSTRAINT uq_doctors_clinic_id_id UNIQUE (clinic_id, id),
    CONSTRAINT ck_doctors_slot_minutes CHECK (slot_minutes BETWEEN 5 AND 120),
    CONSTRAINT ck_doctors_fee_nonneg CHECK (fee_paise IS NULL OR fee_paise >= 0),
    CONSTRAINT fk_doctors_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id)
);

CREATE INDEX ix_doctors_clinic_id ON doctors (clinic_id);

CREATE TABLE patients (
    clinic_id UUID NOT NULL,
    phone VARCHAR(16) NOT NULL,
    name VARCHAR(120) NOT NULL,
    age SMALLINT,
    language VARCHAR(5),
    account_holder_id UUID,
    opted_out_at TIMESTAMP WITH TIME ZONE,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_patients PRIMARY KEY (id),
    CONSTRAINT uq_patients_clinic_id_id UNIQUE (clinic_id, id),
    CONSTRAINT uq_patients_clinic_id_phone_name UNIQUE (clinic_id, phone, name),
    CONSTRAINT fk_patients_clinic_id_account_holder_id_patients FOREIGN KEY(clinic_id, account_holder_id) REFERENCES patients (clinic_id, id),
    CONSTRAINT ck_patients_age CHECK (age IS NULL OR age BETWEEN 0 AND 120),
    CONSTRAINT ck_patients_language CHECK (language IS NULL OR language IN ('gu','hi','en')),
    CONSTRAINT fk_patients_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id)
);

CREATE INDEX ix_patients_clinic_phone ON patients (clinic_id, phone);

CREATE TABLE refresh_tokens (
    user_id UUID NOT NULL,
    clinic_id UUID,
    family_id UUID NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    rotated_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_refresh_tokens PRIMARY KEY (id),
    CONSTRAINT fk_refresh_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id),
    CONSTRAINT fk_refresh_tokens_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id),
    CONSTRAINT uq_refresh_tokens_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);

CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);

CREATE TABLE appointments (
    clinic_id UUID NOT NULL,
    doctor_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    booked_by_phone VARCHAR(16) NOT NULL,
    slot_start TIMESTAMP WITH TIME ZONE NOT NULL,
    slot_end TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(12) NOT NULL,
    source VARCHAR(16) NOT NULL,
    source_ref_id UUID,
    rescheduled_from_id UUID,
    needs_reschedule BOOLEAN DEFAULT 'false' NOT NULL,
    arrived_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_appointments PRIMARY KEY (id),
    CONSTRAINT fk_appointments_clinic_id_doctor_id_doctors FOREIGN KEY(clinic_id, doctor_id) REFERENCES doctors (clinic_id, id),
    CONSTRAINT fk_appointments_clinic_id_patient_id_patients FOREIGN KEY(clinic_id, patient_id) REFERENCES patients (clinic_id, id),
    CONSTRAINT ck_appointments_status CHECK (status IN ('booked', 'confirmed', 'arrived', 'completed', 'cancelled', 'rescheduled', 'no_show')),
    CONSTRAINT ck_appointments_source CHECK (source IN ('assistant', 'staff', 'missed_call', 'recall', 'noshow_rebook')),
    CONSTRAINT ck_appointments_slot_order CHECK (slot_end > slot_start)
);

CREATE INDEX ix_appt_clinic_doctor_start ON appointments (clinic_id, doctor_id, slot_start);

CREATE INDEX ix_appt_clinic_patient_start ON appointments (clinic_id, patient_id, slot_start);

CREATE INDEX ix_appt_clinic_phone_doctor ON appointments (clinic_id, booked_by_phone, doctor_id);

CREATE UNIQUE INDEX uq_appt_active_slot ON appointments (doctor_id, slot_start) WHERE status IN ('booked', 'confirmed', 'arrived', 'completed');

CREATE TABLE clinic_memberships (
    clinic_id UUID NOT NULL,
    user_id UUID NOT NULL,
    role VARCHAR(16) NOT NULL,
    doctor_id UUID,
    status VARCHAR(16) DEFAULT 'active' NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_clinic_memberships PRIMARY KEY (id),
    CONSTRAINT uq_clinic_memberships_clinic_id_user_id UNIQUE (clinic_id, user_id),
    CONSTRAINT fk_clinic_memberships_clinic_id_doctor_id_doctors FOREIGN KEY(clinic_id, doctor_id) REFERENCES doctors (clinic_id, id),
    CONSTRAINT ck_clinic_memberships_role CHECK (role IN ('owner','doctor','receptionist')),
    CONSTRAINT ck_clinic_memberships_status CHECK (status IN ('invited','active','disabled')),
    CONSTRAINT fk_clinic_memberships_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id),
    CONSTRAINT fk_clinic_memberships_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_clinic_memberships_clinic_id ON clinic_memberships (clinic_id);

CREATE INDEX ix_clinic_memberships_user_id ON clinic_memberships (user_id);

CREATE TABLE consent_events (
    clinic_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    purpose VARCHAR(16) NOT NULL,
    granted BOOLEAN NOT NULL,
    channel VARCHAR(16) NOT NULL,
    notice_version VARCHAR(20) NOT NULL,
    at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_consent_events PRIMARY KEY (id),
    CONSTRAINT fk_consent_events_clinic_id_patient_id_patients FOREIGN KEY(clinic_id, patient_id) REFERENCES patients (clinic_id, id),
    CONSTRAINT ck_consent_events_purpose CHECK (purpose IN ('booking','reminders','recalls')),
    CONSTRAINT ck_consent_events_channel CHECK (channel IN ('whatsapp','dashboard','import'))
);

CREATE INDEX ix_consent_events_clinic_id ON consent_events (clinic_id);

CREATE INDEX ix_consent_events_patient_id ON consent_events (patient_id);

CREATE TABLE doctor_sessions (
    clinic_id UUID NOT NULL,
    doctor_id UUID NOT NULL,
    weekday SMALLINT NOT NULL,
    start_time TIME WITHOUT TIME ZONE NOT NULL,
    end_time TIME WITHOUT TIME ZONE NOT NULL,
    max_tokens SMALLINT NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_doctor_sessions PRIMARY KEY (id),
    CONSTRAINT fk_doctor_sessions_clinic_id_doctor_id_doctors FOREIGN KEY(clinic_id, doctor_id) REFERENCES doctors (clinic_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_doctor_sessions_weekday CHECK (weekday BETWEEN 0 AND 6),
    CONSTRAINT ck_doctor_sessions_time_order CHECK (end_time > start_time),
    CONSTRAINT ck_doctor_sessions_max_tokens CHECK (max_tokens BETWEEN 0 AND 500)
);

CREATE INDEX ix_doctor_sessions_clinic_id ON doctor_sessions (clinic_id);

CREATE TABLE schedule_exceptions (
    clinic_id UUID NOT NULL,
    doctor_id UUID,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    kind VARCHAR(10) NOT NULL,
    reason VARCHAR(200),
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_schedule_exceptions PRIMARY KEY (id),
    CONSTRAINT fk_schedule_exceptions_clinic_id_doctor_id_doctors FOREIGN KEY(clinic_id, doctor_id) REFERENCES doctors (clinic_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_schedule_exceptions_date_order CHECK (end_date >= start_date),
    CONSTRAINT ck_schedule_exceptions_kind CHECK (kind IN ('holiday','leave')),
    CONSTRAINT fk_schedule_exceptions_clinic_id_clinics FOREIGN KEY(clinic_id) REFERENCES clinics (id)
);

CREATE INDEX ix_schedule_exceptions_clinic_id ON schedule_exceptions (clinic_id);
"""

TENANT_TABLES = [
    "doctors",
    "doctor_sessions",
    "schedule_exceptions",
    "patients",
    "consent_events",
    "appointments",
]
PLATFORM_TABLES = ["users", "otp_challenges", "refresh_tokens"]
ALL_TABLES = [
    "users",
    "clinics",
    "otp_challenges",
    "refresh_tokens",
    "doctors",
    "patients",
    "clinic_memberships",
    "doctor_sessions",
    "schedule_exceptions",
    "consent_events",
    "appointments",
    "audit_log",
]


def upgrade() -> None:
    op.execute(DDL)
    op.execute(FUNCTIONS_SQL)
    for t in TENANT_TABLES:
        op.execute(enable_rls_sql(t))
    # Tenant root: visible to its own context or to a user who is a member.
    op.execute(
        enable_rls_sql(
            "clinics",
            using="id = app_clinic_id() OR app_bypass_rls() OR EXISTS (SELECT 1 FROM clinic_memberships m "
            "WHERE m.clinic_id = clinics.id AND m.user_id = app_user_id())",
            check="id = app_clinic_id() OR app_bypass_rls()",
        )
    )
    # Memberships: a user may list their own memberships across clinics (login → clinic picker).
    op.execute(
        enable_rls_sql(
            "clinic_memberships",
            using="clinic_id = app_clinic_id() OR user_id = app_user_id() OR app_bypass_rls()",
            check="clinic_id = app_clinic_id() OR app_bypass_rls()",
        )
    )
    # Audit: platform-level rows (clinic_id NULL) may be written but are only readable with bypass.
    op.execute(
        enable_rls_sql(
            "audit_log",
            using="clinic_id = app_clinic_id() OR app_bypass_rls()",
            check="clinic_id IS NULL OR clinic_id = app_clinic_id() OR app_bypass_rls()",
        )
    )
    for t in ALL_TABLES:
        op.execute(grant_dml_sql(t, append_only=(t == "audit_log")))


def downgrade() -> None:
    for t in reversed(ALL_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute(DROP_FUNCTIONS_SQL)
