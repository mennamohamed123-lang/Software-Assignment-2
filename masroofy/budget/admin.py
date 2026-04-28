from django.contrib import admin
from .models import Category, BudgetCycle, Transaction, DailyRecord, NotificationLog
# Register your models here.

admin.site.register(Category)
admin.site.register(BudgetCycle)
admin.site.register(Transaction)
admin.site.register(DailyRecord)
admin.site.register(NotificationLog)