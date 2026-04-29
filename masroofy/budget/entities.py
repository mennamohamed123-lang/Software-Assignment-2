"""
entities.py  — Transaction & Category data classes
Mirrors the DB schema in budget_transaction and budget_category tables.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Category:
    """
    Mirrors: budget_category
    Columns: id, name, icon_res_id
    """
    id: Optional[int]
    name: str
    icon_res_id: int = 0  # drawable resource id (Android-style int)

    def __str__(self):
        return self.name


@dataclass
class Transaction:
    """
    Mirrors: budget_transaction
    Columns: id, amount, timestamp, category_id, cycle_id
    """
    id: Optional[int]
    amount: float
    category_id: int
    cycle_id: int
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if self.amount <= 0:
            raise ValueError(f"Transaction amount must be positive, got {self.amount}")

    def __str__(self):
        return f"Transaction(id={self.id}, amount={self.amount:.2f}, at={self.timestamp.date()})"