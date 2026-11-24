"""Optional read-only router for the isolated P5 trading projection."""

from collections.abc import Callable
import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

_RESOURCES = frozenset({'status', 'account', 'positions', 'decisions', 'orders', 'fills'})
_LISTS = frozenset({'decisions', 'orders', 'fills'})
_CURSOR = re.compile(r'(decisions|orders|fills)\.([0-9]{1,18})\.([0-9]{1,18})')


def build_newow_trading_router(read: Callable[..., dict]) -> APIRouter:
    """The composition supplies one bound read function, without an engine dependency."""
    router = APIRouter(prefix='/api/v1/newow/trading', tags=['Newow trading'])

    @router.get('/{resource}')
    def trading_projection(
        resource: str, limit: Annotated[int, Query(ge=1, le=200)] = 100,
        cursor: Annotated[str | None, Query(max_length=50)] = None,
    ):
        if resource not in _RESOURCES:
            raise HTTPException(404, 'P5_RESOURCE_NOT_FOUND')
        after, through = 0, None
        if cursor is not None:
            match = _CURSOR.fullmatch(cursor)
            if resource not in _LISTS or not match or match[1] != resource:
                raise HTTPException(400, 'P5_CURSOR_INVALID')
            after, through = int(match[2]), int(match[3])
        try:
            result = dict(read(resource, limit=limit, after=after, through=through))
        except ValueError:
            raise HTTPException(400, 'P5_CURSOR_INVALID') from None
        except RuntimeError:
            raise HTTPException(503, 'P5_PROJECTION_UNAVAILABLE') from None
        if resource in _LISTS:
            next_after = result.pop('next_after', None)
            ceiling = result.pop('through', None)
            result['next_cursor'] = f'{resource}.{next_after}.{ceiling}' if next_after is not None else None
        return result

    return router
