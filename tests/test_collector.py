from threading import Event

from set_bidask_service.collector import CollectorState, RealtimeCollector


def test_disconnected_realtime_error_requests_reconnect():
    collector = object.__new__(RealtimeCollector)
    collector.state = CollectorState()
    collector._reconnect_event = Event()

    collector._handle_realtime_error("Bid/offer", "USDM26", "disconnected with rc : 7")

    snapshot = collector.state.snapshot()
    assert snapshot["connected"] is False
    assert snapshot["last_error"] == "disconnected with rc : 7"
    assert snapshot["error_count"] == 1
    assert snapshot["reconnect_count"] == 1
    assert collector._reconnect_event.is_set()
