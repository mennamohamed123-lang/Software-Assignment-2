

from django.db import models
from django.contrib.auth.models import User
from .managers import CycleManager, TransactionManager, DailyRecordManager
from django.db.models.signals import post_delete
from django.dispatch import receiver



# Category icons map
CATEGORY_ICONS = {
    "Food":        "🍔",
    "Transport":   "🚗",
    "Shopping":    "🛍️",
    "Bills":       "💡",
    "Health":      "💊",
    "Entertainment":"🎬",
    "Education":   "📚",
    "Others":      "📦",
}

class Category(models.Model):
    """Represents a budget category and provides display icon metadata."""
    name = models.CharField(max_length=100)
    icon_res_id = models.IntegerField(default=0)

    def __str__(self):
        return self.name

    @property
    def icon_emoji(self):
        # Look up icon by name, fall back to box emoji
        return CATEGORY_ICONS.get(self.name, "📦")

    def get_spending_percentage(self, cat_total, grand_total):
        if grand_total == 0:
            return 0
        return (cat_total / grand_total) * 100


class BudgetCycle(models.Model):
    """Represents a user's budget cycle with allowance and daily limits."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    objects = CycleManager()

    total_allowance   = models.FloatField()
    start_date        = models.DateField()
    end_date          = models.DateField()
    remaining_balance = models.FloatField()
    safe_daily_limit  = models.FloatField()
    is_active         = models.BooleanField(default=True)

    def __str__(self):
        return f"Cycle {self.id}"

    def get_total_days(self):
        """Calculates the total number of days in the budget cycle.

        Computes the duration of the cycle by subtracting start_date from end_date.
        This represents the planned length of the budgeting period.

        Returns:
            The total number of days in the cycle as an integer.
            For example, a cycle from 2024-01-01 to 2024-01-31 returns 30.

        Note:
            This uses date arithmetic which gives the difference in days.
            For a 31-day month cycle, this would return 30 (31-1).
        """
        return (self.end_date - self.start_date).days

    def get_days_remaining(self):
        """Calculates the number of days remaining until the cycle ends.

        Determines how many days are left in the current budget cycle from today.
        This is useful for showing progress and time pressure to users.

        Returns:
            The number of days remaining as an integer. Returns a negative
            number if the cycle has already ended.

        Note:
            Uses date.today() which may not account for timezone differences.
            Consider using timezone-aware dates for production applications.
        """
        from datetime import date
        return (self.end_date - date.today()).days

    def get_remaining_balance(self):
        """Returns the current remaining balance of the budget cycle.

        This is the amount still available to spend in the entire cycle.
        It starts as total_allowance and decreases with each transaction.

        Returns:
            The remaining balance as a float in EGP (Egyptian Pounds).

        Note:
            This value can go negative if overspending occurs, indicating
            the cycle budget has been exceeded.
        """
        return self.remaining_balance

    def get_spent_percentage(self):
        """Calculates the percentage of the total allowance that has been spent.

        Computes what portion of the budgeted amount has been used so far.
        This is useful for progress indicators and budget tracking.

        Returns:
            The spent percentage as a float between 0.0 and 100.0.
            Returns 0.0 if total_allowance is 0 to avoid division by zero.

        Note:
            Spent amount is calculated as total_allowance - remaining_balance.
            Values over 100% indicate overspending.
        """
        spent = self.total_allowance - self.remaining_balance
        if self.total_allowance == 0:
            return 0
        return (spent / self.total_allowance) * 100

    def deduct_from_balance(self, amt):
        """Deducts the specified amount from the cycle's remaining balance.

        Reduces the available budget by the given amount and saves the change
        to the database. This is typically called when recording expenses.

        Args:
            amt: The amount to deduct as a float. Should be positive.

        Note:
            This method modifies the model instance and saves it immediately.
            For bulk operations, consider using update() queries instead.
        """
        self.remaining_balance -= amt
        self.save()


class Transaction(models.Model):
    """Stores a single expense transaction linked to a cycle and category."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    objects = TransactionManager()

    amount    = models.FloatField()
    category  = models.ForeignKey(Category, on_delete=models.CASCADE)
    timestamp = models.DateTimeField()
    cycle     = models.ForeignKey(BudgetCycle, on_delete=models.CASCADE)

    def __str__(self):
        return f"Transaction {self.id} - {self.amount}"

    def get_amount(self):
        """Returns the transaction amount.

        Returns:
            The amount of the transaction.
        """
        return self.amount

    def get_category_id(self):
        """Returns the ID of the associated category.

        Returns:
            The category ID.
        """
        return self.category.id

    def get_timestamp(self):
        """Returns the timestamp of the transaction.

        Returns:
            The transaction timestamp.
        """
        return self.timestamp


class DailyRecord(models.Model):
    """Tracks daily budget allocation and spending for a budget cycle."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    objects = DailyRecordManager()

    date            = models.DateField()
    allocated_limit = models.FloatField()
    total_spent     = models.FloatField(default=0)
    cycle           = models.ForeignKey(BudgetCycle, on_delete=models.CASCADE)

    def __str__(self):
        return f"Record {self.date}"

    def get_unspent_amount(self):
        """Calculates the unspent amount for the day.

        Determines how much of the allocated daily limit remains available.
        This is the difference between what was budgeted for the day and
        what has actually been spent.

        Returns:
            The unspent amount as a float. Can be positive (surplus),
            zero (spent exactly the limit), or negative (overspent).

        Note:
            Positive values can be rolled over to the next day.
            Negative values indicate the daily limit was exceeded.
        """
        return self.allocated_limit - self.total_spent

    def rollover_amount(self):
        """Returns the amount available for rollover (same as unspent).

        This is an alias for get_unspent_amount() for clarity in rollover logic.
        Represents the surplus that can be carried forward to tomorrow.

        Returns:
            The rollover amount as a float. Only positive values are typically
            rolled over; negative values are not carried forward.

        Note:
            The rollover logic ensures this amount doesn't go below zero,
            so negative unspent amounts don't reduce future daily limits.
        """
        return self.get_unspent_amount()

    def is_overspent(self):
        """Checks if the daily spending has exceeded the allocated limit.

        Determines whether the user has spent more than budgeted for this day.
        This affects rollover calculations and may trigger warnings.

        Returns:
            True if total_spent > allocated_limit, False otherwise.

        Note:
            Overspending on one day can affect future daily limits through
            deficit carryover in the rollover process.
        """
        return self.total_spent > self.allocated_limit


# --- Signals to fix calculations on delete ---

@receiver(post_delete, sender=Transaction)
def update_stats_on_delete(sender, instance, **kwargs):
    """Updates cycle and daily record balances when a transaction is deleted.

    Signal handler that automatically corrects budget balances when transactions
    are removed. This ensures data consistency by reversing the balance deductions
    that occurred when the transaction was originally recorded.

    The handler performs two main operations:
    1. Adds the transaction amount back to the cycle's remaining_balance
    2. Subtracts the amount from the corresponding daily record's total_spent

    Args:
        sender: The Transaction model class (automatically passed by Django).
        instance: The Transaction instance being deleted.
        **kwargs: Additional keyword arguments from the signal.

    Note:
        This signal runs after the transaction is deleted from the database.
        It includes safety checks to prevent negative total_spent values that
        could occur from multiple deletions or data inconsistencies.

        The cycle balance update ensures the overall budget tracking remains
        accurate, while the daily record update maintains per-day spending accuracy.
    """
    # 1. Return amount to total budget
    cycle = instance.cycle
    cycle.remaining_balance += instance.amount
    cycle.save()

    # 2. Deduct amount from today spend
    daily_record = DailyRecord.objects.filter(
        cycle=cycle, 
        date=instance.timestamp.date()
    ).first()

    if daily_record:
        daily_record.total_spent -= instance.amount
        # Prevent negative numbers from repeated deletes
        if daily_record.total_spent < 0:
            daily_record.total_spent = 0
        daily_record.save()


class AlertType(models.TextChoices):
    """Defines notification types for budget threshold alerts."""
    WARNING_80    = 'WARNING_80',    'Warning 80%'
    EXHAUSTED_100 = 'EXHAUSTED_100', 'Exhausted 100%'


class NotificationLog(models.Model):
    """Logs budget notification events tied to a specific cycle."""
    cycle         = models.ForeignKey(BudgetCycle, on_delete=models.CASCADE)
    threshold_pct = models.IntegerField()
    type          = models.CharField(max_length=20, choices=AlertType.choices)
    sent_at       = models.DateTimeField(auto_now_add=True)
    is_triggered  = models.BooleanField(default=False)

    def __str__(self):
        return f"Notification {self.id} - {self.type}"

    def mark_as_sent(self):
        self.is_triggered = True
        self.save()

    def is_already_sent(self, pct):
        return self.threshold_pct == pct and self.is_triggered