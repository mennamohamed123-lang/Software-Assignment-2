"""
urls.py — Masroofy
==================
Changes in this version:
  - Removed path('record/reset/') because reset is handled by a POST action at /record/
  - Cleaned duplicate URL patterns
"""

from django.contrib import admin
from django.urls import path
from budget import views

urlpatterns = [

    path('admin/', admin.site.urls),

    # ── Home ──────────────────────────────────────────────
    path('', views.home, name='home'),

    # ── Auth ──────────────────────────────────────────────
    path('login/',  views.login_view,  name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),

    # ── Budget / Expense ──────────────────────────────────
    path('record/', views.record_expense, name='record_expense'),

    # DELETE single transaction
    path('record/delete/<int:tx_id>/', views.delete_transaction, name='delete_transaction'),

    # Setup cycle (separate optional page)
    path('setup/', views.setup_cycle, name='setup_cycle'),

    # ── Dashboard ─────────────────────────────────────────
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),

    # ── History & Stats ───────────────────────────────────
    path('history/',              views.HistoryView.as_view(),      name='history'),
    path('stats/',                views.StatsView.as_view(),         name='stats'),
    path('notifications/check/',  views.NotificationView.as_view(),  name='notifications'),
]