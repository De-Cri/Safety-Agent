import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.queries import get_event_by_id, get_events_filtered, get_events_limited


def test_get_event_by_id_found():
    r = get_event_by_id(4594)
    assert r is not None
    assert r["event_id"] == 4594
    assert r["camera_name"] == "Deposito Pedane Bottom Extended"
    assert r["severity"] == 8
    assert isinstance(r["detections"], list)


def test_get_event_by_id_not_found():
    r = get_event_by_id(9999999)
    assert r is None


def test_get_events_filtered_valid_column():
    r = get_events_filtered("camera_name", "Griglia")
    assert isinstance(r, list)
    assert len(r) > 0
    assert all(e["camera_name"] == "Griglia" for e in r)


def test_get_events_filtered_no_results():
    r = get_events_filtered("camera_name", "CameraInesistente")
    assert r == []


def test_get_events_filtered_invalid_column():
    try:
        get_events_filtered("email", "test")
        assert False, "Doveva sollevare ValueError"
    except ValueError as e:
        assert "email" in str(e)


def test_get_events_limited():
    r = get_events_limited(5)
    assert len(r) == 5
    # verifica ordinamento per datetime crescente
    datetimes = [e["event_datetime"] for e in r]
    assert datetimes == sorted(datetimes)


def test_get_events_limited_zero():
    r = get_events_limited(0)
    assert r == []


if __name__ == "__main__":
    tests = [
        test_get_event_by_id_found,
        test_get_event_by_id_not_found,
        test_get_events_filtered_valid_column,
        test_get_events_filtered_no_results,
        test_get_events_filtered_invalid_column,
        test_get_events_limited,
        test_get_events_limited_zero,
    ]
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL  {t.__name__} — {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__} — {e}")
