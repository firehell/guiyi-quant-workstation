import json
import pytest
from app import subing_projection_source as source


def test_legacy_model_binding_remains_read_only(tmp_path, monkeypatch):
    from app.subing_model import worker
    original = worker.ACTIVE
    binding = tmp_path/'binding.json'
    model = tmp_path/'model'; model.mkdir()
    results = tmp_path/'results'; results.mkdir()
    binding.write_text(json.dumps(dict(model_root=str(model), results_root=str(results))))
    binding.chmod(0o600)
    monkeypatch.setattr(source, 'BINDING', binding)
    assert source.registered_source('model_root') == model
    assert source.registered_source('results_root') == results
    assert worker.ACTIVE == original

@pytest.mark.parametrize('kind', ['bad_json', 'extra_key', 'relative', 'parent', 'symlink', 'public_mode'])
def test_present_invalid_binding_fails_closed(tmp_path, monkeypatch, kind):
    binding = tmp_path/'binding.json'; model = tmp_path/'model'; model.mkdir()
    value = dict(model_root=str(model), results_root=str(model))
    if kind == 'extra_key': value['worker_start'] = True
    if kind == 'relative': value['model_root'] = 'relative'
    if kind == 'parent': value['model_root'] = str(model/'..'/'model')
    if kind == 'symlink':
        link=tmp_path/'link';link.symlink_to(model,target_is_directory=True);value['model_root']=str(link)
    binding.write_text('{' if kind == 'bad_json' else json.dumps(value))
    binding.chmod(0o644 if kind == 'public_mode' else 0o600)
    monkeypatch.setattr(source, 'BINDING', binding)
    with pytest.raises((ValueError, OSError)):
        source.registered_source('model_root')
