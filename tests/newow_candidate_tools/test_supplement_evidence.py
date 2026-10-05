import copy
import hashlib
import json
from urllib.parse import urlencode

import pytest
from test_audit import candidate as make_candidate, binding
from scripts.newow_candidate_tools.checks import validate_supplemental_partner


def evidence(c):
    url = c.web_origin + '/api/v1/market/newow/strategy-detail?' + urlencode(dict(product=c.product, frequency='5m', strategy='oscillation', series_kind='actual_dominant', section='reference', as_of=c.as_of, history_limit=200, snapshot_token='partner'))
    chart_url = url.replace('section=reference', 'section=chart')
    meta = dict(identity=dict(product=c.product, frequency='5m', strategy='oscillation'), as_of=c.as_of, snapshot_token='partner', input_content_sha256='1' * 64)
    status = dict(status='ready', evidence_status='ACTIVE_CODE_VERIFIED')
    payload = dict(meta=meta, reference=dict(delivery='delivered', status=status, value=dict(reference_input_sha256='1' * 64, items=[], curve_trades=[dict(reference_trade_id='full-record')], executable=False, auto_order=False)))
    text = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    b = binding(url); b.update(node_request_id=8, response_text_chars=len(text))
    cb = binding(chart_url); cb['node_request_id'] = 2
    aborted = dict(id=6, url=url, phase='seed', method='GET', failed=True, error='net::ERR_ABORTED')
    chart = dict(row_request=True, request_id=2, request_phase='seed', url=chart_url, http=200, xhr_binding=cb, payload=dict(meta=meta, chart=dict(delivery='delivered', status=status, value={})))
    response = dict(row_request=True, request_id=8, request_phase='seed', url=url, http=200, xhr_binding=b, payload=copy.deepcopy(payload))
    raw = dict(evidence_kind='same_xhr_full_response_readback', extra_get=False, http=200, url=url, response_request_id=8, response_text_chars=len(text), response_text_sha256=hashlib.sha256(text.encode()).hexdigest(), payload_sha256=hashlib.sha256(text.encode()).hexdigest(), response_text=text, payload=payload, xhr_binding=b)
    action = dict(kind='supplemental_partner_reference', source='collector_true_xhr', ui_composable_received=False, phase='initial', request_floor=0, url=url, strategy='oscillation', frequency='5m', snapshot_token='partner', aborted_request=aborted, chart_request_id=2, chart_binding=cb, status='RESPONSE_BOUND', response_readback=raw)
    return dict(actions=[action], responses=[chart, response], failures=[dict(url=url, error='net::ERR_ABORTED', phase='seed', request_phase='seed')], requestEvidence=[aborted, dict(id=8, url=url, phase='seed', method='GET', finished=True)])


def test_complete_supplement_and_no_supplement(tmp_path):
    c = make_candidate(tmp_path)
    assert validate_supplemental_partner(c, '5m', 'dual', evidence(c))['count'] == 1
    assert validate_supplemental_partner(c, '5m', 'trend', {'actions': []})['count'] == 0


@pytest.mark.parametrize('case', ['duplicate', 'mode', 'phase', 'source', 'ui', 'status', 'token', 'floor', 'abort', 'abort_missing', 'failure_missing', 'failure_duplicate', 'curve_changed', 'chart_token', 'chart_binding', 'chart_node_id', 'chart_evidence', 'row_binding', 'row_missing', 'http', 'url', 'text', 'text_hash', 'payload_hash', 'payload', 'chars', 'extra_get', 'evidence_status'])
def test_supplement_tamper_fails(tmp_path, case):
    c = make_candidate(tmp_path); d = evidence(c); a = d['actions'][0]; r = a['response_readback']; mode = 'dual'
    if case == 'duplicate': d['actions'].append(copy.deepcopy(a))
    elif case == 'mode': mode = 'trend'
    elif case == 'phase': a['phase'] = 'away'
    elif case == 'source': a['source'] = 'synthetic'
    elif case == 'ui': a['ui_composable_received'] = True
    elif case == 'status': a['status'] = 'STARTED'
    elif case == 'token': a['snapshot_token'] = 'wrong'
    elif case == 'floor': a['request_floor'] = 9
    elif case == 'abort': a['aborted_request']['error'] = 'net::ERR_FAILED'
    elif case == 'abort_missing': d['requestEvidence'] = d['requestEvidence'][1:]
    elif case == 'failure_missing': d['failures'] = []
    elif case == 'failure_duplicate': d['failures'] *= 2
    elif case == 'curve_changed': d['responses'][1]['payload']['reference']['value']['curve_trades'] = []
    elif case == 'chart_token': d['responses'][0]['payload']['meta']['snapshot_token'] = 'wrong'
    elif case == 'chart_binding': a['chart_binding'] = {}
    elif case == 'chart_node_id': d['responses'][0]['xhr_binding']['node_request_id'] = 10
    elif case == 'chart_evidence': d['responses'][0]['payload']['chart']['status']['evidence_status'] = 'UNKNOWN'
    elif case == 'row_binding': r['xhr_binding'] = {}
    elif case == 'row_missing': d['responses'].pop()
    elif case == 'http': r['http'] = 409
    elif case == 'url': r['url'] += '&snapshot_token=partner'
    elif case == 'text': r['response_text'] += ' '
    elif case == 'text_hash': r['response_text_sha256'] = '0' * 64
    elif case == 'payload_hash': r['payload_sha256'] = '0' * 64
    elif case == 'payload': r['payload']['reference']['value']['items'].append({'fake': True})
    elif case == 'chars': r['response_text_chars'] += 1
    elif case == 'extra_get': r['extra_get'] = True
    elif case == 'evidence_status': r['payload']['reference']['status']['evidence_status'] = 'UNKNOWN'
    with pytest.raises(ValueError): validate_supplemental_partner(c, '5m', mode, d)
