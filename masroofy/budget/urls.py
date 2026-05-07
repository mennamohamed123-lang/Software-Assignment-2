"""
urls.py — Masroofy
==================
تم إضافة:
  - path('record/reset/', ...) مش محتاجها لأن الـ reset بيتم عبر POST action في نفس الـ /record/
  - تم تنظيف التكرار في الـ URLs
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

    # ── Dashboard ─────────────────────────────────────────
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),

    # ── History & Stats ───────────────────────────────────
    path('history/',              views.HistoryView.as_view(),      name='history'),
    path('stats/',                views.StatsView.as_view(),         name='stats'),
    path('notifications/check/',  views.NotificationView.as_view(),  name='notifications'),
]