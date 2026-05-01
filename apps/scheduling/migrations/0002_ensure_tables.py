"""Repair migration — ensures ALL scheduling tables exist on Railway Postgres."""
from django.db import migrations

SQL = """
CREATE TABLE IF NOT EXISTS "scheduling_classtype" (
    "id"               bigserial    PRIMARY KEY,
    "name"             varchar(200) NOT NULL,
    "description"      text         NOT NULL DEFAULT '',
    "duration_minutes" integer      NOT NULL DEFAULT 60,
    "cover_image"      varchar(100) NOT NULL DEFAULT '',
    "is_active"        boolean      NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS "scheduling_classschedule" (
    "id"             bigserial    PRIMARY KEY,
    "title"          varchar(200) NOT NULL DEFAULT '',
    "start_time"     timestamptz  NOT NULL,
    "end_time"       timestamptz  NOT NULL,
    "max_capacity"   integer      NOT NULL DEFAULT 20,
    "is_cancelled"   boolean      NOT NULL DEFAULT false,
    "cancel_reason"  varchar(255) NOT NULL DEFAULT '',
    "class_type_id"  bigint       NULL REFERENCES "scheduling_classtype"("id") ON DELETE SET NULL,
    "instructor_id"  bigint       NULL,
    "location_id"    bigint       NULL
);

CREATE TABLE IF NOT EXISTS "scheduling_booking" (
    "id"           bigserial   PRIMARY KEY,
    "status"       varchar(20) NOT NULL DEFAULT 'confirmed',
    "booked_at"    timestamptz NOT NULL DEFAULT now(),
    "checked_in"   boolean     NOT NULL DEFAULT false,
    "member_id"    bigint      NULL,
    "schedule_id"  bigint      NULL REFERENCES "scheduling_classschedule"("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "scheduling_waitlist" (
    "id"          bigserial   PRIMARY KEY,
    "joined_at"   timestamptz NOT NULL DEFAULT now(),
    "notified"    boolean     NOT NULL DEFAULT false,
    "member_id"   bigint      NULL,
    "schedule_id" bigint      NULL REFERENCES "scheduling_classschedule"("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "scheduling_appointment" (
    "id"               bigserial   PRIMARY KEY,
    "appointment_type" varchar(20) NOT NULL DEFAULT 'training',
    "scheduled_at"     timestamptz NOT NULL,
    "duration_minutes" integer     NOT NULL DEFAULT 60,
    "status"           varchar(20) NOT NULL DEFAULT 'pending',
    "notes_after"      text        NOT NULL DEFAULT '',
    "member_id"        bigint      NULL,
    "staff_id"         bigint      NULL
);

CREATE TABLE IF NOT EXISTS "scheduling_workoutplan" (
    "id"            bigserial   PRIMARY KEY,
    "source"        varchar(20) NOT NULL DEFAULT 'trainer',
    "status"        varchar(20) NOT NULL DEFAULT 'draft',
    "plan_data"     jsonb       NOT NULL DEFAULT '{}',
    "created_at"    timestamptz NOT NULL DEFAULT now(),
    "approved_at"   timestamptz NULL,
    "created_by_id" bigint      NULL,
    "member_id"     bigint      NOT NULL
);
"""


class Migration(migrations.Migration):
    dependencies = [
        ('scheduling', '0001_initial'),
        ('core', '0002_ensure_tables'),
        ('members', '0004_ensure_tables'),
    ]
    operations = [migrations.RunSQL(SQL, reverse_sql='SELECT 1;')]
