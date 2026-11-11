"""Validated file reads for local execution fact evidence."""

import json
import os
from pathlib import Path
import stat

from scripts.research.new_subing_execution_facts import FactsCaptureError

MAX_BYTES = 32 * 1024 * 1024


def safe_path(path: Path) -> Path:
    if not path.is_absolute() or '..' in path.parts:
        raise FactsCaptureError('FACTS_PATH_INVALID')
    for part in (path,*path.parents):
        if part.is_symlink():
            raise FactsCaptureError('FACTS_PATH_INVALID')
    return path


def read_json(path: Path) -> dict:
    safe_path(path)
    try:
        descriptor = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise ValueError()
            with os.fdopen(descriptor,'rb',closefd=False) as stream:
                raw = stream.read(MAX_BYTES+1)
            if len(raw) > MAX_BYTES:
                raise ValueError()
        finally:
            os.close(descriptor)
        def pairs(items):
            result = {}
            for key,value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        value = json.loads(raw,object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value,dict):
            raise ValueError()
        return value
    except (OSError,ValueError,UnicodeError):
        raise FactsCaptureError('FACTS_FILE_INVALID') from None
