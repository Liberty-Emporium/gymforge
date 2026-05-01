"""
Repair migration — ensures core tables exist even when the Railway Postgres DB
has stale migration records (0001 recorded as applied but tables missing).
Uses CREATE TABLE IF NOT EXISTS so it is always safe to re-run.
"""
from django.db import migrations


CREATE_GYMPROFILE = """
CREATE TABLE IF NOT EXISTS "core_gymprofile" (
    "id"                    bigserial PRIMARY KEY,
    "gym_name"              varchar(200) NOT NULL,
    "logo"                  varchar(100) NOT NULL DEFAULT '',
    "primary_color"         varchar(7)   NOT NULL DEFAULT '#1a1a2e',
    "accent_color"          varchar(7)   NOT NULL DEFAULT '#e94560',
    "tagline"               varchar(300) NOT NULL DEFAULT '',
    "about_text"            text         NOT NULL DEFAULT '',
    "welcome_message"       text         NOT NULL DEFAULT '',
    "homepage_layout"       varchar(50)  NOT NULL DEFAULT 'hero',
    "banner_image"          varchar(100) NOT NULL DEFAULT '',
    "social_instagram"      varchar(200) NOT NULL DEFAULT '',
    "social_facebook"       varchar(200) NOT NULL DEFAULT '',
    "social_tiktok"         varchar(200) NOT NULL DEFAULT '',
    "social_youtube"        varchar(200) NOT NULL DEFAULT '',
    "custom_domain"         varchar(200) NOT NULL DEFAULT '',
    "custom_domain_active"  boolean      NOT NULL DEFAULT false,
    "waiver_text"           text         NOT NULL DEFAULT '',
    "email_signature"       text         NOT NULL DEFAULT '',
    "features_enabled"      jsonb        NOT NULL DEFAULT '{}',
    "landing_page_active"   boolean      NOT NULL DEFAULT true,
    "landing_page_sections" jsonb        NOT NULL DEFAULT '[]',
    "updated_at"            timestamptz  NOT NULL
);
"""

CREATE_LOCATION = """
CREATE TABLE IF NOT EXISTS "core_location" (
    "id"         bigserial PRIMARY KEY,
    "name"       varchar(200) NOT NULL,
    "address"    text         NOT NULL,
    "phone"      varchar(20)  NOT NULL DEFAULT '',
    "email"      varchar(254) NOT NULL DEFAULT '',
    "timezone"   varchar(50)  NOT NULL DEFAULT 'America/New_York',
    "is_active"  boolean      NOT NULL DEFAULT true,
    "created_at" timestamptz  NOT NULL
);
"""

CREATE_SERVICE = """
CREATE TABLE IF NOT EXISTS "core_service" (
    "id"          bigserial PRIMARY KEY,
    "name"        varchar(200) NOT NULL,
    "description" text         NOT NULL DEFAULT '',
    "is_active"   boolean      NOT NULL DEFAULT true,
    "is_custom"   boolean      NOT NULL DEFAULT false
);
"""

CREATE_LOCATIONHOURS = """
CREATE TABLE IF NOT EXISTS "core_locationhours" (
    "id"          bigserial PRIMARY KEY,
    "day"         varchar(3)  NOT NULL,
    "open_time"   time        NULL,
    "close_time"  time        NULL,
    "is_closed"   boolean     NOT NULL DEFAULT false,
    "location_id" bigint      NOT NULL REFERENCES "core_location" ("id") ON DELETE CASCADE,
    UNIQUE ("location_id", "day")
);
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_GYMPROFILE,
            reverse_sql='DROP TABLE IF EXISTS "core_gymprofile";',
        ),
        migrations.RunSQL(
            sql=CREATE_LOCATION,
            reverse_sql='DROP TABLE IF EXISTS "core_location";',
        ),
        migrations.RunSQL(
            sql=CREATE_SERVICE,
            reverse_sql='DROP TABLE IF EXISTS "core_service";',
        ),
        migrations.RunSQL(
            sql=CREATE_LOCATIONHOURS,
            reverse_sql='DROP TABLE IF EXISTS "core_locationhours";',
        ),
    ]
