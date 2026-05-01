"""
Add all 52 missing columns identified by /setup/db-status/.
Uses ADD COLUMN IF NOT EXISTS for idempotency.
"""
from django.db import migrations

SQL = """
-- members_familyaccount
ALTER TABLE members_familyaccount ADD COLUMN IF NOT EXISTS primary_member_id bigint NULL;

-- members_healthprofile
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS current_supplements text NOT NULL DEFAULT '';
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS typical_diet_description text NOT NULL DEFAULT '';
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS water_intake_liters float NULL;
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS preferred_workout_time varchar(20) NOT NULL DEFAULT '';
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS prefers_group boolean NOT NULL DEFAULT false;
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS has_worked_with_trainer boolean NOT NULL DEFAULT false;
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS past_obstacles text NOT NULL DEFAULT '';
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS intake_completed boolean NOT NULL DEFAULT false;
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS raw_intake_data jsonb NOT NULL DEFAULT '{}';
ALTER TABLE members_healthprofile ADD COLUMN IF NOT EXISTS last_updated timestamptz NULL;

-- members_workoutlog
ALTER TABLE members_workoutlog ADD COLUMN IF NOT EXISTS workout_date date NULL;
ALTER TABLE members_workoutlog ADD COLUMN IF NOT EXISTS logged_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE members_workoutlog ADD COLUMN IF NOT EXISTS source varchar(20) NOT NULL DEFAULT 'manual';
ALTER TABLE members_workoutlog ADD COLUMN IF NOT EXISTS exercises jsonb NOT NULL DEFAULT '[]';
ALTER TABLE members_workoutlog ADD COLUMN IF NOT EXISTS mood_before varchar(20) NOT NULL DEFAULT '';
ALTER TABLE members_workoutlog ADD COLUMN IF NOT EXISTS energy_after varchar(20) NOT NULL DEFAULT '';

-- members_bodymetric
ALTER TABLE members_bodymetric ADD COLUMN IF NOT EXISTS body_fat_percent float NULL;
ALTER TABLE members_bodymetric ADD COLUMN IF NOT EXISTS measurements jsonb NOT NULL DEFAULT '{}';

-- checkin_membercard
ALTER TABLE checkin_membercard ADD COLUMN IF NOT EXISTS rfid_token varchar(100) NOT NULL DEFAULT '';
ALTER TABLE checkin_membercard ADD COLUMN IF NOT EXISTS card_number varchar(50) NOT NULL DEFAULT '';
ALTER TABLE checkin_membercard ADD COLUMN IF NOT EXISTS deactivated_at timestamptz NULL;
ALTER TABLE checkin_membercard ADD COLUMN IF NOT EXISTS deactivation_reason varchar(200) NOT NULL DEFAULT '';

-- checkin_cardscanlog
ALTER TABLE checkin_cardscanlog ADD COLUMN IF NOT EXISTS scan_type varchar(20) NOT NULL DEFAULT 'entry';

-- checkin_lockerassignment
ALTER TABLE checkin_lockerassignment ADD COLUMN IF NOT EXISTS location_id bigint NULL;
ALTER TABLE checkin_lockerassignment ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

-- checkin_accessrule
ALTER TABLE checkin_accessrule ADD COLUMN IF NOT EXISTS access_start_time time NULL;
ALTER TABLE checkin_accessrule ADD COLUMN IF NOT EXISTS access_end_time time NULL;
ALTER TABLE checkin_accessrule ADD COLUMN IF NOT EXISTS days_allowed jsonb NOT NULL DEFAULT '[]';
ALTER TABLE checkin_accessrule ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

-- checkin_shift
ALTER TABLE checkin_shift ADD COLUMN IF NOT EXISTS attended boolean NOT NULL DEFAULT false;

-- checkin_staffrequest
ALTER TABLE checkin_staffrequest ADD COLUMN IF NOT EXISTS target_email varchar(254) NOT NULL DEFAULT '';
ALTER TABLE checkin_staffrequest ADD COLUMN IF NOT EXISTS role varchar(20) NOT NULL DEFAULT '';
ALTER TABLE checkin_staffrequest ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

-- checkin_membernote
ALTER TABLE checkin_membernote ADD COLUMN IF NOT EXISTS visibility varchar(20) NOT NULL DEFAULT 'staff';

-- checkin_clientassignment
ALTER TABLE checkin_clientassignment ADD COLUMN IF NOT EXISTS assignment_type varchar(20) NOT NULL DEFAULT 'trainer';
ALTER TABLE checkin_clientassignment ADD COLUMN IF NOT EXISTS start_date date NULL;

-- checkin_tasktemplate
ALTER TABLE checkin_tasktemplate ADD COLUMN IF NOT EXISTS area varchar(100) NOT NULL DEFAULT '';
ALTER TABLE checkin_tasktemplate ADD COLUMN IF NOT EXISTS shift_type varchar(20) NOT NULL DEFAULT 'any';

-- checkin_cleaningtask
ALTER TABLE checkin_cleaningtask ADD COLUMN IF NOT EXISTS verification_photo varchar(100) NOT NULL DEFAULT '';

-- checkin_trainerprofile
ALTER TABLE checkin_trainerprofile ADD COLUMN IF NOT EXISTS specialties jsonb NOT NULL DEFAULT '[]';
ALTER TABLE checkin_trainerprofile ADD COLUMN IF NOT EXISTS is_visible_to_members boolean NOT NULL DEFAULT true;

-- inventory_supplyitem
ALTER TABLE inventory_supplyitem ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '';
ALTER TABLE inventory_supplyitem ADD COLUMN IF NOT EXISTS reorder_quantity integer NOT NULL DEFAULT 0;
ALTER TABLE inventory_supplyitem ADD COLUMN IF NOT EXISTS supplier varchar(200) NOT NULL DEFAULT '';
ALTER TABLE inventory_supplyitem ADD COLUMN IF NOT EXISTS unit_cost numeric(8,2) NULL;

-- loyalty_loyaltytransaction
ALTER TABLE loyalty_loyaltytransaction ADD COLUMN IF NOT EXISTS created_by_id bigint NULL;

-- loyalty_loyaltyreward
ALTER TABLE loyalty_loyaltyreward ADD COLUMN IF NOT EXISTS image varchar(100) NOT NULL DEFAULT '';
ALTER TABLE loyalty_loyaltyreward ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

-- loyalty_badgemilestone
ALTER TABLE loyalty_badgemilestone ADD COLUMN IF NOT EXISTS points_reward integer NOT NULL DEFAULT 0;

-- loyalty_memberbadge
ALTER TABLE loyalty_memberbadge ADD COLUMN IF NOT EXISTS milestone_id bigint NULL;

-- platform_admin_plan
ALTER TABLE platform_admin_plan ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
"""


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0004_fix_missing_columns'),
    ]
    operations = [
        migrations.RunSQL(SQL, reverse_sql='SELECT 1;'),
    ]
