"""
expense_view.py  — ExpenseView
Business logic layer: validates and records a new expense,
then updates DailyRecord and BudgetCycle remaining balance.

Flow:
  1. Validate input (amount > 0, category exists, cycle active)
  2. Insert Transaction via TransactionDAO
  3. Update budget_dailyrecord.total_spent for today
  4. Update budget_budgetcycle.remaining_balance
  5. Return result dict (success / error / warning flags)
"""

from datetime import date as date_type
from typing import Optional

from django.db import transaction as db_transaction
from django.utils import timezone

from .dao import CategoryDAO, TransactionDAO
from .entities import Transaction
from .models import BudgetCycle, DailyRecord


class ExpenseView:
    """
    Records a new expense and keeps the cycle + daily record in sync.
    All DB writes happen in a single atomic block.
    """

    # Result status keys
    STATUS_OK           = "ok"
    STATUS_OVER_DAILY   = "over_daily_limit"   # warning — over today's limit
    STATUS_OVER_CYCLE   = "over_cycle"          # warning — over full cycle budget
    STATUS_ERROR        = "error"

    def __init__(self):
        self.tx_dao = TransactionDAO()
        self.cat_dao = CategoryDAO()

    def record_expense(
        self,
        amount: float,
        category_id: int,
        cycle_id: int,
        timestamp=None,
        user=None,
    ) -> dict:
        """
        Main entry point.

        Returns:
            {
                "status": STATUS_OK | STATUS_OVER_DAILY | STATUS_OVER_CYCLE | STATUS_ERROR,
                "message": str,
                "transaction": Transaction | None,
                "remaining_balance": float | None,
                "daily_remaining": float | None,
            }
        """
        # ── 1. Validate ──────────────────────────────────────────────────────
        if not amount or amount <= 0:
            return self._error("Amount must be greater than zero")

        category = self.cat_dao.get_by_id(category_id)
        if category is None:
            return self._error(f"Category {category_id} not found")

        try:
            cycle = BudgetCycle.objects.get(pk=cycle_id, is_active=True)
        except BudgetCycle.DoesNotExist:
            return self._error("No active budget cycle found with this ID")

        ts = timestamp or timezone.now()
        today = ts.date() if hasattr(ts, "date") else ts

        # ── 2. Write atomically ──────────────────────────────────────────────
        with db_transaction.atomic():
            # Insert transaction
            tx = Transaction(
                id=None,
                amount=amount,
                category_id=category_id,
                cycle_id=cycle_id,
                timestamp=ts,
            )
            tx = self.tx_dao.insert(tx, user=user)

            # Update or create DailyRecord for today
            daily, _ = DailyRecord.objects.get_or_create(
                user=user,
                cycle=cycle,
                date=today,
                defaults={
                    "allocated_limit": cycle.safe_daily_limit,
                    "total_spent": 0.0,
                },
            )
            daily.total_spent += amount
            daily.save(update_fields=["total_spent"])

            # Update cycle remaining balance
            cycle.remaining_balance -= amount
            cycle.save(update_fields=["remaining_balance"])

        # ── 3. Determine status ──────────────────────────────────────────────
        daily_remaining = daily.allocated_limit - daily.total_spent

        if cycle.remaining_balance < 0:
            status  = self.STATUS_OVER_CYCLE
            message = f"⚠️ Total budget exceeded! Remaining balance: {cycle.remaining_balance:.2f} EGP"
        elif daily_remaining < 0:
            status  = self.STATUS_OVER_DAILY
            message = f"⚠️ Daily limit exceeded! Remaining today: {daily_remaining:.2f} EGP"
        else:
            status  = self.STATUS_OK
            message = f"✅ Expense saved. Remaining: {cycle.remaining_balance:.2f} EGP"

        return {
            "status": status,
            "message": message,
            "transaction": tx,
            "remaining_balance": cycle.remaining_balance,
            "daily_remaining": daily_remaining,
        }

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _error(msg: str) -> dict:
        """Creates an error result dictionary.

        Args:
            msg: The error message.

        Returns:
            A dictionary with error status and message.
        """
        return {
            "status": ExpenseView.STATUS_ERROR,
            "message": msg,
            "transaction": None,
            "remaining_balance": None,
            "daily_remaining": None,
        }