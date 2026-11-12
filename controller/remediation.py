"""Remediation engine: maps each fault kind to an automated action and
executes it against the simulated network.

Policy:
  BGP_SESSION_DOWN     -> restart the BGP session (clear + re-establish)
  HIGH_ERROR_RATE      -> shut/no-shut bounce of the interface
  LINK_FLAP            -> shut/no-shut bounce of the interface
  OPTICAL_DEGRADATION  -> reroute traffic via the backup path and raise a
                          ticket for the physical optics (cannot be fixed
                          remotely); ticket only if no healthy backup exists
  CPU_SATURATION       -> raise a ticket (no safe automated action)
"""

from __future__ import annotations

from .detector import Fault
from .simnet import SimNetwork

BACKUP_HEALTHY_DBM = -20.0


class RemediationEngine:
    def __init__(self, net: SimNetwork):
        self.net = net

    def decide(self, fault: Fault) -> str:
        return {
            "BGP_SESSION_DOWN": "restart_bgp_session",
            "HIGH_ERROR_RATE": "bounce_interface",
            "LINK_FLAP": "bounce_interface",
            "OPTICAL_DEGRADATION": "reroute_via_backup",
            "CPU_SATURATION": "raise_ticket",
        }[fault.kind]

    def execute(self, fault: Fault, action: str) -> str:
        net = self.net
        if action == "restart_bgp_session":
            return net.restart_bgp(
                fault.device, fault.target, fault_key=f"bgp:{fault.device}:{fault.target}"
            )
        if action == "bounce_interface":
            return net.bounce_interface(
                fault.device, fault.target, fault_key=f"iface:{fault.device}:{fault.target}"
            )
        if action == "reroute_via_backup":
            dev = net.device(fault.device)
            backup = dev["backup_interface"]
            backup_rx = dev["interfaces"][backup]["rx_power_dbm"]
            if backup_rx >= BACKUP_HEALTHY_DBM:
                reroute = net.reroute_via_backup(
                    fault.device, fault_key=f"optical:{fault.device}:{fault.target}"
                )
                ticket = net.raise_ticket(
                    fault.device,
                    f"degraded optics on {fault.target} "
                    f"({dev['interfaces'][fault.target]['rx_power_dbm']:.1f} dBm) - "
                    "schedule fibre/optics replacement; traffic on backup path",
                )
                return f"{reroute}; {ticket}"
            return net.raise_ticket(
                fault.device,
                f"optical degradation on {fault.target} and backup {backup} "
                f"unhealthy ({backup_rx:.1f} dBm) - field dispatch required",
            )
        if action == "raise_ticket":
            return net.raise_ticket(
                fault.device, f"{fault.kind} on {fault.target}: {fault.detail}"
            )
        raise ValueError(f"unknown action {action!r}")
