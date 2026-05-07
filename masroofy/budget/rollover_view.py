"""
rollover_view.py  — RolloverView
Transfers any leftover daily balance to tomorrow's DailyRecord.

Business rule (based on budget_dailyrecord + budget_budgetcycle schema):
  • At end of each day, if (allocated_limit - total_spent) > 0,
    that surplus is added to tomorrow's allocated_limit.
  • If today overspent, tomorrow's limit is reduced by the deficit.
  • The cycle's remaining_balance is NOT changed here — it was already
    decremented by ExpenseView. We only adjust the per-day allocation.
  • If today's DailyRecord doesn't exist yet, nothing to roll over.

Typical call: scheduled task / management command at midnight,
OR called lazily when the user opens the app on a new day.
"""

from datetime import date, timedelta

from django.db import transaction as db_transaction
from django.utils import timezone

from .models import BudgetCycle, DailyRecord


class RolloverView:
    """
    Rolls over the surplus (or deficit) from `from_date` into `to_date`
    within the given active cycle.
    """

    def rollover(
        self,
        cycle_id: int,
        from_date: date = None,
        to_date: date = None,
    ) -> dict:
        """
        Perform the rollover.

        Args:
            cycle_id:  active BudgetCycle id
            from_date: the day to roll FROM (default = yesterday)
            to_date:   the day to roll INTO (default = today)

        Returns:
            {
                "status": "ok" | "skipped" | "error",
                "message": str,
                "carried_over": float,     # positive = surplus, negative = deficit
                "new_daily_limit": float,
            }
        """
        today = timezone.now().date()
        from_date = from_date or (today - timedelta(days=1))
        to_date   = to_date   or today

        # ── Validate ──────────────────────────────────────────────────────────
        try:
            cycle = BudgetCycle.objects.get(pk=cycle_id, is_active=True)
        except BudgetCycle.DoesNotExist:
            return self._result("error", f"No active cycle found with id={cycle_id}", 0, 0)

        # Check from_date is inside the cycle range
        if not (cycle.start_date <= from_date <= cycle.end_date):
            return self._result(
                "skipped",
                f"Date {from_date} is outside the cycle ({cycle.start_date} → {cycle.end_date})",
                0,
                cycle.safe_daily_limit,
            )

        # ── Load yesterday's record ───────────────────────────────────────────
        try:
            yesterday_rec = DailyRecord.objects.get(cycle=cycle, date=from_date)
        except DailyRecord.DoesNotExist:
            # Nothing was recorded that day — use the full daily limit as base
            # (no surplus, no deficit to carry)
            return self._result(
                "skipped",
                f"No record found for {from_date}, nothing to roll over",
                0,
                cycle.safe_daily_limit,
            )

        # ── Calculate carry-over ──────────────────────────────────────────────
        # positive = surplus (spent less than limit)
        # negative = deficit (overspent)
        carried_over = yesterday_rec.allocated_limit - yesterday_rec.total_spent

        if carried_over == 0:
            return self._result(
                "skipped",
                f"Day {from_date} spent exactly the limit — nothing to carry over",
                0,
                cycle.safe_daily_limit,
            )

        # ── Write atomically ─────────────────────────────────────────────────
        with db_transaction.atomic():
            tomorrow_rec, created = DailyRecord.objects.get_or_create(
                cycle=cycle,
                date=to_date,
                defaults={
                    "allocated_limit": cycle.safe_daily_limit,
                    "total_spent": 0.0,
                },
            )
            new_limit = tomorrow_rec.allocated_limit + carried_over
            # Safety: limit can't go below zero (don't give a negative day limit)
            new_limit = max(new_limit, 0.0)

            tomorrow_rec.allocated_limit = new_limit
            tomorrow_rec.save(update_fields=["allocated_limit"])

        direction = "surplus" if carried_over > 0 else "deficit"
        sign      = "+" if carried_over > 0 else ""
        return self._result(
            "ok",
            f"✅ Carried over {direction} {sign}{carried_over:.2f} EGP from {from_date} to {to_date}. "
            f"Tomorrow's limit: {new_limit:.2f} EGP",
            carried_over,
            new_limit,
        )

    # ── Batch rollover: roll every day in a cycle up to today ─────────────────

    def rollover_all_pending(self, cycle_id: int) -> list:
        """
        Called when the user opens the app after several days offline.
        Rolls over every consecutive day from the last processed date up to yesterday.
        Returns a list of per-day result dicts.
        """
        try:
            cycle = BudgetCycle.objects.get(pk=cycle_id, is_active=True)
        except BudgetCycle.DoesNotExist:
            return [self._result("error", f"No active cycle found with id={cycle_id}", 0, 0)]

        today = timezone.now().date()
        results = []

        # Find all days in the cycle that already have a DailyRecord, sorted
        recorded_dates = list(
            DailyRecord.objects
            .filter(cycle=cycle, date__lt=today)
            .order_by("date")
            .values_list("date", flat=True)
        )

        if not recorded_dates:
            return [self._result("skipped", "No previous days to roll over", 0, cycle.safe_daily_limit)]

        for i in range(len(recorded_dates) - 1):
            from_d = recorded_dates[i]
            to_d   = recorded_dates[i + 1]
            results.append(self.rollover(cycle_id, from_date=from_d, to_date=to_d))

        # Roll the last recorded day into today if not already done
        last = recorded_dates[-1]
        if last < today:
            results.append(self.rollover(cycle_id, from_date=last, to_date=today))

        return results

    # ── helper ────────────────────────────────────────────────────────────────

    @staticmethod
    def _result(status, message, carried_over, new_daily_limit) -> dict:
        """Creates a result dictionary for rollover operations.

        Args:
            status: The status of the operation.
            message: A descriptive message.
            carried_over: The amount carried over.
            new_daily_limit: The new daily limit.

        Returns:
            A dictionary with the result details.
        """
        return {
            "status": status,
            "message": message,
            "carried_over": carried_over,
            "new_daily_limit": new_daily_limit,
        }