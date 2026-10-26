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

# Step 2: pick SimPoints from the BBVs with the SimPoint tool.
#
# Usage:
#   scripts/03_run_simpoint.sh SIMPOINT BBV_FILE OUTPUT_DIR [MAX_K]
#
#   SIMPOINT    the simpoint binary (bin/simpoint in the SimPoint sources)
#   BBV_FILE    simpoint.bb.gz from step 1.2
#   OUTPUT_DIR  where to write results.simpoints, results.weights and the log
#   MAX_K       the most SimPoints to pick (default 50)
#
# Example:
#   scripts/03_run_simpoint.sh simpoint/bin/simpoint m5out/bbv/simpoint.bb.gz \
#       simpoints 50

set -euo pipefail

if [ $# -lt 3 ] || [ $# -gt 4 ]; then
    sed -n '/^# Usage:/,/^$/p' "$0"
    exit 1
fi

SIMPOINT=$1
BBV_FILE=$2
OUTPUT_DIR=$3
MAX_K=${4:-50}

mkdir -p "$OUTPUT_DIR"

# -k search (the default) clusters the intervals for several values of k up
# to -maxK and keeps the smallest k whose clustering scores close to the best
# one. gem5 writes the BBV file gzipped, hence -inputVectorsGzipped.
"$SIMPOINT" \
    -loadFVFile "$BBV_FILE" \
    -inputVectorsGzipped \
    -maxK "$MAX_K" \
    -saveSimpoints "$OUTPUT_DIR/results.simpoints" \
    -saveSimpointWeights "$OUTPUT_DIR/results.weights" \
    > "$OUTPUT_DIR/simpoint.log" 2>&1

echo "SimPoint picked $(wc -l < "$OUTPUT_DIR/results.simpoints" | tr -d ' ')" \
    "SimPoints; the log is in $OUTPUT_DIR/simpoint.log."
echo "interval index, cluster, weight:"
paste -d ' ' "$OUTPUT_DIR/results.simpoints" "$OUTPUT_DIR/results.weights" |
    awk '{ printf "  %8d  %3d  %.4f\n", $1, $2, $3 }' | sort -n
