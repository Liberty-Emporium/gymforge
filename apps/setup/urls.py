from django.urls import path
from . import views

app_name = 'setup'

urlpatterns = [
    # Entry point — clears session and starts fresh
    path('', views.wizard_start, name='start'),

    # 7 wizard steps
    path('step/1/', views.step1, name='step1'),
    path('step/2/', views.step2, name='step2'),
    path('step/3/', views.step3, name='step3'),
    path('step/4/', views.step4, name='step4'),
    path('step/5/', views.step5, name='step5'),
    path('step/6/', views.step6, name='step6'),
    path('step/7/', views.step7, name='step7'),

    # Final confirm POST → triggers provisioning task
    path('confirm/', views.confirm, name='confirm'),

    # Provisioning progress page
    path('pending/<str:task_id>/', views.pending, name='pending'),

    # HTMX: poll task status (returns HX-Redirect when ready)
    path('status/<str:task_id>/', views.task_status, name='status'),

    # HTMX partials for dynamic form rows
    path('partials/location-form/', views.partial_location_form, name='partial_location_form'),
    path('partials/plan-row/', views.partial_plan_row, name='partial_plan_row'),

    # One-time domain repair — adds the current HOST to every tenant's GymDomain
    path('repair-domains/', views.repair_domains, name='repair_domains'),

    # One-time platform admin bootstrap — POST only, safe to leave deployed
    path('create-admin/', views.create_admin, name='create_admin'),
]
