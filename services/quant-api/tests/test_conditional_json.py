from unittest.mock import patch

from starlette.requests import Request

from app.api.conditional import conditional_json


def _request(etag=None):
    return Request({"type": "http", "method": "GET", "path": "/", "headers":
                    [] if etag is None else [(b"if-none-match", etag.encode())]})


def test_strong_etag_hashes_the_actual_canonical_response_bytes():
    from hashlib import sha256
    response = conditional_json(_request(), {"z": 2, "a": {"y": "焦煤", "b": 1}})
    assert response.headers["etag"] == '"json-v2-' + sha256(response.body).hexdigest() + '"'
    assert response.body == '{"a":{"b":1,"y":"焦煤"},"z":2}'.encode()


def test_old_encoding_etag_cannot_validate_a_different_byte_representation():
    from hashlib import sha256
    old = '"' + sha256(b'{"a":1,"z":2}').hexdigest() + '"'
    assert conditional_json(_request(old), {"z": 2, "a": 1}).status_code == 200


def test_stable_conditional_body_is_serialized_once():
    import json
    with patch("app.api.conditional.json.dumps", wraps=json.dumps) as encode:
        response = conditional_json(_request(), {"items": [{"symbol": "jm"}]})
    assert response.status_code == 200
    assert encode.call_count == 1


def test_volatile_fields_use_weak_etag_without_reusing_old_body():
    first = conditional_json(_request(), {"read_at": "old", "value": 1}, volatile=frozenset({"read_at"}))
    second = conditional_json(_request(first.headers["etag"]), {"read_at": "new", "value": 1}, volatile=frozenset({"read_at"}))
    assert first.headers["etag"].startswith('W/"')
    assert second.status_code == 304 and second.body == b""
    fresh = conditional_json(_request(first.headers["etag"]), {"read_at": "new", "value": 2}, volatile=frozenset({"read_at"}))
    assert fresh.status_code == 200 and b"new" in fresh.body
