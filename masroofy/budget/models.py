from django.db import models
from django.contrib.auth.models import User
from .managers import CycleManager, TransactionManager, DailyRecordManager
from django.db.models.signals import post_delete
from django.dispatch import receiver

# القائمة المحدثة باللغة الإنجليزية للأيقونات
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
    name = models.CharField(max_length=100)
    icon_res_id = models.IntegerField(default=0)

    def __str__(self):
        return self.name

    @property
    def icon_emoji(self):
        # بيبحث في القائمة ولو ملقاش الاسم بيحط أيقونة الصندوق كافتراضي
        return CATEGORY_ICONS.get(self.name, "📦")

    def get_spending_percentage(self, cat_total, grand_total):
        if grand_total == 0:
            return 0
        return (cat_total / grand_total) * 100


class BudgetCycle(models.Model):
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
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    objects = TransactionManager()

    amount    = models.FloatField()
    category  = models.ForeignKey(Category, on_delete=models.CASCADE)
    timestamp = models.DateTimeField()
    cycle     = models.ForeignKey(BudgetCycle, on_delete=models.CASCADE)

    def __str__(self):
        return f"Transaction {self.id} - {self.amount}"

    def get_amount(self):
        return self.amount

    def get_category_id(self):
        return self.category.id

    def get_timestamp(self):
        return self.timestamp


class DailyRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    objects = DailyRecordManager()

    date            = models.DateField()
    allocated_limit = models.FloatField()
    total_spent     = models.FloatField(default=0)
    cycle           = models.ForeignKey(BudgetCycle, on_delete=models.CASCADE)

    def __str__(self):
        return f"Record {self.date}"

    def get_unspent_amount(self):
        return self.allocated_limit - self.total_spent

    def rollover_amount(self):
        return self.get_unspent_amount()

    def is_overspent(self):
        return self.total_spent > self.allocated_limit


# --- Signals لتصحيح الحسابات عند المسح ---

@receiver(post_delete, sender=Transaction)
def update_stats_on_delete(sender, instance, **kwargs):
    # 1. إرجاع المبلغ للميزانية الكلية
    cycle = instance.cycle
    cycle.remaining_balance += instance.amount
    cycle.save()

    # 2. خصم المبلغ من صرف اليوم (Spent Today)
    daily_record = DailyRecord.objects.filter(
        cycle=cycle, 
        date=instance.timestamp.date()
    ).first()

    if daily_record:
        daily_record.total_spent -= instance.amount
        # لضمان عدم وجود أرقام سالبة في حالة المسح المتكرر
        if daily_record.total_spent < 0:
            daily_record.total_spent = 0
        daily_record.save()


class AlertType(models.TextChoices):
    WARNING_80    = 'WARNING_80',    'Warning 80%'
    EXHAUSTED_100 = 'EXHAUSTED_100', 'Exhausted 100%'


class NotificationLog(models.Model):
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