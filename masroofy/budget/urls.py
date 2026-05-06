from django.contrib import admin
from django.urls import path
from budget import views

urlpatterns = [

    path('record/', views.record_expense, name='record_expense'),
    path('record/delete/<int:tx_id>/', views.delete_transaction, name='delete_transaction'),
    path('history/', views.HistoryView.as_view(), name='history'),
    path('notifications/check/', views.NotificationView.as_view(), name='notifications'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('stats/', views.StatsView.as_view(), name='stats'),
# شيلنا _view من الآخر عشان تبقى زي ما هي مكتوبة في الـ views
    path('record/', views.record_expense, name='record_expense'),
    path('', views.home, name='home'),
    
    path('admin/', admin.site.urls),

    # AUTH
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),

    # DASHBOARD
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),

    # EXPENSE ENTRY
    path('record/', views.record_expense, name='record_expense'),

    # HISTORY & STATS
    path('history/', views.HistoryView.as_view(), name='history'),
    path('stats/', views.StatsView.as_view(), name='stats'),
    path('notifications/check/', views.NotificationView.as_view(), name='notifications_check'),
]

