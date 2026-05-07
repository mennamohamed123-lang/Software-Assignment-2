from django.db import models


class CycleManager(models.Manager):
    """Provides helper queries for budget cycle management."""
    def get_active_cycle(self):
        """Retrieves the currently active budget cycle.

        Finds the budget cycle that is marked as active (is_active=True).
        Since the application enforces only one active cycle per user,
        this returns the single active cycle or None if none exists.

        Returns:
            The active BudgetCycle instance, or None if no active cycle exists.

        Note:
            This method assumes business logic prevents multiple active cycles.
            If multiple exist due to data issues, it returns the first one found.
        """
        return self.filter(is_active=True).first()


class TransactionManager(models.Manager):
    """Provides transaction query and aggregation helpers."""
    def get_by_cycle(self, cycle_id):
        """Retrieves all transactions for a specific budget cycle.

        Filters transactions by the provided cycle_id, returning all
        transactions that belong to that budgeting period.

        Args:
            cycle_id: The primary key of the BudgetCycle to filter by.

        Returns:
            A QuerySet of Transaction instances for the specified cycle.

        Note:
            This returns a QuerySet, not a list. Further filtering or
            ordering can be applied before evaluation.
        """
        return self.filter(cycle_id=cycle_id)

    def get_total_by_cycle(self, cycle_id):
        """Calculates the total amount of all transactions in a cycle.

        Aggregates the sum of all transaction amounts for the specified cycle
        using Django's Sum aggregation. Returns 0 if no transactions exist.

        Args:
            cycle_id: The primary key of the BudgetCycle to aggregate.

        Returns:
            The total transaction amount as a float, or 0.0 if no transactions.

        Note:
            This performs a database aggregation query for efficiency.
            It sums all transaction amounts regardless of category or date.
        """
        from django.db.models import Sum
        result = self.filter(cycle_id=cycle_id).aggregate(Sum('amount'))
        return result['amount__sum'] or 0

    def sum_by_category(self, cycle_id, cat_id):
        """Calculates the total amount spent in a specific category within a cycle.

        Aggregates transaction amounts for transactions that match both the
        specified cycle and category. Useful for category-wise budget analysis.

        Args:
            cycle_id: The primary key of the BudgetCycle.
            cat_id: The primary key of the Category to filter by.

        Returns:
            The total amount spent in the category as a float, or 0.0 if
            no transactions in that category.

        Note:
            This enables per-category spending reports and budget tracking
            within individual cycles.
        """
        from django.db.models import Sum
        result = self.filter(cycle_id=cycle_id, category_id=cat_id).aggregate(Sum('amount'))
        return result['amount__sum'] or 0


class DailyRecordManager(models.Manager):
    """Provides lookup helpers for daily budget records."""
    def get_by_date(self, date, cycle_id):
        """Retrieves the daily record for a specific date and cycle.

        Finds the DailyRecord that matches the exact date and belongs to
        the specified budget cycle. Returns None if no record exists.

        Args:
            date: The date to look up (should be a date object).
            cycle_id: The primary key of the BudgetCycle.

        Returns:
            The DailyRecord instance for the date/cycle combination, or None.

        Note:
            Daily records are created as needed when expenses are recorded.
            This method returns None for dates with no spending activity.
        """
        return self.filter(date=date, cycle_id=cycle_id).first()