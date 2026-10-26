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
The system and workload shared by the gem5 scripts in this directory.

All runs in the SimPoint flow must keep the parts of the system that a
checkpoint holds. The BBV run (step 1.2) and the SimPoint checkpoint run
(step 3) both restore the ROI checkpoint from step 1.1, and their
instruction counts only line up if both execute the same instructions on the
same system. Building the system here, once, keeps the scripts from drifting
apart.

A run uses one of two kinds of workload:

* ``--workload``: a workload from gem5 resources, such as
  ``x86-ubuntu-24.04-npb-is-s``, to try the flow without SPEC.
* ``--disk-image`` and ``--run-script``: your own disk image (for example one
  with SPEC CPU2017 installed) and the script the guest runs after it boots.
"""

import argparse
from pathlib import Path

from gem5.components.boards.x86_board import X86Board
from gem5.components.cachehierarchies.classic.no_cache import NoCache
from gem5.components.cachehierarchies.classic.private_l1_private_l2_walk_cache_hierarchy import (
    PrivateL1PrivateL2WalkCacheHierarchy,
)
from gem5.components.memory import DualChannelDDR4_2400
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import (
    DiskImageResource,
    KernelResource,
    obtain_resource,
)

# A checkpoint stores the guest's memory and one CPU state per core, so the
# memory size and the number of cores must not change between runs. The CPU
# model and the caches can change: neither is stored in a checkpoint.
MEMORY_SIZE = "3GiB"
NUM_CORES = 1
CLOCK = "3GHz"

# The CPU models that step 4 can measure with.
DETAILED_CPU_TYPES = {
    "o3": CPUTypes.O3,
    "minor": CPUTypes.MINOR,
    "timing": CPUTypes.TIMING,
}

# The kernel and kernel command line that the Ubuntu 24.04 disk images in
# gem5 resources boot with.
DEFAULT_KERNEL_ID = "x86-linux-kernel-6.8.0-52-generic"
DEFAULT_KERNEL_VERSION = "1.0.0"
KERNEL_ARGS = ["earlyprintk=ttyS0", "console=ttyS0", "lpj=7999923"]


def add_workload_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the options that choose the workload."""
    group = parser.add_argument_group(
        "workload",
        "Give --workload for a gem5 resources workload, or --disk-image and "
        "--run-script for your own disk image.",
    )
    group.add_argument(
        "--workload",
        help="ID of a gem5 resources workload, for example "
        "x86-ubuntu-24.04-npb-is-s.",
    )
    group.add_argument(
        "--workload-version",
        help="Version of --workload. Default: the newest version in gem5 "
        "resources; gem5 warns if it does not support this gem5 release.",
    )
    group.add_argument(
        "--disk-image",
        type=Path,
        help="Path to your x86 disk image, for example one with SPEC "
        "CPU2017 installed.",
    )
    group.add_argument(
        "--run-script",
        type=Path,
        help="Script that the guest runs after it boots; see "
        "spec-run-script.sh. Required with --disk-image. With --workload, it "
        "replaces the workload's own script.",
    )
    group.add_argument(
        "--kernel-arg",
        action="append",
        default=[],
        help="Extra argument for the kernel command line; repeat for more. "
        "For example, no_systemd=true makes the Ubuntu 24.04 images "
        "from gem5 resources skip systemd, which shortens a boot on the "
        "atomic CPU.",
    )
    group.add_argument(
        "--kernel",
        type=Path,
        help="Path to the guest kernel (vmlinux) for --disk-image. Default: "
        f"{DEFAULT_KERNEL_ID} from gem5 resources.",
    )
    group.add_argument(
        "--root-device",
        default="/dev/sda2",
        help="Root device on the kernel command line for --disk-image. "
        "Default: /dev/sda2, as for the Ubuntu 24.04 images in gem5 "
        "resources.",
    )


def check_workload_arguments(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Stop with a usage error unless exactly one workload was chosen and
    --disk-image comes with --run-script.
    """
    if bool(args.workload) == bool(args.disk_image):
        parser.error("give either --workload or --disk-image")
    if args.disk_image and not args.run_script:
        parser.error("--disk-image needs --run-script")


def build_board(
    cpu_type: CPUTypes,
    with_caches: bool = False,
    kvm_use_perf: bool = True,
) -> X86Board:
    """Build the system that every run simulates.

    :param cpu_type: The CPU model of the single core.
    :param with_caches: Give the core private L1 and L2 caches. Runs that
                        only move the guest forward (booting, profiling,
                        taking checkpoints) do not need caches and run
                        faster without them.
    :param kvm_use_perf: Whether a KVM core uses the host's perf counters.
                         Turn this off on hosts that restrict perf.
    """
    processor = SimpleProcessor(
        cpu_type=cpu_type, isa=ISA.X86, num_cores=NUM_CORES, clk_freq=CLOCK
    )
    if cpu_type == CPUTypes.KVM and not kvm_use_perf:
        for core in processor.get_cores():
            core.core.usePerf = False

    if with_caches:
        cache_hierarchy = PrivateL1PrivateL2WalkCacheHierarchy(
            l1d_size="32KiB", l1i_size="32KiB", l2_size="1MiB"
        )
    else:
        cache_hierarchy = NoCache()

    return X86Board(
        clk_freq=CLOCK,
        processor=processor,
        memory=DualChannelDDR4_2400(size=MEMORY_SIZE),
        cache_hierarchy=cache_hierarchy,
    )


def set_workload(
    board: X86Board,
    args: argparse.Namespace,
    checkpoint: Path | None = None,
) -> None:
    """Give the board the workload chosen on the command line.

    :param checkpoint: A checkpoint directory to restore, or ``None`` to
                       boot from the start.
    """
    if args.workload:
        workload = obtain_resource(
            args.workload, resource_version=args.workload_version
        )
        if args.run_script:
            workload.set_parameter(
                "readfile_contents", args.run_script.read_text()
            )
        if args.kernel_arg:
            kernel_args = (
                workload.get_parameters().get("kernel_args")
                or board.get_default_kernel_args()
            )
            workload.set_parameter(
                "kernel_args", list(kernel_args) + args.kernel_arg
            )
        if checkpoint is not None:
            workload.set_parameter("checkpoint", checkpoint)
        board.set_workload(workload)
        return

    if args.kernel:
        kernel = KernelResource(local_path=str(args.kernel))
    else:
        kernel = obtain_resource(
            DEFAULT_KERNEL_ID, resource_version=DEFAULT_KERNEL_VERSION
        )
    kernel_args = KERNEL_ARGS + [f"root={args.root_device}"]
    board.set_kernel_disk_workload(
        kernel=kernel,
        disk_image=DiskImageResource(local_path=str(args.disk_image)),
        readfile_contents=args.run_script.read_text(),
        kernel_args=kernel_args + args.kernel_arg,
        checkpoint=checkpoint,
    )
