"""Closed-loop engine: generator -> collector -> detector -> remediation
-> simulated network, tick by tick, producing a detect/decide/act/verify
timeline.

A fault counts as cleared when its condition stays absent for
VERIFY_TICKS consecutive ticks after the action.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .collector import Collector
from .detector import Detector, Fault
from .remediation import RemediationEngine
from .simnet import SimNetwork
from .telemetry import SCENARIOS, TelemetryGenerator

VERIFY_TICKS = 2

DEFAULT_TICKS = {
    "healthy": 8,
    "bgp_drop": 12,
    "link_flap": 14,
    "optical_degradation": 12,
}


@dataclass
class TimelineEvent:
    tick: int
    phase: str  # DETECT | DECIDE | ACT | VERIFY | INFO
    message: str

    def __str__(self) -> str:
        return f"[t={self.tick:02d}] {self.phase:<6} {self.message}"


@dataclass
class RunResult:
    scenario: str
    status: str  # NO FAULTS | RECOVERED | UNRESOLVED
    events: list[TimelineEvent] = field(default_factory=list)
    faults_seen: int = 0
    tickets: list[dict] = field(default_factory=list)


def run_scenario(scenario_name: str, ticks: int | None = None) -> RunResult:
    if scenario_name not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario_name!r}; choose from {sorted(SCENARIOS)}")
    ticks = ticks if ticks is not None else DEFAULT_TICKS[scenario_name]
    net = SimNetwork()
    gen = TelemetryGenerator(net, SCENARIOS[scenario_name])
    collector = Collector()
    detector = Detector()
    remediation = RemediationEngine(net)

    result = RunResult(scenario=scenario_name, status="NO FAULTS")
    active: dict[tuple, dict] = {}  # fault key -> {"fault": Fault, "clear_streak": int}

    for tick in range(ticks):
        for notification in gen.tick(tick):
            collector.ingest(notification)

        present = {f.key: f for f in detector.evaluate(collector, tick)}

        for key, fault in present.items():
            if key not in active:
                active[key] = {"fault": fault, "clear_streak": 0}
                result.faults_seen += 1
                result.events.append(TimelineEvent(tick, "DETECT", str(fault)))
                action = remediation.decide(fault)
                result.events.append(
                    TimelineEvent(tick, "DECIDE", f"{fault.kind} -> {action}")
                )
                outcome = remediation.execute(fault, action)
                result.events.append(TimelineEvent(tick, "ACT", outcome))
            else:
                active[key]["clear_streak"] = 0

        for key in list(active):
            if key not in present:
                active[key]["clear_streak"] += 1
                if active[key]["clear_streak"] >= VERIFY_TICKS:
                    fault = active[key]["fault"]
                    result.events.append(TimelineEvent(
                        tick, "VERIFY",
                        f"{fault.kind} on {fault.device} ({fault.target}) cleared -- "
                        "condition absent for "
                        f"{VERIFY_TICKS} consecutive ticks after remediation",
                    ))
                    del active[key]

    if result.faults_seen == 0:
        result.status = "NO FAULTS"
    elif active:
        result.status = "UNRESOLVED"
        for entry in active.values():
            result.events.append(TimelineEvent(
                ticks - 1, "INFO",
                f"still active at end of run: {entry['fault']}",
            ))
    else:
        result.status = "RECOVERED"
    result.tickets = list(net.tickets)
    return result
