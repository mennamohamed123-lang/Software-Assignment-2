"""
views.py — Masroofy (FIXED)
===========================
الإصلاحات في هذه النسخة:
  1. Edit cycle  → يعدّل الـ cycle الحالي بدون مسح transactions
  2. Reset cycle → يمسح كل الـ transactions ثم يعيد تعيين التواريخ
  3. timedelta   → days - 1 لإصلاح حساب الـ 31 يوم
  4. History     → فلترة دقيقة بالتاريخ داخل نطاق الـ cycle
"""

import json
from datetime import date, timedelta, datetime

from django.shortcuts import render, redirect, get_object_or_404
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
from .models import Transaction, Category, BudgetCycle, DailyRecord


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

def login_view(request):
    """Handles user authentication and login.

    Processes login form submissions by authenticating the provided username
    and password. On successful authentication, logs the user in and redirects
    to the dashboard. On failure, displays an error message and redirects back
    to the login page.

    Args:
        request: The HTTP request object containing POST data with 'username'
                and 'password' fields.

    Returns:
        If POST request:
            - Redirect to 'dashboard' on successful login
            - Redirect to 'login' with error message on failure
        If GET request:
            - Rendered login.html template

    Note:
        Uses Django's built-in authentication system. Error messages are
        displayed using Django's messages framework.
    """
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


def signup_view(request):
    """Handles new user registration.

    Processes signup form submissions by validating the provided data and
    creating a new user account. Checks for username uniqueness and password
    confirmation. On successful registration, logs the new user in and
    redirects to the dashboard.

    Args:
        request: The HTTP request object containing POST data with 'username',
                'password', 'confirm_password', and other user fields.

    Returns:
        If POST request:
            - Redirect to 'dashboard' on successful registration
            - Redirect to 'signup' with error message on validation failure
        If GET request:
            - Rendered signup.html template

    Note:
        Performs basic validation for username availability and password
        matching. Uses Django's User model for account creation.
    """
    if request.method == "POST":
        username         = request.POST.get("username")
        email            = request.POST.get("email")
        password         = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            messages.error(request, "❌ Passwords do not match")
            return render(request, "signup.html")

        if User.objects.filter(username=username).exists():
            messages.error(request, "❌ Username already exists")
            return render(request, "signup.html")

        user = User.objects.create_user(username=username, email=email, password=password)
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("dashboard")

        messages.error(request, "❌ Authentication failed")
        return render(request, "signup.html")

    return render(request, "signup.html")


def logout_view(request):
    """Handles user logout and redirects to login page.

    Logs out the current user using Django's authentication system and
    redirects them to the login page. This function works for both GET
    and POST requests.

    Args:
        request: The HTTP request object from the logged-in user.

    Returns:
        Redirect response to the login page.

    Note:
        This function does not require authentication checks as Django's
        logout function handles unauthenticated users gracefully.
    """
    logout(request)
    return redirect("login")


def home(request):
    """Handles the home page routing based on authentication status.

    If the user is not authenticated, displays the public landing page.
    If authenticated, redirects to the expense recording page as the main
    application interface.

    Args:
        request: The HTTP request object.

    Returns:
        Rendered index.html for unauthenticated users, or redirect to
        record_expense for authenticated users.

    Note:
        This serves as the entry point that routes users to appropriate
        sections based on their login status.
    """
    if not request.user.is_authenticated:
        return render(request, "index.html")
    return redirect("record_expense")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _parse_cycle_form(post, today):
    """Parses and validates budget cycle form data from POST request.

    Processes form input for creating or editing budget cycles, handling
    both duration-based (number of days) and end-date-based cycle specifications.
    Performs comprehensive validation and provides detailed error messages.

    Args:
        post: The request.POST QueryDict containing form data with keys:
             - 'total_allowance': String representation of budget amount
             - 'duration_days': Optional string for number of days
             - 'end_date': Optional string in 'YYYY-MM-DD' format
        today: Date object representing the current date for validation.

    Returns:
        Tuple of (total_allowance, end_date, errors, form_data):
        - total_allowance: Float budget amount or None if invalid
        - end_date: Date object for cycle end or None if invalid
        - errors: List of error message strings
        - form_data: Dict with original form values for re-populating forms

    Validation Rules:
        - total_allowance: Must be positive float
        - duration_days: Must be positive integer >= 1, calculates end_date
        - end_date: Must be valid date >= today, or duration_days must be provided
        - Either duration_days or end_date must be specified

    Note:
        Uses corrected date calculation (days - 1) so 30 days means
        day 1 through day 30 inclusive, not 31 days total.
    """
    errors    = []
    form_data = {}

    raw_total = post.get("total_allowance", "").strip()
    raw_days  = post.get("duration_days",   "").strip()
    raw_end   = post.get("end_date",         "").strip()
    form_data.update(total_allowance=raw_total, duration_days=raw_days, end_date=raw_end)

    total_allowance = None
    try:
        total_allowance = float(raw_total)
        if total_allowance <= 0:
            errors.append("Total budget must be greater than zero.")
    except (ValueError, TypeError):
        errors.append("Please enter a valid budget amount.")

    end_date = None
    if raw_days:
        try:
            days = int(raw_days)
            if days < 1:
                errors.append("Duration must be at least 1 day.")
            else:
                # ✅ -1 يجعل 30 يوماً = اليوم الأول حتى اليوم الـ 30 (وليس الـ 31)
                end_date = today + timedelta(days=days - 1)
        except ValueError:
            errors.append("Please enter a valid number of days.")
    elif raw_end:
        try:
            end_date = datetime.strptime(raw_end, "%Y-%m-%d").date()
            if end_date < today:
                errors.append("End date must be in the future.")
        except ValueError:
            errors.append("Invalid end date format.")
    else:
        errors.append("Please specify a duration or an end date.")

    return total_allowance, end_date, errors, form_data


# ─────────────────────────────────────────────
# SETUP CYCLE (صفحة منفصلة)
# ─────────────────────────────────────────────

@csrf_exempt
def setup_cycle(request):
    """Dedicated view for initial budget cycle setup.

    Provides a separate interface for creating the first budget cycle when
    a user has no active cycle. Handles form validation and cycle creation
    with proper error handling and user feedback.

    Args:
        request: HTTP request object from authenticated user.

    Returns:
        POST: Redirect to record_expense on successful cycle creation,
              or re-render form with errors
        GET: Render setup_cycle.html template with form

    Context Variables:
        - errors: List of validation error messages
        - form_data: Dictionary with current form values for re-population
        - active_cycle: Current active cycle (should be None for this view)

    Business Logic:
        - Deactivates any existing active cycles before creating new one
        - Calculates safe_daily_limit as total_allowance / total_days
        - Sets cycle as active and initializes remaining_balance

    Note:
        This view is typically accessed when record_expense detects no active cycle.
        Uses the same _parse_cycle_form helper for consistent validation.
    """
    active_cycle = (
        BudgetCycle.objects.filter(is_active=True, user=request.user).first()
        if request.user.is_authenticated else None
    )

    if request.method == "POST":
        today = date.today()
        total_allowance, end_date, errors, form_data = _parse_cycle_form(request.POST, today)

        if errors:
            return render(request, "budget/setup_cycle.html", {
                "errors": errors, "form_data": form_data, "active_cycle": active_cycle,
            })

        total_days       = (end_date - today).days + 1
        safe_daily_limit = round(total_allowance / total_days, 2)

        BudgetCycle.objects.filter(is_active=True, user=request.user).update(is_active=False)
        BudgetCycle.objects.create(
            user=request.user,
            total_allowance=total_allowance,
            start_date=today,
            end_date=end_date,
            remaining_balance=total_allowance,
            safe_daily_limit=safe_daily_limit,
            is_active=True,
        )
        return redirect("record_expense")

    return render(request, "budget/setup_cycle.html", {
        "active_cycle": active_cycle, "form_data": {}, "errors": [],
    })


# ─────────────────────────────────────────────
# ALERT HELPERS
# ─────────────────────────────────────────────

def get_daily_alert(daily_record):
    """Generates alert information for daily spending status.

    Analyzes the current day's spending against the allocated daily limit
    and returns appropriate alert information based on spending thresholds.
    Used to provide user feedback on daily budget status.

    Args:
        daily_record: DailyRecord instance for the current day, or None.

    Returns:
        Dict with alert information or None if no alert needed:
        {
            "msg": str,           # Alert message in Arabic
            "type": str,          # Bootstrap alert type ("danger", "warning", "info")
            "percentage": float   # Spending percentage (0-100)
        }

    Alert Thresholds:
        - 100%+: "danger" - Daily limit reached/exceeded
        - 80-99%: "warning" - High spending warning
        - 60-79%: "info" - Moderate spending notice
        - <60%: None - No alert

    Note:
        Queries actual transactions for the day to ensure accurate spending
        calculation, rather than relying on stored total_spent which may be stale.
    """
    if not daily_record:
        return None
    limit = daily_record.allocated_limit
    if limit <= 0:
        return None

    spent = float(
        Transaction.objects.filter(
            cycle=daily_record.cycle,
            timestamp__date=daily_record.date,
        ).aggregate(total=Sum("amount"))["total"] or 0
    )

    remaining  = limit - spent
    percentage = (spent / limit) * 100

    if spent >= limit:
        return {"msg": f"Daily limit reached — spent {spent:.2f} of {limit:.2f} EGP.", "type": "danger",  "percentage": min(round(percentage), 100)}
    elif spent >= limit * 0.8:
        return {"msg": f"You've used {percentage:.0f}% of today's limit. {remaining:.2f} EGP left.", "type": "warning", "percentage": round(percentage)}
    elif spent >= limit * 0.6:
        return {"msg": f"Spending is a bit high today ({percentage:.0f}%). {remaining:.2f} EGP left.", "type": "info", "percentage": round(percentage)}
    return None


def get_cycle_alert(cycle):
    """Generates alert information for overall cycle budget status.

    Analyzes total spending against the cycle's total allowance and returns
    appropriate alert information based on budget utilization thresholds.

    Args:
        cycle: BudgetCycle instance, or None.

    Returns:
        Dict with alert information or None if no alert needed:
        {
            "msg": str,           # Alert message in Arabic
            "type": str,          # Bootstrap alert type ("danger", "warning", "info")
            "percentage": float   # Spending percentage (0-100)
        }

    Alert Thresholds:
        - 100%+: "danger" - Budget exhausted
        - 80-99%: "warning" - High utilization warning
        - 60-79%: "info" - Moderate utilization notice
        - <60%: None - No alert

    Note:
        Calculates actual spending by querying all transactions in the cycle,
        ensuring accuracy even if balance calculations have discrepancies.
    """
    if not cycle:
        return None
    total = float(cycle.total_allowance)
    spent = float(Transaction.objects.filter(cycle=cycle).aggregate(total=Sum("amount"))["total"] or 0)
    remaining  = total - spent
    percentage = (spent / total * 100) if total > 0 else 0

    if percentage >= 100:
        return {"msg": f"Budget exhausted — spent {spent:.2f} of {total:.2f} EGP.", "type": "danger", "percentage": 100}
    elif percentage >= 80:
        return {"msg": f"Heads up — {percentage:.0f}% used. {remaining:.2f} EGP left.", "type": "warning", "percentage": round(percentage)}
    elif percentage >= 60:
        return {"msg": f"You've used {percentage:.0f}% of your budget. {remaining:.2f} EGP left.", "type": "info", "percentage": round(percentage)}
    return None


# ─────────────────────────────────────────────
# DELETE SINGLE TRANSACTION
# ─────────────────────────────────────────────

@csrf_exempt
def delete_transaction(request, tx_id):
    """Deletes a specific transaction and redirects to expense recording page.

    Removes a transaction by ID, ensuring the user owns it. The deletion
    automatically triggers balance updates via the post_delete signal in models.py
    which adjusts both cycle remaining_balance and daily record total_spent.

    Args:
        request: The HTTP request object from an authenticated user.
        tx_id: The primary key of the transaction to delete.

    Returns:
        Redirect response to the record_expense page.

    Raises:
        Http404: If the transaction doesn't exist or doesn't belong to the user.

    Note:
        Uses get_object_or_404 for security, ensuring users can only delete
        their own transactions. Balance reconciliation happens automatically
        through the signal system.
    """
    transaction = get_object_or_404(Transaction, pk=tx_id, user=request.user)
    transaction.delete()
    return redirect("record_expense")


# ─────────────────────────────────────────────
# RECORD EXPENSE — الصفحة الرئيسية
# ─────────────────────────────────────────────

@csrf_exempt
def record_expense(request):
    """Main expense recording interface handling cycle management and expense logging.

    This is the primary application view that handles:
    - Creating new budget cycles when none exist
    - Editing existing cycles (updating budget/duration without clearing transactions)
    - Resetting cycles (clearing all transactions and restarting)
    - Recording new expenses with validation and balance updates
    - Displaying current budget status, alerts, and transaction history

    The function supports multiple POST actions via request.POST.get("action"):
    - "create_cycle": Creates initial budget cycle
    - "edit_cycle": Modifies existing cycle parameters
    - "reset_cycle": Clears transactions and resets cycle
    - Default POST: Records a new expense

    Args:
        request: HTTP request object from authenticated user.

    Returns:
        Rendered expense_entry.html template with comprehensive context including:
        - Current cycle information and status
        - Available categories for expense selection
        - Today's transactions and spending summary
        - Alert notifications for budget thresholds
        - Form data and validation errors
        - Dynamic daily limit calculations

    Context Variables:
        - cycle: Current active BudgetCycle or None
        - categories: List of all available categories
        - today_transactions: List of today's transactions
        - daily_alert/cycle_alert: Budget threshold alerts
        - dynamic_daily_limit: Recalculated daily spending limit
        - spent_today: Total spent today
        - form: Dictionary with current form values and errors

    Business Logic:
        - Automatically rolls over pending surpluses/deficits
        - Updates daily records with current spending
        - Recalculates remaining balances and daily limits
        - Provides real-time budget status feedback

    Note:
        This function integrates multiple business concerns: cycle management,
        expense recording, balance calculations, and UI state management.
        Changes here affect the core user experience and data integrity.
    """
    cat_dao = CategoryDAO()
    tx_dao  = TransactionDAO()
    today   = timezone.now().date()

    # ══════════════════════════════════════════
    # POST: إنشاء cycle جديد (لما مفيش cycle)
    # ══════════════════════════════════════════
    if request.method == "POST" and request.POST.get("action") == "create_cycle":
        total_allowance, end_date, errors, form_data = _parse_cycle_form(request.POST, today)

        if not errors:
            total_days       = (end_date - today).days + 1
            safe_daily_limit = round(total_allowance / total_days, 2)
            BudgetCycle.objects.filter(is_active=True, user=request.user).update(is_active=False)
            BudgetCycle.objects.create(
                user=request.user,
                total_allowance=total_allowance,
                start_date=today,
                end_date=end_date,
                remaining_balance=total_allowance,
                safe_daily_limit=safe_daily_limit,
                is_active=True,
            )
            return redirect("record_expense")

        return render(request, "budget/expense_entry.html", {
            "cycle": None, "categories": cat_dao.get_all(),
            "today_transactions": [], "cycle_errors": errors,
            "cycle_form": form_data,
            "daily_alert": None, "cycle_alert": None,
            "result_message": None, "result_status": None,
            "dynamic_daily_limit": 0, "spent_today": 0,
            "form": {"amount": {"value": "", "errors": []}, "category_id": {"value": "", "errors": []}},
        })

    # ══════════════════════════════════════════
    # POST: تعديل الـ cycle الحالي (EDIT — بدون مسح transactions)
    #
    # ✅ المنطق الصحيح:
    #   - Edit   → يعدّل total_allowance + end_date فقط
    #             الـ transactions القديمة تظل كما هي
    #   - Reset  → action منفصل يمسح كل الـ transactions
    # ══════════════════════════════════════════
    if request.method == "POST" and request.POST.get("action") == "edit_cycle":
        cycle = BudgetCycle.objects.filter(is_active=True, user=request.user).first()
        if cycle:
            total_allowance, end_date, errors, form_data = _parse_cycle_form(request.POST, today)
            if not errors:
                # حساب المصروف الفعلي حتى الآن
                actual_spent = float(
                    Transaction.objects.filter(cycle=cycle)
                    .aggregate(total=Sum("amount"))["total"] or 0
                )
                # ✅ remaining = new_total - ما تم صرفه فعلاً (لا نمسح الـ transactions)
                new_remaining = total_allowance - actual_spent
                total_days    = (end_date - today).days + 1
                days_left     = max((end_date - today).days + 1, 1)

                cycle.total_allowance   = total_allowance
                cycle.end_date          = end_date
                cycle.remaining_balance = new_remaining
                cycle.safe_daily_limit  = round(new_remaining / days_left, 2)
                cycle.save()
                return redirect("record_expense")

        return redirect("record_expense")

    # ══════════════════════════════════════════
    # POST: Reset الـ cycle (يمسح كل الـ transactions)
    # ══════════════════════════════════════════
    if request.method == "POST" and request.POST.get("action") == "reset_cycle":
        cycle = BudgetCycle.objects.filter(is_active=True, user=request.user).first()
        if cycle:
            # ✅ مسح كل الـ transactions المرتبطة بهذا الـ cycle
            deleted_count, _ = Transaction.objects.filter(
                cycle=cycle, user=request.user
            ).delete()

            # ✅ مسح الـ DailyRecords أيضاً
            DailyRecord.objects.filter(cycle=cycle, user=request.user).delete()

            # إعادة تعيين الـ cycle من اليوم
            total_allowance  = float(cycle.total_allowance)
            raw_days = request.POST.get("duration_days", "").strip()
            raw_end  = request.POST.get("end_date", "").strip()

            if raw_days:
                try:
                    days     = int(raw_days)
                    end_date = today + timedelta(days=days - 1)
                except ValueError:
                    end_date = cycle.end_date
            elif raw_end:
                try:
                    end_date = datetime.strptime(raw_end, "%Y-%m-%d").date()
                except ValueError:
                    end_date = cycle.end_date
            else:
                # نفس المدة الأصلية
                original_days = (cycle.end_date - cycle.start_date).days + 1
                end_date      = today + timedelta(days=original_days - 1)

            total_days = (end_date - today).days + 1
            cycle.start_date        = today
            cycle.end_date          = end_date
            cycle.remaining_balance = total_allowance
            cycle.safe_daily_limit  = round(total_allowance / total_days, 2)
            cycle.save()

        return redirect("record_expense")

    # ══════════════════════════════════════════
    # GET: عرض صفحة التسجيل
    # ══════════════════════════════════════════
    cycle = BudgetCycle.objects.filter(is_active=True, user=request.user).first()

    if cycle:
        actual_spent = float(
            Transaction.objects.filter(cycle=cycle)
            .aggregate(total=Sum("amount"))["total"] or 0
        )
        cycle.remaining_balance = float(cycle.total_allowance) - actual_spent
        cycle.save(update_fields=["remaining_balance"])

    dynamic_daily_limit = 0
    spent_today         = 0.0
    daily_record        = None

    if cycle:
        days_left           = max((cycle.end_date - today).days + 1, 1)
        dynamic_daily_limit = round(cycle.remaining_balance / days_left, 2)

        if cycle.safe_daily_limit != dynamic_daily_limit:
            cycle.safe_daily_limit = dynamic_daily_limit
            cycle.save(update_fields=["safe_daily_limit"])

        spent_today = float(
            Transaction.objects.filter(cycle=cycle, timestamp__date=today)
            .aggregate(total=Sum("amount"))["total"] or 0
        )

        daily_record, _ = DailyRecord.objects.get_or_create(
            user=request.user, cycle=cycle, date=today,
            defaults={"allocated_limit": dynamic_daily_limit, "total_spent": spent_today},
        )
        daily_record.total_spent     = spent_today
        daily_record.allocated_limit = dynamic_daily_limit
        daily_record.save(update_fields=["total_spent", "allocated_limit"])

    days_left  = max((cycle.end_date - today).days + 1, 0) if cycle else 0
    total_days = (cycle.end_date - cycle.start_date).days + 1 if cycle else 1

    context = {
        "categories":           cat_dao.get_all(),
        "cycle":                cycle,
        "daily_record":         daily_record,
        "dynamic_daily_limit":  dynamic_daily_limit,
        "spent_today":          spent_today,
        "days_left":            days_left,
        "total_days":           total_days,
        "today_transactions":   tx_dao.get_by_date(today) if cycle else [],
        "result_message":       None,
        "result_status":        None,
        "daily_alert":          get_daily_alert(daily_record),
        "cycle_alert":          get_cycle_alert(cycle),
        "cycle_errors":         [],
        "cycle_form":           {},
        "form": {
            "amount":      {"value": "", "errors": []},
            "category_id": {"value": "", "errors": []},
        },
    }

    if request.method == "POST":
        if cycle:
            RolloverView().rollover_all_pending(cycle.id)

        raw_amount      = request.POST.get("amount",      "").strip()
        raw_category_id = request.POST.get("category_id", "").strip()
        context["form"]["amount"]["value"]      = raw_amount
        context["form"]["category_id"]["value"] = raw_category_id

        errors = []
        try:
            amount = float(raw_amount)
            if amount <= 0:
                errors.append("Amount must be greater than zero.")
        except (ValueError, TypeError):
            errors.append("Amount must be a valid number.")
            amount = None

        if not raw_category_id:
            errors.append("Please select a category.")
        if not cycle:
            errors.append("No active budget cycle found.")

        if errors:
            context["form"]["amount"]["errors"] = errors
            return render(request, "budget/expense_entry.html", context)

        ExpenseView().record_expense(
            amount=amount,
            category_id=int(raw_category_id),
            cycle_id=cycle.id,
            user=request.user,
        )
        return redirect("record_expense")

    return render(request, "budget/expense_entry.html", context)


# ─────────────────────────────────────────────
# HISTORY VIEW
# ─────────────────────────────────────────────

class HistoryView(View):
    """Presents historical transactions and spending filters for the active cycle."""

    def get(self, request):
        """Displays transaction history with filtering and analytics for the active cycle.

        Shows all transactions within the current active budget cycle, with support
        for category and date filtering. Provides spending summaries and category
        breakdowns. Only displays transactions that fall within the cycle's date range.

        Query Logic:
        - Filters transactions by current active cycle
        - Constrains to cycle.start_date <= transaction.date <= cycle.end_date
        - Applies optional category and date filters from request.GET
        - Orders results by timestamp descending (newest first)

        Args:
            request: HTTP request with optional GET parameters:
                   - category: Category ID to filter by
                   - date: Specific date to filter transactions

        Returns:
            Rendered history.html template with:
            - Filtered transactions list
            - Category list with spending totals
            - Total spent amount
            - Current cycle information
            - Budget alerts

        Note:
            Uses select_related for efficient category loading.
            Category totals include all user transactions, not just filtered ones.
        """
        # الـ cycle الحالي النشط
        cycle = BudgetCycle.objects.filter(user=request.user, is_active=True).first()

        # ✅ جلب transactions الـ cycle الحالي فقط (مش كل الـ transactions)
        if cycle:
            transactions = Transaction.objects.filter(
                user=request.user,
                cycle=cycle,
                timestamp__date__gte=cycle.start_date,   # ✅ من بداية الـ cycle
                timestamp__date__lte=cycle.end_date,     # ✅ حتى نهاية الـ cycle
            ).select_related("category")
        else:
            transactions = Transaction.objects.none()

        # فلاتر اختيارية
        category_id   = request.GET.get("category")
        selected_date = request.GET.get("date")

        if category_id:
            transactions = transactions.filter(category_id=category_id)

        if selected_date:
            # ✅ فلتر دقيق بالتاريخ عبر timestamp__date
            transactions = transactions.filter(timestamp__date=selected_date)

        transactions = transactions.order_by("-timestamp")
        total_spent  = transactions.aggregate(total=Sum("amount"))["total"] or 0

        categories = Category.objects.annotate(
            total_spent_cat=Sum(
                "transaction__amount",
                filter=Q(transaction__user=request.user)
            )
        )

        today        = timezone.now().date()
        daily_record = None
        if cycle:
            daily_record, _ = DailyRecord.objects.get_or_create(
                user=request.user, cycle=cycle, date=today,
                defaults={"allocated_limit": cycle.safe_daily_limit, "total_spent": 0.0},
            )

        return render(request, "history.html", {
            "transactions": transactions,
            "categories":   categories,
            "total_spent":  total_spent,
            "cycle":        cycle,
            "daily_alert":  get_daily_alert(daily_record),
            "cycle_alert":  get_cycle_alert(cycle),
        })

    def post(self, request):
        """Handles transaction deletion from history view.

        Processes POST requests to delete specific transactions from the history.
        Ensures user owns the transaction before deletion.

        Args:
            request: HTTP request with 'transaction_id' in POST data.

        Returns:
            Redirect to history page after deletion.

        Note:
            Deletion triggers automatic balance updates via post_delete signal.
            No validation errors are shown; failed deletions are silent.
        """
        transaction_id = request.POST.get("transaction_id")
        if transaction_id:
            Transaction.objects.filter(id=transaction_id, user=request.user).delete()
        return redirect("/history/")


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

class DashboardView(LoginRequiredMixin, View):
    """Shows the authenticated user's current budget dashboard and progress."""
    login_url = "login"

    def get(self, request):
        """Displays comprehensive budget dashboard with key metrics and recent activity.

        Provides an overview of the current budget cycle including spending progress,
        remaining budget, recent transactions, and budget health indicators.
        Requires authentication and an active budget cycle.

        Dashboard Metrics:
        - Total budget, spent amount, and remaining balance
        - Spending percentage and progress indicators
        - Recent transactions (last 5)
        - Dynamic daily spending limit
        - Budget alerts and warnings
        - Days remaining in cycle

        Args:
            request: HTTP request from authenticated user.

        Returns:
            Rendered dashboard.html template with comprehensive budget data,
            or error page if no active cycle exists.

        Context Variables:
            - total: Total cycle budget amount
            - spent: Amount spent so far
            - remaining: Amount still available
            - latest: List of 5 most recent transactions
            - cycle: Current active BudgetCycle
            - daily_limit: Calculated daily spending limit
            - spent_pct: Percentage of budget used
            - Various boolean flags for UI states (alerts, warnings)

        Note:
            Calculates real-time metrics by querying actual transactions
            rather than relying on stored balance fields for accuracy.
        """
        cycle = BudgetCycle.objects.filter(is_active=True, user=request.user).first()

        if not cycle:
            return render(request, "dashboard.html", {"error": "No active cycle"})

        transactions = Transaction.objects.filter(user=request.user, cycle=cycle)
        spent        = float(transactions.aggregate(total=Sum("amount"))["total"] or 0)
        total        = float(cycle.total_allowance)
        remaining    = total - spent
        latest       = transactions.order_by("-timestamp")[:5]

        today        = timezone.now().date()
        days_left    = max((cycle.end_date - today).days + 1, 0)
        daily_limit  = round(remaining / days_left, 2) if days_left > 0 else 0

        daily_record = None
        daily_record, _ = DailyRecord.objects.get_or_create(
            user=request.user, cycle=cycle, date=today,
            defaults={"allocated_limit": cycle.safe_daily_limit, "total_spent": 0.0},
        )

        spent_pct = min((spent / total * 100) if total > 0 else 0, 100)

        return render(request, "dashboard.html", {
            "total":        total,
            "spent":        spent,
            "remaining":    remaining,
            "latest":       latest,
            "cycle":        cycle,
            "daily_limit":  daily_limit,
            "spent_pct":    round(spent_pct, 1),
            "show_80_alert":     spent_pct >= 80,
            "spent_percentage":  round(spent_pct, 1),
            "is_final_day":      days_left <= 1,
            "budget_is_tight":   daily_limit < (daily_limit * 0.5) if daily_limit else False,
            "daily_alert":       get_daily_alert(daily_record),
            "cycle_alert":       get_cycle_alert(cycle),
        })


# ─────────────────────────────────────────────
# STATS VIEW
# ─────────────────────────────────────────────

class StatsView(View):
    """Provides spending statistics and chart-ready data for the active cycle."""

    def get(self, request):
        """Displays spending statistics and visualizations for the active budget cycle.

        Generates data for charts and graphs showing spending patterns by category
        and over time. Provides insights into spending habits and budget utilization.

        Chart Data Generated:
        - Category pie chart: Spending distribution across categories
        - Daily spending line chart: Spending progression over cycle days

        Args:
            request: HTTP request object.

        Returns:
            Rendered stats.html template with chart data:
            - labels: Category names for pie chart
            - values: Spending amounts per category
            - total_spent: Total cycle spending
            - line_labels: Dates for line chart
            - line_values: Daily spending amounts

        Data Processing:
        - Aggregates spending by category using Django's values/annotate
        - Groups daily spending using TruncDate for accurate date bucketing
        - Orders daily data chronologically for proper chart rendering

        Note:
        Requires an active budget cycle. If none exists, shows error message.
        Chart data is suitable for JavaScript charting libraries like Chart.js.
        """
        from django.db.models.functions import TruncDate

        cycle = BudgetCycle.objects.filter(is_active=True, user=request.user).first()
        if not cycle:
            return render(request, "stats.html", {"error": "No active cycle"})

        transactions = Transaction.objects.filter(user=request.user, cycle=cycle)
        total_spent  = float(transactions.aggregate(total=Sum("amount"))["total"] or 0)

        category_data = transactions.values("category__name").annotate(total=Sum("amount"))
        labels = [d["category__name"] for d in category_data]
        values = [float(d["total"]) for d in category_data]

        daily_data = (
            transactions
            .annotate(day=TruncDate("timestamp"))
            .values("day")
            .annotate(total=Sum("amount"))
            .order_by("day")
        )
        line_labels = [str(d["day"]) for d in daily_data]
        line_values = [float(d["total"]) for d in daily_data]

        return render(request, "stats.html", {
            "labels":      labels,
            "values":      values,
            "total_spent": total_spent,
            "line_labels": line_labels,
            "line_values": line_values,
        })


# ─────────────────────────────────────────────
# NOTIFICATIONS VIEW
# ─────────────────────────────────────────────

class NotificationView(View):
    """Renders budget notification status based on current cycle utilization."""

    def get(self, request):
        """Displays budget notifications and spending alerts.

        Shows current budget status with color-coded notifications based on
        spending levels. Provides clear feedback on budget health and spending
        patterns to help users stay within their limits.

        Notification Levels:
        - Success (Green): Spending under 80% of budget
        - Warning (Yellow): Spending between 80-99% of budget
        - Danger (Red): Budget exhausted (100%+ spending)

        Args:
            request: HTTP request object.

        Returns:
            Rendered notifications.html template with:
            - spent_pct: Percentage of budget used (rounded to 1 decimal)
            - notification_level: Bootstrap alert class ("success", "warning", "danger")
            - total_spent: Total amount spent in cycle
            - cycle: Current active BudgetCycle
            - daily_alert/cycle_alert: Additional budget alerts

        Note:
        Requires an active budget cycle. Shows error message if none exists.
        Calculates spending percentage from actual transactions for accuracy.
        """
        cycle = BudgetCycle.objects.filter(is_active=True, user=request.user).first()
        if not cycle:
            return render(request, "notifications.html", {"message": "No active cycle found"})

        total_spent_amt = float(
            Transaction.objects.filter(user=request.user, cycle=cycle)
            .aggregate(total=Sum("amount"))["total"] or 0
        )
        spent_pct = (total_spent_amt / float(cycle.total_allowance) * 100) if cycle.total_allowance > 0 else 0

        if spent_pct >= 100:
            notification_level = "danger"
        elif spent_pct >= 80:
            notification_level = "warning"
        else:
            notification_level = "success"

        today        = timezone.now().date()
        daily_record = None
        if cycle:
            daily_record, _ = DailyRecord.objects.get_or_create(
                user=request.user, cycle=cycle, date=today,
                defaults={"allocated_limit": cycle.safe_daily_limit, "total_spent": 0.0},
            )

        return render(request, "notifications.html", {
            "spent_pct":          round(spent_pct, 1),
            "notification_level": notification_level,
            "total_spent":        total_spent_amt,
            "cycle":              cycle,
            "daily_alert":        get_daily_alert(daily_record),
            "cycle_alert":        get_cycle_alert(cycle),
        })