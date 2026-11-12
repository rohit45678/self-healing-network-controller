#!/usr/bin/env python3
"""Self-healing network controller -- CLI (simulation).

Usage:
    python main.py --scenario bgp_drop
    python main.py --scenario link_flap
    python main.py --scenario optical_degradation
    python main.py --scenario healthy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from controller.engine import run_scenario
from controller.telemetry import SCENARIOS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Closed-loop self-healing network controller (simulation)")
    ap.add_argument("--scenario", default="bgp_drop", choices=sorted(SCENARIOS))
    ap.add_argument("--ticks", type=int, default=None, help="override scenario length")
    args = ap.parse_args(argv)

    result = run_scenario(args.scenario, ticks=args.ticks)
    print(f"Scenario: {result.scenario}")
    print("Timeline:")
    if result.events:
        for event in result.events:
            print("  " + str(event))
    else:
        print("  (no faults detected)")
    print(f"\nFaults detected: {result.faults_seen}")
    for ticket in result.tickets:
        print(f"Ticket: {ticket['id']} [{ticket['device']}] {ticket['summary']}")
    print(f"SCENARIO RESULT: {result.status}")
    return 0 if result.status in ("RECOVERED", "NO FAULTS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
