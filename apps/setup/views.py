"""
Gym Owner Setup Wizard — 7-step session-based onboarding flow.

All wizard state is stored in request.session['wizard'].
No login required — this is the signup flow for new gym owners.
"""
import os
import re
import uuid

from django.conf import settings
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from apps.tenants.models import GymTenant
from .tasks import provision_gym


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PREDEFINED_SERVICES = [
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

STAFF_ROLES = [
    ('manager',      'Location Manager',      'Manages schedules, staff, and daily operations'),
    ('trainer',      'Personal Trainer',       'Teaches classes and personal training sessions'),
    ('front_desk',   'Front Desk Staff',       'Handles check-ins, memberships, and POS sales'),
    ('cleaner',      'Cleaner',                'Manages equipment maintenance and cleaning tasks'),
    ('nutritionist', 'Nutritionist',           'Provides nutrition plans and consultations'),
]

TIMEZONES = [
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Phoenix',
    'America/Anchorage',
    'America/Honolulu',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Madrid',
    'Europe/Rome',
    'Europe/Amsterdam',
    'Asia/Dubai',
    'Asia/Tokyo',
    'Asia/Singapore',
    'Asia/Shanghai',
    'Asia/Kolkata',
    'Australia/Sydney',
    'Australia/Melbourne',
    'Pacific/Auckland',
    'Pacific/Auckland',
]

DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
DAY_NAMES = {
    'mon': 'Monday', 'tue': 'Tuesday', 'wed': 'Wednesday',
    'thu': 'Thursday', 'fri': 'Friday', 'sat': 'Saturday', 'sun': 'Sunday',
}

BILLING_CYCLES = [
    ('monthly',  'Monthly'),
    ('annual',   'Annual'),
    ('drop_in',  'Drop-in / Visit'),
    ('free',     'Free'),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wizard(request):
    """Return the current wizard dict from the session (creating if absent)."""
    return request.session.setdefault('wizard', {})


def _save(request, key, value):
    """Persist a wizard section to the session."""
    wizard = request.session.setdefault('wizard', {})
    wizard[key] = value
    request.session.modified = True


def _identity_ctx(wizard):
    """Return identity dict with all keys guaranteed present (avoids VariableDoesNotExist in templates)."""
    raw = wizard.get('identity') or {}
    return {
        'gym_name':      raw.get('gym_name', ''),
        'tagline':       raw.get('tagline', ''),
        'primary_color': raw.get('primary_color', '#1a1a2e'),
        'accent_color':  raw.get('accent_color', '#e94560'),
        'logo_path':     raw.get('logo_path', ''),
    }


def _account_ctx(wizard):
    """Return owner account dict with all keys guaranteed present (avoids VariableDoesNotExist in templates)."""
    raw = wizard.get('owner') or {}
    return {
        'first_name': raw.get('first_name', ''),
        'last_name':  raw.get('last_name', ''),
        'email':      raw.get('email', ''),
    }


def _generate_schema_name(gym_name):
    """
    Derive a unique PostgreSQL schema name from the gym name.
    e.g. "Iron House Gym!" → "iron_house_gym"
    """
    base = re.sub(r'[^a-z0-9]+', '_', gym_name.lower()).strip('_')[:50]
    if not base:
        base = 'gym'
    schema_name = base
    n = 1
    while GymTenant.objects.filter(schema_name=schema_name).exists():
        schema_name = f'{base}_{n}'
        n += 1
    return schema_name


def _location_for_template(location):
    """
    Convert a stored location dict into a template-friendly version.
    The 'hours' dict (keyed by day code) becomes a list of dicts
    so Django templates can iterate without a custom filter.
    """
    return {
        'name':     location.get('name', ''),
        'address':  location.get('address', ''),
        'timezone': location.get('timezone', 'America/New_York'),
        'hours_list': [
            {
                'day':    day,
                'label':  DAY_NAMES[day],
                'open':   location.get('hours', {}).get(day, {}).get('open', '06:00'),
                'close':  location.get('hours', {}).get(day, {}).get('close', '22:00'),
                'closed': location.get('hours', {}).get(day, {}).get('closed', day in ('sat', 'sun')),
            }
            for day in DAYS
        ],
    }


def _parse_locations(post):
    """
    Extract all submitted location data from POST dict.
    Returns a list of location dicts.
    """
    # Detect how many locations were submitted
    locations = []
    idx = 0
    while f'location_{idx}_address' in post:
        hours = {}
        for day in DAYS:
            hours[day] = {
                'open':   post.get(f'location_{idx}_{day}_open', '06:00'),
                'close':  post.get(f'location_{idx}_{day}_close', '22:00'),
                'closed': f'location_{idx}_{day}_closed' in post,
            }
        locations.append({
            'name':     post.get(f'location_{idx}_name', f'Location {idx + 1}').strip(),
            'address':  post.get(f'location_{idx}_address', '').strip(),
            'timezone': post.get(f'location_{idx}_timezone', 'America/New_York'),
            'hours':    hours,
        })
        idx += 1
    return locations


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def wizard_start(request):
    """Clear any prior session state and jump to step 1."""
    request.session.pop('wizard', None)
    request.session.modified = True
    return redirect('setup:step1')


# ---------------------------------------------------------------------------
# Step 1 — Gym Identity
# ---------------------------------------------------------------------------

def step1(request):
    wizard = _wizard(request)

    if request.method == 'POST':
        gym_name      = request.POST.get('gym_name', '').strip()
        tagline       = request.POST.get('tagline', '').strip()
        primary_color = request.POST.get('primary_color', '#1a1a2e').strip()
        accent_color  = request.POST.get('accent_color', '#e94560').strip()

        errors = {}
        if not gym_name:
            errors['gym_name'] = 'Gym name is required.'

        if not errors:
            # Handle optional logo upload
            logo_path = wizard.get('identity', {}).get('logo_path')
            logo_file = request.FILES.get('logo')
            if logo_file:
                logo_dir = os.path.join(settings.MEDIA_ROOT, 'wizard')
                os.makedirs(logo_dir, exist_ok=True)
                ext = os.path.splitext(logo_file.name)[1].lower()
                fname = f'{uuid.uuid4().hex}{ext}'
                fpath = os.path.join(logo_dir, fname)
                with open(fpath, 'wb+') as dest:
                    for chunk in logo_file.chunks():
                        dest.write(chunk)
                logo_path = f'wizard/{fname}'

            schema_name = wizard.get('schema_name') or _generate_schema_name(gym_name)
            # Regenerate if gym_name changed
            prev_name = wizard.get('identity', {}).get('gym_name', '')
            if prev_name != gym_name:
                schema_name = _generate_schema_name(gym_name)

            _save(request, 'schema_name', schema_name)
            _save(request, 'identity', {
                'gym_name':      gym_name,
                'tagline':       tagline,
                'primary_color': primary_color,
                'accent_color':  accent_color,
                'logo_path':     logo_path,
            })
            return redirect('setup:step2')

        vals = {
            'gym_name':      gym_name,
            'tagline':       tagline,
            'primary_color': primary_color,
            'accent_color':  accent_color,
            'logo_path':     wizard.get('identity', {}).get('logo_path', ''),
        }
        return render(request, 'owner/step1_identity.html', {
            'step': 1, 'wizard': wizard, 'errors': errors,
            'vals': vals,
        })

    identity = _identity_ctx(wizard)
    return render(request, 'owner/step1_identity.html', {
        'step': 1, 'wizard': wizard,
        'vals': identity,
        'errors': {},
    })


# ---------------------------------------------------------------------------
# Step 2 — Location Setup
# ---------------------------------------------------------------------------

def step2(request):
    wizard = _wizard(request)

    if not wizard.get('identity'):
        return redirect('setup:step1')

    if request.method == 'POST':
        locations = _parse_locations(request.POST)
        errors = {}

        if not locations:
            errors['general'] = 'At least one location is required.'
        else:
            for i, loc in enumerate(locations):
                if not loc['address']:
                    errors[f'location_{i}_address'] = 'Address is required.'

        if not errors:
            _save(request, 'locations', locations)
            return redirect('setup:step3')

        return render(request, 'owner/step2_location.html', {
            'step': 2, 'wizard': wizard, 'errors': errors,
            'locations': [_location_for_template(l) for l in locations],
            'timezones': TIMEZONES,
        })

    # GET — restore previous locations or seed one blank location
    locations = wizard.get('locations') or [{
        'name': 'Main Location',
        'address': '',
        'timezone': 'America/New_York',
        'hours': {d: {'open': '06:00', 'close': '22:00', 'closed': d in ('sat', 'sun')} for d in DAYS},
    }]

    return render(request, 'owner/step2_location.html', {
        'step': 2, 'wizard': wizard,
        'locations': [_location_for_template(l) for l in locations],
        'timezones': TIMEZONES,
    })


# ---------------------------------------------------------------------------
# Step 3 — Owner Account
# ---------------------------------------------------------------------------

def step3(request):
    wizard = _wizard(request)

    if not wizard.get('locations'):
        return redirect('setup:step2')

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip().lower()
        password   = request.POST.get('password', '')
        confirm    = request.POST.get('confirm_password', '')

        errors = {}
        if not first_name:
            errors['first_name'] = 'First name is required.'
        if not last_name:
            errors['last_name'] = 'Last name is required.'
        if not email:
            errors['email'] = 'Email is required.'
        elif '@' not in email:
            errors['email'] = 'Enter a valid email address.'
        if not password:
            errors['password'] = 'Password is required.'
        elif len(password) < 8:
            errors['password'] = 'Password must be at least 8 characters.'
        elif password != confirm:
            errors['confirm_password'] = 'Passwords do not match.'

        # Check email uniqueness in the public schema
        if not errors.get('email'):
            from apps.accounts.models import User
            if User.objects.filter(email__iexact=email).exists():
                errors['email'] = 'An account with this email already exists.'

        if not errors:
            _save(request, 'owner', {
                'first_name': first_name,
                'last_name':  last_name,
                'email':      email,
                'password':   password,  # hashed by create_user() in the task
            })
            return redirect('setup:step4')

        vals = {
            'first_name': first_name,
            'last_name':  last_name,
            'email':      email,
        }
        return render(request, 'owner/step3_account.html', {
            'step': 3, 'wizard': wizard, 'errors': errors,
            'vals': vals,
        })

    return render(request, 'owner/step3_account.html', {
        'step': 3, 'wizard': wizard,
        'vals': _account_ctx(wizard),
        'errors': {},
    })


# ---------------------------------------------------------------------------
# Step 4 — Membership Plans
# ---------------------------------------------------------------------------

def step4(request):
    wizard = _wizard(request)

    if not wizard.get('owner'):
        return redirect('setup:step3')

    if request.method == 'POST':
        plans = []
        idx = 0
        while f'plan_{idx}_name' in request.POST:
            name    = request.POST.get(f'plan_{idx}_name', '').strip()
            price   = request.POST.get(f'plan_{idx}_price', '0').strip()
            cycle   = request.POST.get(f'plan_{idx}_billing_cycle', 'monthly')
            desc    = request.POST.get(f'plan_{idx}_description', '').strip()
            if name:
                plans.append({'name': name, 'price': price,
                               'billing_cycle': cycle, 'description': desc})
            idx += 1

        if not plans:
            plans = [{'name': 'Basic Membership', 'price': '0',
                      'billing_cycle': 'monthly', 'description': ''}]

        _save(request, 'plans', plans)
        return redirect('setup:step5')

    plans = wizard.get('plans') or [
        {'name': 'Basic Membership', 'price': '29', 'billing_cycle': 'monthly', 'description': ''},
        {'name': 'Premium Membership', 'price': '49', 'billing_cycle': 'monthly', 'description': ''},
    ]

    return render(request, 'owner/step4_plans.html', {
        'step': 4, 'wizard': wizard,
        'plans': plans, 'billing_cycles': BILLING_CYCLES,
    })


# ---------------------------------------------------------------------------
# Step 5 — Services Offered
# ---------------------------------------------------------------------------

def step5(request):
    wizard = _wizard(request)

    if not wizard.get('plans') is not None and not wizard.get('owner'):
        return redirect('setup:step4')

    if request.method == 'POST':
        selected = request.POST.getlist('services')
        custom_raw = request.POST.get('custom_services', '')
        custom = [s.strip() for s in custom_raw.split(',') if s.strip()]
        _save(request, 'services', {'selected': selected, 'custom': custom})
        return redirect('setup:step6')

    prev = wizard.get('services', {})
    return render(request, 'owner/step5_services.html', {
        'step': 5, 'wizard': wizard,
        'predefined': PREDEFINED_SERVICES,
        'selected': prev.get('selected', PREDEFINED_SERVICES[:4]),
        'custom_services': ', '.join(prev.get('custom', [])),
    })


# ---------------------------------------------------------------------------
# Step 6 — Staff Roles
# ---------------------------------------------------------------------------

def step6(request):
    wizard = _wizard(request)

    if not wizard.get('owner'):
        return redirect('setup:step3')

    if request.method == 'POST':
        roles = {role: (f'role_{role}' in request.POST) for role, *_ in STAFF_ROLES}
        _save(request, 'roles', roles)
        return redirect('setup:step7')

    prev_roles = wizard.get('roles', {r: True for r, *_ in STAFF_ROLES})
    return render(request, 'owner/step6_roles.html', {
        'step': 6, 'wizard': wizard,
        'staff_roles': STAFF_ROLES,
        'roles': prev_roles,
    })


# ---------------------------------------------------------------------------
# Step 7 — Preview & Confirm
# ---------------------------------------------------------------------------

def step7(request):
    wizard = _wizard(request)

    if not wizard.get('identity'):
        return redirect('setup:step1')

    schema_name = wizard.get('schema_name', '')
    identity    = wizard.get('identity', {})
    locations   = wizard.get('locations', [])
    owner       = wizard.get('owner', {})
    plans       = wizard.get('plans', [])
    services    = wizard.get('services', {})
    roles       = wizard.get('roles', {})

    subdomain = f"{schema_name}.gymforge.com"

    return render(request, 'owner/step7_preview.html', {
        'step': 7, 'wizard': wizard,
        'identity': identity,
        'locations': locations,
        'owner': owner,
        'plans': plans,
        'services': services,
        'roles': roles,
        'schema_name': schema_name,
        'subdomain': subdomain,
        'staff_roles': STAFF_ROLES,
    })


# ---------------------------------------------------------------------------
# Confirm — trigger Celery task
# ---------------------------------------------------------------------------

@require_POST
def confirm(request):
    wizard = _wizard(request)

    if not wizard.get('identity') or not wizard.get('owner'):
        return redirect('setup:step1')

    # Pass a plain dict — no Django objects, fully JSON-serializable
    wizard_data = dict(wizard)

    result = provision_gym.delay(wizard_data)

    # In dev (CELERY_TASK_ALWAYS_EAGER=True) result is already ready
    if result.ready():
        info = result.get()
        # Clear wizard session
        request.session.pop('wizard', None)
        request.session.modified = True
        return redirect(f'/auth/login/?setup=done&gym={info.get("schema_name", "")}')

    request.session.pop('wizard', None)
    request.session.modified = True
    return redirect('setup:pending', task_id=result.id)


# ---------------------------------------------------------------------------
# Pending — provisioning progress page
# ---------------------------------------------------------------------------

def pending(request, task_id):
    return render(request, 'owner/setup_pending.html', {'task_id': task_id})


def task_status(request, task_id):
    """
    HTMX polling endpoint. Returns HX-Redirect header when task is done.
    Returns an HTML progress snippet while still running.
    """
    from celery.result import AsyncResult
    result = AsyncResult(task_id)

    if result.ready():
        if result.successful():
            info = result.get()
            response = HttpResponse('')
            response['HX-Redirect'] = (
                f'/auth/login/?setup=done&gym={info.get("schema_name", "")}'
            )
            return response
        else:
            return HttpResponse(
                '<p class="text-red-400 text-sm">Provisioning failed. Please contact support.</p>'
            )

    # Still running — return a progress message
    meta = result.info or {}
    step_label = meta.get('step', 'Preparing your gym…')
    step_num   = meta.get('step_num', 0)
    html = f"""
    <div class="text-center">
      <p class="text-gray-300 text-sm mb-2">{step_label}</p>
      <div class="w-full bg-gray-800 rounded-full h-2">
        <div class="bg-brand h-2 rounded-full transition-all duration-500" style="width:{step_num * 6}%"></div>
      </div>
    </div>
    """
    return HttpResponse(html)


# ---------------------------------------------------------------------------
# HTMX Partials
# ---------------------------------------------------------------------------

def partial_location_form(request):
    """Return HTML block for a new location entry (HTMX append)."""
    idx = int(request.GET.get('idx', 1))
    blank = {
        'name': f'Location {idx + 1}',
        'address': '',
        'timezone': 'America/New_York',
        'hours': {d: {'open': '06:00', 'close': '22:00', 'closed': d in ('sat', 'sun')} for d in DAYS},
    }
    return render(request, 'owner/partials/location_form.html', {
        'location': _location_for_template(blank), 'idx': idx,
        'timezones': TIMEZONES,
    })


def partial_plan_row(request):
    """Return HTML row for a new membership plan (HTMX append)."""
    idx = int(request.GET.get('idx', 1))
    return render(request, 'owner/partials/plan_row.html', {
        'plan': {'name': '', 'price': '', 'billing_cycle': 'monthly', 'description': ''},
        'idx': idx, 'billing_cycles': BILLING_CYCLES,
    })
