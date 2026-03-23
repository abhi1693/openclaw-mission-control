from __future__ import annotations

from app.services.auto_heartbeat_governor import compute_desired_heartbeat


def test_policy_active_resets_to_5m() -> None:
    desired = compute_desired_heartbeat(is_lead=False, active=True, step=3)
    assert desired.every == "5m"
    assert desired.step == 0
    assert desired.off is False


def test_policy_backoff_steps_non_lead() -> None:
    # idle step 0 -> 10m
    d1 = compute_desired_heartbeat(is_lead=False, active=False, step=0)
    assert d1.every == "10m"
    assert d1.off is False

    # keep idling up the ladder
    d2 = compute_desired_heartbeat(is_lead=False, active=False, step=d1.step)
    assert d2.every == "30m"

    d3 = compute_desired_heartbeat(is_lead=False, active=False, step=d2.step)
    assert d3.every == "1h"

    d4 = compute_desired_heartbeat(is_lead=False, active=False, step=d3.step)
    assert d4.every == "3h"

    d5 = compute_desired_heartbeat(is_lead=False, active=False, step=d4.step)
    assert d5.every == "6h"

    # next step goes fully off
    d6 = compute_desired_heartbeat(is_lead=False, active=False, step=d5.step)
    assert d6.every is None
    assert d6.off is True


def test_policy_lead_caps_at_1h_never_off() -> None:
    # step beyond ladder should still cap at 1h
    d = compute_desired_heartbeat(is_lead=True, active=False, step=999)
    assert d.every == "1h"
    assert d.off is False
