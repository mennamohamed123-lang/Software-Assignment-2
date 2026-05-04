import json
from django.shortcuts import render
from django.utils import timezone
from django.views import View
from django.db.models import Sum, Q

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

from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, redirect



def delete_transaction(request, tx_id):
    # 1. بنجيب المعاملة اللي هنمسحها
    transaction = get_object_or_404(Transaction, pk=tx_id)
    cycle = BudgetCycle.objects.filter(is_active=True).first()
    today = transaction.timestamp.date()
    
    # 2. بنمسح المعاملة
    transaction.delete()
    
    if cycle:
        # 3. تحديث الـ Remaining Balance (المربع اللي في الصورة)
        # بنحسب مجموع كل المعاملات اللي باقية في الـ Cycle ده
        total_spent_now = Transaction.objects.filter(
            timestamp__range=(cycle.start_date, cycle.end_date)
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # بنفترض إن الميزانية الكلية متخزنة في حقل اسمه total_budget أو initial_limit
        # إحنا بنحدث القيمة اللي بتظهر في المربع الأزرق يدوياً
        # جربي تشوفي اسم الحقل عندك إيه (غالباً balance أو total_budget)
        if hasattr(cycle, 'total_budget'):
            # لو الـ 1800 دي هي الـ total_budget، فإحنا بنرجع ليها الفلوس
            # لكن الأفضل إن الـ UI يعرض (Initial - Spent)
            cycle.total_budget = cycle.total_budget # ده مجرد تأكيد
            cycle.save()

        # 4. تحديث صرف اليوم (عشان الـ Spent Today يصفر)
        daily_record = DailyRecord.objects.filter(cycle=cycle, date=today).first()
        if daily_record:
            daily_spent = Transaction.objects.filter(
                timestamp__date=today
            ).aggregate(total=Sum('amount'))['total'] or 0
            daily_record.total_spent = daily_spent
            daily_record.save()
            
    return redirect('record_expense')
# =========================
# DAILY ALERT HELPER
# =========================
def get_daily_alert(daily_record):
    if not daily_record:
        return None

    spent = daily_record.total_spent
    limit = daily_record.allocated_limit
    remaining = limit - spent

    percentage = (spent / limit) * 100 if limit > 0 else 0

    if spent >= limit:
        return {
            "msg": f"🚨 تجاوزت الحد اليومي ({limit} ج.م)",
            "type": "danger",
            "percentage": round(percentage, 0)
        }

    elif spent >= (limit * 0.8):
        return {
            "msg": f"⚠️ استخدمتي {percentage:.0f}%، فاضل {remaining:.2f} ج.م",
            "type": "warning",
            "percentage": round(percentage, 0)
        }

    elif spent >= (limit * 0.6):
        return {
            "msg": f"ℹ️ استهلاك عالي شوية ({percentage:.0f}%)، المتبقي {remaining:.2f} ج.م",
            "type": "info",
            "percentage": round(percentage, 0)
        }

    return None

from django.views.decorators.csrf import csrf_exempt


# =========================
# DAILY ALERT HELPER
# =========================
def get_daily_alert(daily_record):
    if not daily_record:
        return None

    spent = daily_record.total_spent
    limit = daily_record.allocated_limit
    remaining = limit - spent

    percentage = (spent / limit) * 100 if limit > 0 else 0

    if spent >= limit:
        return {
            "msg": f"🚨 تجاوزت الحد اليومي ({limit} ج.م)",
            "type": "danger",
            "percentage": round(percentage, 0)
        }

    elif spent >= (limit * 0.8):
        return {
            "msg": f"⚠️ استخدمتي {percentage:.0f}%، فاضل {remaining:.2f} ج.م",
            "type": "warning",
            "percentage": round(percentage, 0)
        }

    elif spent >= (limit * 0.6):
        return {
            "msg": f"ℹ️ استهلاك عالي شوية ({percentage:.0f}%)، المتبقي {remaining:.2f} ج.م",
            "type": "info",
            "percentage": round(percentage, 0)
        }

    return None


# =========================
# RECORD EXPENSE
# =========================
@csrf_exempt
def record_expense(request):
    cat_dao = CategoryDAO()
    tx_dao  = TransactionDAO()

    cycle = BudgetCycle.objects.filter(is_active=True).first()
    today = timezone.now().date()

    if cycle:
        # 1. بنحسب الصرف الحقيقي من جدول المعاملات
        actual_spent = Transaction.objects.filter(cycle=cycle).aggregate(total=Sum('amount'))['total'] or 0
        
        # 2. بنحدث الـ remaining_balance في الداتابيز نفسها
        # عشان الـ 1800 دي تتغير وتبقى هي الميزانية الكلية ناقص الصرف الفعلي
        cycle.remaining_balance = float(cycle.total_allowance) - float(actual_spent)
        cycle.save() # السطر ده هو اللي هيخلي الـ Admin والـ UI يظبطوا

    daily_record = (
        DailyRecord.objects.filter(cycle=cycle, date=today).first()
        if cycle else None
    )

    context = {
        "categories": cat_dao.get_all(),
        "cycle": cycle,
        "remaining_balance": cycle.remaining_balance if cycle else 0,
        "daily_record": daily_record,
        "today_transactions": tx_dao.get_by_date(today) if cycle else [],
        "form": {"amount": {"value": "", "errors": []}, "category_id": {"value": "", "errors": []}},
        "result_message": None,
        "result_status": None,
        "daily_alert": None,
        "form": {
            "amount": {"value": "", "errors": []},
            "category_id": {"value": "", "errors": []},
        },
    }

    if request.method == "POST":
        # ... (نفس كود الـ POST اللي فات) ...
        # بس اتأكدي إنك بتنادي على نفس الحسبة بعد الـ ExpenseView().record_expense
        if cycle:
            RolloverView().rollover_all_pending(cycle.id)

        raw_amount      = request.POST.get("amount", "").strip()
        raw_category_id = request.POST.get("category_id", "").strip()
        raw_cycle_id    = request.POST.get("cycle_id", "").strip()

        context["form"]["amount"]["value"]      = raw_amount
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
            amount=float(request.POST.get("amount")),
            category_id=int(request.POST.get("category_id")),
            cycle_id=cycle.id,
        )
        
        # تحديث الميزانية فوراً بعد الإضافة
        new_spent = Transaction.objects.filter(cycle=cycle).aggregate(total=Sum('amount'))['total'] or 0
        cycle.remaining_balance = float(cycle.total_allowance) - float(new_spent)
        cycle.save()
        
        return redirect('record_expense') # اعملي Redirect عشان الصفحة تحمل بالداتا الجديدة

        context["result_message"] = result["message"]
        context["result_status"]  = result["status"]

        # تحديث + تنبيه
        current_daily = DailyRecord.objects.filter(cycle=cycle, date=today).first()
        context["daily_alert"] = get_daily_alert(current_daily)

        context["cycle"] = BudgetCycle.objects.filter(is_active=True).first()
        context["daily_record"] = current_daily
        context["today_transactions"] = tx_dao.get_by_date(today)

        context["form"]["amount"]["value"] = ""
        context["form"]["category_id"]["value"] = ""

    else:
        context["daily_alert"] = get_daily_alert(daily_record)

    return render(request, "budget/expense_entry.html", context)


# =========================
# HISTORY VIEW
# =========================
class HistoryView(View):
    def get(self, request):
        transactions = Transaction.objects.select_related("category").order_by('-timestamp')

        # الفلاتر (زي ما هي)
        category_id = request.GET.get('category')
        if category_id:
            transactions = transactions.filter(category_id=category_id)
        
        date_filter = request.GET.get('date')
        if date_filter:
            transactions = transactions.filter(timestamp__date=date_filter)

        total_spent = sum(t.amount for t in transactions)
        # ✅ أداء أفضل
        total_spent = transactions.aggregate(
            total=Sum('amount')
        )['total'] or 0

        # ✅ categories حسب الفلتر
        categories = Category.objects.annotate(
            total_spent=Sum(
                'transaction__amount',
                filter=Q(transaction__in=transactions)
            )
        )

        cycle = BudgetCycle.objects.filter(is_active=True).first()
        today = timezone.now().date()

        # 1. تنبيه الحد اليومي (Daily Limit Alert)
        daily_record = DailyRecord.objects.filter(cycle=cycle, date=today).first() if cycle else None
        daily_alert = get_daily_alert(daily_record)

        # 2. تنبيه الميزانية الكلية (Remaining Balance Alert)
        cycle_alert = get_notification_alert(cycle)
        today = timezone.now().date()
        daily_record = DailyRecord.objects.filter(cycle=cycle, date=today).first()

        context = {
            'transactions': transactions,
            'categories': categories,
            'total_spent': total_spent,
            'daily_alert': daily_alert,   # التنبيه اليومي
            'cycle_alert': cycle_alert,   # التنبيه الكلي (بتاع الـ 80% و 100%)
            'cycle': cycle,
            'daily_alert': get_daily_alert(daily_record),
        }

        return render(request, 'history.html', context)


# =========================
# NOTIFICATION VIEW
# =========================
class NotificationView(View):
    def get(self, request):
        cycle = BudgetCycle.objects.filter(is_active=True).first()

        if not cycle:
            return render(request, 'notifications.html', {
                'message': 'No active cycle found'
            })

        total_spent_amt = Transaction.objects.filter(cycle=cycle).aggregate(
            Sum('amount')
        )['amount__sum'] or 0

        spent_pct = (total_spent_amt / cycle.total_allowance) * 100 if cycle.total_allowance > 0 else 0

        if spent_pct >= 100:
            notification_level = "danger"
        elif spent_pct >= 80:
            notification_level = "warning"
        else:
            notification_level = "success"

        return render(request, 'notifications.html', {
            'spent_pct': float(spent_pct),
            'notification_level': notification_level,
            'total_spent': total_spent_amt
        })
    
# =========================
# DashboardView
# =========================
class DashboardView(View):
    def get(self, request):
        cycle = BudgetCycle.objects.filter(is_active=True).first()

        if not cycle:
            return render(request, 'dashboard.html', {'error': "No active cycle"})

        transactions = Transaction.objects.filter(cycle=cycle)

        spent = transactions.aggregate(Sum('amount'))['amount__sum'] or 0
        total = cycle.total_allowance or 0
        remaining = total - spent

        days = (cycle.end_date - cycle.start_date).days + 1
        daily_limit = total / days if days > 0 else 0

        today = timezone.now().date()
        is_final_day = (cycle.end_date == today)

        spent_percentage = (spent / total * 100) if total > 0 else 0
        show_80_alert = spent_percentage >= 80

        # مقارنة بسيطة وآمنة بدل التعقيد
        budget_is_tight = remaining < (total * 0.2)

        latest = transactions.order_by('-timestamp')[:5]

        return render(request, 'dashboard.html', {
            'total': total,
            'spent': spent,
            'remaining': remaining,
            'daily_limit': daily_limit,
            'latest': latest,

            'is_final_day': is_final_day,
            'spent_percentage': round(spent_percentage, 1),
            'show_80_alert': show_80_alert,
            'budget_is_tight': budget_is_tight,
        })


class StatsView(View):
    def get(self, request):
        cycle = BudgetCycle.objects.filter(is_active=True).first()

        if not cycle:
            return render(request, 'stats.html', {'error': "No active cycle"})

        transactions = Transaction.objects.filter(cycle=cycle)

        total_spent = transactions.aggregate(Sum('amount'))['amount__sum'] or 0

        category_data = (
            transactions
            .values('category__name')
            .annotate(total=Sum('amount'))
        )

        labels = [d['category__name'] for d in category_data]
        values = [float(d['total']) for d in category_data]

        daily_data = (
            transactions
            .values('timestamp__date')
            .annotate(total=Sum('amount'))
            .order_by('timestamp__date')
        )

        line_labels = [str(d['timestamp__date']) for d in daily_data]
        line_values = [float(d['total']) for d in daily_data]

        return render(request, 'stats.html', {
            'labels': labels,
            'values': values,
            'line_labels': line_labels,
            'line_values': line_values,
            'total_spent': float(total_spent),
        })