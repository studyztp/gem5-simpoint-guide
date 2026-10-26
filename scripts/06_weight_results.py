# Copyright (c) 2026 Zhantong Qiu
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
Step 4.2: combine the per-SimPoint results into one estimate for the ROI.

Reads ``simpoints.json`` from step 3 and the ``stats.txt`` of every
SimPoint's run from step 4.1, then prints the CPI of each SimPoint and the
weighted CPI of the whole ROI:

    estimated CPI = sum over the SimPoints of (weight x CPI of the SimPoint)

Weighting the CPI is right because each SimPoint stands for the intervals of
its cluster and every interval has the same number of instructions, so the
weights split the ROI's instructions. The IPC of the ROI is 1 / CPI; do not
average IPC itself.

With ``--baseline``, it also reads the ``stats.txt`` of a whole-ROI run
(``07_measure_whole_roi.py``) and prints the estimate's error.

This is plain Python 3, not a gem5 script. It expects the run of SimPoint
``i`` in ``<runs-dir>/simpoint-<i>``:

```
python3 scripts/06_weight_results.py checkpoints/simpoints/simpoints.json \
    m5out/measure --baseline m5out/baseline/stats.txt
```
"""

import argparse
import json
from pathlib import Path

CYCLES = "board.processor.cores.core.numCycles"
INSTRUCTIONS = "simInsts"


def read_stats(path: Path) -> tuple[int, int]:
    """Return (instructions, cycles) from the first dump in a stats.txt."""
    stats = {}
    for line in path.read_text().splitlines():
        if line.startswith("---------- End Simulation Statistics"):
            break
        fields = line.split()
        if len(fields) >= 2 and not line.startswith("-"):
            stats[fields[0]] = fields[1]
    return int(stats[INSTRUCTIONS]), int(stats[CYCLES])


parser = argparse.ArgumentParser(
    description="Combine the per-SimPoint results into one estimate."
)
parser.add_argument("manifest", type=Path, help="simpoints.json from step 3.")
parser.add_argument(
    "runs_dir",
    type=Path,
    help="Directory holding simpoint-<i>/stats.txt for every SimPoint.",
)
parser.add_argument(
    "--baseline",
    type=Path,
    help="stats.txt of a whole-ROI run, to compare the estimate with.",
)
args = parser.parse_args()

simpoints = json.loads(args.manifest.read_text())["simpoints"]
print(
    f"{'SimPoint':>8} {'interval':>8} {'weight':>8} "
    f"{'instructions':>12} {'cycles':>12} {'CPI':>8}"
)
total_weight = 0.0
weighted_cpi = 0.0
for simpoint in simpoints:
    stats_file = (
        args.runs_dir / f"simpoint-{simpoint['simpoint']}" / "stats.txt"
    )
    if not stats_file.exists():
        raise SystemExit(f"Missing {stats_file}: run step 4.1 for it first.")
    instructions, cycles = read_stats(stats_file)
    cpi = cycles / instructions
    total_weight += simpoint["weight"]
    weighted_cpi += simpoint["weight"] * cpi
    print(
        f"{simpoint['simpoint']:>8} {simpoint['interval_index']:>8} "
        f"{simpoint['weight']:>8.4f} {instructions:>12} {cycles:>12} "
        f"{cpi:>8.4f}"
    )

# SimPoint's weights add up to 1, but it writes them to six significant
# digits; dividing by their sum removes the rounding.
estimate = weighted_cpi / total_weight
print(f"\nEstimated CPI of the ROI: {estimate:.4f} (IPC {1 / estimate:.4f})")

if args.baseline:
    instructions, cycles = read_stats(args.baseline)
    baseline = cycles / instructions
    print(
        f"Baseline CPI of the ROI:  {baseline:.4f} (IPC {1 / baseline:.4f}), "
        f"from {instructions} instructions"
    )
    print(f"Error of the estimate:    {(estimate / baseline - 1) * 100:+.2f}%")
