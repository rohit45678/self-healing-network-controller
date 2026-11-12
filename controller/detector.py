"""Fault detector: evaluates the collector's latest state and history
against thresholds, with streak tracking so single-sample noise does not
raise faults.

Fault kinds:
  BGP_SESSION_DOWN     BGP neighbour not in Established state
  HIGH_ERROR_RATE      interface input-error delta > 100/tick, sustained 2 ticks
  LINK_FLAP            >= 3 oper-status transitions in the last 6 samples
  OPTICAL_DEGRADATION  rx power on the ACTIVE path interface below -24 dBm
  CPU_SATURATION       cpu_util > 90% sustained 3 ticks
"""

from __future__ import annotations

from dataclasses import dataclass

from .collector import Collector
from .telemetry import BGP_PATH, IFACE_PATH, ROUTING_PATH, SYSTEM_PATH

ERROR_DELTA_THRESHOLD = 100
ERROR_SUSTAIN_TICKS = 2
FLAP_TRANSITIONS = 3
FLAP_WINDOW = 6
OPTICAL_CRITICAL_DBM = -24.0
CPU_THRESHOLD = 90.0
CPU_SUSTAIN_TICKS = 3


@dataclass(frozen=True)
class Fault:
    kind: str
    device: str
    target: str  # interface name, neighbour IP, or "cpu"
    detail: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.kind, self.device, self.target)

    def __str__(self) -> str:
        return f"{self.kind} on {self.device} ({self.target}): {self.detail}"


class Detector:
    def __init__(self) -> None:
        self._error_streak: dict[tuple[str, str], int] = {}
        self._cpu_streak: dict[str, int] = {}

    def evaluate(self, collector: Collector, tick: int) -> list[Fault]:
        faults: list[Fault] = []
        for device in collector.devices():
            faults.extend(self._check_bgp(collector, device))
            faults.extend(self._check_interfaces(collector, device))
            faults.extend(self._check_optical(collector, device))
            faults.extend(self._check_cpu(collector, device))
        return faults

    # -- individual checks ---------------------------------------------------
    def _check_bgp(self, collector: Collector, device: str) -> list[Fault]:
        out = []
        for nbr in collector.bgp_neighbours(device):
            latest = collector.latest(device, BGP_PATH.format(nbr=nbr))
            if latest and latest["session_state"] != "Established":
                out.append(Fault(
                    "BGP_SESSION_DOWN", device, nbr,
                    f"session state is {latest['session_state']}, "
                    f"prefixes_received={latest['prefixes_received']}",
                ))
        return out

    def _check_interfaces(self, collector: Collector, device: str) -> list[Fault]:
        out = []
        for iface in collector.interfaces(device):
            samples = collector.interface_samples(device, iface)
            if len(samples) < 2:
                continue
            # error-rate streak
            deltas = [
                b["in_errors"] - a["in_errors"]
                for a, b in zip(samples, samples[1:])
            ]
            streak_key = (device, iface)
            if deltas and deltas[-1] > ERROR_DELTA_THRESHOLD:
                self._error_streak[streak_key] = self._error_streak.get(streak_key, 0) + 1
            else:
                self._error_streak[streak_key] = 0
            if self._error_streak.get(streak_key, 0) >= ERROR_SUSTAIN_TICKS:
                out.append(Fault(
                    "HIGH_ERROR_RATE", device, iface,
                    f"input errors growing by {deltas[-1]}/tick "
                    f"for {self._error_streak[streak_key]} consecutive ticks",
                ))
            # link flap: transitions in the recent window
            window = samples[-FLAP_WINDOW:]
            transitions = sum(
                1 for a, b in zip(window, window[1:])
                if a["oper_status"] != b["oper_status"]
            )
            if transitions >= FLAP_TRANSITIONS:
                out.append(Fault(
                    "LINK_FLAP", device, iface,
                    f"{transitions} oper-status transitions in last "
                    f"{len(window)} samples",
                ))
        return out

    def _check_optical(self, collector: Collector, device: str) -> list[Fault]:
        routing = collector.latest(device, ROUTING_PATH)
        if not routing:
            return []
        active_iface = (
            routing["primary_interface"]
            if routing["active_path"] == "primary"
            else routing["backup_interface"]
        )
        latest = collector.latest(device, IFACE_PATH.format(iface=active_iface))
        if latest and latest["rx_power_dbm"] < OPTICAL_CRITICAL_DBM:
            return [Fault(
                "OPTICAL_DEGRADATION", device, active_iface,
                f"rx power {latest['rx_power_dbm']:.1f} dBm on active path "
                f"interface is below critical threshold {OPTICAL_CRITICAL_DBM} dBm",
            )]
        return []

    def _check_cpu(self, collector: Collector, device: str) -> list[Fault]:
        latest = collector.latest(device, SYSTEM_PATH)
        if not latest:
            return []
        if latest["cpu_util"] > CPU_THRESHOLD:
            self._cpu_streak[device] = self._cpu_streak.get(device, 0) + 1
        else:
            self._cpu_streak[device] = 0
        if self._cpu_streak.get(device, 0) >= CPU_SUSTAIN_TICKS:
            return [Fault(
                "CPU_SATURATION", device, "cpu",
                f"cpu_util {latest['cpu_util']:.0f}% above {CPU_THRESHOLD:.0f}% "
                f"for {self._cpu_streak[device]} consecutive ticks",
            )]
        return []
