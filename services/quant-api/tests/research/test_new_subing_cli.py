from datetime import date
import importlib.util


def test_new_subing_cli_exists():
    assert importlib.util.find_spec('scripts.research.new_subing') is not None


def test_blocked_packet_has_no_fabricated_return():
    from scripts.research.new_subing import build_packet
    packet=build_packet(product='al',scenario='baseline',code_revision='a'*40,
        status='DATA_INSUFFICIENT',diagnostic={'code':'DATASET_OR_PARTITION_MISSING','contract':'AL2411'})
    assert packet['metadata']['product']=='AL'
    assert packet['metadata']['input_snapshot_hash'] is None
    assert packet['summary']=={'status':'DATA_INSUFFICIENT'}
    assert packet['decisions']==packet['trades']==packet['equity']==[]
    assert packet['metadata']['oos_status']=='NOT_PROVEN'
    assert packet['metadata']['auto_order'] is False


def test_validation_windows_do_not_overlap_and_are_not_stitched():
    from scripts.research.new_subing import DIAGNOSTIC_WINDOWS
    expected=[(date(2024,10,14),date(2025,10,10)),(date(2025,10,13),date(2026,10,9)),
      (date(2025,10,13),date(2025,12,31)),(date(2026,1,1),date(2026,3,31)),
      (date(2026,4,1),date(2026,6,30)),(date(2026,7,1),date(2026,10,9))]
    assert [(s,t) for _,s,t in DIAGNOSTIC_WINDOWS]==expected
