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
Step 3: take a checkpoint one warmup before every SimPoint.

Restores the ROI checkpoint from step 1.1 on the atomic CPU, and stops one
warmup before each SimPoint's interval to save a checkpoint there. The
SimPoints come from step 2 (``results.simpoints`` and ``results.weights``).
SimPoint ``i`` is the ``i``-th SimPoint in order of where it lies in the ROI.
The script writes one checkpoint per SimPoint, ``cpt.SimPoint<i>``, and
``simpoints.json``, which records the interval, weight, start, warmup and
checkpoint of every SimPoint for step 4.

``--stop`` chooses how gem5 stops at an instruction count:

* ``global-tracker`` (the default): a ``GlobalInstTracker`` and one
  ``LocalInstTracker`` per core. While they are listening, the trackers add
  up the instructions that all cores commit, and stop the simulation when the
  total reaches a threshold (a ``MAX_INSTS`` exit). A script can start and
  stop the listening; this one listens from the restored ROI checkpoint on.
* ``set-simpoint``: the first core's ``_set_simpoint()`` registers the
  counts. That core's first thread counts its own instructions from the
  moment the counts are registered, and stops the simulation at each one (a
  ``SIMPOINT_BEGIN`` exit). ``Simulator.schedule_simpoint()`` is meant to do
  this, but in gem5 v26.0 it raises ``AttributeError: object 'SimpleCore'
  has no attribute 'set_simpoint'``.

Give the same workload options as in step 1.1, and the same interval as in
step 1.2. Run from the guide's directory, with ``$GEM5`` set to your
``build/X86/gem5.opt``:

```
$GEM5 -d m5out/simpoint-checkpoints scripts/04_take_simpoint_checkpoints.py \
    --disk-image /path/to/spec-2017.img \
    --run-script scripts/spec-run-script.sh \
    --checkpoint-dir checkpoints/roi \
    --simpoints-dir simpoints \
    --interval 100000000 --warmup 100000000 \
    --output-dir checkpoints/simpoints
```
"""

import argparse
import json
import shutil
from pathlib import Path

from common import (
    add_workload_arguments,
    build_board,
    check_workload_arguments,
    set_workload,
)

import m5
from m5.objects import (
    GlobalInstTracker,
    LocalInstTracker,
)

from gem5.components.processors.cpu_types import CPUTypes
from gem5.resources.resource import SimpointDirectoryResource
from gem5.simulate.exit_event import ExitEvent
from gem5.simulate.exit_event_generators import (
    simpoints_save_checkpoint_generator,
)
from gem5.simulate.simulator import Simulator

parser = argparse.ArgumentParser(
    description="Take a checkpoint one warmup before every SimPoint."
)
add_workload_arguments(parser)
parser.add_argument(
    "--checkpoint-dir",
    type=Path,
    required=True,
    help="The ROI checkpoint from step 1.1.",
)
parser.add_argument(
    "--simpoints-dir",
    type=Path,
    required=True,
    help="Directory with results.simpoints and results.weights from step 2.",
)
parser.add_argument(
    "--interval",
    type=int,
    default=100_000_000,
    help="Instructions per interval, as in step 1.2. Default: 100000000.",
)
parser.add_argument(
    "--warmup",
    type=int,
    help="Instructions of warmup before each SimPoint. Default: one "
    "interval.",
)
parser.add_argument(
    "--stop",
    choices=["global-tracker", "set-simpoint"],
    default="global-tracker",
    help="How to stop at an instruction count. Default: global-tracker.",
)
parser.add_argument(
    "--output-dir",
    type=Path,
    required=True,
    help="Directory to write the SimPoint checkpoints and simpoints.json "
    "to.",
)
args = parser.parse_args()
check_workload_arguments(parser, args)
warmup = args.interval if args.warmup is None else args.warmup

# SimpointDirectoryResource reads SimPoint's output, sorts the SimPoints by
# interval, and computes each start as interval index * interval - warmup.
# When a SimPoint lies less than a warmup into the ROI, its warmup shrinks to
# what is there and it starts at instruction 0.
simpoint = SimpointDirectoryResource(
    local_path=str(args.simpoints_dir),
    simpoint_file="results.simpoints",
    weight_file="results.weights",
    simpoint_interval=args.interval,
    warmup_interval=warmup,
)
starts = simpoint.get_simpoint_start_insts()

args.output_dir.mkdir(parents=True, exist_ok=True)
manifest = {
    "interval": args.interval,
    "simpoints": [
        {
            "simpoint": i,
            "interval_index": index,
            "weight": weight,
            "start": start,
            "warmup": warmup_insts,
            "checkpoint": f"cpt.SimPoint{i}",
        }
        for i, (index, weight, start, warmup_insts) in enumerate(
            zip(
                simpoint.get_simpoint_list(),
                simpoint.get_weight_list(),
                starts,
                simpoint.get_warmup_list(),
            )
        )
    ],
}
(args.output_dir / "simpoints.json").write_text(
    json.dumps(manifest, indent=2) + "\n"
)

board = build_board(CPUTypes.ATOMIC)
set_workload(board, args, checkpoint=args.checkpoint_dir)
core = board.get_processor().get_cores()[0].core


def checkpoint_path(i: int) -> Path:
    return args.output_dir / f"cpt.SimPoint{i}"


if args.stop == "global-tracker":
    # The trackers count from 1, so a threshold of 0 never fires. A SimPoint
    # that starts at instruction 0 starts exactly where the ROI checkpoint
    # is, so its checkpoint is a copy of the ROI checkpoint.
    for i, start in enumerate(starts):
        if start == 0:
            shutil.copytree(
                args.checkpoint_dir, checkpoint_path(i), dirs_exist_ok=True
            )
            print(f"SimPoint {i} starts at 0: copied the ROI checkpoint.")
    stops = sorted({start for start in starts if start > 0})

    tracker = GlobalInstTracker(inst_thresholds=stops)
    for each_core in board.get_processor().get_cores():
        each_core.core.probeListener = LocalInstTracker(
            global_inst_tracker=tracker, start_listening=True
        )

    def save_at_each_stop():
        for stop in stops:
            print(
                f"Stopped at tick {m5.curTick()}: global tracker count "
                f"{tracker.getCounter()}."
            )
            for i, start in enumerate(starts):
                if start == stop:
                    m5.checkpoint(str(checkpoint_path(i)))
            yield stop == stops[-1]

    simulator = Simulator(
        board=board, on_exit_event={ExitEvent.MAX_INSTS: save_at_each_stop()}
    )
else:
    stops = sorted(set(starts))

    def report_each_stop(generator):
        while True:
            print(
                f"Stopped at tick {m5.curTick()}: the core's stop at "
                f"instruction {core.getCurrentInstCount(0)} fired."
            )
            yield next(generator)

    # gem5's generator saves cpt.SimPoint<i> at each stop, saving several
    # when SimPoints share a start, and ends the run after the last one.
    simulator = Simulator(
        board=board,
        on_exit_event={
            ExitEvent.SIMPOINT_BEGIN: report_each_stop(
                simpoints_save_checkpoint_generator(args.output_dir, simpoint)
            )
        },
    )
    # Before the simulation starts (board_initialized=False), this sets the
    # core's simpoint_start_insts parameter, so the counts are counted from
    # the restored ROI checkpoint.
    board.get_processor().get_cores()[0]._set_simpoint(
        starts, board_initialized=False
    )

if stops:
    simulator.run()

missing = [
    i
    for i in range(len(starts))
    if not (checkpoint_path(i) / "m5.cpt").exists()
]
if missing:
    raise SystemExit(
        f"No checkpoint for SimPoints {missing}: the ROI ended before the "
        "simulation reached them. Check that --interval matches step 1.2."
    )
print(f"Saved {len(starts)} SimPoint checkpoints in {args.output_dir}.")
