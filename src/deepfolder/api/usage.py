from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.dependencies import require_user
from deepfolder.db import get_session
from deepfolder.models.usage import Usage
from deepfolder.models.user import User

router = APIRouter(prefix="/usage", tags=["usage"])


class UsageResponse(BaseModel):
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    by_kind: dict[str, dict[str, int | float]]
    by_model: dict[str, dict[str, int | float]]


@router.get("")
async def get_usage(
    from_date: str = Query(default=None, alias="from"),
    to_date: str = Query(default=None, alias="to"),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> UsageResponse:
    query = select(
        func.coalesce(func.sum(Usage.cost_usd), 0.0),
        func.coalesce(func.sum(Usage.input_tokens), 0),
        func.coalesce(func.sum(Usage.output_tokens), 0),
    ).where(Usage.user_id == user.id)

    if from_date:
        try:
            from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from date format (use YYYY-MM-DD)")
        query = query.where(Usage.created_at >= from_dt)

    if to_date:
        try:
            to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to date format (use YYYY-MM-DD)")
        query = query.where(Usage.created_at < to_dt)

    result = await db.execute(query)
    total_cost, total_input, total_output = result.one()

    kind_query = select(
        Usage.kind,
        func.coalesce(func.sum(Usage.cost_usd), 0.0),
        func.coalesce(func.sum(Usage.input_tokens), 0),
        func.coalesce(func.sum(Usage.output_tokens), 0),
    ).where(Usage.user_id == user.id)
    if from_date:
        kind_query = kind_query.where(Usage.created_at >= from_dt)
    if to_date:
        kind_query = kind_query.where(Usage.created_at < to_dt)
    kind_query = kind_query.group_by(Usage.kind)
    kind_result = await db.execute(kind_query)

    by_kind = {}
    for kind, cost, inp, out in kind_result:
        by_kind[kind] = {"cost_usd": float(cost), "input_tokens": inp, "output_tokens": out}

    model_query = select(
        Usage.model,
        func.coalesce(func.sum(Usage.cost_usd), 0.0),
        func.coalesce(func.sum(Usage.input_tokens), 0),
        func.coalesce(func.sum(Usage.output_tokens), 0),
    ).where(Usage.user_id == user.id)
    if from_date:
        model_query = model_query.where(Usage.created_at >= from_dt)
    if to_date:
        model_query = model_query.where(Usage.created_at < to_dt)
    model_query = model_query.group_by(Usage.model)
    model_result = await db.execute(model_query)

    by_model = {}
    for model, cost, inp, out in model_result:
        by_model[model] = {"cost_usd": float(cost), "input_tokens": inp, "output_tokens": out}

    return UsageResponse(
        total_cost_usd=float(total_cost),
        total_input_tokens=total_input or 0,
        total_output_tokens=total_output or 0,
        by_kind=by_kind,
        by_model=by_model,
    )
