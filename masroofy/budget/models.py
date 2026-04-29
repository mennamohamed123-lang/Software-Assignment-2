from django.db import models
from .managers import CycleManager, TransactionManager, DailyRecordManager


class Category(models.Model):
    name = models.CharField(max_length=100)
    icon_res_id = models.IntegerField()

    def __str__(self):
        return self.name
    
    def get_spending_percentage(self, cat_total, grand_total):
        if grand_total == 0:
            return 0
        return (cat_total / grand_total) * 100
# Create your models here.

class BudgetCycle(models.Model):
    objects = CycleManager() 
        
    total_allowance = models.FloatField()
    start_date = models.DateField()
    end_date = models.DateField()
    remaining_balance = models.FloatField()
    safe_daily_limit = models.FloatField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Cycle {self.id}"

    def get_total_days(self):
        return (self.end_date - self.start_date).days

    def get_days_remaining(self):
        from datetime import date
        return (self.end_date - date.today()).days

    def get_remaining_balance(self):
        return self.remaining_balance

    def get_spent_percentage(self):
        spent = self.total_allowance - self.remaining_balance
        if self.total_allowance == 0:
            return 0
        return (spent / self.total_allowance) * 100

    def deduct_from_balance(self, amt):
        self.remaining_balance -= amt
        self.save()

class Transaction(models.Model):
    objects = TransactionManager()

    amount = models.FloatField()
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    cycle = models.ForeignKey(BudgetCycle, on_delete=models.CASCADE)

    def __str__(self):
        return f"Transaction {self.id} - {self.amount}"

    def get_amount(self):
        return self.amount

    def get_category_id(self):
        return self.category.id

    def get_timestamp(self):
        return self.timestamp

class DailyRecord(models.Model):
    objects = DailyRecordManager()

    date = models.DateField()
    allocated_limit = models.FloatField()
    total_spent = models.FloatField(default=0)
    cycle = models.ForeignKey(BudgetCycle, on_delete=models.CASCADE)

    def __str__(self):
        return f"Record {self.date}"

    def get_unspent_amount(self):
        return self.allocated_limit - self.total_spent

    def rollover_amount(self):
        return self.get_unspent_amount()

    def is_overspent(self):
        return self.total_spent > self.allocated_limit


class AlertType(models.TextChoices):
    WARNING_80 = 'WARNING_80', 'Warning 80%'
    EXHAUSTED_100 = 'EXHAUSTED_100', 'Exhausted 100%'


class NotificationLog(models.Model):
    cycle = models.ForeignKey(BudgetCycle, on_delete=models.CASCADE)
    threshold_pct = models.IntegerField()
    type = models.CharField(max_length=20, choices=AlertType.choices)
    sent_at = models.DateTimeField(auto_now_add=True)
    is_triggered = models.BooleanField(default=False)

    def __str__(self):
        return f"Notification {self.id} - {self.type}"

    def mark_as_sent(self):
        self.is_triggered = True
        self.save()

    def is_already_sent(self, pct):
        return self.threshold_pct == pct and self.is_triggered            