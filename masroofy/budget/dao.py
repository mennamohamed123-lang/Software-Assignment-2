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
        """Inserts a new category into the database.

        Creates a new record in the budget_category table using the provided
        Category entity's data. The ID of the newly created database record
        is assigned back to the category entity.

        Args:
            category: The Category entity containing name and icon_res_id.
                     The id field should be None for new categories.

        Returns:
            The same Category entity with its id field updated to the
            database-assigned primary key.

        Raises:
            IntegrityError: If a database constraint is violated (e.g., duplicate name).
        """
        obj = CategoryModel.objects.create(
            name=category.name,
            icon_res_id=category.icon_res_id,
        )
        category.id = obj.id
        return category

    def get_by_id(self, category_id: int) -> Optional[Category]:
        """Retrieves a category by its unique ID.

        Queries the budget_category table for a record with the specified ID.
        If found, converts the model instance to a Category entity.

        Args:
            category_id: The primary key of the category to retrieve.
                        Must be a positive integer.

        Returns:
            A Category entity if a matching record exists, None otherwise.

        Note:
            This method does not raise exceptions; it returns None for
            non-existent categories to allow graceful error handling.
        """
        try:
            obj = CategoryModel.objects.get(pk=category_id)
            return Category(id=obj.id, name=obj.name, icon_res_id=obj.icon_res_id)
        except CategoryModel.DoesNotExist:
            return None

    def get_all(self) -> List[Category]:
        """Retrieves all categories from the database.

        Fetches all records from the budget_category table, ordered by name
        in ascending order. Converts each model instance to a Category entity.

        Returns:
            A list of Category entities representing all categories in the database.
            Returns an empty list if no categories exist.

        Note:
            Categories are ordered alphabetically by name for consistent display.
        """
        return [
            Category(id=obj.id, name=obj.name, icon_res_id=obj.icon_res_id)
            for obj in CategoryModel.objects.all().order_by("name")
        ]

    def update(self, category: Category) -> bool:
        """Updates an existing category in the database.

        Modifies the record in budget_category table matching the category's ID
        with the new name and icon_res_id values.

        Args:
            category: The Category entity with updated data. The id field must
                     correspond to an existing database record.

        Returns:
            True if the update was successful (at least one row affected),
            False if no matching record was found.

        Note:
            This method uses Django's update() which is efficient for bulk
            operations but doesn't trigger model save() signals.
        """
        updated = CategoryModel.objects.filter(pk=category.id).update(
            name=category.name,
            icon_res_id=category.icon_res_id,
        )
        return updated > 0

    def delete(self, category_id: int) -> bool:
        """Deletes a category by its ID.

        Removes the record from budget_category table with the specified ID.
        Also cascades to delete any related transactions if foreign key constraints
        are set up (though typically categories should not be deleted if in use).

        Args:
            category_id: The primary key of the category to delete.

        Returns:
            True if the deletion was successful (at least one row affected),
            False if no matching record was found.

        Note:
            Use with caution as this permanently removes data. Consider soft
            deletes for production applications.
        """
        deleted, _ = CategoryModel.objects.filter(pk=category_id).delete()
        return deleted > 0


class TransactionDAO:
    """CRUD + queries for budget_transaction table."""

    def insert(self, tx: Transaction, user=None) -> Transaction:
        """Inserts a new transaction into the database.

        Creates a new record in the budget_transaction table with the provided
        transaction data. The ID of the newly created record is assigned back
        to the transaction entity. The user parameter is stored for audit purposes.

        Args:
            tx: The Transaction entity containing amount, category_id, cycle_id,
                and timestamp. The id field should be None for new transactions.
            user: Optional User instance associated with this transaction.

        Returns:
            The same Transaction entity with its id field updated to the
            database-assigned primary key.

        Raises:
            IntegrityError: If foreign key constraints are violated (e.g., invalid
                           category_id or cycle_id).
            ValidationError: If the transaction data violates model constraints.
        """
        obj = TransactionModel.objects.create(
            amount=tx.amount,
            # ✅ FIX: timestamp is no longer auto_now_add, send it correctly
            timestamp=tx.timestamp,
            category_id=tx.category_id,
            cycle_id=tx.cycle_id,
            user=user,
        )
        tx.id = obj.id
        return tx

    def get_by_id(self, tx_id: int) -> Optional[Transaction]:
        """Retrieves a transaction by its unique ID.

        Queries the budget_transaction table for a record with the specified ID.
        If found, converts the model instance to a Transaction entity using the
        internal _to_entity helper method.

        Args:
            tx_id: The primary key of the transaction to retrieve.
                  Must be a positive integer.

        Returns:
            A Transaction entity if a matching record exists, None otherwise.

        Note:
            This method does not raise exceptions; it returns None for
            non-existent transactions to allow graceful error handling.
        """
        try:
            obj = TransactionModel.objects.get(pk=tx_id)
            return self._to_entity(obj)
        except TransactionModel.DoesNotExist:
            return None

    def get_by_cycle(self, cycle_id: int) -> List[Transaction]:
        """Retrieves all transactions for a specific budget cycle.

        Fetches all records from budget_transaction table that belong to the
        specified cycle, ordered by timestamp in descending order (newest first).
        Converts each model instance to a Transaction entity.

        Args:
            cycle_id: The ID of the budget cycle to filter transactions by.

        Returns:
            A list of Transaction entities for the specified cycle.
            Returns an empty list if no transactions exist for the cycle.

        Note:
            Transactions are ordered by timestamp descending to show recent
            expenses first in UI displays.
        """
        return [
            self._to_entity(obj)
            for obj in TransactionModel.objects.filter(cycle_id=cycle_id)
                                               .order_by("-timestamp")
        ]

    def get_by_date(self, date) -> list:
        """
        ✅ FIX: Returns Django ORM objects not entities so templates can access category.name and icon_emoji
        
        """
        return list(
            TransactionModel.objects
            .select_related("category")
            .filter(timestamp__date=date)
            .order_by("-timestamp")
        )

    def get_total_spent_today(self, cycle_id: int) -> float:
        """Calculates the total amount spent today for a specific cycle.

        Aggregates the sum of all transaction amounts in the current cycle
        that occurred on today's date (based on timestamp__date).

        Args:
            cycle_id: The ID of the budget cycle to calculate spending for.

        Returns:
            The total amount spent today as a float. Returns 0.0 if no
            transactions were recorded today.

        Note:
            Uses Django's timezone.now().date() to determine "today",
            ensuring consistency with the application's timezone settings.
        """
        today = timezone.now().date()
        result = (
            TransactionModel.objects
            .filter(cycle_id=cycle_id, timestamp__date=today)
            .aggregate(total=Sum("amount"))
        )
        return result["total"] or 0.0

    def get_total_spent_in_cycle(self, cycle_id: int) -> float:
        """Calculates the total amount spent in the entire budget cycle.

        Aggregates the sum of all transaction amounts for the specified cycle,
        regardless of date. This represents the cumulative spending from the
        cycle's start date to the current moment.

        Args:
            cycle_id: The ID of the budget cycle to calculate total spending for.

        Returns:
            The total amount spent in the cycle as a float. Returns 0.0 if
            no transactions exist for the cycle.

        Note:
            This differs from cycle.remaining_balance which tracks the
            allocated budget minus spending. This method sums actual transactions.
        """
        result = (
            TransactionModel.objects
            .filter(cycle_id=cycle_id)
            .aggregate(total=Sum("amount"))
        )
        return result["total"] or 0.0

    def delete(self, tx_id: int) -> bool:
        """Deletes a transaction by its ID.

        Removes the record from budget_transaction table with the specified ID.
        Note that related balance updates should be handled by signals or
        separate business logic to maintain data consistency.

        Args:
            tx_id: The primary key of the transaction to delete.

        Returns:
            True if the deletion was successful (at least one row affected),
            False if no matching record was found.

        Note:
            Deletion triggers the post_delete signal which updates cycle and
            daily record balances automatically.
        """
        deleted, _ = TransactionModel.objects.filter(pk=tx_id).delete()
        return deleted > 0

    @staticmethod
    def _to_entity(obj) -> Transaction:
        """Converts a TransactionModel instance to a Transaction entity.

        Helper method that maps database model fields to the domain entity,
        ensuring proper data type conversion and field mapping.

        Args:
            obj: The TransactionModel instance from the database.

        Returns:
            A Transaction entity with data copied from the model instance.

        Note:
            This method is private and used internally by query methods.
            It ensures the entity layer remains decoupled from ORM specifics.
        """
        return Transaction(
            id=obj.id,
            amount=obj.amount,
            timestamp=obj.timestamp,
            # ✅ FIX: Read category_id not category (which is a FK object)
            category_id=obj.category_id,
            cycle_id=obj.cycle_id,
        )