from django.urls import path
from apps.kiosk import views

app_name = 'kiosk'

urlpatterns = [
    path('',                             views.idle,           name='idle'),
    path('setup/',                       views.setup,          name='setup'),
    path('door/',                        views.door_scanner,   name='door_scanner'),
    path('checkin/card/',                views.card_checkin,   name='card_checkin'),
    path('checkin/pin/',                 views.pin_checkin,    name='pin_checkin'),
    path('checkin/guest/',               views.guest_checkin,  name='guest_checkin'),
    path('result/',                      views.result,         name='result'),
    path('pin/set/<int:member_pk>/',     views.set_pin,        name='set_pin'),
]
