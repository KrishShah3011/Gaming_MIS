"""Pretend to be café PCs PC02..PC30, so the dashboard can be tested without the café.

Each tick every virtual PC is either playing (recent input), away (idle time grows)
or off (one shutdown message, then silence). About 5% of PCs change mode each tick.
Standard library only.

Example:
  python tools/simulate_pcs.py --token <AGENT TOKEN> --interval 15
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request
from collections import Counter

PLAYING, AWAY, OFF = "playing", "away", "off"


class VirtualPC:
    def __init__(self, name, mode, idle_s=0):
        self.name, self.mode, self.idle_s = name, mode, idle_s
        self.on = mode != OFF

    def step(self, rng, interval):
        """Advance one tick. Returns the event to send, or None to stay silent."""
        if rng.random() < 0.05:
            self.mode = rng.choice([PLAYING, AWAY, OFF])
        if self.mode == OFF:
            was_on, self.on = self.on, False
            return "shutdown" if was_on else None
        if not self.on:
            self.on, self.idle_s = True, 0
            return "boot"
        self.idle_s = rng.randint(0, 20) if self.mode == PLAYING else self.idle_s + interval
        return "heartbeat"


def send(url, token, pc, event):
    data = json.dumps({
        "pc": pc.name, "event": event, "idle_s": pc.idle_s,
        "boot_id": f"sim-{pc.name}", "agent_version": "simulator",
    }).encode()
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError as error:
        return f"unreachable ({error})"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000/api/v1/heartbeat")
    parser.add_argument("--token", required=True, help="the agent token (not its hash)")
    parser.add_argument("--first", type=int, default=2, help="number of the first virtual PC (2 = PC02)")
    parser.add_argument("--count", type=int, default=29, help="number of virtual PCs")
    parser.add_argument("--interval", type=int, default=60, help="seconds between ticks")
    parser.add_argument("--ticks", type=int, default=0, help="stop after N ticks (0 = run until Ctrl+C)")
    parser.add_argument("--seed", type=int, help="make the run repeatable")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    pcs = []
    for i in range(args.count):  # roughly 2/3 playing, 1/6 away, 1/6 off
        mode = OFF if i % 6 == 5 else AWAY if i % 6 == 4 else PLAYING
        pcs.append(VirtualPC(f"PC{args.first + i:02d}", mode, idle_s=rng.randint(300, 900) if mode == AWAY else 0))

    tick = 0
    while args.ticks == 0 or tick < args.ticks:
        tick += 1
        responses = Counter()
        for pc in pcs:
            event = pc.step(rng, args.interval)
            if event:
                responses[send(args.url, args.token, pc, event)] += 1
        modes = Counter(pc.mode for pc in pcs)
        print(f"tick {tick}: playing {modes[PLAYING]}, away {modes[AWAY]}, off {modes[OFF]}; "
              f"responses {dict(responses)}", flush=True)
        if args.ticks == 0 or tick < args.ticks:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
