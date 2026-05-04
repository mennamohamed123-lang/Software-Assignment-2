from django.urls import path
from . import views

urlpatterns = [
    path('history/', views.HistoryView.as_view(), name='history'),
    path('notifications/check/', views.NotificationView.as_view(), name='notifications'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('stats/', views.StatsView.as_view(), name='stats'),
    path('record/', views.record_expense, name='record_expense'),
# شيلنا _view من الآخر عشان تبقى زي ما هي مكتوبة في الـ views
path('record/', views.record_expense, name='record_expense'),
path('transaction/delete/<int:tx_id>/', views.delete_transaction, name='delete_transaction'),]