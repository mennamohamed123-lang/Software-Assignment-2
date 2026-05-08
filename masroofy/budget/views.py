"""
views.py — Masroofy (FIXED)
===========================
Fixes in this version:
  1. Edit cycle  → updates the current cycle without deleting transactions
  2. Reset cycle → deletes all transactions and resets cycle dates
  3. timedelta   → uses days - 1 to correct 31-day calculations
  4. History     → applies accurate date filtering within the cycle range
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
    """
    Authenticate a user and establish an active session.

    This view supports both GET and POST methods. On GET it renders the
    login page. On POST it validates the submitted credentials using Django's
    authentication system and, if valid, logs the user in and redirects to
    the dashboard.

    Side effects:
        - Creates a session for authenticated users.
        - Emits Django authentication events used by middleware and signals.

    Args:
        request (HttpRequest): The incoming request. Expected POST fields:
            - username (str): The username of the user.
            - password (str): The raw password.

    Returns:
        HttpResponse: Rendered login page for GET or failed POST.
        HttpResponseRedirect: Redirect to dashboard on successful login,
                              or back to login on failure.

    Notes:
        This view does not perform rate limiting or lockout checks.
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
    """
    Register a new user account and log them in.

    GET requests render the signup page. POST requests validate the user's
    submitted username, email, and password fields, create a new Django User,
    and automatically authenticate and log in the new account.

    Side effects:
        - Creates a new User record in the auth_user table.
        - Starts a new session for the registered user.

    Args:
        request (HttpRequest): The incoming request. Expected POST fields:
            - username         (str): Desired username; must be unique.
            - email            (str): User email address.
            - password         (str): Desired account password.
            - confirm_password (str): Must match password.

    Returns:
        HttpResponse: Rendered signup page on GET or when validation fails.
        HttpResponseRedirect: Redirect to dashboard after successful signup.

    Validation rules:
        - username must not already exist.
        - password and confirm_password must match.

    Notes:
        This view does not enforce password strength rules or email verification.
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
    """
    Log out the current user and clear session state.

    Calls Django's logout() to remove the authenticated user from the session
    and clear any session data tied to the current request. After logout it
    redirects the user to the login page.

    Args:
        request (HttpRequest): The incoming HTTP request.

    Returns:
        HttpResponseRedirect: Redirect to the login page.

    Notes:
        This view is safe for unauthenticated requests, as logout() handles
        missing session state gracefully.
    """
    logout(request)
    return redirect("login")


def home(request):
    """
    Route visitors to the appropriate entry point.

    If the request is from an unauthenticated user, this view renders the
    public landing page. If the user is authenticated, it redirects them to
    the main expense recording page, which is the primary application UI.

    Args:
        request (HttpRequest): The incoming HTTP request.

    Returns:
        HttpResponse: Rendered landing page for unauthenticated users.
        HttpResponseRedirect: Redirect to record_expense for logged-in users.

    Notes:
        This view does not perform any business logic beyond routing.
    """
    if not request.user.is_authenticated:
        return render(request, "index.html")
    return redirect("record_expense")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _parse_cycle_form(post, today):
    """
    Parse and validate budget cycle creation or update form data.

    This helper supports two mutually exclusive ways to define the cycle
    duration: a numeric day count or an explicit end date. It also validates
    the total allowance and returns sanitized results for the calling view.

    Args:
        post (QueryDict): The POST data with fields:
            - total_allowance (str): Required budget amount.
            - duration_days   (str): Optional cycle length in days.
            - end_date        (str): Optional cycle end date in YYYY-MM-DD.
        today (date): Current server date used for validation and to compute
                      the inclusive end date range.

    Returns:
        tuple: (total_allowance, end_date, errors, form_data)
            - total_allowance (float | None): Parsed budget amount, or None if invalid.
            - end_date (date | None): Parsed or computed cycle end date.
            - errors (list[str]): Validation errors to show to the user.
            - form_data (dict): Raw submitted values for form repopulation.

    Validation rules:
        - total_allowance must be a positive float.
        - duration_days must be a positive integer if provided.
        - end_date must be a valid date string and not before today.
        - At least one of duration_days or end_date must be provided.

    Inclusive range logic:
        Uses end_date = today + timedelta(days=duration_days - 1) so that a
        duration of 30 days counts today as day 1 and the computed end date
        as day 30.
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
    """
    Create or replace the user's active budget cycle via a dedicated setup page.

    This view is used when the user wants to create a new budget cycle from a
    separate page rather than the inline form in record_expense. It validates
    the cycle input, deactivates an existing active cycle, and creates a new
    BudgetCycle record with initial balance data.

    HTTP behavior:
        GET: Render the cycle setup page.
        POST: Validate input and create the new cycle.

    Args:
        request (HttpRequest): Authenticated user's request. Expected POST
                               fields are the same as _parse_cycle_form.

    Returns:
        HttpResponse: Rendered setup page on GET or validation failure.
        HttpResponseRedirect: Redirect to record_expense on success.

    Business rules:
        - Only one active cycle exists per user at a time.
        - A newly created cycle starts today and lasts until the computed end date.
        - remaining_balance is initialized to total_allowance.
        - safe_daily_limit is calculated as total_allowance / total_days.

    Note:
        This view does not preserve old transactions; it strictly replaces the
        active cycle record when a new cycle is created.
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
    """
    Determine the daily spending alert state for the current day.

    This helper compares the actual amount spent today against the currently
    allocated daily limit and generates a user-facing alert dictionary if the
    spending threshold has been crossed.

    Args:
        daily_record (DailyRecord | None): The DailyRecord for today.

    Returns:
        dict | None: Returns None if no alert is needed. Otherwise a dictionary
        with keys:
            - msg (str): Alert message for the user.
            - type (str): Alert styling type (danger, warning, info).
            - percentage (float): Spending percentage of today's limit.

    Behavior:
        - Uses actual recorded transactions for today to compute spent.
        - Falls back to no alert if the daily limit is zero.
        - Caps the displayed percentage at 100 for the danger case.

    Thresholds:
        >= 100% -> danger
        >= 80%  -> warning
        >= 60%  -> info
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
    """
    Determine the overall cycle-level budget alert state.

    This helper uses actual cycle transactions to compute the total amount
    spent so far. It then compares that spending to the cycle's total
    allowance and returns an alert dictionary if the budget crosses a threshold.

    Args:
        cycle (BudgetCycle | None): The active budget cycle.

    Returns:
        dict | None: Returns None if no alert is needed. Otherwise returns:
            - msg (str): Alert message describing budget status.
            - type (str): Alert type (danger, warning, success).
            - percentage (float): Percentage of the cycle budget spent.

    Behavior:
        - Uses a live transaction aggregation to avoid stale balance state.
        - Handles cycles with zero allowance gracefully.

    Thresholds:
        >= 100% -> danger
        >= 80%  -> warning
        >= 60%  -> info
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
    """
    Delete a specific transaction and redirect to the expense page.

    This view ensures that the transaction belongs to the currently logged-in
    user before deletion. It relies on the Transaction post_delete signal to
    restore budget state consistency after the record is removed.

    Args:
        request (HttpRequest): The incoming request.
        tx_id (int): Primary key of the transaction to delete.

    Returns:
        HttpResponseRedirect: Redirect to record_expense.

    Raises:
        Http404: If the transaction does not exist or does not belong to the user.

    Notes:
        Deletion is permanent and cascade safety is handled by Django ORM and
        the models.py signal handler.
    """
    transaction = get_object_or_404(Transaction, pk=tx_id, user=request.user)
    transaction.delete()
    return redirect("record_expense")


# ─────────────────────────────────────────────
# RECORD EXPENSE — الصفحة الرئيسية
# ─────────────────────────────────────────────

@csrf_exempt
def record_expense(request):
    """
    The main budget interface: cycle management and expense entry.

    This view combines several responsibilities on a single page. It can:
        - Create a new budget cycle when none exists.
        - Edit an existing cycle's budget and end date without deleting past transactions.
        - Reset the active cycle by clearing transactions and daily records.
        - Record a new expense transaction and update budget state.
        - Display current cycle progress, alert messages, and today's transactions.

    POST actions are determined by request.POST["action"]:
        - create_cycle: initialize a new BudgetCycle.
        - edit_cycle: modify an active cycle while preserving history.
        - reset_cycle: clear existing cycle data and restart from today.
        - default POST: record a new expense.

    Daily limit strategy:
        - If today already has a DailyRecord, keep its allocated_limit fixed.
        - If today has no record, compute a fresh limit from remaining_balance
          and persist it once for the day.
        - This makes the daily limit stable for the duration of the day.

    Args:
        request (HttpRequest): The incoming request from a logged-in user.

    Returns:
        HttpResponse: Rendered expense entry page for GET and validation failures.
        HttpResponseRedirect: Redirect to record_expense after successful POST.

    Context available to the template:
        - cycle: current active BudgetCycle or None.
        - categories: categories list for expense selection.
        - today_transactions: today's transaction list.
        - dynamic_daily_limit: today's locked daily limit.
        - spent_today: total spent today.
        - days_left: remaining days in the cycle.
        - total_days: duration of the cycle in days.
        - daily_alert / cycle_alert: alert dictionaries for UI.
        - form: current input values and validation errors.

    Notes:
        - All cycle and expense operations are handled here to keep the
          user experience centralized.
        - Expense recording delegates the actual transaction insertion to
          ExpenseView for atomic balance updates.
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

                new_daily_limit = round(new_remaining / days_left, 2)

                cycle.total_allowance   = total_allowance
                cycle.end_date          = end_date
                cycle.remaining_balance = new_remaining
                cycle.safe_daily_limit  = new_daily_limit
                cycle.save()

                # ✅ لما اليوزر يعمل edit بإرادته، حدّث الـ limit لليوم الحالي
                DailyRecord.objects.filter(
                    user=request.user, cycle=cycle, date=today
                ).update(allocated_limit=new_daily_limit)

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
        # ── الـ spent_today يتحدث دايماً (عشان يعرض الصح) ──────────────
        spent_today = float(
            Transaction.objects.filter(cycle=cycle, timestamp__date=today)
            .aggregate(total=Sum("amount"))["total"] or 0
        )

        # ── الـ DailyRecord: يتحسب الـ limit مرة واحدة في بداية كل يوم ──
        #
        # المنطق:
        #   - لو في DailyRecord لليوم ده → استخدم الـ allocated_limit المخزّن
        #     (لا تغيّره طول اليوم حتى لو اتصرف فلوس)
        #   - لو مفيش DailyRecord (يوم جديد) → احسب الـ limit من الـ remaining
        #     واحفظه مرة واحدة فقط
        #
        # ✅ كده الـ limit ثابت طول اليوم ويتغير بس في أول request لليوم الجديد
        existing_record = DailyRecord.objects.filter(
            user=request.user, cycle=cycle, date=today
        ).first()

        if existing_record:
            # ✅ يوم مستمر — الـ limit ثابت، بس الـ spent_today يتحدث
            dynamic_daily_limit = existing_record.allocated_limit
            existing_record.total_spent = spent_today
            existing_record.save(update_fields=["total_spent"])
            daily_record = existing_record
        else:
            # ✅ يوم جديد — احسب الـ limit الآن من الـ remaining الحالي
            days_left           = max((cycle.end_date - today).days + 1, 1)
            dynamic_daily_limit = round(cycle.remaining_balance / days_left, 2)

            # احفظ الـ limit في الـ DailyRecord — ولن يتغير طول اليوم
            daily_record = DailyRecord.objects.create(
                user=request.user,
                cycle=cycle,
                date=today,
                allocated_limit=dynamic_daily_limit,
                total_spent=spent_today,
            )

            # حدّث الـ safe_daily_limit في الـ cycle كمرجع فقط
            cycle.safe_daily_limit = dynamic_daily_limit
            cycle.save(update_fields=["safe_daily_limit"])

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
        "today_transactions":   tx_dao.get_by_date(today, user=request.user) if cycle else [],
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
    """
    Render the user's transaction history page for the active cycle.

    This view limits history to transactions that belong to the currently
    active budget cycle and its date range. It also supports optional GET
    filters for category and date, and accepts POST requests to delete a
    single transaction from the history.

    URL: /history/
    """
    def get(self, request):
        """
        Retrieve and display filtered transaction history for the active cycle.

        The query is constrained to the active cycle and its date range, which
        prevents older cycle records from appearing in the current cycle's
        history. Optional query parameters permit filtering by category or date.

        Returns:
            HttpResponse: Rendered history.html with filtered transactions,
                          category aggregates, and alert context.
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
        """
        Delete a transaction from the active cycle history.

        Expects a POST field named transaction_id and removes the matching
        transaction for the authenticated user. After deletion it redirects
        back to the history page.

        Args:
            request (HttpRequest): The incoming POST request.

        Returns:
            HttpResponseRedirect: Redirect to /history/.
        """
        transaction_id = request.POST.get("transaction_id")
        if transaction_id:
            Transaction.objects.filter(id=transaction_id, user=request.user).delete()
        return redirect("/history/")


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

class DashboardView(LoginRequiredMixin, View):
    """
    Render the authenticated user's main budget dashboard.

    Provides a summary of the active cycle including:
        - total budget allowance
        - amount spent so far
        - remaining balance
        - days left in the cycle
        - dynamic daily spending guidance
        - recent transactions and budget status alerts

    Requires a logged-in user and redirects unauthenticated requests to login.
    URL: /dashboard/
    """
    login_url = "login"

    def get(self, request):
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
    """
    Provide spending statistics for the active budget cycle.

    This view aggregates transaction data into datasets suitable for charting.
    It generates a category breakdown and a daily spending trend for the
    currently active cycle.

    URL: /stats/
    """
    def get(self, request):
        """
        Retrieve statistics for the user's active budget cycle.

        Aggregates transactions by category and by calendar date, then renders
        the stats page with chart-ready values. If no active cycle exists, it
        returns the template with an error indicator.

        Args:
            request (HttpRequest): The incoming GET request.

        Returns:
            HttpResponse: Rendered stats page populated with spending data.
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
    """
    Render budget health notifications for the active cycle.

    This view calculates the current cycle spending percentage and returns a
    status panel indicating whether the user is within budget, approaching the
    limit, or has exhausted the budget. It also includes daily and cycle-level
    alert context.

    Notification Levels:
        100% or more -> danger
        80% or more  -> warning
        below 80%    -> success

    URL: /notifications/check/
    """
    def get(self, request):
        """
        Show current notifications for the active budget cycle.

        Computes the cycle spending percentage and selects a notification level
        of danger, warning, or success. It also provides daily and cycle alerts
        for the template.

        Args:
            request (HttpRequest): The incoming GET request.

        Returns:
            HttpResponse: Rendered notifications page with current budget status.
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