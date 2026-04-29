import json
from django.shortcuts import render
from django.utils import timezone
from django.views import View
from django.db.models import Sum

from .dao import CategoryDAO, TransactionDAO
from .expense_view import ExpenseView
from .rollover_view import RolloverView
from .models import (
    Transaction,
    Category,
    BudgetCycle,
    DailyRecord,
    NotificationLog
)


# =========================
# RECORD EXPENSE
# =========================
def record_expense(request):

    cat_dao = CategoryDAO()
    tx_dao  = TransactionDAO()

    cycle = BudgetCycle.objects.filter(is_active=True).first()
    today = timezone.now().date()

    daily_record = (
        DailyRecord.objects.filter(cycle=cycle, date=today).first()
        if cycle else None
    )

    context = {
        "categories": cat_dao.get_all(),
        "cycle": cycle,
        "daily_record": daily_record,
        "today_transactions": tx_dao.get_by_date(today) if cycle else [],
        "result_message": None,
        "result_status": None,
        "form": {
            "amount": {"value": "", "errors": []},
            "category_id": {"value": "", "errors": []},
        },
    }

    if request.method == "POST":

        if cycle:
            RolloverView().rollover_all_pending(cycle.id)

        raw_amount      = request.POST.get("amount", "").strip()
        raw_category_id = request.POST.get("category_id", "").strip()
        raw_cycle_id    = request.POST.get("cycle_id", "").strip()

        context["form"]["amount"]["value"] = raw_amount
        context["form"]["category_id"]["value"] = raw_category_id

        errors = []

        try:
            amount = float(raw_amount)
            if amount <= 0:
                errors.append("المبلغ لازم يكون أكبر من صفر")
        except ValueError:
            errors.append("المبلغ لازم يكون رقم صحيح")
            amount = None

        if not raw_category_id:
            errors.append("اختر فئة")

        if not raw_cycle_id:
            errors.append("مفيش cycle محدد")

        if errors:
            context["form"]["amount"]["errors"] = errors
            return render(request, "budget/expense_entry.html", context)

        result = ExpenseView().record_expense(
            amount=amount,
            category_id=int(raw_category_id),
            cycle_id=int(raw_cycle_id),
        )

        context["result_message"] = result["message"]
        context["result_status"] = result["status"]

        cycle = BudgetCycle.objects.filter(is_active=True).first()

        context["cycle"] = cycle
        context["daily_record"] = DailyRecord.objects.filter(
            cycle=cycle,
            date=today
        ).first()

        context["today_transactions"] = tx_dao.get_by_date(today)

    return render(request, "budget/expense_entry.html", context)


# =========================
# HISTORY VIEW (MAIN FIXED)
# =========================
class HistoryView(View):

    def get(self, request):

        transactions = Transaction.objects.select_related("category").order_by('-timestamp')
        categories = Category.objects.all()

        # filters
        category_id = request.GET.get('category')
        if category_id:
            transactions = transactions.filter(category_id=category_id)

        date_filter = request.GET.get('date')
        if date_filter:
            transactions = transactions.filter(timestamp__date=date_filter)

        # total spent
        total_spent = transactions.aggregate(total=Sum('amount'))['total'] or 0

        # JSON for chart
        categories_json = json.dumps(list(categories.values('name')))

        context = {
            "transactions": transactions,
            "categories": categories,
            "total_spent": total_spent,
            "categories_json": categories_json,
        }

        return render(request, "history.html", context)


# =========================
# NOTIFICATION VIEW (SAFE)
# =========================
class NotificationView(View):

    def get(self, request):

        cycle = BudgetCycle.objects.filter(is_active=True).first()

        transactions = Transaction.objects.select_related("category")
        categories = Category.objects.all()

        if not cycle:
            return render(request, "history.html", {
                "transactions": transactions,
                "categories": categories,
                "total_spent": 0,
                "categories_json": json.dumps(list(categories.values('name'))),
                "message": "مفيش cycle نشط"
            })

        spent_pct = cycle.get_spent_percentage()
        notification = None

        if spent_pct >= 100:
            already = NotificationLog.objects.filter(
                cycle=cycle,
                threshold_pct=100,
                is_triggered=True
            ).exists()

            if not already:
                notification = NotificationLog.objects.create(
                    cycle=cycle,
                    threshold_pct=100,
                    type='EXHAUSTED_100'
                )
                notification.mark_as_sent()

        elif spent_pct >= 80:
            already = NotificationLog.objects.filter(
                cycle=cycle,
                threshold_pct=80,
                is_triggered=True
            ).exists()

            if not already:
                notification = NotificationLog.objects.create(
                    cycle=cycle,
                    threshold_pct=80,
                    type='WARNING_80'
                )
                notification.mark_as_sent()

        return render(request, "history.html", {
            "transactions": transactions,
            "categories": categories,
            "total_spent": 0,
            "categories_json": json.dumps(list(categories.values('name'))),
            "spent_pct": spent_pct,
            "notification": notification,
        })