from django.urls import path, include
from . import views
from apps.shop import views as shop_views

app_name = 'gym_owner'

urlpatterns = [
    path('',                                views.dashboard,        name='dashboard'),
    path('branding/',                       views.branding_preview, name='branding_preview'),
    path('branding/edit/',                  views.branding_edit,    name='branding_edit'),
    path('tiers/',                          views.tier_list,        name='tier_list'),
    path('tiers/new/',                      views.tier_create,      name='tier_create'),
    path('tiers/<int:pk>/edit/',            views.tier_edit,        name='tier_edit'),
    path('tiers/<int:pk>/deactivate/',      views.tier_deactivate,  name='tier_deactivate'),
    path('staff/',                          views.staff_list,       name='staff_list'),
    path('staff/invite/',                   views.staff_invite,     name='staff_invite'),
    path('staff/<int:pk>/deactivate/',      views.staff_deactivate, name='staff_deactivate'),
    path('locations/',                      views.location_list,    name='location_list'),
    path('locations/new/',                  views.location_create,  name='location_create'),
    path('locations/<int:pk>/edit/',        views.location_edit,    name='location_edit'),
    path('ai/',                             views.ai_chat,          name='ai_chat'),
    path('ai/send/',                        views.ai_chat_send,     name='ai_chat_send'),
    path('ai/new/',                         views.ai_chat_new,      name='ai_chat_new'),
    path('members/',                        views.member_list,            name='member_list'),
    path('schedule/',                       views.schedule_view,          name='schedule'),
    path('analytics/',                      views.analytics_view,         name='analytics'),
    path('inventory/',                      views.inventory_view,         name='inventory'),
    path('settings/',                       views.gym_settings,           name='gym_settings'),
    path('leads/',                          include('apps.leads.urls')),
    # Shop management
    path('shop/',                           shop_views.owner_product_list,   name='shop_products'),
    path('shop/new/',                       shop_views.owner_product_form,   name='shop_product_new'),
    path('shop/<int:pk>/edit/',             shop_views.owner_product_form,   name='shop_product_edit'),
    path('shop/<int:pk>/toggle/',           shop_views.owner_product_deactivate, name='shop_product_toggle'),
    path('shop/<int:pk>/stock/',            shop_views.owner_stock_update,   name='shop_stock_update'),
    path('shop/orders/',                    shop_views.owner_order_list,     name='shop_orders'),
    path('shop/orders/<int:order_pk>/fulfill/', shop_views.owner_order_fulfill, name='shop_order_fulfill'),
]
