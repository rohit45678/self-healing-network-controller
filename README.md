# Self-Healing Network Controller
Event-driven, closed-loop network automation that streams gNMI telemetry from network devices, detects faults and performance anomalies, and triggers automated remediation workflows to restore service without manual intervention.
**Tech stack:** Python, gNMI, Streaming Telemetry, Network Automation
**Highlights:** real-time telemetry ingestion; anomaly/fault detection on device state; closed-loop remediation actions; built from production network operations experience.

## What it does

A complete detect → decide → act → verify loop, running against a simulated
network (no lab gear needed): a telemetry generator streams gNMI-style JSON
notifications from three devices, a collector ingests them, a detector raises
faults from thresholds plus state tracking, and a remediation engine executes
actions against the simulated device state. Telemetry then recovers, the
detector confirms the fault has cleared, and the run prints the full timeline.

## Scenarios

| Scenario | Injected fault | Automated response |
|---|---|---|
| `bgp_drop` | BGP session on edge-rtr-1 drops (state Active, 0 prefixes) | Restart the BGP session; it re-establishes 2 ticks later |
| `link_flap` | Primary uplink flaps every tick, input errors +400/tick | Shut/no-shut bounce of the interface |
| `optical_degradation` | Rx power on the primary uplink decays past −24 dBm | Reroute traffic via the backup path + raise a ticket for the physical optics |
| `healthy` | None | No faults, no actions |

## Detector rules

- **BGP_SESSION_DOWN** — neighbour session state ≠ `Established`
- **HIGH_ERROR_RATE** — input-error delta > 100/tick, sustained 2 ticks (debounced)
- **LINK_FLAP** — ≥ 3 oper-status transitions in the last 6 samples
- **OPTICAL_DEGRADATION** — rx power on the *active-path* interface < −24 dBm
- **CPU_SATURATION** — CPU > 90% sustained 3 ticks → ticket only (no safe automated action)

A fault is verified cleared only after its condition stays absent for 2
consecutive ticks, so the loop proves recovery instead of assuming it.

## Architecture

```
                ┌───────────────── SimNetwork (device state) ◄── remediation actions
                │                            ▲
   scenario overlay (fault injection)        │ state
                │                            │
                ▼                            │
   TelemetryGenerator ──► Collector ──► Detector ──► fault?
   (gNMI-style JSON)        (latest +     (thresholds +      │ yes
                             history)      streaks)          ▼
                                              RemediationEngine ──► DECIDE/ACT
                                                     │
   VERIFY ◄── condition absent 2 ticks ◄─────────────┘
```

```
controller/
  simnet.py       simulated device state + delayed remediation effects
  telemetry.py    gNMI-style generator + scripted fault scenarios
  collector.py    streaming ingestion, latest/history per (device, path)
  detector.py     threshold + state-tracking fault detection
  remediation.py  fault -> action policy, executed on the SimNetwork
  engine.py       closed loop: ticks, timeline, recovery verification
main.py           CLI entry point
tests/            plain-assert test suite (pytest-compatible) + run_tests.py
```

## How to run

```bash
python3 main.py --scenario bgp_drop
python3 main.py --scenario link_flap
python3 main.py --scenario optical_degradation
python3 main.py --scenario healthy
python3 tests/run_tests.py        # 10 tests
```

## Sample output — `bgp_drop`

```
Scenario: bgp_drop
Timeline:
  [t=03] DETECT BGP_SESSION_DOWN on edge-rtr-1 (198.51.100.1): session state is Active, prefixes_received=0
  [t=03] DECIDE BGP_SESSION_DOWN -> restart_bgp_session
  [t=03] ACT    cleared BGP session to 198.51.100.1 on edge-rtr-1; re-establishing
  [t=06] VERIFY BGP_SESSION_DOWN on edge-rtr-1 (198.51.100.1) cleared -- condition absent for 2 consecutive ticks after remediation

Faults detected: 1
SCENARIO RESULT: RECOVERED
```

## Sample output — `optical_degradation`

```
  [t=05] DETECT OPTICAL_DEGRADATION on edge-rtr-1 (GigabitEthernet0/0/0): rx power -25.1 dBm on active path interface is below critical threshold -24.0 dBm
  [t=05] DECIDE OPTICAL_DEGRADATION -> reroute_via_backup
  [t=05] ACT    traffic on edge-rtr-1 rerouted to backup path (GigabitEthernet0/0/1); primary left in place for repair; raised ticket T-1001: degraded optics on GigabitEthernet0/0/0 (-25.1 dBm) - schedule fibre/optics replacement; traffic on backup path
  [t=07] VERIFY OPTICAL_DEGRADATION on edge-rtr-1 (GigabitEthernet0/0/0) cleared -- condition absent for 2 consecutive ticks after remediation

SCENARIO RESULT: RECOVERED
```

## Design notes

- **Delayed effects are modelled, not faked**: a restarted BGP session takes
  2 ticks to re-establish and a bounced interface stays shut for 2 ticks, so
  the detector watches the network actually recover.
- **Debouncing**: error-rate and CPU faults need sustained breaches, so a
  single noisy sample never triggers a remediation.
- **Not everything is auto-fixable**: optics degradation reroutes service and
  opens a ticket for the physical repair; CPU saturation escalates to a
  ticket only — mirroring real NOC policy.
