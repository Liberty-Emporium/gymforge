"""
Gym Owner portal views.

All views require the user to be authenticated with role='gym_owner'.
"""
from functools import wraps

from django.conf import settings
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.crypto import get_random_string


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def gym_owner_required(view_func):
    """Redirect to login if not an authenticated gym owner."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'{settings.LOGIN_URL}?next={request.path}')
        if request.user.role != 'gym_owner':
            return redirect(settings.LOGIN_URL)
        return view_func(request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@gym_owner_required
def dashboard(request):
    from apps.billing.models import CardPurchase, MemberMembership
    from apps.checkin.models import CheckIn
    from apps.leads.models import Lead
    from apps.accounts.models import User

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timezone.timedelta(days=30)

    active_member_count = MemberMembership.objects.filter(status='active').count()

    try:
        revenue_month = (
            CardPurchase.objects
            .filter(processed_at__gte=month_start, status='completed')
            .aggregate(total=Sum('amount'))['total'] or 0
        )
    except Exception:
        revenue_month = 0

    active_ids = set(
        MemberMembership.objects.filter(status='active').values_list('member_id', flat=True)
    )
    recent_ids = set(
        CheckIn.objects.filter(checked_in_at__gte=thirty_days_ago).values_list('member_id', flat=True)
    )
    churn_risk = len(active_ids - recent_ids)

    try:
        from apps.inventory.models import MaintenanceTicket
        open_tickets = MaintenanceTicket.objects.filter(status='open').count()
    except Exception:
        open_tickets = 0

    try:
        from apps.members.models import MemberProfile
        new_members = MemberProfile.objects.filter(
            join_date__gte=month_start.date()
        ).count()
    except Exception:
        new_members = 0

    try:
        from apps.scheduling.models import Booking
        top = (
            Booking.objects
            .filter(
                status__in=['confirmed', 'attended'],
                class_session__start_datetime__year=now.year,
                class_session__start_datetime__month=now.month,
            )
            .values('class_session__class_type__name')
            .annotate(total=Count('id'))
            .order_by('-total')
            .first()
        )
        top_class = top['class_session__class_type__name'] if top else '—'
    except Exception:
        top_class = '—'

    recent_checkins = (
        CheckIn.objects
        .select_related('member__user', 'location')
        .order_by('-checked_in_at')[:12]
    )

    open_leads = Lead.objects.exclude(status__in=['converted', 'lost']).count()
    staff_count = (
        User.objects.filter(is_active=True)
        .exclude(role__in=['member', 'platform_admin'])
        .count()
    )

    return render(request, 'owner/dashboard.html', {
        'active_member_count': active_member_count,
        'revenue_month':       revenue_month,
        'churn_risk':          churn_risk,
        'open_tickets':        open_tickets,
        'new_members':         new_members,
        'top_class':           top_class,
        'recent_checkins':     recent_checkins,
        'open_leads':          open_leads,
        'staff_count':         staff_count,
    })


# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------

@gym_owner_required
def branding_preview(request):
    from apps.core.models import GymProfile
    try:
        profile = GymProfile.objects.get()
    except GymProfile.DoesNotExist:
        profile = None
    return render(request, 'owner/branding_preview.html', {'profile': profile})


@gym_owner_required
def branding_edit(request):
    from apps.core.models import GymProfile
    try:
        profile = GymProfile.objects.get()
    except GymProfile.DoesNotExist:
        return redirect('gym_owner:branding_preview')

    errors = {}

    if request.method == 'POST':
        gym_name      = request.POST.get('gym_name', '').strip()
        tagline       = request.POST.get('tagline', '').strip()
        about_text    = request.POST.get('about_text', '').strip()
        primary_color = request.POST.get('primary_color', '#1a1a2e').strip()
        accent_color  = request.POST.get('accent_color', '#e94560').strip()

        if not gym_name:
            errors['gym_name'] = 'Gym name is required.'
        if primary_color and not primary_color.startswith('#'):
            errors['primary_color'] = 'Enter a valid hex color (e.g. #1a1a2e).'
        if accent_color and not accent_color.startswith('#'):
            errors['accent_color'] = 'Enter a valid hex color (e.g. #e94560).'

        if not errors:
            profile.gym_name         = gym_name
            profile.tagline          = tagline
            profile.about_text       = about_text
            profile.primary_color    = primary_color
            profile.accent_color     = accent_color
            profile.social_instagram = request.POST.get('social_instagram', '').strip()
            profile.social_facebook  = request.POST.get('social_facebook', '').strip()
            profile.social_tiktok    = request.POST.get('social_tiktok', '').strip()
            profile.social_youtube   = request.POST.get('social_youtube', '').strip()
            if 'logo' in request.FILES:
                profile.logo = request.FILES['logo']
            elif request.POST.get('clear_logo'):
                profile.logo = None
            profile.save()
            return redirect('gym_owner:branding_preview')

    return render(request, 'owner/branding_edit.html', {
        'profile': profile,
        'errors':  errors,
    })


# ---------------------------------------------------------------------------
# Membership Tiers
# ---------------------------------------------------------------------------

@gym_owner_required
def tier_list(request):
    from apps.billing.models import MembershipTier
    tiers = MembershipTier.objects.prefetch_related('included_services').order_by('price')
    return render(request, 'owner/tiers.html', {'tiers': tiers})


@gym_owner_required
def tier_create(request):
    from apps.billing.models import MembershipTier
    from apps.core.models import Service
    services = Service.objects.filter(is_active=True)
    errors = {}

    if request.method == 'POST':
        errors, tier_data = _parse_tier_post(request.POST)
        selected_services = request.POST.getlist('included_services')
        if not errors:
            tier = MembershipTier.objects.create(**tier_data)
            if selected_services:
                tier.included_services.set(
                    Service.objects.filter(id__in=selected_services)
                )
            return redirect('gym_owner:tier_list')

    return render(request, 'owner/tier_form.html', {
        'tier':           None,
        'services':       services,
        'errors':         errors,
        'post':           request.POST,
        'billing_cycles': _BILLING_CYCLES,
    })


@gym_owner_required
def tier_edit(request, pk):
    from apps.billing.models import MembershipTier
    from apps.core.models import Service
    tier     = get_object_or_404(MembershipTier, pk=pk)
    services = Service.objects.filter(is_active=True)
    errors   = {}

    if request.method == 'POST':
        errors, tier_data = _parse_tier_post(request.POST)
        selected_services = request.POST.getlist('included_services')
        if not errors:
            for field, value in tier_data.items():
                setattr(tier, field, value)
            tier.save()
            tier.included_services.set(
                Service.objects.filter(id__in=selected_services)
            )
            return redirect('gym_owner:tier_list')

    return render(request, 'owner/tier_form.html', {
        'tier':           tier,
        'services':       services,
        'errors':         errors,
        'post':           request.POST if request.method == 'POST' else None,
        'billing_cycles': _BILLING_CYCLES,
    })


@gym_owner_required
def tier_deactivate(request, pk):
    if request.method != 'POST':
        return redirect('gym_owner:tier_list')
    from apps.billing.models import MembershipTier
    tier = get_object_or_404(MembershipTier, pk=pk)
    tier.is_active = False
    tier.save(update_fields=['is_active'])
    return redirect('gym_owner:tier_list')


_BILLING_CYCLES = [
    ('monthly', 'Monthly'),
    ('annual',  'Annual'),
    ('drop_in', 'Drop-in'),
    ('free',    'Free'),
]


def _parse_tier_post(post):
    errors = {}
    name          = post.get('name', '').strip()
    price_raw     = post.get('price', '').strip()
    billing_cycle = post.get('billing_cycle', '').strip()
    description   = post.get('description', '').strip()

    if not name:
        errors['name'] = 'Tier name is required.'
    price = None
    try:
        price = float(price_raw)
        if price < 0:
            errors['price'] = 'Price cannot be negative.'
    except (ValueError, TypeError):
        errors['price'] = 'Enter a valid price.'
    if not billing_cycle:
        errors['billing_cycle'] = 'Select a billing cycle.'

    def _int(val, default=0):
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def _dec(val):
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.00

    data = {
        'name':                       name,
        'price':                      price,
        'billing_cycle':              billing_cycle,
        'description':                description,
        'trial_days':                 _int(post.get('trial_days', '0')),
        'cancellation_window_hours':  _int(post.get('cancellation_window_hours', '2'), 2),
        'no_show_fee':                _dec(post.get('no_show_fee', '0')),
        'late_cancel_fee':            _dec(post.get('late_cancel_fee', '0')),
    }
    return errors, data


# ---------------------------------------------------------------------------
# Staff Management
# ---------------------------------------------------------------------------

STAFF_ROLES = [
    ('manager',      'Manager'),
    ('trainer',      'Trainer'),
    ('front_desk',   'Front Desk'),
    ('cleaner',      'Cleaner'),
    ('nutritionist', 'Nutritionist'),
]
_STAFF_ROLE_KEYS = {r[0] for r in STAFF_ROLES}


@gym_owner_required
def staff_list(request):
    from apps.accounts.models import User
    staff = (
        User.objects
        .filter(is_active=True)
        .exclude(role__in=['member', 'platform_admin'])
        .order_by('role', 'first_name', 'last_name')
    )
    return render(request, 'owner/staff.html', {
        'staff': staff,
        'roles': STAFF_ROLES,
    })


@gym_owner_required
def staff_invite(request):
    from apps.accounts.models import User
    errors = {}

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip().lower()
        role       = request.POST.get('role', '').strip()
        phone      = request.POST.get('phone', '').strip()

        if not first_name:
            errors['first_name'] = 'First name is required.'
        if not email or '@' not in email:
            errors['email'] = 'Enter a valid email address.'
        elif User.objects.filter(email=email).exists():
            errors['email'] = 'A user with this email already exists.'
        if role not in _STAFF_ROLE_KEYS:
            errors['role'] = 'Select a valid role.'

        if not errors:
            temp_password = get_random_string(12)
            User.objects.create_user(
                username=email,
                email=email,
                password=temp_password,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                role=role,
            )
            # TODO Step 38: send invitation email with temp_password
            return redirect('gym_owner:staff_list')

    return render(request, 'owner/staff_invite.html', {
        'roles':  STAFF_ROLES,
        'errors': errors,
        'post':   request.POST,
    })


@gym_owner_required
def staff_deactivate(request, pk):
    if request.method != 'POST':
        return redirect('gym_owner:staff_list')
    from apps.accounts.models import User
    member = get_object_or_404(User, pk=pk)
    if member.role in _STAFF_ROLE_KEYS:
        member.is_active = False
        member.save(update_fields=['is_active'])
    return redirect('gym_owner:staff_list')


# ---------------------------------------------------------------------------
# Location Management
# ---------------------------------------------------------------------------

DAYS = [
    ('mon', 'Monday'), ('tue', 'Tuesday'), ('wed', 'Wednesday'),
    ('thu', 'Thursday'), ('fri', 'Friday'), ('sat', 'Saturday'), ('sun', 'Sunday'),
]


@gym_owner_required
def location_list(request):
    from apps.core.models import Location
    locations = Location.objects.prefetch_related('hours').order_by('name')
    return render(request, 'owner/locations.html', {'locations': locations})


@gym_owner_required
def location_create(request):
    from apps.core.models import Location
    errors = {}

    if request.method == 'POST':
        name    = request.POST.get('name', '').strip()
        address = request.POST.get('address', '').strip()

        if not name:
            errors['name'] = 'Location name is required.'
        if not address:
            errors['address'] = 'Address is required.'

        if not errors:
            location = Location.objects.create(
                name=name,
                address=address,
                phone=request.POST.get('phone', '').strip(),
                email=request.POST.get('email', '').strip(),
                timezone=request.POST.get('timezone', 'America/New_York').strip(),
            )
            _save_location_hours(request, location)
            return redirect('gym_owner:location_list')

    return render(request, 'owner/location_form.html', {
        'location':  None,
        'days':      DAYS,
        'errors':    errors,
        'post':      request.POST,
        'hours_map': {},
    })


@gym_owner_required
def location_edit(request, pk):
    from apps.core.models import Location
    location = get_object_or_404(Location, pk=pk)
    errors = {}

    if request.method == 'POST':
        name    = request.POST.get('name', '').strip()
        address = request.POST.get('address', '').strip()

        if not name:
            errors['name'] = 'Location name is required.'
        if not address:
            errors['address'] = 'Address is required.'

        if not errors:
            location.name      = name
            location.address   = address
            location.phone     = request.POST.get('phone', '').strip()
            location.email     = request.POST.get('email', '').strip()
            location.timezone  = request.POST.get('timezone', 'America/New_York').strip()
            location.is_active = request.POST.get('is_active') == 'on'
            location.save()
            _save_location_hours(request, location)
            return redirect('gym_owner:location_list')

    hours_map = {h.day: h for h in location.hours.all()}
    return render(request, 'owner/location_form.html', {
        'location':  location,
        'days':      DAYS,
        'errors':    errors,
        'post':      request.POST if request.method == 'POST' else None,
        'hours_map': hours_map,
    })


def _save_location_hours(request, location):
    from apps.core.models import LocationHours
    for day, _ in DAYS:
        is_closed  = request.POST.get(f'hours_{day}_closed') == 'on'
        open_time  = request.POST.get(f'hours_{day}_open',  '').strip() or None
        close_time = request.POST.get(f'hours_{day}_close', '').strip() or None
        LocationHours.objects.update_or_create(
            location=location,
            day=day,
            defaults={
                'is_closed':  is_closed,
                'open_time':  None if is_closed else open_time,
                'close_time': None if is_closed else close_time,
            },
        )


# ---------------------------------------------------------------------------
# AI Business Assistant
# ---------------------------------------------------------------------------

@gym_owner_required
def ai_chat(request):
    from apps.ai_coach.models import OwnerAIConversation
    conversation = (
        OwnerAIConversation.objects
        .filter(owner=request.user)
        .order_by('-started_at')
        .first()
    )
    if not conversation:
        conversation = OwnerAIConversation.objects.create(
            owner=request.user,
            conversation_history=[],
        )
    return render(request, 'owner/ai_chat.html', {'conversation': conversation})


@gym_owner_required
def ai_chat_send(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    from apps.ai_coach.client import GymForgeAIClient
    from apps.ai_coach.context import build_owner_context
    from apps.ai_coach.models import OwnerAIConversation
    from apps.ai_coach.prompts import render_owner_prompt

    user_message = request.POST.get('message', '').strip()
    if not user_message:
        return HttpResponse('', status=200)

    conversation_id = request.POST.get('conversation_id')
    try:
        conversation = OwnerAIConversation.objects.get(
            id=conversation_id, owner=request.user
        )
    except (OwnerAIConversation.DoesNotExist, ValueError, TypeError):
        conversation = OwnerAIConversation.objects.create(
            owner=request.user,
            conversation_history=[],
        )

    context = build_owner_context(request.user)
    system_prompt = render_owner_prompt(context)
    ai_client = GymForgeAIClient(
        system_prompt=system_prompt,
        conversation_history=conversation.conversation_history,
    )

    try:
        reply = ai_client.send_message(user_message)
        conversation.conversation_history = ai_client.get_history()
        conversation.save(update_fields=['conversation_history', 'last_message_at'])
    except Exception:
        reply = "I'm unable to respond right now. Please try again shortly."

    return render(request, 'owner/partials/ai_message.html', {
        'user_message': user_message,
        'reply':        reply,
    })


@gym_owner_required
def ai_chat_new(request):
    """Start a fresh AI conversation."""
    if request.method == 'POST':
        from apps.ai_coach.models import OwnerAIConversation
        OwnerAIConversation.objects.create(
            owner=request.user,
            conversation_history=[],
        )
    return redirect('gym_owner:ai_chat')


# ---------------------------------------------------------------------------
# GymProfile Settings
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Member Management (owner view)
# ---------------------------------------------------------------------------

@gym_owner_required
def member_list(request):
    from apps.members.models import MemberProfile
    from apps.billing.models import MemberMembership

    status_filter = request.GET.get('filter', '')

    members_qs = (
        MemberProfile.objects
        .select_related('user')
        .order_by('-join_date')
    )

    # Attach active membership status via subquery-friendly approach
    active_memberships = {
        m.member_id: m
        for m in MemberMembership.objects.filter(
            status__in=['active', 'overdue', 'expiring', 'frozen', 'suspended']
        ).select_related('tier')
    }

    members = []
    for mp in members_qs:
        membership = active_memberships.get(mp.pk)
        status = membership.status if membership else 'none'
        if status_filter == 'churn' and status not in ['active', 'expiring']:
            continue
        members.append({
            'profile':    mp,
            'membership': membership,
            'status':     status,
        })

    return render(request, 'owner/members.html', {
        'members':       members,
        'status_filter': status_filter,
        'total':         len(members),
    })


# ---------------------------------------------------------------------------
# Stub views — sections not yet fully implemented
# ---------------------------------------------------------------------------

@gym_owner_required
def schedule_view(request):
    return render(request, 'owner/stub.html', {
        'section_title': 'Schedule',
        'section_icon':  'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
        'description':   'Class scheduling and session management is coming soon.',
    })


@gym_owner_required
def analytics_view(request):
    return render(request, 'owner/stub.html', {
        'section_title': 'Analytics',
        'section_icon':  'M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z',
        'description':   'Advanced analytics and revenue reporting is coming soon.',
    })


@gym_owner_required
def inventory_view(request):
    return render(request, 'owner/stub.html', {
        'section_title': 'Inventory',
        'section_icon':  'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
        'description':   'Equipment and inventory tracking is coming soon.',
    })


FEATURE_KEYS = [
    ('community_feed',  'Community Feed'),
    ('shop',            'Shop / POS'),
    ('loyalty',         'Loyalty Program'),
    ('ai_coach',        'AI Coach (Members)'),
    ('class_booking',   'Class Booking'),
    ('nutrition_plans', 'Nutrition Plans'),
]


@gym_owner_required
def gym_settings(request):
    from apps.core.models import GymProfile
    try:
        profile = GymProfile.objects.get()
    except GymProfile.DoesNotExist:
        return render(request, 'owner/gym_settings.html', {
            'profile': None, 'feature_keys': FEATURE_KEYS,
        })

    saved = False

    if request.method == 'POST':
        profile.welcome_message  = request.POST.get('welcome_message', '').strip()
        profile.waiver_text      = request.POST.get('waiver_text', '').strip()
        profile.email_signature  = request.POST.get('email_signature', '').strip()
        profile.features_enabled = {
            key: request.POST.get(f'feature_{key}') == 'on'
            for key, _ in FEATURE_KEYS
        }
        profile.save(update_fields=[
            'welcome_message', 'waiver_text', 'email_signature', 'features_enabled',
        ])
        saved = True

    # Pre-compute enabled state for each feature (default True if key not in dict)
    feature_states = [
        (key, label, bool(profile.features_enabled.get(key, True)))
        for key, label in FEATURE_KEYS
    ]

    return render(request, 'owner/gym_settings.html', {
        'profile':        profile,
        'feature_states': feature_states,
        'saved':          saved,
    })
