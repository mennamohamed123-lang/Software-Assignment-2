"""
tests.py — Masroofy Test Suite
================================
يغطي:
  - Models: BudgetCycle, Transaction, DailyRecord, Category, NotificationLog
  - DAOs: CategoryDAO, TransactionDAO
  - Business Logic: ExpenseView, RolloverView
  - Views: login, signup, logout, home, record_expense, HistoryView, DashboardView,
           StatsView, NotificationView, setup_cycle, delete_transaction
  - Signals: update_stats_on_delete
  - Helpers: get_daily_alert, get_cycle_alert, _parse_cycle_form
"""

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from budget.dao import CategoryDAO, TransactionDAO
from budget.entities import Category as CategoryEntity, Transaction as TransactionEntity
from budget.expense_view import ExpenseView
from budget.models import (
    BudgetCycle,
    Category,
    DailyRecord,
    NotificationLog,
    Transaction,
    AlertType,
)
from budget.rollover_view import RolloverView
from budget.views import get_cycle_alert, get_daily_alert


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def make_user(username="testuser", password="pass1234"):
    return User.objects.create_user(username=username, password=password)


def make_cycle(user, total=1000.0, days=30, start=None):
    today = start or date.today()
    end   = today + timedelta(days=days - 1)
    return BudgetCycle.objects.create(
        user=user,
        total_allowance=total,
        start_date=today,
        end_date=end,
        remaining_balance=total,
        safe_daily_limit=round(total / days, 2),
        is_active=True,
    )


def make_category(name="Food"):
    return Category.objects.get_or_create(name=name, defaults={"icon_res_id": 0})[0]


def make_transaction(user, cycle, category, amount=50.0, ts=None):
    return Transaction.objects.create(
        user=user,
        cycle=cycle,
        category=category,
        amount=amount,
        timestamp=ts or timezone.now(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────────────

class BudgetCycleModelTests(TestCase):

    def setUp(self):
        self.user  = make_user()
        self.cycle = make_cycle(self.user, total=3000.0, days=30)

    def test_get_total_days(self):
        self.assertEqual(self.cycle.get_total_days(), 29)  # timedelta difference

    def test_get_remaining_balance(self):
        self.assertEqual(self.cycle.get_remaining_balance(), 3000.0)

    def test_get_spent_percentage_zero(self):
        self.assertAlmostEqual(self.cycle.get_spent_percentage(), 0.0)

    def test_get_spent_percentage_partial(self):
        self.cycle.remaining_balance = 1500.0
        self.assertAlmostEqual(self.cycle.get_spent_percentage(), 50.0)

    def test_get_spent_percentage_zero_allowance(self):
        self.cycle.total_allowance = 0
        self.assertEqual(self.cycle.get_spent_percentage(), 0)

    def test_deduct_from_balance(self):
        self.cycle.deduct_from_balance(200.0)
        self.cycle.refresh_from_db()
        self.assertAlmostEqual(self.cycle.remaining_balance, 2800.0)

    def test_str(self):
        self.assertIn("Cycle", str(self.cycle))


class DailyRecordModelTests(TestCase):

    def setUp(self):
        self.user   = make_user()
        self.cycle  = make_cycle(self.user, total=1000.0, days=10)
        self.record = DailyRecord.objects.create(
            user=self.user,
            cycle=self.cycle,
            date=date.today(),
            allocated_limit=100.0,
            total_spent=60.0,
        )

    def test_get_unspent_amount(self):
        self.assertAlmostEqual(self.record.get_unspent_amount(), 40.0)

    def test_rollover_amount(self):
        self.assertAlmostEqual(self.record.rollover_amount(), 40.0)

    def test_is_overspent_false(self):
        self.assertFalse(self.record.is_overspent())

    def test_is_overspent_true(self):
        self.record.total_spent = 110.0
        self.assertTrue(self.record.is_overspent())

    def test_str(self):
        self.assertIn("Record", str(self.record))


class CategoryModelTests(TestCase):

    def test_icon_emoji_known(self):
        cat = Category(name="Food")
        self.assertEqual(cat.icon_emoji, "🍔")

    def test_icon_emoji_unknown(self):
        cat = Category(name="Unknown")
        self.assertEqual(cat.icon_emoji, "📦")

    def test_get_spending_percentage(self):
        cat = Category(name="Food")
        self.assertAlmostEqual(cat.get_spending_percentage(200, 1000), 20.0)

    def test_get_spending_percentage_zero_grand_total(self):
        cat = Category(name="Food")
        self.assertEqual(cat.get_spending_percentage(200, 0), 0)


class TransactionModelTests(TestCase):

    def setUp(self):
        self.user     = make_user()
        self.cycle    = make_cycle(self.user)
        self.category = make_category()
        self.tx       = make_transaction(self.user, self.cycle, self.category, amount=75.0)

    def test_get_amount(self):
        self.assertEqual(self.tx.get_amount(), 75.0)

    def test_get_category_id(self):
        self.assertEqual(self.tx.get_category_id(), self.category.id)

    def test_get_timestamp(self):
        self.assertIsNotNone(self.tx.get_timestamp())

    def test_str(self):
        self.assertIn("Transaction", str(self.tx))


class NotificationLogModelTests(TestCase):

    def setUp(self):
        self.user  = make_user()
        self.cycle = make_cycle(self.user)
        self.notif = NotificationLog.objects.create(
            cycle=self.cycle,
            threshold_pct=80,
            type=AlertType.WARNING_80,
            is_triggered=False,
        )

    def test_mark_as_sent(self):
        self.notif.mark_as_sent()
        self.notif.refresh_from_db()
        self.assertTrue(self.notif.is_triggered)

    def test_is_already_sent_true(self):
        self.notif.is_triggered = True
        self.assertTrue(self.notif.is_already_sent(80))

    def test_is_already_sent_wrong_pct(self):
        self.notif.is_triggered = True
        self.assertFalse(self.notif.is_already_sent(100))

    def test_str(self):
        self.assertIn("Notification", str(self.notif))


# ─────────────────────────────────────────────────────────────────────────────
# SIGNALS
# ─────────────────────────────────────────────────────────────────────────────

class TransactionDeleteSignalTests(TestCase):

    def setUp(self):
        self.user     = make_user()
        self.cycle    = make_cycle(self.user, total=1000.0)
        self.category = make_category()
        self.tx       = make_transaction(self.user, self.cycle, self.category, amount=100.0)
        DailyRecord.objects.create(
            user=self.user,
            cycle=self.cycle,
            date=date.today(),
            allocated_limit=200.0,
            total_spent=100.0,
        )

    def test_delete_restores_cycle_balance(self):
        before = self.cycle.remaining_balance
        self.tx.delete()
        self.cycle.refresh_from_db()
        self.assertAlmostEqual(self.cycle.remaining_balance, before + 100.0)

    def test_delete_reduces_daily_spent(self):
        self.tx.delete()
        record = DailyRecord.objects.get(cycle=self.cycle, date=date.today())
        self.assertAlmostEqual(record.total_spent, 0.0)

    def test_delete_no_negative_daily_spent(self):
        record = DailyRecord.objects.get(cycle=self.cycle, date=date.today())
        record.total_spent = 0.0
        record.save()
        self.tx.delete()
        record.refresh_from_db()
        self.assertGreaterEqual(record.total_spent, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# DAO
# ─────────────────────────────────────────────────────────────────────────────

class CategoryDAOTests(TestCase):

    def setUp(self):
        self.dao = CategoryDAO()

    def test_insert_and_get_by_id(self):
        entity = CategoryEntity(id=None, name="Transport", icon_res_id=0)
        saved  = self.dao.insert(entity)
        self.assertIsNotNone(saved.id)
        fetched = self.dao.get_by_id(saved.id)
        self.assertEqual(fetched.name, "Transport")

    def test_get_by_id_not_found(self):
        self.assertIsNone(self.dao.get_by_id(9999))

    def test_get_all(self):
        self.dao.insert(CategoryEntity(id=None, name="Health",   icon_res_id=0))
        self.dao.insert(CategoryEntity(id=None, name="Shopping", icon_res_id=0))
        all_cats = self.dao.get_all()
        names = [c.name for c in all_cats]
        self.assertIn("Health",   names)
        self.assertIn("Shopping", names)

    def test_update(self):
        entity = self.dao.insert(CategoryEntity(id=None, name="Bills", icon_res_id=0))
        entity.name = "Bills Updated"
        result = self.dao.update(entity)
        self.assertTrue(result)
        self.assertEqual(self.dao.get_by_id(entity.id).name, "Bills Updated")

    def test_update_nonexistent(self):
        entity = CategoryEntity(id=99999, name="Ghost", icon_res_id=0)
        self.assertFalse(self.dao.update(entity))

    def test_delete(self):
        entity = self.dao.insert(CategoryEntity(id=None, name="Education", icon_res_id=0))
        self.assertTrue(self.dao.delete(entity.id))
        self.assertIsNone(self.dao.get_by_id(entity.id))

    def test_delete_nonexistent(self):
        self.assertFalse(self.dao.delete(9999))


class TransactionDAOTests(TestCase):

    def setUp(self):
        self.user     = make_user()
        self.cycle    = make_cycle(self.user, total=500.0, days=10)
        self.category = make_category("Food")
        self.dao      = TransactionDAO()

    def test_insert_and_get_by_id(self):
        entity = TransactionEntity(
            id=None, amount=50.0,
            category_id=self.category.id,
            cycle_id=self.cycle.id,
        )
        saved   = self.dao.insert(entity, user=self.user)
        fetched = self.dao.get_by_id(saved.id)
        self.assertIsNotNone(fetched)
        self.assertAlmostEqual(fetched.amount, 50.0)

    def test_get_by_id_not_found(self):
        self.assertIsNone(self.dao.get_by_id(9999))

    def test_get_by_cycle(self):
        for amt in [20.0, 30.0, 40.0]:
            self.dao.insert(
                TransactionEntity(id=None, amount=amt, category_id=self.category.id, cycle_id=self.cycle.id),
                user=self.user,
            )
        txs = self.dao.get_by_cycle(self.cycle.id)
        self.assertEqual(len(txs), 3)

    def test_get_by_date(self):
        self.dao.insert(
            TransactionEntity(id=None, amount=25.0, category_id=self.category.id, cycle_id=self.cycle.id),
            user=self.user,
        )
        txs = self.dao.get_by_date(date.today(), user=self.user)
        self.assertGreaterEqual(len(txs), 1)

    def test_get_total_spent_today(self):
        for amt in [10.0, 20.0]:
            self.dao.insert(
                TransactionEntity(id=None, amount=amt, category_id=self.category.id, cycle_id=self.cycle.id),
                user=self.user,
            )
        total = self.dao.get_total_spent_today(self.cycle.id)
        self.assertAlmostEqual(total, 30.0)

    def test_get_total_spent_in_cycle(self):
        for amt in [100.0, 200.0]:
            self.dao.insert(
                TransactionEntity(id=None, amount=amt, category_id=self.category.id, cycle_id=self.cycle.id),
                user=self.user,
            )
        total = self.dao.get_total_spent_in_cycle(self.cycle.id)
        self.assertAlmostEqual(total, 300.0)

    def test_delete(self):
        entity = self.dao.insert(
            TransactionEntity(id=None, amount=15.0, category_id=self.category.id, cycle_id=self.cycle.id),
            user=self.user,
        )
        self.assertTrue(self.dao.delete(entity.id))
        self.assertIsNone(self.dao.get_by_id(entity.id))

    def test_delete_nonexistent(self):
        self.assertFalse(self.dao.delete(9999))


# ─────────────────────────────────────────────────────────────────────────────
# EXPENSE VIEW (Business Logic)
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseViewTests(TestCase):

    def setUp(self):
        self.user     = make_user()
        self.cycle    = make_cycle(self.user, total=1000.0, days=10)
        self.category = make_category("Food")
        self.ev       = ExpenseView()

    def test_record_expense_ok(self):
        result = self.ev.record_expense(100.0, self.category.id, self.cycle.id, user=self.user)
        self.assertEqual(result["status"], ExpenseView.STATUS_OK)
        self.assertIsNotNone(result["transaction"])
        self.assertAlmostEqual(result["remaining_balance"], 900.0)

    def test_record_expense_zero_amount(self):
        result = self.ev.record_expense(0, self.category.id, self.cycle.id, user=self.user)
        self.assertEqual(result["status"], ExpenseView.STATUS_ERROR)

    def test_record_expense_negative_amount(self):
        result = self.ev.record_expense(-50.0, self.category.id, self.cycle.id, user=self.user)
        self.assertEqual(result["status"], ExpenseView.STATUS_ERROR)

    def test_record_expense_invalid_category(self):
        result = self.ev.record_expense(50.0, 9999, self.cycle.id, user=self.user)
        self.assertEqual(result["status"], ExpenseView.STATUS_ERROR)

    def test_record_expense_invalid_cycle(self):
        result = self.ev.record_expense(50.0, self.category.id, 9999, user=self.user)
        self.assertEqual(result["status"], ExpenseView.STATUS_ERROR)

    def test_record_expense_over_cycle(self):
        result = self.ev.record_expense(1500.0, self.category.id, self.cycle.id, user=self.user)
        self.assertEqual(result["status"], ExpenseView.STATUS_OVER_CYCLE)

    def test_record_expense_over_daily(self):
        # Daily limit = 1000/10 = 100, so 150 is over daily but not over cycle
        self.cycle.safe_daily_limit = 100.0
        self.cycle.save()
        result = self.ev.record_expense(150.0, self.category.id, self.cycle.id, user=self.user)
        self.assertIn(result["status"], [ExpenseView.STATUS_OVER_DAILY, ExpenseView.STATUS_OVER_CYCLE])

    def test_record_expense_creates_daily_record(self):
        DailyRecord.objects.filter(user=self.user, cycle=self.cycle, date=date.today()).delete()
        self.ev.record_expense(50.0, self.category.id, self.cycle.id, user=self.user)
        exists = DailyRecord.objects.filter(user=self.user, cycle=self.cycle, date=date.today()).exists()
        self.assertTrue(exists)

    def test_record_expense_updates_cycle_balance(self):
        self.ev.record_expense(200.0, self.category.id, self.cycle.id, user=self.user)
        self.cycle.refresh_from_db()
        self.assertAlmostEqual(self.cycle.remaining_balance, 800.0)


# ─────────────────────────────────────────────────────────────────────────────
# ROLLOVER VIEW
# ─────────────────────────────────────────────────────────────────────────────

class RolloverViewTests(TestCase):

    def setUp(self):
        self.user  = make_user()
        self.today = date.today()
        self.cycle = make_cycle(self.user, total=1000.0, days=10, start=self.today)
        self.rv    = RolloverView()

    def _make_daily(self, d, allocated=100.0, spent=60.0):
        return DailyRecord.objects.create(
            user=self.user,
            cycle=self.cycle,
            date=d,
            allocated_limit=allocated,
            total_spent=spent,
        )

    def test_rollover_surplus(self):
        yesterday = self.today - timedelta(days=1)
        self._make_daily(yesterday, allocated=100.0, spent=60.0)
        result = self.rv.rollover(self.cycle.id, from_date=yesterday, to_date=self.today)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["carried_over"], 40.0)

    def test_rollover_deficit(self):
        yesterday = self.today - timedelta(days=1)
        self._make_daily(yesterday, allocated=100.0, spent=130.0)
        result = self.rv.rollover(self.cycle.id, from_date=yesterday, to_date=self.today)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["carried_over"], -30.0)

    def test_rollover_exact_spend_skipped(self):
        yesterday = self.today - timedelta(days=1)
        self._make_daily(yesterday, allocated=100.0, spent=100.0)
        result = self.rv.rollover(self.cycle.id, from_date=yesterday, to_date=self.today)
        self.assertEqual(result["status"], "skipped")

    def test_rollover_no_daily_record_skipped(self):
        yesterday = self.today - timedelta(days=1)
        result = self.rv.rollover(self.cycle.id, from_date=yesterday, to_date=self.today)
        self.assertEqual(result["status"], "skipped")

    def test_rollover_invalid_cycle(self):
        result = self.rv.rollover(9999)
        self.assertEqual(result["status"], "error")

    def test_rollover_date_outside_cycle(self):
        far_future = self.today + timedelta(days=365)
        result = self.rv.rollover(self.cycle.id, from_date=far_future)
        self.assertEqual(result["status"], "skipped")

    def test_new_daily_limit_not_negative(self):
        yesterday = self.today - timedelta(days=1)
        self._make_daily(yesterday, allocated=100.0, spent=500.0)  # huge deficit
        result = self.rv.rollover(self.cycle.id, from_date=yesterday, to_date=self.today)
        self.assertGreaterEqual(result["new_daily_limit"], 0.0)

    def test_rollover_all_pending_no_records(self):
        results = self.rv.rollover_all_pending(self.cycle.id)
        self.assertEqual(results[0]["status"], "skipped")

    def test_rollover_all_pending_multiple_days(self):
        d1 = self.today - timedelta(days=3)
        d2 = self.today - timedelta(days=2)
        d3 = self.today - timedelta(days=1)
        self._make_daily(d1, 100, 80)
        self._make_daily(d2, 100, 60)
        self._make_daily(d3, 100, 50)
        results = self.rv.rollover_all_pending(self.cycle.id)
        statuses = [r["status"] for r in results]
        self.assertIn("ok", statuses)


# ─────────────────────────────────────────────────────────────────────────────
# ALERT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

class AlertHelperTests(TestCase):

    def setUp(self):
        self.user  = make_user()
        self.cycle = make_cycle(self.user, total=1000.0, days=10)
        self.cat   = make_category()

    def _make_daily(self, limit=100.0):
        return DailyRecord.objects.create(
            user=self.user, cycle=self.cycle,
            date=date.today(), allocated_limit=limit, total_spent=0.0,
        )

    def test_get_daily_alert_none_when_no_record(self):
        self.assertIsNone(get_daily_alert(None))

    def test_get_daily_alert_none_below_60(self):
        record = self._make_daily(100.0)
        make_transaction(self.user, self.cycle, self.cat, amount=50.0)
        alert = get_daily_alert(record)
        self.assertIsNone(alert)

    def test_get_daily_alert_info_at_60(self):
        record = self._make_daily(100.0)
        make_transaction(self.user, self.cycle, self.cat, amount=65.0)
        alert = get_daily_alert(record)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["type"], "info")

    def test_get_daily_alert_warning_at_80(self):
        record = self._make_daily(100.0)
        make_transaction(self.user, self.cycle, self.cat, amount=85.0)
        alert = get_daily_alert(record)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["type"], "warning")

    def test_get_daily_alert_danger_at_100(self):
        record = self._make_daily(100.0)
        make_transaction(self.user, self.cycle, self.cat, amount=100.0)
        alert = get_daily_alert(record)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["type"], "danger")

    def test_get_cycle_alert_none_when_no_cycle(self):
        self.assertIsNone(get_cycle_alert(None))

    def test_get_cycle_alert_none_below_60(self):
        make_transaction(self.user, self.cycle, self.cat, amount=100.0)  # 10%
        self.assertIsNone(get_cycle_alert(self.cycle))

    def test_get_cycle_alert_warning_at_80(self):
        make_transaction(self.user, self.cycle, self.cat, amount=850.0)
        alert = get_cycle_alert(self.cycle)
        self.assertEqual(alert["type"], "warning")

    def test_get_cycle_alert_danger_at_100(self):
        make_transaction(self.user, self.cycle, self.cat, amount=1000.0)
        alert = get_cycle_alert(self.cycle)
        self.assertEqual(alert["type"], "danger")


# ─────────────────────────────────────────────────────────────────────────────
# VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class AuthViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user   = make_user(username="alice", password="secret123")

    def test_login_get(self):
        res = self.client.get(reverse("login"))
        self.assertEqual(res.status_code, 200)

    def test_login_post_valid(self):
        res = self.client.post(reverse("login"), {"username": "alice", "password": "secret123"})
        self.assertRedirects(res, reverse("dashboard"))

    def test_login_post_invalid(self):
        res = self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        self.assertRedirects(res, reverse("login"))

    def test_signup_get(self):
        res = self.client.get(reverse("signup"))
        self.assertEqual(res.status_code, 200)

    def test_signup_post_valid(self):
        res = self.client.post(reverse("signup"), {
            "username": "newuser", "email": "new@test.com",
            "password": "pass1234", "confirm_password": "pass1234",
        })
        self.assertRedirects(res, reverse("dashboard"))

    def test_signup_post_password_mismatch(self):
        res = self.client.post(reverse("signup"), {
            "username": "newuser2", "email": "x@x.com",
            "password": "pass1234", "confirm_password": "different",
        })
        self.assertEqual(res.status_code, 200)

    def test_signup_post_duplicate_username(self):
        res = self.client.post(reverse("signup"), {
            "username": "alice", "email": "a@a.com",
            "password": "pass1234", "confirm_password": "pass1234",
        })
        self.assertEqual(res.status_code, 200)

    def test_logout(self):
        self.client.login(username="alice", password="secret123")
        res = self.client.get(reverse("logout"))
        self.assertRedirects(res, reverse("login"))


class HomeViewTests(TestCase):

    def setUp(self):
        self.client = Client()

    def test_home_unauthenticated_renders_index(self):
        res = self.client.get(reverse("home"))
        self.assertEqual(res.status_code, 200)

    def test_home_authenticated_redirects(self):
        user = make_user()
        self.client.login(username="testuser", password="pass1234")
        res = self.client.get(reverse("home"))
        self.assertRedirects(res, reverse("record_expense"))


class RecordExpenseViewTests(TestCase):

    def setUp(self):
        self.client   = Client()
        self.user     = make_user()
        self.client.login(username="testuser", password="pass1234")
        self.category = make_category("Food")

    def test_get_no_cycle(self):
        res = self.client.get(reverse("record_expense"))
        self.assertEqual(res.status_code, 200)

    def test_get_with_cycle(self):
        make_cycle(self.user)
        res = self.client.get(reverse("record_expense"))
        self.assertEqual(res.status_code, 200)

    def test_create_cycle_action(self):
        res = self.client.post(reverse("record_expense"), {
            "action": "create_cycle",
            "total_allowance": "5000",
            "duration_days": "30",
        })
        self.assertRedirects(res, reverse("record_expense"))
        self.assertTrue(BudgetCycle.objects.filter(user=self.user, is_active=True).exists())

    def test_create_cycle_invalid_allowance(self):
        res = self.client.post(reverse("record_expense"), {
            "action": "create_cycle",
            "total_allowance": "abc",
            "duration_days": "30",
        })
        self.assertEqual(res.status_code, 200)

    def test_edit_cycle_action(self):
        cycle = make_cycle(self.user, total=2000.0)
        res   = self.client.post(reverse("record_expense"), {
            "action": "edit_cycle",
            "total_allowance": "3000",
            "duration_days": "20",
        })
        self.assertRedirects(res, reverse("record_expense"))
        cycle.refresh_from_db()
        self.assertAlmostEqual(cycle.total_allowance, 3000.0)

    def test_reset_cycle_action(self):
        cycle = make_cycle(self.user, total=1000.0)
        cat   = make_category()
        make_transaction(self.user, cycle, cat, amount=100.0)
        res = self.client.post(reverse("record_expense"), {
            "action": "reset_cycle",
            "duration_days": "30",
        })
        self.assertRedirects(res, reverse("record_expense"))
        self.assertFalse(Transaction.objects.filter(cycle=cycle).exists())

    def test_record_expense_post(self):
        make_cycle(self.user)
        res = self.client.post(reverse("record_expense"), {
            "amount": "150",
            "category_id": str(self.category.id),
        })
        self.assertRedirects(res, reverse("record_expense"))

    def test_record_expense_invalid_amount(self):
        make_cycle(self.user)
        res = self.client.post(reverse("record_expense"), {
            "amount": "xyz",
            "category_id": str(self.category.id),
        })
        self.assertEqual(res.status_code, 200)

    def test_record_expense_no_category(self):
        make_cycle(self.user)
        res = self.client.post(reverse("record_expense"), {
            "amount": "100",
            "category_id": "",
        })
        self.assertEqual(res.status_code, 200)


class DeleteTransactionViewTests(TestCase):

    def setUp(self):
        self.client   = Client()
        self.user     = make_user()
        self.client.login(username="testuser", password="pass1234")
        self.cycle    = make_cycle(self.user)
        self.category = make_category()
        self.tx       = make_transaction(self.user, self.cycle, self.category, amount=50.0)

    def test_delete_own_transaction(self):
        res = self.client.get(reverse("delete_transaction", args=[self.tx.id]))
        self.assertRedirects(res, reverse("record_expense"))
        self.assertFalse(Transaction.objects.filter(pk=self.tx.id).exists())

    def test_delete_other_user_transaction_404(self):
        other_user = make_user("other", "pass1234")
        other_tx   = make_transaction(other_user, self.cycle, self.category, amount=30.0)
        res        = self.client.get(reverse("delete_transaction", args=[other_tx.id]))
        self.assertEqual(res.status_code, 404)


class HistoryViewTests(TestCase):

    def setUp(self):
        self.client   = Client()
        self.user     = make_user()
        self.client.login(username="testuser", password="pass1234")
        self.cycle    = make_cycle(self.user)
        self.category = make_category()

    def test_get_history(self):
        make_transaction(self.user, self.cycle, self.category, 100.0)
        res = self.client.get(reverse("history"))
        self.assertEqual(res.status_code, 200)

    def test_filter_by_category(self):
        res = self.client.get(reverse("history"), {"category": self.category.id})
        self.assertEqual(res.status_code, 200)

    def test_filter_by_date(self):
        res = self.client.get(reverse("history"), {"date": str(date.today())})
        self.assertEqual(res.status_code, 200)

    def test_delete_transaction_via_post(self):
        tx  = make_transaction(self.user, self.cycle, self.category, 50.0)
        res = self.client.post(reverse("history"), {"transaction_id": tx.id})
        self.assertRedirects(res, "/history/")
        self.assertFalse(Transaction.objects.filter(pk=tx.id).exists())

    def test_no_cycle_returns_empty(self):
        BudgetCycle.objects.all().delete()
        res = self.client.get(reverse("history"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(list(res.context["transactions"]), [])


class DashboardViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user   = make_user()
        self.client.login(username="testuser", password="pass1234")

    def test_dashboard_no_cycle(self):
        res = self.client.get(reverse("dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("error", res.context)

    def test_dashboard_with_cycle(self):
        cycle = make_cycle(self.user, total=2000.0)
        res   = self.client.get(reverse("dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("spent", res.context)
        self.assertIn("remaining", res.context)

    def test_dashboard_redirects_unauthenticated(self):
        self.client.logout()
        res = self.client.get(reverse("dashboard"))
        self.assertEqual(res.status_code, 302)


class StatsViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user   = make_user()
        self.client.login(username="testuser", password="pass1234")

    def test_stats_no_cycle(self):
        res = self.client.get(reverse("stats"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("error", res.context)

    def test_stats_with_transactions(self):
        cycle = make_cycle(self.user, total=1000.0)
        cat   = make_category()
        make_transaction(self.user, cycle, cat, 100.0)
        make_transaction(self.user, cycle, cat, 200.0)
        res = self.client.get(reverse("stats"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("labels", res.context)
        self.assertIn("values", res.context)


class NotificationViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user   = make_user()
        self.client.login(username="testuser", password="pass1234")

    def test_notifications_no_cycle(self):
        res = self.client.get(reverse("notifications"))
        self.assertEqual(res.status_code, 200)

    def test_notifications_success_level(self):
        make_cycle(self.user, total=1000.0)
        res = self.client.get(reverse("notifications"))
        self.assertEqual(res.context["notification_level"], "success")

    def test_notifications_warning_level(self):
        cycle = make_cycle(self.user, total=1000.0)
        cat   = make_category()
        make_transaction(self.user, cycle, cat, 850.0)
        res = self.client.get(reverse("notifications"))
        self.assertEqual(res.context["notification_level"], "warning")

    def test_notifications_danger_level(self):
        cycle = make_cycle(self.user, total=1000.0)
        cat   = make_category()
        make_transaction(self.user, cycle, cat, 1000.0)
        res = self.client.get(reverse("notifications"))
        self.assertEqual(res.context["notification_level"], "danger")


class SetupCycleViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user   = make_user()
        self.client.login(username="testuser", password="pass1234")

    def test_get_setup_page(self):
        res = self.client.get(reverse("setup_cycle"))
        self.assertEqual(res.status_code, 200)

    def test_post_valid_creates_cycle(self):
        res = self.client.post(reverse("setup_cycle"), {
            "total_allowance": "2000",
            "duration_days": "15",
        })
        self.assertRedirects(res, reverse("record_expense"))
        self.assertTrue(BudgetCycle.objects.filter(user=self.user, is_active=True).exists())

    def test_post_invalid_shows_errors(self):
        res = self.client.post(reverse("setup_cycle"), {
            "total_allowance": "-100",
            "duration_days": "15",
        })
        self.assertEqual(res.status_code, 200)

    def test_post_deactivates_old_cycle(self):
        old_cycle = make_cycle(self.user, total=500.0)
        self.assertTrue(old_cycle.is_active)
        self.client.post(reverse("setup_cycle"), {
            "total_allowance": "2000",
            "duration_days": "20",
        })
        old_cycle.refresh_from_db()
        self.assertFalse(old_cycle.is_active)