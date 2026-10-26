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
Step 1.1: boot the guest and take the ROI checkpoint.

The guest boots, starts its run script, and marks the start of the region of
interest (ROI) with hypercall 4: ``gem5-bridge hypercall 4`` in a SPEC run
script, or the ``m5_hypercall_addr(4)`` call built into the NPB binaries. At
that point this script saves one checkpoint and stops. Steps 1.2, 3 and 4.3
restore this checkpoint, and step 4.1 restores checkpoints taken from it, so
every later run starts from the same state.

Boot on KVM when the host has it (an x86-64 Linux host). Booting on the
atomic CPU works on any host but takes much longer.

Run from the guide's directory, with ``$GEM5`` set to your
``build/X86/gem5.opt``. SPEC CPU2017, with your own disk image:

```
$GEM5 -d m5out/roi-checkpoint scripts/01_take_roi_checkpoint.py \
    --disk-image /path/to/spec-2017.img \
    --run-script scripts/spec-run-script.sh \
    --checkpoint-dir checkpoints/roi
```

NPB IS from gem5 resources, to try the flow without SPEC:

```
$GEM5 -d m5out/roi-checkpoint scripts/01_take_roi_checkpoint.py \
    --workload x86-ubuntu-24.04-npb-is-s --workload-version 3.0.0 \
    --run-script scripts/npb-run-script.sh --kernel-arg no_systemd=true \
    --boot-cpu atomic --checkpoint-dir checkpoints/roi
```
"""

import argparse
from pathlib import Path

from common import (
    add_workload_arguments,
    build_board,
    check_workload_arguments,
    set_workload,
)

from gem5.components.processors.cpu_types import CPUTypes
from gem5.simulate.exit_handler import WorkBeginExitHandler
from gem5.simulate.simulator import Simulator
from gem5.utils.override import overrides

parser = argparse.ArgumentParser(
    description="Boot the guest and checkpoint the start of the ROI."
)
add_workload_arguments(parser)
parser.add_argument(
    "--boot-cpu",
    choices=["kvm", "atomic"],
    default="kvm",
    help="CPU model to boot on. Default: kvm.",
)
parser.add_argument(
    "--kvm-no-perf",
    action="store_true",
    help="Run KVM without the host's perf counters.",
)
parser.add_argument(
    "--checkpoint-dir",
    type=Path,
    required=True,
    help="Directory to write the ROI checkpoint to.",
)
args = parser.parse_args()
check_workload_arguments(parser, args)

board = build_board(
    CPUTypes.KVM if args.boot_cpu == "kvm" else CPUTypes.ATOMIC,
    kvm_use_perf=not args.kvm_no_perf,
)
set_workload(board, args)


class SaveRoiCheckpoint(WorkBeginExitHandler):
    """When the ROI begins, save the checkpoint and stop."""

    @overrides(WorkBeginExitHandler)
    def _process(self, simulator: Simulator) -> None:
        print(
            f"ROI begins at tick {simulator.get_current_tick()}. "
            f"Saving the ROI checkpoint to {args.checkpoint_dir}"
        )
        simulator.save_checkpoint(args.checkpoint_dir)

    @overrides(WorkBeginExitHandler)
    def _exit_simulation(self) -> bool:
        return True


simulator = Simulator(board=board)
simulator.run()

if not (args.checkpoint_dir / "m5.cpt").exists():
    raise SystemExit(
        "The simulation stopped before the ROI began, so there is no ROI "
        "checkpoint. Check that the run script calls "
        "`gem5-bridge hypercall 4` before the benchmark."
    )
