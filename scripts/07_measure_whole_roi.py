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
Optional check: simulate the whole ROI in detail, as a baseline.

Restores the ROI checkpoint from step 1.1 on the same detailed CPU and caches
as step 4.1, and simulates to the end of the ROI (hypercall 5). Its
``stats.txt`` gives the actual CPI of the ROI on that system, which
``06_weight_results.py --baseline`` compares with the SimPoint estimate.

This simulates every instruction of the ROI in detail, which is what
SimPoints exist to avoid, so it is practical only for a short ROI, such as a
test input or the NPB example.

Give the same workload options as in step 1.1. Run from the guide's
directory, with ``$GEM5`` set to your ``build/X86/gem5.opt``:

```
$GEM5 -d m5out/baseline scripts/07_measure_whole_roi.py \
    --disk-image /path/to/spec-2017.img \
    --run-script scripts/spec-run-script.sh \
    --checkpoint-dir checkpoints/roi
```
"""

import argparse
from pathlib import Path

from common import (
    DETAILED_CPU_TYPES,
    add_workload_arguments,
    build_board,
    check_workload_arguments,
    set_workload,
)

import m5

from gem5.simulate.exit_handler import WorkEndExitHandler
from gem5.simulate.simulator import Simulator
from gem5.utils.override import overrides

parser = argparse.ArgumentParser(
    description="Simulate the whole ROI in detail, as a baseline."
)
add_workload_arguments(parser)
parser.add_argument(
    "--checkpoint-dir",
    type=Path,
    required=True,
    help="The ROI checkpoint from step 1.1.",
)
parser.add_argument(
    "--cpu",
    choices=sorted(DETAILED_CPU_TYPES),
    default="o3",
    help="The detailed CPU model, as in step 4.1. Default: o3.",
)
args = parser.parse_args()
check_workload_arguments(parser, args)

board = build_board(DETAILED_CPU_TYPES[args.cpu], with_caches=True)
set_workload(board, args, checkpoint=args.checkpoint_dir)


class StopAtRoiEnd(WorkEndExitHandler):
    """When the ROI ends, dump the statistics and stop."""

    reached = False

    @overrides(WorkEndExitHandler)
    def _process(self, simulator: Simulator) -> None:
        StopAtRoiEnd.reached = True
        print(
            f"ROI ends at tick {simulator.get_current_tick()} after "
            f"{simulator.get_instruction_count()} instructions."
        )
        m5.stats.dump()

    @overrides(WorkEndExitHandler)
    def _exit_simulation(self) -> bool:
        return True


simulator = Simulator(board=board)
simulator.run()

if not StopAtRoiEnd.reached:
    raise SystemExit(
        "The simulation stopped before the ROI ended, so stats.txt does not "
        "cover the whole ROI."
    )
