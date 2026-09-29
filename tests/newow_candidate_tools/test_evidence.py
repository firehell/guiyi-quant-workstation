import pytest
from scripts.newow_candidate_tools.evidence import EvidenceStore


def test_existing_evidence_is_never_overwritten(tmp_path):
    store=EvidenceStore(tmp_path)
    store.write('context.json',{'state':'failed'})
    with pytest.raises(FileExistsError): store.write('context.json',{'state':'passed'})
    assert store.read('context.json')['state']=='failed'


@pytest.mark.parametrize('name',['../escape.json','/tmp/escape.json','a/../../escape.json'])
def test_paths_cannot_escape_declared_output(tmp_path,name):
    with pytest.raises(ValueError):EvidenceStore(tmp_path).write(name,{})


def test_symlink_evidence_is_rejected(tmp_path):
    external=tmp_path.parent/'external.json';external.write_text('{}')
    (tmp_path/'linked.json').symlink_to(external)
    with pytest.raises(ValueError):EvidenceStore(tmp_path).read('linked.json')


def test_json_encoding_failure_leaves_no_success_artifact(tmp_path):
    with pytest.raises(ValueError):EvidenceStore(tmp_path).write('result.json',{'number':float('nan')})
    assert not (tmp_path/'result.json').exists()
