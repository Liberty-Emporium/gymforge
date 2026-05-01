"""
Nuclear repair migration — uses Django's schema editor to create ALL missing
tables across ALL apps in one shot.

Iterates every model registered in INSTALLED_APPS, checks if its table exists
in Postgres, and creates it via schema_editor if it's absent.
Safe to run multiple times (always checks before creating).
"""
from django.db import migrations


def create_missing_tables(apps, schema_editor):
    from django.apps import apps as django_apps
    from django.db import connection

    # Get all tables currently in the DB
    existing = set(connection.introspection.table_names())

    created = []
    skipped = []
    failed = []

    with connection.schema_editor() as editor:
        for model in django_apps.get_models():
            table = model._meta.db_table
            if table in existing:
                skipped.append(table)
                continue
            try:
                editor.create_model(model)
                created.append(table)
                existing.add(table)  # update set so M2M through tables see their parents
                print(f"  CREATED: {table}")
            except Exception as e:
                err = str(e)
                # Ignore "already exists" race conditions
                if 'already exists' in err.lower():
                    skipped.append(table)
                else:
                    failed.append(f"{table}: {err[:120]}")
                    print(f"  FAILED:  {table} — {err[:120]}")

    print(f"\nDone. Created: {len(created)}, Skipped: {len(skipped)}, Failed: {len(failed)}")
    if failed:
        print("Failures (non-fatal):")
        for f in failed:
            print(f"  {f}")


class Migration(migrations.Migration):

    dependencies = [
        # Depend on all previous repair migrations so they run first
        ('core', '0002_ensure_tables'),
        ('gym', '0002_gymconfig_api_secrets'),
        ('accounts', '0001_initial'),
        ('billing', '0004_ensure_tables'),
        ('members', '0005_ensure_tables_2'),
        ('checkin', '0003_ensure_tables_2'),
        ('scheduling', '0004_ensure_tables_2'),
        ('inventory', '0003_ensure_tables_2'),
        ('loyalty', '0002_ensure_tables'),
        ('platform_admin', '0002_ensure_tables'),
        ('leads', '0002_ensure_tables'),
        ('payroll', '0002_ensure_tables'),
        ('shop', '0002_ensure_tables'),
        ('community', '0002_ensure_tables'),
        ('ai_coach', '0002_ensure_tables'),
    ]

    operations = [
        migrations.RunPython(
            create_missing_tables,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
