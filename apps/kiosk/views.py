"""
Kiosk mode — fullscreen self-service check-in terminal.

Device authentication: DoorDevice.device_token stored in request.session['kiosk_device_token'].
The /kiosk/setup/ page lets staff enter the token once; all other views require it.

PIN: 4-digit, hashed on MemberProfile.pin_hash using Django's make_password / check_password.
Result screen auto-returns to idle after 5 seconds via JS.
"""
from datetime import date

from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.billing.models import MemberMembership
from apps.checkin.models import AccessRule, CheckIn, DoorDevice, MemberCard
from apps.core.models import Location
from apps.members.models import MemberProfile


_DAY_MAP = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}

_DENIAL_MESSAGES = {
    'denied_inactive':  'This card has been deactivated. Please visit the front desk.',
    'denied_payment':   'Your membership is not currently active. Please visit reception.',
    'denied_suspended': 'Your account has been suspended. Please see a manager.',
    'denied_hours':     'Access is not permitted at this time.',
    'denied_unknown':   'Card not recognised. Please try again or visit the front desk.',
    'denied_pin':       'Incorrect PIN. Please try again or use your card.',
    'denied_no_card':   'No card found matching that number. Please try again.',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_device(request) -> DoorDevice | None:
    token = request.session.get('kiosk_device_token')
    if not token:
        return None
    try:
        return DoorDevice.objects.select_related('location').get(
            device_token=token, is_active=True
        )
    except DoorDevice.DoesNotExist:
        return None


def _check_access_rule(device: DoorDevice, membership: MemberMembership) -> str | None:
    try:
        rule = AccessRule.objects.get(
            membership_tier=membership.tier,
            location=device.location,
            is_active=True,
        )
    except AccessRule.DoesNotExist:
        return None  # No rule = unrestricted

    now = timezone.localtime()
    current_day = _DAY_MAP[now.weekday()]
    current_time = now.time()

    if rule.days_allowed and current_day not in rule.days_allowed:
        return 'denied_hours'

    if rule.access_start_time and rule.access_end_time:
        if not (rule.access_start_time <= current_time <= rule.access_end_time):
            return 'denied_hours'

    return None


def _validate_and_checkin(device: DoorDevice, member: MemberProfile) -> dict:
    """
    Run full membership + access-rule validation, create CheckIn on success.
    Returns dict: {'ok': bool, 'member': member, 'message': str, 'code': str}
    """
    membership = MemberMembership.objects.filter(
        member=member
    ).order_by('-start_date').first()

    if not membership:
        return {'ok': False, 'code': 'denied_payment',
                'message': _DENIAL_MESSAGES['denied_payment']}

    if membership.status == 'suspended':
        return {'ok': False, 'code': 'denied_suspended',
                'message': _DENIAL_MESSAGES['denied_suspended']}

    if not membership.allows_access:
        return {'ok': False, 'code': 'denied_payment',
                'message': _DENIAL_MESSAGES['denied_payment']}

    rule_result = _check_access_rule(device, membership)
    if rule_result:
        return {'ok': False, 'code': rule_result,
                'message': _DENIAL_MESSAGES[rule_result]}

    # Check already checked in today
    already = CheckIn.objects.filter(
        member=member,
        location=device.location,
        checked_in_at__date=date.today(),
        checked_out_at__isnull=True,
    ).exists()

    if not already:
        CheckIn.objects.create(
            member=member,
            location=device.location,
            method='kiosk',
        )

    return {'ok': True, 'code': 'granted', 'member': member,
            'message': f'Welcome, {member.full_name}!'}


def _gym_context(device: DoorDevice | None) -> dict:
    """Branding context from the device's location tenant."""
    if not device:
        return {}
    location = device.location
    # Get gym branding from the public tenant's GymProfile if available
    try:
        from apps.gym_owner.models import GymProfile
        profile = GymProfile.objects.first()
        return {
            'gym_name': profile.gym_name if profile else location.name,
            'primary_color': profile.primary_color if profile else '#1a1a2e',
            'accent_color': profile.accent_color if profile else '#e94560',
            'gym_logo_url': profile.logo.url if (profile and profile.logo) else None,
        }
    except Exception:
        return {
            'gym_name': location.name,
            'primary_color': '#1a1a2e',
            'accent_color': '#e94560',
            'gym_logo_url': None,
        }


# ---------------------------------------------------------------------------
# Setup — enter device token once to authenticate the kiosk session
# ---------------------------------------------------------------------------

def setup(request):
    """Staff enter a DoorDevice token to activate this kiosk session."""
    error = None

    if request.method == 'POST':
        token = request.POST.get('device_token', '').strip()
        try:
            device = DoorDevice.objects.get(device_token=token, is_active=True)
            request.session['kiosk_device_token'] = token
            request.session.set_expiry(86400 * 30)  # 30 days
            device.last_seen = timezone.now()
            device.save(update_fields=['last_seen'])
            return redirect('kiosk:idle')
        except DoorDevice.DoesNotExist:
            error = "Invalid or inactive device token."

    return render(request, 'kiosk/setup.html', {'error': error})


# ---------------------------------------------------------------------------
# Idle screen
# ---------------------------------------------------------------------------

def idle(request):
    device = _get_device(request)
    if not device:
        return redirect('kiosk:setup')

    ctx = _gym_context(device)
    ctx['device'] = device
    return render(request, 'kiosk/idle.html', ctx)


# ---------------------------------------------------------------------------
# Card check-in (card number or RFID text field)
# ---------------------------------------------------------------------------

@require_POST
def card_checkin(request):
    device = _get_device(request)
    if not device:
        return redirect('kiosk:setup')

    card_number = request.POST.get('card_number', '').strip().upper()
    if not card_number:
        return redirect('kiosk:idle')

    try:
        card = MemberCard.objects.select_related('member__user').get(card_number=card_number)
    except MemberCard.DoesNotExist:
        request.session['kiosk_result'] = {
            'ok': False, 'code': 'denied_unknown',
            'message': _DENIAL_MESSAGES['denied_unknown'],
        }
        return redirect('kiosk:result')

    if not card.is_active:
        request.session['kiosk_result'] = {
            'ok': False, 'code': 'denied_inactive',
            'message': _DENIAL_MESSAGES['denied_inactive'],
        }
        return redirect('kiosk:result')

    result = _validate_and_checkin(device, card.member)
    if result['ok']:
        result['member_name'] = result['member'].full_name
        result['loyalty_points'] = result['member'].loyalty_points
        result['profile_photo_url'] = (
            result['member'].user.profile_photo.url
            if result['member'].user.profile_photo
            else None
        )
        del result['member']  # not JSON-serialisable in session
    request.session['kiosk_result'] = result
    return redirect('kiosk:result')


# ---------------------------------------------------------------------------
# PIN check-in
# ---------------------------------------------------------------------------

@require_POST
def pin_checkin(request):
    device = _get_device(request)
    if not device:
        return redirect('kiosk:setup')

    pin = request.POST.get('pin', '').strip()
    if not pin or len(pin) != 4 or not pin.isdigit():
        request.session['kiosk_result'] = {
            'ok': False, 'code': 'denied_pin',
            'message': 'PIN must be exactly 4 digits.',
        }
        return redirect('kiosk:result')

    # Find member by PIN at this location (scan all — PINs are rare)
    matched = None
    for mp in MemberProfile.objects.filter(pin_hash__gt='').select_related('user'):
        if mp.pin_hash and check_password(pin, mp.pin_hash):
            matched = mp
            break

    if not matched:
        request.session['kiosk_result'] = {
            'ok': False, 'code': 'denied_pin',
            'message': _DENIAL_MESSAGES['denied_pin'],
        }
        return redirect('kiosk:result')

    result = _validate_and_checkin(device, matched)
    if result['ok']:
        result['member_name'] = result['member'].full_name
        result['loyalty_points'] = result['member'].loyalty_points
        result['profile_photo_url'] = (
            result['member'].user.profile_photo.url
            if result['member'].user.profile_photo
            else None
        )
        del result['member']
    request.session['kiosk_result'] = result
    return redirect('kiosk:result')


# ---------------------------------------------------------------------------
# Result screen
# ---------------------------------------------------------------------------

def result(request):
    device = _get_device(request)
    if not device:
        return redirect('kiosk:setup')

    data = request.session.pop('kiosk_result', None)
    if not data:
        return redirect('kiosk:idle')

    ctx = _gym_context(device)
    ctx.update(data)
    ctx['device'] = device
    return render(request, 'kiosk/result.html', ctx)


# ---------------------------------------------------------------------------
# Guest check-in
# ---------------------------------------------------------------------------

@require_POST
def guest_checkin(request):
    device = _get_device(request)
    if not device:
        return redirect('kiosk:setup')

    # CheckIn.member is non-nullable — track via session count
    today_key = f"kiosk_guest_{device.location_id}_{date.today().isoformat()}"
    request.session[today_key] = request.session.get(today_key, 0) + 1

    request.session['kiosk_result'] = {
        'ok': True,
        'code': 'guest',
        'message': 'Guest visit logged. Welcome!',
        'member_name': 'Guest',
        'loyalty_points': None,
        'profile_photo_url': None,
    }
    return redirect('kiosk:result')


# ---------------------------------------------------------------------------
# Door Scanner — fullscreen tablet UI for a physical door reader
# ---------------------------------------------------------------------------

def door_scanner(request):
    """
    Fullscreen door scanner page for a tablet mounted at the gym entrance.

    Works with:
    - USB HID card readers (type card number + Enter)
    - QR code scanners (same HID keyboard mode)
    - Manual entry fallback (on-screen button)

    The page POSTs to /api/v1/door/validate/ with the card number
    and displays a full-screen green (granted) or red (denied) result
    for 4 seconds before returning to idle.

    Setup: visit /kiosk/setup/ first to set the device token in session.
    """
    device = _get_device(request)
    if not device:
        return redirect('kiosk:setup')

    ctx = _gym_context(device)
    ctx['device'] = device
    return render(request, 'kiosk/door_scanner.html', ctx)


# ---------------------------------------------------------------------------
# Set PIN (for members via front desk — not a kiosk-facing page)
# ---------------------------------------------------------------------------

def set_pin(request, member_pk):
    """Front-desk helper: set or reset a member's kiosk PIN."""
    from django.contrib.auth.decorators import login_required
    from django.contrib import messages as django_messages

    member = get_object_or_404(MemberProfile, pk=member_pk)

    if request.method == 'POST':
        pin = request.POST.get('pin', '').strip()
        if len(pin) == 4 and pin.isdigit():
            member.pin_hash = make_password(pin)
            member.save(update_fields=['pin_hash'])
            django_messages.success(request, f"PIN set for {member.full_name}.")
        else:
            django_messages.error(request, "PIN must be exactly 4 digits.")
        return redirect('front_desk:member_detail', member_pk=member_pk)

    return render(request, 'kiosk/set_pin.html', {'member': member})
