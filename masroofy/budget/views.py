import json

from django.shortcuts import render, redirect, get_object_or_404
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views import View
from django.db.models import Sum, Q

from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin 
from django.contrib import messages

from django.views.decorators.csrf import csrf_exempt

from .dao import CategoryDAO, TransactionDAO
from .expense_view import ExpenseView
from .rollover_view import RolloverView
from .models import (
    Transaction,
    Category,
    BudgetCycle,
    DailyRecord,
)

from django.views.decorators.csrf import csrf_exempt


# =========================
# AUTH - LOGIN
# =========================
def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect("dashboard")

        messages.error(request, "Invalid username or password")
        return redirect("login")

    return render(request, "login.html")


# =========================
# AUTH - SIGNUP
# =========================
def signup_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            messages.error(request, "❌ Passwords do not match")
            return render(request, 'signup.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "❌ Username already exists")
            return render(request, 'signup.html')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('dashboard')

        messages.error(request, "❌ Authentication failed")
        return render(request, 'signup.html')

    return render(request, 'signup.html')


# =========================
# AUTH - LOGOUT
# =========================
def logout_view(request):
    logout(request)
    return redirect('login')


def home(request):
    return render(request, 'index.html')


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
        return {"msg": f"🚨 تجاوزت الحد اليومي ({limit} ج.م)", "type": "danger", "percentage": round(percentage, 0)}
    elif spent >= (limit * 0.8):
        return {"msg": f"⚠️ استخدمتي {percentage:.0f}%، فاضل {remaining:.2f} ج.م", "type": "warning", "percentage": round(percentage, 0)}
    elif spent >= (limit * 0.6):
        return {"msg": f"ℹ️ استهلاك عالي ({percentage:.0f}%)، المتبقي {remaining:.2f} ج.م", "type": "info", "percentage": round(percentage, 0)}

    return None


# =========================
# CYCLE ALERT
# =========================
def get_cycle_alert(cycle):
    if not cycle:
        return None

    total = float(cycle.total_allowance)
    spent = Transaction.objects.filter(cycle=cycle).aggregate(total=Sum('amount'))['total'] or 0
    spent = float(spent)

    remaining = total - spent
    percentage = (spent / total) * 100 if total > 0 else 0

    if percentage >= 100:
        return {"msg": "🚨 انتهت الميزانية!", "type": "danger", "percentage": 100}
    elif percentage >= 80:
        return {"msg": f"⚠️ استخدمت {percentage:.0f}%", "type": "warning", "percentage": round(percentage, 0)}
    elif percentage >= 60:
        return {"msg": f"ℹ️ استخدمت {percentage:.0f}%", "type": "info", "percentage": round(percentage, 0)}

    return None


# =========================
# DELETE TRANSACTION
# =========================
@csrf_exempt
def delete_transaction(request, tx_id):
    transaction = get_object_or_404(Transaction, pk=tx_id)

    cycle = BudgetCycle.objects.filter(
        user=request.user,
        is_active=True
    ).first()

    today = transaction.timestamp.date()

    transaction.delete()

    if cycle:
        total_spent_now = Transaction.objects.filter(
            user=request.user,
            cycle=cycle
        ).aggregate(total=Sum('amount'))['total'] or 0

        cycle.remaining_balance = float(cycle.total_allowance) - float(total_spent_now)
        cycle.save()

        daily_record = DailyRecord.objects.filter(
            user=request.user,
            cycle=cycle,
            date=today
        ).first()

        if daily_record:
            daily_spent = Transaction.objects.filter(
                user=request.user,
                timestamp__date=today
            ).aggregate(total=Sum('amount'))['total'] or 0

            daily_record.total_spent = daily_spent
            daily_record.save()

    return redirect('record_expense')


# =========================
# RECORD EXPENSE
# =========================
@csrf_exempt
def record_expense(request):
    cat_dao = CategoryDAO()
    tx_dao = TransactionDAO()

    cycle = BudgetCycle.objects.filter(
        user=request.user,
        is_active=True
    ).first()

    today = timezone.now().date()

    daily_record = DailyRecord.objects.filter(
        user=request.user,
        cycle=cycle,
        date=today
    ).first() if cycle else None

    context = {
        "categories": cat_dao.get_all(),
        "cycle": cycle,
        "daily_record": daily_record,
        "today_transactions": tx_dao.get_by_date(today) if cycle else [],
        "result_message": None,
        "result_status": None,
        "daily_alert": get_daily_alert(daily_record),
        "cycle_alert": get_cycle_alert(cycle),
        "form": {
            "amount": {"value": "", "errors": []},
            "category_id": {"value": "", "errors": []},
        },
    }

    if request.method == "POST":
        if cycle:
            RolloverView().rollover_all_pending(cycle.id)

        raw_amount = request.POST.get("amount", "").strip()
        raw_category_id = request.POST.get("category_id", "").strip()

        context["form"]["amount"]["value"] = raw_amount
        context["form"]["category_id"]["value"] = raw_category_id

        errors = []

        try:
            amount = float(raw_amount)
            if amount <= 0:
                errors.append("المبلغ لازم يكون أكبر من صفر")
        except:
            errors.append("المبلغ لازم يكون رقم صحيح")
            amount = None

        if errors:
            context["form"]["amount"]["errors"] = errors
            return render(request, "budget/expense_entry.html", context)

        result = ExpenseView().record_expense(
            amount=amount,
            category_id=int(raw_category_id),
            cycle_id=cycle.id,
        )

        return redirect("record_expense")

    return render(request, "budget/expense_entry.html", context)


# =========================
# HISTORY VIEW
# =========================
class HistoryView(View):
    def get(self, request):
        transactions = Transaction.objects.filter(
            user=request.user
        ).select_related("category").order_by('-timestamp')

        total_spent = transactions.aggregate(total=Sum('amount'))['total'] or 0

        categories = Category.objects.annotate(
            total_spent=Sum('transaction__amount', filter=Q(transaction__user=request.user))
        )

        cycle = BudgetCycle.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        today = timezone.now().date()
        daily_record = DailyRecord.objects.filter(
            user=request.user,
            cycle=cycle,
            date=today
        ).first() if cycle else None

        return render(request, 'history.html', {
            'transactions': transactions,
            'categories': categories,
            'total_spent': total_spent,
            'daily_alert': get_daily_alert(daily_record),
            'cycle_alert': get_cycle_alert(cycle),
        })

    def post(self, request):
        transaction_id = request.POST.get('transaction_id')
        if transaction_id:
            Transaction.objects.filter(
                id=transaction_id,
                user=request.user
            ).delete()
        return redirect('/history/')


# =========================
# DASHBOARD
# =========================
class DashboardView(LoginRequiredMixin, View):
    login_url = 'login'

    def get(self, request):

        cycle = BudgetCycle.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        if not cycle:
            return render(request, 'dashboard.html', {'error': "No active cycle"})

        transactions = Transaction.objects.filter(
            user=request.user,
            cycle=cycle
        )

        spent = transactions.aggregate(Sum('amount'))['amount__sum'] or 0
        total = cycle.total_allowance or 0
        remaining = total - spent

        latest = transactions.order_by('-timestamp')[:5]

        return render(request, 'dashboard.html', {
            'total': total,
            'spent': spent,
            'remaining': remaining,
            'latest': latest,
        })


# =========================
# STATS VIEW
# =========================
class StatsView(View):
    def get(self, request):
        cycle = BudgetCycle.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        if not cycle:
            return render(request, 'stats.html', {'error': "No active cycle"})

        transactions = Transaction.objects.filter(
            user=request.user,
            cycle=cycle
        )

        total_spent = transactions.aggregate(Sum('amount'))['total'] or 0

        category_data = transactions.values('category__name').annotate(total=Sum('amount'))

        labels = [d['category__name'] for d in category_data]
        values = [float(d['total']) for d in category_data]

        return render(request, 'stats.html', {
            'labels': labels,
            'values': values,
            'total_spent': float(total_spent),
        })
    
    
class NotificationView(View):
    def get(self, request):
        cycle = BudgetCycle.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        if not cycle:
            return render(request, 'notifications.html', {
                'message': 'No active cycle found'
            })

        total_spent_amt = Transaction.objects.filter(
            user=request.user,
            cycle=cycle
        ).aggregate(Sum('amount'))['amount__sum'] or 0

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