"""Closed-loop engine tests: every fault scenario must end RECOVERED with a
DETECT -> DECIDE -> ACT -> VERIFY timeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controller.engine import run_scenario


def phases(result):
    return [e.phase for e in result.events]


def test_bgp_drop_recovers():
    result = run_scenario("bgp_drop")
    assert result.status == "RECOVERED", [str(e) for e in result.events]
    assert result.faults_seen == 1
    seq = phases(result)
    assert seq.index("DETECT") < seq.index("ACT") < seq.index("VERIFY"), seq


def test_link_flap_recovers():
    result = run_scenario("link_flap")
    assert result.status == "RECOVERED", [str(e) for e in result.events]
    assert result.faults_seen >= 1
    assert "VERIFY" in phases(result)


def test_optical_degradation_recovers_via_backup_and_tickets_optics():
    result = run_scenario("optical_degradation")
    assert result.status == "RECOVERED", [str(e) for e in result.events]
    assert len(result.tickets) == 1, result.tickets
    assert "optics" in result.tickets[0]["summary"]
    assert "VERIFY" in phases(result)


def test_healthy_scenario_has_no_faults():
    result = run_scenario("healthy")
    assert result.status == "NO FAULTS", [str(e) for e in result.events]
    assert result.faults_seen == 0
    assert result.events == []


def test_unknown_scenario_rejected():
    try:
        run_scenario("does_not_exist")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown scenario")
