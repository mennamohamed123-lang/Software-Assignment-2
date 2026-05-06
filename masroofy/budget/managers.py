from django.db import models


class CycleManager(models.Manager):
    def get_active_cycle(self):
        return self.filter(is_active=True).first()


class TransactionManager(models.Manager):
    def get_by_cycle(self, cycle_id):
        return self.filter(cycle_id=cycle_id)

    def get_total_by_cycle(self, cycle_id):
        from django.db.models import Sum
        result = self.filter(cycle_id=cycle_id).aggregate(Sum('amount'))
        return result['amount__sum'] or 0

    def sum_by_category(self, cycle_id, cat_id):
        from django.db.models import Sum
        result = self.filter(cycle_id=cycle_id, category_id=cat_id).aggregate(Sum('amount'))
        return result['amount__sum'] or 0


class DailyRecordManager(models.Manager):
    def get_by_date(self, date, cycle_id):
        return self.filter(date=date, cycle_id=cycle_id).first()