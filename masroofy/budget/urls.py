from django.urls import path
from . import views

urlpatterns = [
    path('history/', views.HistoryView.as_view(), name='history'),
    path('notifications/check/', views.NotificationView.as_view(), name='notifications'),
]