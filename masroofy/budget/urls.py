from django.urls import path
from . import views

urlpatterns = [
    path('history/', views.HistoryView.as_view(), name='history'),
    path('notifications/check/', views.NotificationView.as_view(), name='notifications'),
# شيلنا _view من الآخر عشان تبقى زي ما هي مكتوبة في الـ views
path('record/', views.record_expense, name='record_expense'),]