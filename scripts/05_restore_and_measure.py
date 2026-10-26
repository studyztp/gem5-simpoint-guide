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
Step 4.1: restore one SimPoint checkpoint and measure its interval.

Restores ``cpt.SimPoint<i>`` from step 3 on a detailed CPU with caches,
simulates the SimPoint's warmup, resets the statistics, simulates one
interval, and dumps the statistics, so ``stats.txt`` in the output directory
describes that interval alone. The warmup, the interval and the checkpoint
come from the ``simpoints.json`` that step 3 wrote.

Run it once per SimPoint, each with its own output directory. Give the same
workload options as in step 1.1. Run from the guide's directory, with
``$GEM5`` set to your ``build/X86/gem5.opt``:

```
$GEM5 -d m5out/measure/simpoint-0 scripts/05_restore_and_measure.py \
    --disk-image /path/to/spec-2017.img \
    --run-script scripts/spec-run-script.sh \
    --simpoint-checkpoints checkpoints/simpoints --simpoint 0
```
"""

import argparse
import json
from pathlib import Path

from common import (
    DETAILED_CPU_TYPES,
    add_workload_arguments,
    build_board,
    check_workload_arguments,
    set_workload,
)

import m5

from gem5.simulate.exit_event import ExitEvent
from gem5.simulate.simulator import Simulator

parser = argparse.ArgumentParser(
    description="Restore one SimPoint checkpoint and measure its interval."
)
add_workload_arguments(parser)
parser.add_argument(
    "--simpoint-checkpoints",
    type=Path,
    required=True,
    help="The --output-dir of step 3, with simpoints.json and the "
    "cpt.SimPoint<i> checkpoints.",
)
parser.add_argument(
    "--simpoint",
    type=int,
    required=True,
    help="Which SimPoint to measure: the i of cpt.SimPoint<i>.",
)
parser.add_argument(
    "--cpu",
    choices=sorted(DETAILED_CPU_TYPES),
    default="o3",
    help="The detailed CPU model to measure with. Default: o3.",
)
args = parser.parse_args()
check_workload_arguments(parser, args)

manifest = json.loads(
    (args.simpoint_checkpoints / "simpoints.json").read_text()
)
interval = manifest["interval"]
simpoint = manifest["simpoints"][args.simpoint]
warmup = simpoint["warmup"]

board = build_board(DETAILED_CPU_TYPES[args.cpu], with_caches=True)
set_workload(
    board,
    args,
    checkpoint=args.simpoint_checkpoints / simpoint["checkpoint"],
)


def warm_up_then_measure():
    if warmup > 0:
        print(f"Warmed up for {warmup} instructions. Measuring {interval}.")
        m5.stats.reset()
        simulator.schedule_max_insts(interval)
        yield False
    print(
        f"Measured SimPoint {args.simpoint} (interval {simpoint['interval_index']})."
    )
    m5.stats.dump()
    yield True


simulator = Simulator(
    board=board, on_exit_event={ExitEvent.MAX_INSTS: warm_up_then_measure()}
)
# A stop counts each thread's instructions from when it is scheduled: this
# one from the restored checkpoint, the one in warm_up_then_measure() from
# the end of the warmup. A SimPoint at the very start of the ROI has no
# warmup; its measurement then starts right away, with cold caches.
simulator.schedule_max_insts(warmup if warmup > 0 else interval)
simulator.run()
