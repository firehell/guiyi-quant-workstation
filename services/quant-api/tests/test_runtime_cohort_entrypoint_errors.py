"""The native -m entrypoint and host must share the same protocol exception."""
import json
import runpy
import sys

import pytest

from app.runtime_cohort import CohortError
from app import runtime_cohort_host


def test_module_entrypoint_preserves_host_protocol_error(monkeypatch, capsys, tmp_path):
    class Host:
        def bindings(self):
            raise CohortError('COHORT_SERVICE_SET_INVALID')
    monkeypatch.setattr(runtime_cohort_host, 'CohortHost', Host)
    monkeypatch.setattr(sys, 'argv', ['cohort', 'plan', '--candidate-root', str(tmp_path),
        '--tag', 'v1.16.48', '--commit', 'a'*40])
    with pytest.warns(RuntimeWarning, match='found in sys.modules'), pytest.raises(SystemExit) as caught:
        runpy.run_module('app.runtime_cohort', run_name='__main__')
    assert caught.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        'status':'blocked', 'code':'COHORT_SERVICE_SET_INVALID'}
