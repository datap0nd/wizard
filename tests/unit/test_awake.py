"""The PC stays awake while a question runs, and may sleep again once none does."""
from __future__ import annotations

from wizard_api.awake import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, KeepAwake

AWAKE, NORMAL = ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS


def test_awake_while_any_question_runs():
    calls: list[int] = []
    awake = KeepAwake(lambda flags: calls.append(flags) or 1)
    with awake:
        assert calls == [AWAKE]
        with awake:  # a second person's question on a shared server
            pass
        assert calls == [AWAKE], "still awake: one question is still running"
    assert calls == [AWAKE, NORMAL] and awake.running == 0


def test_a_refusal_or_an_error_never_stops_the_question():
    def broken(flags: int) -> int:
        raise OSError("no kernel32 here")
    with KeepAwake(broken):
        pass
    with KeepAwake(lambda flags: 0):  # Windows said no
        pass
    with KeepAwake(None) as awake:  # not Windows: nothing to do
        assert awake.running == 1
