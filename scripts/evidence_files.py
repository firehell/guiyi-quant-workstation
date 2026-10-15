"""Durable atomic JSON publication used by historical evidence tools."""
import json
import os
from pathlib import Path
import tempfile


def atomic_json(path, value, *, exclusive=True):
    """Publish complete bytes durably; reservation never replaces older evidence."""
    if path.is_symlink():
        raise FileExistsError('EVIDENCE_FILE_EXISTS')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(value, file, sort_keys=True, separators=(',', ':'))
            file.flush()
            os.fsync(file.fileno())
        if exclusive:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise FileExistsError('EVIDENCE_FILE_EXISTS') from error
        else:
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
