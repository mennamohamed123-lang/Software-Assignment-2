from django.shortcuts import render
from django.views import View
from .models import Transaction, Category, BudgetCycle, NotificationLog


class HistoryView(View):
    def get(self, request):
        transactions = Transaction.objects.all().order_by('-timestamp')
        categories = Category.objects.all()

        category_id = request.GET.get('category')
        if category_id:
            transactions = transactions.filter(category_id=category_id)

        date_filter = request.GET.get('date')
        if date_filter:
            transactions = transactions.filter(timestamp__date=date_filter)

        context = {
            'transactions': transactions,
            'categories': categories,
        }
        return render(request, 'history.html', context)


class NotificationView(View):
    def get(self, request):
        cycle = BudgetCycle.objects.filter(is_active=True).first()

        if not cycle:
            return render(request, 'history.html', {'message': 'مفيش cycle نشط'})

        spent_pct = cycle.get_spent_percentage()
        notification = None

        if spent_pct >= 100:
            already = NotificationLog.objects.filter(
                cycle=cycle, threshold_pct=100, is_triggered=True
            ).exists()
            if not already:
                notification = NotificationLog.objects.create(
                    cycle=cycle, threshold_pct=100, type='EXHAUSTED_100'
                )
                notification.mark_as_sent()

        elif spent_pct >= 80:
            already = NotificationLog.objects.filter(
                cycle=cycle, threshold_pct=80, is_triggered=True
            ).exists()
            if not already:
                notification = NotificationLog.objects.create(
                    cycle=cycle, threshold_pct=80, type='WARNING_80'
                )
                notification.mark_as_sent()

        return render(request, 'history.html', {
            'spent_pct': spent_pct,
            'notification': notification,
        })