"""
Gym provisioning task — 16 steps to bring a new gym tenant online.

Triggered from the setup wizard confirm view. Receives all wizard
data as a plain JSON-serializable dict (no Django objects).
"""
from celery import shared_task
from django.utils import timezone


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

DEFAULT_CLASS_TYPES = [
    ('HIIT',               'High-Intensity Interval Training', 45),
    ('Yoga Flow',          'Mindful movement and flexibility', 60),
    ('Spin',               'High-energy indoor cycling',       45),
    ('Pilates',            'Core strength and flexibility',    55),
    ('Boxing Fit',         'Boxing-inspired cardio workout',   45),
    ('Stretch & Recovery', 'Mobility and recovery session',    30),
]

DEFAULT_LOYALTY_RULES = [
    # (action, points, max_per_day, description)
    ('checkin',          10, 1,    'Points awarded on each gym check-in'),
    ('class_attended',   20, 1,    'Points awarded for attending a class'),
    ('referral',        100, None, 'Points awarded for referring a new member'),
    ('birthday',         50, None, 'Birthday bonus points'),
]

# Predefined services that are always seeded (is_custom=False)
ALL_PREDEFINED = [
    'Group Fitness Classes',
    'Personal Training',
    'Nutrition Coaching',
    'Sauna',
    'Swimming Pool',
    'Yoga',
    'Pilates',
    'CrossFit',
    'Boxing / Kickboxing',
    'Spin / Cycling',
    'Stretch & Recovery',
    'Open Gym',
]


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@shared_task(bind=True)
def provision_gym(self, wizard_data: dict) -> dict:
    """
    Provision a new gym tenant in 16 steps.

    Args:
        wizard_data: fully JSON-serializable dict from request.session['wizard']

    Returns:
        dict with schema_name, owner_email, status='ready'
    """
    from django_tenants.utils import schema_context
    from apps.tenants.models import GymTenant, GymDomain
    from apps.accounts.models import User

    identity    = wizard_data.get('identity', {})
    locations   = wizard_data.get('locations', [])
    owner_data  = wizard_data.get('owner', {})
    plans_data  = wizard_data.get('plans', [])
    services    = wizard_data.get('services', {})
    schema_name = wizard_data.get('schema_name', '')

    selected_services = services.get('selected', [])
    custom_services   = services.get('custom', [])
    gym_name          = identity.get('gym_name', 'New Gym')
    owner_email       = owner_data.get('email', '')

    def _progress(step_num, label):
        try:
            self.update_state(state='PROGRESS', meta={'step_num': step_num, 'step': label})
        except Exception:
            pass  # Redis unavailable — ignore progress updates, provisioning continues

    # ------------------------------------------------------------------
    # Step 1 — Validate schema name uniqueness (final check)
    # ------------------------------------------------------------------
    _progress(1, 'Validating gym identity…')
    if not schema_name:
        import re
        base = re.sub(r'[^a-z0-9]+', '_', gym_name.lower()).strip('_')[:50] or 'gym'
        schema_name = base
        n = 1
        while GymTenant.objects.filter(schema_name=schema_name).exists():
            schema_name = f'{base}_{n}'
            n += 1

    # ------------------------------------------------------------------
    # Step 2 — Create GymTenant (auto_create_schema=True runs migrations)
    # ------------------------------------------------------------------
    _progress(2, 'Creating gym database schema…')
    tenant = GymTenant(
        schema_name=schema_name,
        gym_name=gym_name,
        owner_email=owner_email,
        subscription_status='trial',
        trial_active=True,
        member_app_active=False,
    )
    tenant.save()  # triggers create_schema() + migrate_schemas for this tenant

    # ------------------------------------------------------------------
    # Step 3 — Create GymDomain (subdomain + Railway preview URL)
    # ------------------------------------------------------------------
    _progress(3, 'Configuring subdomain…')
    GymDomain.objects.create(
        domain=f'{schema_name}.gymforge.com',
        tenant=tenant,
        is_primary=True,
    )
    # Also map the Railway deployment URL so the demo works without DNS
    import os
    railway_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if railway_domain:
        GymDomain.objects.get_or_create(
            domain=railway_domain,
            tenant=tenant,
            defaults={'is_primary': False},
        )

    # ------------------------------------------------------------------
    # Step 4 — Create gym owner User (public schema — accounts is SHARED_APPS)
    # ------------------------------------------------------------------
    _progress(4, 'Creating owner account…')
    owner_user = User.objects.create_user(
        username=owner_email,
        email=owner_email,
        password=owner_data.get('password', ''),
        first_name=owner_data.get('first_name', ''),
        last_name=owner_data.get('last_name', ''),
        role='gym_owner',
        is_active=True,
    )

    # ------------------------------------------------------------------
    # Steps 5–14 — Run inside the new tenant schema
    # ------------------------------------------------------------------
    with schema_context(schema_name):

        # Step 5 — GymProfile (branding)
        _progress(5, 'Setting up gym branding…')
        from apps.core.models import GymProfile
        profile_kwargs = {
            'gym_name':      gym_name,
            'tagline':       identity.get('tagline', ''),
            'primary_color': identity.get('primary_color', '#1a1a2e'),
            'accent_color':  identity.get('accent_color', '#e94560'),
            'landing_page_active': True,
        }
        logo_path = identity.get('logo_path')
        if logo_path:
            profile_kwargs['logo'] = logo_path
        GymProfile.objects.create(**profile_kwargs)

        # Step 6 — Locations
        _progress(6, 'Setting up locations…')
        from apps.core.models import Location, LocationHours
        location_objs = []
        for loc_data in locations:
            loc = Location.objects.create(
                name=loc_data.get('name', 'Main Location'),
                address=loc_data.get('address', ''),
                timezone=loc_data.get('timezone', 'America/New_York'),
            )
            location_objs.append(loc)

            # Step 7 — LocationHours
            hours_data = loc_data.get('hours', {})
            for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
                day_info = hours_data.get(day, {})
                LocationHours.objects.create(
                    location=loc,
                    day=day,
                    open_time=day_info.get('open', '06:00') or None,
                    close_time=day_info.get('close', '22:00') or None,
                    is_closed=day_info.get('closed', False),
                )

        # Step 8 — Seed predefined Services (all of them, active or not per selection)
        _progress(8, 'Setting up services…')
        from apps.core.models import Service
        service_objs = {}
        for svc_name in ALL_PREDEFINED:
            is_active = svc_name in selected_services
            svc = Service.objects.create(name=svc_name, is_custom=False, is_active=is_active)
            service_objs[svc_name] = svc

        # Step 9 — Custom services
        _progress(9, 'Adding custom services…')
        for custom_name in custom_services:
            svc = Service.objects.create(name=custom_name, is_custom=True, is_active=True)
            service_objs[custom_name] = svc

        # Step 10 — MembershipTiers
        _progress(10, 'Creating membership plans…')
        from apps.billing.models import MembershipTier
        tier_objs = []
        for plan in plans_data:
            try:
                price = float(plan.get('price', 0) or 0)
            except (ValueError, TypeError):
                price = 0.0
            tier = MembershipTier.objects.create(
                name=plan.get('name', 'Membership'),
                price=price,
                billing_cycle=plan.get('billing_cycle', 'monthly'),
                description=plan.get('description', ''),
                is_active=True,
            )
            tier_objs.append(tier)

        # Step 11 — Link selected services to all tiers
        _progress(11, 'Linking services to plans…')
        active_services = [s for name, s in service_objs.items() if s.is_active]
        for tier in tier_objs:
            tier.included_services.set(active_services)

        # Step 12 — Seed default ClassTypes
        _progress(12, 'Creating default class types…')
        from apps.scheduling.models import ClassType
        for name, description, duration in DEFAULT_CLASS_TYPES:
            ClassType.objects.create(
                name=name,
                description=description,
                duration_minutes=duration,
                is_active=True,
            )

        # Step 13 — Seed default LoyaltyRules
        _progress(13, 'Setting up loyalty programme…')
        from apps.loyalty.models import LoyaltyRule
        for action, points, max_per_day, description in DEFAULT_LOYALTY_RULES:
            LoyaltyRule.objects.create(
                action=action,
                points=points,
                max_per_day=max_per_day,
                is_active=True,
            )

        # Step 14 — Assign owner user to the gym (link via profile if applicable)
        _progress(14, 'Finalising owner access…')
        # Owner user already has role='gym_owner' in public schema.
        # No tenant-specific profile needed at provisioning time.

    # ------------------------------------------------------------------
    # Step 15 — Log AuditLog (public schema)
    # ------------------------------------------------------------------
    _progress(15, 'Recording audit event…')
    from apps.platform_admin.models import AuditLog
    AuditLog.objects.create(
        actor_email='system',
        gym_schema=schema_name,
        action=f'Gym provisioned: {gym_name}',
        target_model='GymTenant',
        target_id=str(tenant.pk),
        details={
            'owner_email': owner_email,
            'locations':   len(locations),
            'plans':       len(plans_data),
            'services':    len(selected_services) + len(custom_services),
        },
    )

    # ------------------------------------------------------------------
    # Step 16 — Send welcome email
    # ------------------------------------------------------------------
    _progress(16, 'Sending welcome email…')
    try:
        from django.core.mail import send_mail
        from django.conf import settings as django_settings
        send_mail(
            subject=f'Welcome to GymForge — {gym_name} is live!',
            message=(
                f"Hi {owner_data.get('first_name', '')},\n\n"
                f"Your gym '{gym_name}' has been provisioned and is ready.\n\n"
                f"Log in at: https://{schema_name}.gymforge.com/auth/login/\n\n"
                f"Your 14-day trial starts today.\n\n"
                f"— The GymForge Team"
            ),
            from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@gymforge.com'),
            recipient_list=[owner_email],
            fail_silently=True,
        )
    except Exception:
        pass  # Email failure must never abort provisioning

    return {
        'status':       'ready',
        'schema_name':  schema_name,
        'owner_email':  owner_email,
        'gym_name':     gym_name,
    }
