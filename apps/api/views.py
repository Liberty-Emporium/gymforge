"""
Door Agent REST API — Section 7

POST /api/v1/door/validate/
    Called by Raspberry Pi door agents in real time to validate an RFID tap.
    Auth: device_token field in JSON body.
    Returns: result + member_name + denial_reason (JSON).
    Side-effects: CardScanLog entry (immutable), CheckIn record, loyalty points.

GET /api/v1/door/status/
    Health-check endpoint for the door agent.
    Auth: X-Device-Token request header.
    Returns: device info + last 10 scan results.

Design rules (Section 7):
  - No CSRF, no session, no JWT — device_token IS the auth.
  - Every tap is logged to CardScanLog — no exceptions except denied_unknown
    (CardScanLog.card is a non-nullable FK; without a card record we cannot log).
  - Optimised with select_related / prefetch_related to avoid N+1 queries.
  - DoorDevice.last_seen updated on every request that includes a valid device_token.
"""
import json

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.billing.models import MemberMembership
from apps.checkin.models import AccessRule, CardScanLog, CheckIn, DoorDevice, MemberCard
from apps.loyalty.utils import award_loyalty_points


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DAY_MAP = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}


def _json_body(request) -> dict | None:
    """Parse the JSON request body. Returns None on failure."""
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _auth_device(token: str) -> DoorDevice | None:
    """
    Look up and return the DoorDevice for this token, updating last_seen.
    Returns None if the token is unknown or the device is inactive.
    """
    try:
        device = DoorDevice.objects.select_related('location').get(
            device_token=token,
            is_active=True,
        )
    except DoorDevice.DoesNotExist:
        return None
    device.mark_seen()
    return device


def _check_access_rule(device: DoorDevice, membership: MemberMembership) -> str | None:
    """
    Check whether the AccessRule for (membership_tier, location) permits
    access at the current time and day.

    Returns:
        None          — access is permitted (or no rule exists → unrestricted)
        'denied_hours' — outside allowed time window or day
    """
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

    # Day check — empty list means all days allowed
    if rule.days_allowed and current_day not in rule.days_allowed:
        return 'denied_hours'

    # Time window check — null times mean 24/7
    if rule.access_start_time and rule.access_end_time:
        if not (rule.access_start_time <= current_time <= rule.access_end_time):
            return 'denied_hours'

    return None


def _log_scan(card: MemberCard, device: DoorDevice, result: str, scan_type: str) -> None:
    """Write an immutable CardScanLog entry. Never raises."""
    try:
        CardScanLog.objects.create(
            card=card,
            device=device,
            result=result,
            scan_type=scan_type,
        )
    except Exception:
        pass  # Scan log failure must never block door response


_DENIAL_MESSAGES = {
    'denied_inactive':  'This card has been deactivated. Please see the front desk.',
    'denied_payment':   'Your membership is inactive or payment is overdue.',
    'denied_suspended': 'Your account has been suspended. Please contact us.',
    'denied_hours':     'Access is not permitted at this time.',
    'denied_unknown':   'Card not recognised. Please see the front desk.',
}


# ---------------------------------------------------------------------------
# POST /api/v1/door/validate/
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(['POST'])
def validate(request):
    """
    Validate an RFID tap and decide whether to grant or deny access.

    Request JSON:
        device_token  str  — device authentication token
        rfid_token    str  — SHA-256 token stored on the card
        scan_type     str  — 'entry' | 'exit' | 'studio' | 'locker' | 'purchase' | 'kiosk'
                             (optional, defaults to 'entry')

    Response JSON:
        result        str  — 'granted' | denial code
        member_name   str  — member's full name (null on denied_unknown)
        card_number   str  — e.g. 'GF-00001' (null on denied_unknown)
        denial_reason str  — human-readable reason (null on granted)
        timestamp     str  — ISO-8601 UTC
    """
    body = _json_body(request)
    if not body:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    device_token = body.get('device_token', '').strip()
    rfid_token   = body.get('rfid_token', '').strip()
    card_number  = body.get('card_number', '').strip().upper()  # from USB reader / QR
    scan_type    = body.get('scan_type', 'entry').strip()

    # ── 1. Authenticate device ────────────────────────────────────────────
    if not device_token:
        return JsonResponse({'error': 'device_token required'}, status=401)

    device = _auth_device(device_token)
    if not device:
        return JsonResponse({'error': 'Unknown or inactive device'}, status=401)

    # Validate scan_type against model choices
    valid_scan_types = {t[0] for t in CardScanLog.SCAN_TYPES}
    if scan_type not in valid_scan_types:
        scan_type = 'entry'

    now_iso = timezone.now().isoformat()

    # ── 2. Look up RFID card ──────────────────────────────────────────────
    if not rfid_token:
        return JsonResponse(
            {
                'result': 'denied_unknown',
                'member_name': None,
                'card_number': None,
                'denial_reason': _DENIAL_MESSAGES['denied_unknown'],
                'timestamp': now_iso,
            },
            status=200,
        )

    # Lookup by rfid_token (RFID hardware) OR card_number (USB/QR reader)
    card = None
    if rfid_token:
        try:
            card = (
                MemberCard.objects
                .select_related('member__user', 'member')
                .get(rfid_token=rfid_token)
            )
        except MemberCard.DoesNotExist:
            pass
    if card is None and card_number:
        try:
            card = (
                MemberCard.objects
                .select_related('member__user', 'member')
                .get(card_number=card_number)
            )
        except MemberCard.DoesNotExist:
            pass
    if card is None:
        # Cannot log — no card record exists
        return JsonResponse(
            {
                'result': 'denied_unknown',
                'member_name': None,
                'card_number': None,
                'denial_reason': _DENIAL_MESSAGES['denied_unknown'],
                'timestamp': now_iso,
            },
            status=200,
        )

    member = card.member
    member_name = member.full_name or member.email

    # ── 3. Check card is active ───────────────────────────────────────────
    if not card.is_active:
        _log_scan(card, device, 'denied_inactive', scan_type)
        return JsonResponse(
            {
                'result': 'denied_inactive',
                'member_name': member_name,
                'card_number': card.card_number,
                'denial_reason': _DENIAL_MESSAGES['denied_inactive'],
                'timestamp': now_iso,
            },
            status=200,
        )

    # ── 4. Check membership ───────────────────────────────────────────────
    membership = (
        MemberMembership.objects
        .select_related('tier')
        .filter(member=member)
        .order_by('-start_date')
        .first()
    )

    if not membership:
        _log_scan(card, device, 'denied_payment', scan_type)
        return JsonResponse(
            {
                'result': 'denied_payment',
                'member_name': member_name,
                'card_number': card.card_number,
                'denial_reason': _DENIAL_MESSAGES['denied_payment'],
                'timestamp': now_iso,
            },
            status=200,
        )

    if membership.status == 'suspended':
        _log_scan(card, device, 'denied_suspended', scan_type)
        return JsonResponse(
            {
                'result': 'denied_suspended',
                'member_name': member_name,
                'card_number': card.card_number,
                'denial_reason': _DENIAL_MESSAGES['denied_suspended'],
                'timestamp': now_iso,
            },
            status=200,
        )

    # 'overdue', 'cancelled' → denied_payment
    if not membership.allows_access:
        _log_scan(card, device, 'denied_payment', scan_type)
        return JsonResponse(
            {
                'result': 'denied_payment',
                'member_name': member_name,
                'card_number': card.card_number,
                'denial_reason': _DENIAL_MESSAGES['denied_payment'],
                'timestamp': now_iso,
            },
            status=200,
        )

    # ── 5. Check access rule (time/day) ───────────────────────────────────
    denial = _check_access_rule(device, membership)
    if denial:
        _log_scan(card, device, denial, scan_type)
        return JsonResponse(
            {
                'result': denial,
                'member_name': member_name,
                'card_number': card.card_number,
                'denial_reason': _DENIAL_MESSAGES[denial],
                'timestamp': now_iso,
            },
            status=200,
        )

    # ── 6. GRANTED ────────────────────────────────────────────────────────
    _log_scan(card, device, 'granted', scan_type)

    if scan_type == 'entry':
        CheckIn.objects.create(
            member=member,
            location=device.location,
            method='rfid',
        )
        award_loyalty_points(
            member,
            action='checkin',
            description=f'Check-in at {device.location.name}',
        )
    # 'purchase' scan type is handled by the POS flow — no CheckIn here
    # 'exit', 'studio', 'locker', 'kiosk' — log only

    return JsonResponse(
        {
            'result': 'granted',
            'member_name': member_name,
            'card_number': card.card_number,
            'denial_reason': None,
            'timestamp': now_iso,
        },
        status=200,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/door/status/
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(['GET'])
def door_status(request):
    """
    Health-check endpoint for the door agent.

    Auth: X-Device-Token request header.

    Response JSON:
        device       — name, type, location, is_active, last_seen
        last_10_scans — [{scanned_at, result, scan_type, member_name, card_number}]
    """
    token = request.headers.get('X-Device-Token', '').strip()
    if not token:
        return JsonResponse({'error': 'X-Device-Token header required'}, status=401)

    device = _auth_device(token)
    if not device:
        return JsonResponse({'error': 'Unknown or inactive device'}, status=401)

    recent_scans = (
        CardScanLog.objects
        .filter(device=device)
        .select_related('card__member__user')
        .order_by('-scanned_at')[:10]
    )

    scans_data = [
        {
            'scanned_at': s.scanned_at.isoformat(),
            'result': s.result,
            'scan_type': s.scan_type,
            'member_name': s.card.member.full_name,
            'card_number': s.card.card_number,
        }
        for s in recent_scans
    ]

    return JsonResponse(
        {
            'device': {
                'id': device.id,
                'name': device.name,
                'device_type': device.device_type,
                'location': device.location.name,
                'is_active': device.is_active,
                'last_seen': device.last_seen.isoformat() if device.last_seen else None,
            },
            'last_10_scans': scans_data,
        },
        status=200,
    )
