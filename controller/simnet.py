"""Simulated network: mutable device state that the telemetry generator
reads and the remediation engine writes. No real devices are involved.

State model per device:
  interfaces: {name: {"oper_status": "up"/"down", "in_errors": int,
                      "out_errors": int, "rx_power_dbm": float}}
  cpu_util: float (percent)
  bgp: {neighbour_ip: {"state": "Established"/"Idle"/..., "prefixes_received": int}}
  active_path: "primary" | "backup"
  primary_interface / backup_interface: interface names

The SimNetwork also tracks delayed effects: remediation actions schedule
recoveries that fire after N ticks (e.g. a BGP session takes 2 ticks to
re-establish after a restart), and a set of fault keys that have been
addressed (so the scenario overlay stops re-injecting them).
"""

from __future__ import annotations

import copy


def _iface(rx_power_dbm: float) -> dict:
    return {
        "oper_status": "up",
        "in_errors": 0,
        "out_errors": 0,
        "rx_power_dbm": rx_power_dbm,
    }


def default_topology() -> dict:
    """Three devices: two edge routers and a core switch."""
    return {
        "edge-rtr-1": {
            "interfaces": {
                "GigabitEthernet0/0/0": _iface(-8.2),   # primary uplink
                "GigabitEthernet0/0/1": _iface(-9.6),   # backup uplink
            },
            "cpu_util": 23.0,
            "bgp": {"198.51.100.1": {"state": "Established", "prefixes_received": 812}},
            "primary_interface": "GigabitEthernet0/0/0",
            "backup_interface": "GigabitEthernet0/0/1",
            "active_path": "primary",
        },
        "edge-rtr-2": {
            "interfaces": {
                "GigabitEthernet0/0/0": _iface(-7.9),
                "GigabitEthernet0/0/1": _iface(-10.1),
            },
            "cpu_util": 31.0,
            "bgp": {"198.51.100.5": {"state": "Established", "prefixes_received": 795}},
            "primary_interface": "GigabitEthernet0/0/0",
            "backup_interface": "GigabitEthernet0/0/1",
            "active_path": "primary",
        },
        "core-sw-1": {
            "interfaces": {
                "GigabitEthernet1/0/1": _iface(-6.4),
                "GigabitEthernet1/0/2": _iface(-6.8),
            },
            "cpu_util": 18.0,
            "bgp": {},
            "primary_interface": "GigabitEthernet1/0/1",
            "backup_interface": "GigabitEthernet1/0/2",
            "active_path": "primary",
        },
    }


class SimNetwork:
    def __init__(self, topology: dict | None = None):
        self.devices: dict = copy.deepcopy(topology or default_topology())
        self._pending: dict[tuple, int] = {}  # effect key -> ticks remaining
        self.addressed: set[str] = set()      # fault keys an action has addressed
        self.tickets: list[dict] = []

    # -- device state ----------------------------------------------------
    def device(self, name: str) -> dict:
        return self.devices[name]

    def interface(self, device: str, iface: str) -> dict:
        return self.devices[device]["interfaces"][iface]

    # -- delayed effects ---------------------------------------------------
    def schedule(self, key: tuple, ticks: int) -> None:
        self._pending[key] = ticks

    def step_effects(self) -> list[tuple]:
        """Advance delayed effects by one tick; return the keys that fired."""
        fired = []
        for key in list(self._pending):
            self._pending[key] -= 1
            if self._pending[key] <= 0:
                fired.append(key)
                del self._pending[key]
        return fired

    # -- remediation primitives (called by the remediation engine) --------
    def restart_bgp(self, device: str, neighbour: str, fault_key: str) -> str:
        self.addressed.add(fault_key)
        sess = self.devices[device]["bgp"][neighbour]
        sess["state"] = "Idle"
        sess["prefixes_received"] = 0
        self.schedule(("bgp_up", device, neighbour), 2)
        return f"cleared BGP session to {neighbour} on {device}; re-establishing"

    def bounce_interface(self, device: str, iface: str, fault_key: str) -> str:
        already = fault_key in self.addressed
        self.addressed.add(fault_key)
        state = self.interface(device, iface)
        state["oper_status"] = "down"  # shut
        self.schedule(("iface_up", device, iface), 2)
        if already:
            return f"interface {iface} on {device} bounce already in progress"
        return f"shut/no-shut bounce of {iface} on {device}"

    def reroute_via_backup(self, device: str, fault_key: str) -> str:
        self.addressed.add(fault_key)
        dev = self.devices[device]
        dev["active_path"] = "backup"
        return (
            f"traffic on {device} rerouted to backup path "
            f"({dev['backup_interface']}); primary left in place for repair"
        )

    def raise_ticket(self, device: str, summary: str) -> str:
        ticket_id = f"T-{1001 + len(self.tickets)}"
        self.tickets.append({"id": ticket_id, "device": device, "summary": summary})
        return f"raised ticket {ticket_id}: {summary}"

    # -- recovery application (called by the generator when effects fire) --
    def apply_recovery(self, key: tuple) -> None:
        kind = key[0]
        if kind == "bgp_up":
            _, device, neighbour = key
            sess = self.devices[device]["bgp"][neighbour]
            sess["state"] = "Established"
            sess["prefixes_received"] = 812
        elif kind == "iface_up":
            _, device, iface = key
            self.interface(device, iface)["oper_status"] = "up"
