from __future__ import annotations

import update_helper


def test_main_shows_hint_when_started_without_session(monkeypatch):
    calls: list[str] = []

    def fake_show_hint() -> int:
        calls.append("shown")
        return 0

    monkeypatch.setattr(update_helper, "_show_direct_launch_hint", fake_show_hint)

    result = update_helper.main([])

    assert result == 0
    assert calls == ["shown"]
