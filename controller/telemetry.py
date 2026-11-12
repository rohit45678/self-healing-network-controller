"""gNMI-style telemetry generator with scripted fault scenarios.

Each tick the generator first lets delayed remediation effects fire, then
applies the scenario's fault overlay to the simulated network (unless the
fault has been addressed by a remediation action), then emits one
notification per (device, path) built from the resulting state.

Notification format (gNMI-flavoured JSON):
  {"timestamp": <float>, "device": "edge-rtr-1",
   "path": "/interfaces/interface[name=GigabitEthernet0/0/0]/state",
   "values": {"oper_status": "up", "in_errors": 123, "out_errors": 4,
              "rx_power_dbm": -8.2}}
"""

from __future__ import annotations

from .simnet import SimNetwork

BASE_TS = 1765440000.0  # fixed epoch so runs are deterministic
TICK_SECONDS = 10.0

IFACE_PATH = "/interfaces/interface[name={iface}]/state"
SYSTEM_PATH = "/system/state"
BGP_PATH = (
    "/network-instances/network-instance[name=default]/protocols/"
    "protocol[identifier=BGP][name=bgp]/bgp/neighbors/"
    "neighbor[neighbor-address={nbr}]/state"
)
ROUTING_PATH = "/routing/state"


class Scenario:
    name = "base"

    def overlay(self, net: SimNetwork, tick: int) -> None:
        """Perturb device state for this tick (fault injection)."""


class HealthyScenario(Scenario):
    name = "healthy"


class BgpDropScenario(Scenario):
    """BGP session on edge-rtr-1 drops at tick 3 and stays down until a
    restart action addresses it."""
    name = "bgp_drop"
    FAULT_KEY = "bgp:edge-rtr-1:198.51.100.1"

    def overlay(self, net: SimNetwork, tick: int) -> None:
        if tick >= 3 and self.FAULT_KEY not in net.addressed:
            sess = net.device("edge-rtr-1")["bgp"]["198.51.100.1"]
            sess["state"] = "Active"
            sess["prefixes_received"] = 0


class LinkFlapScenario(Scenario):
    """Primary interface of edge-rtr-1 flaps from tick 2: oper status
    alternates every tick and the input error counter jumps hard."""
    name = "link_flap"
    FAULT_KEY = "iface:edge-rtr-1:GigabitEthernet0/0/0"
    DEVICE = "edge-rtr-1"
    IFACE = "GigabitEthernet0/0/0"

    def overlay(self, net: SimNetwork, tick: int) -> None:
        if tick >= 2 and self.FAULT_KEY not in net.addressed:
            state = net.interface(self.DEVICE, self.IFACE)
            state["oper_status"] = "down" if tick % 2 == 0 else "up"
            state["in_errors"] += 400


class OpticalDegradationScenario(Scenario):
    """Receive power on edge-rtr-1's primary uplink decays tick by tick
    until it crosses the -24 dBm critical threshold. Optics are physical:
    the overlay never 'heals' -- recovery comes from rerouting."""
    name = "optical_degradation"
    FAULT_KEY = "optical:edge-rtr-1:GigabitEthernet0/0/0"
    LEVELS = {2: -13.5, 3: -18.9, 4: -22.4, 5: -25.1, 6: -26.8}

    def overlay(self, net: SimNetwork, tick: int) -> None:
        state = net.interface("edge-rtr-1", "GigabitEthernet0/0/0")
        if tick in self.LEVELS:
            state["rx_power_dbm"] = self.LEVELS[tick]
        elif tick > 6:
            state["rx_power_dbm"] = -27.5


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (
        HealthyScenario(),
        BgpDropScenario(),
        LinkFlapScenario(),
        OpticalDegradationScenario(),
    )
}


class TelemetryGenerator:
    def __init__(self, net: SimNetwork, scenario: Scenario):
        self.net = net
        self.scenario = scenario

    def tick(self, tick: int) -> list[dict]:
        # 1. delayed remediation effects fire (session re-establishes, etc.)
        for key in self.net.step_effects():
            self.net.apply_recovery(key)
        # 2. scenario fault overlay
        self.scenario.overlay(self.net, tick)
        # 3. baseline noise: a couple of error counts on busy interfaces
        for dev_name, dev in self.net.devices.items():
            primary = dev["interfaces"][dev["primary_interface"]]
            primary["in_errors"] += (tick * 7 + len(dev_name)) % 3
        # 4. emit notifications from current state
        ts = BASE_TS + tick * TICK_SECONDS
        out: list[dict] = []
        for dev_name, dev in self.net.devices.items():
            for iface_name, st in dev["interfaces"].items():
                out.append({
                    "timestamp": ts,
                    "device": dev_name,
                    "path": IFACE_PATH.format(iface=iface_name),
                    "values": {
                        "oper_status": st["oper_status"],
                        "in_errors": st["in_errors"],
                        "out_errors": st["out_errors"],
                        "rx_power_dbm": st["rx_power_dbm"],
                    },
                })
            out.append({
                "timestamp": ts,
                "device": dev_name,
                "path": SYSTEM_PATH,
                "values": {"cpu_util": dev["cpu_util"]},
            })
            out.append({
                "timestamp": ts,
                "device": dev_name,
                "path": ROUTING_PATH,
                "values": {
                    "active_path": dev["active_path"],
                    "primary_interface": dev["primary_interface"],
                    "backup_interface": dev["backup_interface"],
                },
            })
            for nbr, sess in dev["bgp"].items():
                out.append({
                    "timestamp": ts,
                    "device": dev_name,
                    "path": BGP_PATH.format(nbr=nbr),
                    "values": {
                        "session_state": sess["state"],
                        "prefixes_received": sess["prefixes_received"],
                    },
                })
        return out
