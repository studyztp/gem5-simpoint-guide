#!/bin/bash
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

# Guest run script for one SPEC CPU2017 speed benchmark, run directly rather
# than through runcpu. gem5 hands this script to the guest, which runs it
# after it boots.
#
# Example: 619.lbm_s with its reference input. For another benchmark, change
# RUN_DIR and the command line. RUN_DIR is a run directory that runcpu set up
# on the disk image, and the command line is what `specinvoke -n` prints in
# that directory, with the executable name of your build.

RUN_DIR=/home/gem5/spec2017/benchspec/CPU/619.lbm_s/run/run_base_refspeed_mytest-m64.0000

# The echo lines go to the guest's serial console, which gem5 writes to
# board.pc.com_1.device in the output directory. They show how far the guest
# got if a run stops or seems stuck.
echo "spec-run-script: started"
cd "$RUN_DIR" || { echo "spec-run-script: cannot cd to $RUN_DIR"; exit 1; }

# The floating-point speed benchmarks and 657.xz_s can be built with OpenMP.
# One thread keeps such a build single-threaded.
export OMP_NUM_THREADS=1

# Hypercall 4 marks the start of the region of interest (ROI) and hypercall 5
# its end: step 1.1 checkpoints at hypercall 4, and steps 1.2 and 4.3 stop at
# hypercall 5. A SPEC benchmark as SPEC builds it makes neither call, so this
# script makes them right before and after the benchmark's command. If you
# add the calls to the benchmark itself (see README.md), remove the two
# gem5-bridge lines.
echo "spec-run-script: ROI begins"
gem5-bridge hypercall 4
./lbm_s_base.mytest-m64 2000 reference.dat 0 0 200_200_260_ldc.of > lbm.out 2>> lbm.err
gem5-bridge hypercall 5
echo "spec-run-script: ROI ended"
