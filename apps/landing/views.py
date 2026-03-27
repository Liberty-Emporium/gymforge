"""
Gym landing page — publicly accessible, no login required.

Lives at the root of each gym's subdomain (e.g. ironhouse.gymforge.com/).
All content is driven by GymProfile + tenant-schema data.
GymForge branding must never appear on this page.
"""
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpResponseNotAllowed
from django.views.decorators.http import require_POST


# Sections rendered when GymProfile.landing_page_sections is empty
DEFAULT_SECTIONS = ['hero', 'about', 'classes', 'trainers', 'pricing', 'contact']


def landing_page(request):
    """
    Render the gym's public landing page.

    Sections are toggled via GymProfile.landing_page_sections JSON.
    Returns a minimal "coming soon" response if landing_page_active is False.
    """
    from apps.core.models import GymProfile, Service, Location

    # Guard: public schema has no tenant tables — return immediately without
    # touching the DB or rendering any template that triggers context processors.
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return redirect('/setup/')
    try:
        from django_tenants.utils import get_public_schema_name
        if tenant.schema_name == get_public_schema_name():
            return redirect('/setup/')
    except Exception:
        return redirect('/setup/')

    try:
        profile = GymProfile.objects.get()
    except GymProfile.DoesNotExist:
        # Tenant exists but provisioning hasn't completed yet
        return render(request, 'landing/landing.html', {
            'profile': None,
            'active_sections': [],
        })

    if not profile.landing_page_active:
        return render(request, 'landing/coming_soon.html', {'profile': profile})

    # ------------------------------------------------------------------
    # Resolve active sections
    # ------------------------------------------------------------------
    sections_config = profile.landing_page_sections
    if sections_config:
        active_sections = [
            s.get('section', '')
            for s in sections_config
            if isinstance(s, dict) and s.get('section')
        ]
    else:
        active_sections = list(DEFAULT_SECTIONS)

    context = {
        'profile':         profile,
        'active_sections': active_sections,
    }

    # ------------------------------------------------------------------
    # Fetch only what each active section needs
    # ------------------------------------------------------------------
    if 'about' in active_sections:
        context['services'] = Service.objects.filter(is_active=True)

    if 'classes' in active_sections:
        from apps.scheduling.models import ClassType
        context['class_types'] = ClassType.objects.filter(is_active=True)[:8]

    if 'trainers' in active_sections:
        from apps.checkin.models import TrainerProfile
        context['trainers'] = (
            TrainerProfile.objects
            .filter(is_visible_to_members=True)
            .select_related('user')
        )

    if 'pricing' in active_sections:
        from apps.billing.models import MembershipTier
        context['tiers'] = (
            MembershipTier.objects
            .filter(is_active=True)
            .prefetch_related('included_services')
        )

    if 'contact' in active_sections:
        context['locations'] = (
            Location.objects
            .filter(is_active=True)
            .prefetch_related('hours')
        )

    return render(request, 'landing/landing.html', context)


def submit_lead(request):
    """
    HTMX endpoint — create a Lead record from the contact form.

    Returns:
        - On validation error: re-renders the form partial with errors.
        - On success: renders the success partial (replaces the form).
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    from apps.leads.models import Lead

    first_name = request.POST.get('first_name', '').strip()
    last_name  = request.POST.get('last_name', '').strip()
    email      = request.POST.get('email', '').strip().lower()
    phone      = request.POST.get('phone', '').strip()

    errors = {}
    if not first_name:
        errors['first_name'] = 'First name is required.'
    if not email and not phone:
        errors['contact'] = 'Please provide an email address or phone number.'
    elif email and '@' not in email:
        errors['email'] = 'Enter a valid email address.'

    if errors:
        return render(request, 'landing/partials/lead_form.html', {
            'errors': errors,
            'post':   request.POST,
        })

    # Use 'website' — closest source choice to landing_page in the model
    Lead.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        source='website',
        status='new',
    )

    return render(request, 'landing/partials/lead_success.html', {
        'first_name': first_name,
    })
