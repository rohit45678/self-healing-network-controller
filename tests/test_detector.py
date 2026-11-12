"""Detector tests: faults trigger on fault streams, not on healthy ones."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controller.collector import Collector
from controller.detector import Detector
from controller.simnet import SimNetwork
from controller.telemetry import (
    SCENARIOS,
    SYSTEM_PATH,
    TelemetryGenerator,
)


def run_stream(scenario_name, ticks):
    """Feed a scenario through collector+detector; return per-tick fault kinds."""
    net = SimNetwork()
    gen = TelemetryGenerator(net, SCENARIOS[scenario_name])
    collector = Collector()
    detector = Detector()
    per_tick = []
    for t in range(ticks):
        for n in gen.tick(t):
            collector.ingest(n)
        per_tick.append([f.kind for f in detector.evaluate(collector, t)])
    return per_tick


def test_bgp_drop_triggers_detector():
    per_tick = run_stream("bgp_drop", 6)
    assert not any("BGP_SESSION_DOWN" in kinds for kinds in per_tick[:3]), per_tick
    assert "BGP_SESSION_DOWN" in per_tick[3], per_tick


def test_link_flap_triggers_error_detector():
    per_tick = run_stream("link_flap", 6)
    flat = [k for kinds in per_tick for k in kinds]
    assert "HIGH_ERROR_RATE" in flat or "LINK_FLAP" in flat, per_tick


def test_optical_degradation_triggers_detector():
    per_tick = run_stream("optical_degradation", 7)
    assert not any("OPTICAL_DEGRADATION" in kinds for kinds in per_tick[:5]), per_tick
    assert "OPTICAL_DEGRADATION" in per_tick[5], per_tick


def test_healthy_stream_raises_no_faults():
    per_tick = run_stream("healthy", 8)
    assert all(kinds == [] for kinds in per_tick), per_tick


def test_cpu_saturation_needs_sustained_breach():
    collector = Collector()
    detector = Detector()
    note = {"timestamp": 0.0, "device": "edge-rtr-1", "path": SYSTEM_PATH,
            "values": {"cpu_util": 95.0}}
    collector.ingest(note)
    assert detector.evaluate(collector, 0) == []
    assert detector.evaluate(collector, 1) == []
    faults = detector.evaluate(collector, 2)
    assert [f.kind for f in faults] == ["CPU_SATURATION"], faults
