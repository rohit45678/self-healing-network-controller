"""Streaming collector: ingests gNMI-style notifications and keeps the
latest value plus a bounded history per (device, path)."""

from __future__ import annotations

import re
from collections import defaultdict, deque

HISTORY_LEN = 64

_IFACE_RE = re.compile(r"interface\[name=([^\]]+)\]")
_NBR_RE = re.compile(r"neighbor\[neighbor-address=([^\]]+)\]")


def interface_of(path: str) -> str | None:
    m = _IFACE_RE.search(path)
    return m.group(1) if m else None


def neighbour_of(path: str) -> str | None:
    m = _NBR_RE.search(path)
    return m.group(1) if m else None


class Collector:
    def __init__(self) -> None:
        self._latest: dict[tuple[str, str], dict] = {}
        self._history: dict[tuple[str, str], deque] = defaultdict(
            lambda: deque(maxlen=HISTORY_LEN)
        )
        self.count = 0

    def ingest(self, notification: dict) -> None:
        key = (notification["device"], notification["path"])
        values = dict(notification["values"])
        self._latest[key] = values
        self._history[key].append(values)
        self.count += 1

    def latest(self, device: str, path: str) -> dict | None:
        return self._latest.get((device, path))

    def history(self, device: str, path: str) -> list[dict]:
        return list(self._history.get((device, path), ()))

    def devices(self) -> list[str]:
        return sorted({d for d, _ in self._latest})

    def paths(self, device: str) -> list[str]:
        return sorted(p for d, p in self._latest if d == device)

    # -- typed views used by the detector ----------------------------------
    def interface_samples(self, device: str, iface: str) -> list[dict]:
        from .telemetry import IFACE_PATH

        return self.history(device, IFACE_PATH.format(iface=iface))

    def interfaces(self, device: str) -> list[str]:
        names = []
        for path in self.paths(device):
            name = interface_of(path)
            if name:
                names.append(name)
        return names

    def bgp_neighbours(self, device: str) -> list[str]:
        names = []
        for path in self.paths(device):
            name = neighbour_of(path)
            if name:
                names.append(name)
        return names
