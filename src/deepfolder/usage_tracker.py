from datetime import datetime, date, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.config import settings, MODEL_PRICES
from deepfolder.models.usage import Usage


class SpendCapExceeded(Exception):
    pass


class UsageTracker:
    def __init__(self, session: AsyncSession, user_id: int) -> None:
        self.session = session
        self.user_id = user_id

    async def check_spend_cap(self) -> None:
        """Raise SpendCapExceeded if today's total cost exceeds the cap."""
        today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
        result = await self.session.execute(
            select(func.coalesce(func.sum(Usage.cost_usd), 0.0)).where(
                Usage.user_id == self.user_id,
                Usage.created_at >= today_start,
            )
        )
        total = result.scalar()
        if total is not None and total >= settings.spend_cap_usd:
            raise SpendCapExceeded(
                f"Daily spend cap of ${settings.spend_cap_usd:.2f} exceeded "
                f"(current: ${total:.4f})"
            )

    async def record(
        self, kind: str, model: str, input_tokens: int, output_tokens: int
    ) -> None:
        cost = self._compute_cost(kind, model, input_tokens, output_tokens)
        usage = Usage(
            user_id=self.user_id,
            kind=kind,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self.session.add(usage)

    @staticmethod
    def _compute_cost(kind: str, model: str, input_tokens: int, output_tokens: int) -> float:
        prices = MODEL_PRICES.get(model, {})
        if kind == "llm":
            input_price = prices.get("input_per_1m", 0.0)
            output_price = prices.get("output_per_1m", 0.0)
            cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
        elif kind == "embedding":
            input_price = prices.get("input_per_1m", 0.0)
            cost = (input_tokens / 1_000_000) * input_price
        else:
            cost = 0.0
        return round(cost, 6)
