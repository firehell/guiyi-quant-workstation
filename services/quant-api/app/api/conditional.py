"""Conditional transfer after the route has completed its authoritative read."""

from hashlib import sha256
import json

from fastapi import Request, Response
from fastapi.responses import JSONResponse


def conditional_json(request: Request, payload: dict, *, volatile: frozenset[str] = frozenset(), allow_not_modified: bool = True) -> Response:
    def stable(value):
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items() if key not in volatile}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    digest = sha256(json.dumps(stable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    # Volatile display fields may vary in a semantically identical response.
    etag = ('W/' if volatile else '') + '"' + digest + '"'
    headers = {'ETag': etag, 'Cache-Control': 'private, no-cache'}
    matches = request.headers.get('if-none-match', '').split(',')
    if allow_not_modified and any(tag.strip() == '*' or tag.strip().removeprefix('W/') == etag.removeprefix('W/') for tag in matches):
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)
