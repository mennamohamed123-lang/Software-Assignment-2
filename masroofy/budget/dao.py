from typing import List, Optional
from django.utils import timezone
from django.db.models import Sum

from .entities import Category, Transaction
from .models import (
    Category as CategoryModel,
    Transaction as TransactionModel,
)


class CategoryDAO:
    """CRUD for budget_category table."""

    def insert(self, category: Category) -> Category:
        obj = CategoryModel.objects.create(
            name=category.name,
            icon_res_id=category.icon_res_id,
        )
        category.id = obj.id
        return category

    def get_by_id(self, category_id: int) -> Optional[Category]:
        try:
            obj = CategoryModel.objects.get(pk=category_id)
            return Category(id=obj.id, name=obj.name, icon_res_id=obj.icon_res_id)
        except CategoryModel.DoesNotExist:
            return None

    def get_all(self) -> List[Category]:
        return [
            Category(id=obj.id, name=obj.name, icon_res_id=obj.icon_res_id)
            for obj in CategoryModel.objects.all().order_by("name")
        ]

    def update(self, category: Category) -> bool:
        updated = CategoryModel.objects.filter(pk=category.id).update(
            name=category.name,
            icon_res_id=category.icon_res_id,
        )
        return updated > 0

    def delete(self, category_id: int) -> bool:
        deleted, _ = CategoryModel.objects.filter(pk=category_id).delete()
        return deleted > 0


class TransactionDAO:
    """CRUD + queries for budget_transaction table."""

    def insert(self, tx: Transaction) -> Transaction:
        obj = TransactionModel.objects.create(
            amount=tx.amount,
            # ✅ FIX: timestamp مش auto_now_add بقى، فبنبعته صح
            timestamp=tx.timestamp,
            category_id=tx.category_id,
            cycle_id=tx.cycle_id,
        )
        tx.id = obj.id
        return tx

    def get_by_id(self, tx_id: int) -> Optional[Transaction]:
        try:
            obj = TransactionModel.objects.get(pk=tx_id)
            return self._to_entity(obj)
        except TransactionModel.DoesNotExist:
            return None

    def get_by_cycle(self, cycle_id: int) -> List[Transaction]:
        return [
            self._to_entity(obj)
            for obj in TransactionModel.objects.filter(cycle_id=cycle_id)
                                               .order_by("-timestamp")
        ]

    def get_by_date(self, date) -> list:
        """
        ✅ FIX: بترجع Django ORM objects مش entities عشان الـ template
        تقدر تعمل tx.category.name و tx.category.icon_emoji
        """
        return list(
            TransactionModel.objects
            .select_related("category")
            .filter(timestamp__date=date)
            .order_by("-timestamp")
        )

    def get_total_spent_today(self, cycle_id: int) -> float:
        today = timezone.now().date()
        result = (
            TransactionModel.objects
            .filter(cycle_id=cycle_id, timestamp__date=today)
            .aggregate(total=Sum("amount"))
        )
        return result["total"] or 0.0

    def get_total_spent_in_cycle(self, cycle_id: int) -> float:
        result = (
            TransactionModel.objects
            .filter(cycle_id=cycle_id)
            .aggregate(total=Sum("amount"))
        )
        return result["total"] or 0.0

    def delete(self, tx_id: int) -> bool:
        deleted, _ = TransactionModel.objects.filter(pk=tx_id).delete()
        return deleted > 0

    @staticmethod
    def _to_entity(obj) -> Transaction:
        return Transaction(
            id=obj.id,
            amount=obj.amount,
            timestamp=obj.timestamp,
            # ✅ FIX: بنقرأ category_id مش category (اللي هو FK object)
            category_id=obj.category_id,
            cycle_id=obj.cycle_id,
        )