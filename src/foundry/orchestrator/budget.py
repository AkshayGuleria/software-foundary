from __future__ import annotations

from typing import Literal

from foundry.store.models import Run

BudgetStatus = Literal["ok", "warning", "exceeded"]


def check_budget(run: Run) -> BudgetStatus:
    if run.token_budget <= 0:
        return "ok"
    ratio = run.tokens_used / run.token_budget
    if ratio >= 1.0:
        return "exceeded"
    if ratio >= 0.8:
        return "warning"
    return "ok"
