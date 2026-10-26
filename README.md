# SimPoints for SPEC CPU2017 in gem5 (x86 full system)

This guide shows how to sample a SPEC CPU2017 benchmark with SimPoints in
gem5's x86 full-system simulation, with the gem5 standard library. You
profile the benchmark's basic block vectors with gem5's SimPoint probe, pick
SimPoints with the SimPoint 3.2 tool, take a checkpoint at each SimPoint, and
simulate the checkpoints in detail to estimate the whole run. It covers
single-threaded runs: one core, with the SPEC CPU2017 speed benchmarks run
with `OMP_NUM_THREADS=1`.

Every step here was run with gem5 v26.0.0.0 and SimPoint 3.2, on the NPB IS
benchmark from gem5 resources and on `gzip`, which stands in for a SPEC
benchmark on the same disk image;
[Try the flow without SPEC](#try-the-flow-without-spec-npb-is-from-gem5-resources)
has the exact commands and results. The validation host was an arm64 Mac,
which cannot run x86 KVM, so the KVM boot in step 1.1 was not exercised, and
SPEC itself was not run, because it needs your own licensed disk image.

## What is in this repository

- `README.md`: this guide.
- `scripts/common.py`: the system that every script simulates, and the
  options that choose the workload.
- `scripts/spec-run-script.sh`: the guest run script for one SPEC CPU2017
  benchmark (`619.lbm_s`); copy it for yours.
- `scripts/npb-run-script.sh`: the guest run script of the NPB example.
- `scripts/01_take_roi_checkpoint.py`: step 1.1, boot and checkpoint the
  start of the region of interest (ROI).
- `scripts/02_collect_bbv.py`: step 1.2, profile the ROI into basic block
  vectors (BBVs).
- `scripts/03_run_simpoint.sh`: step 2, pick SimPoints with SimPoint 3.2.
- `scripts/04_take_simpoint_checkpoints.py`: step 3, checkpoint every
  SimPoint.
- `scripts/05_restore_and_measure.py`: step 4.1, measure one SimPoint in
  detail.
- `scripts/06_weight_results.py`: step 4.2, combine the measurements into
  one estimate.
- `scripts/07_measure_whole_roi.py`: step 4.3, simulate a short ROI in full
  to check the estimate.
- `LICENSE`: the BSD 3-Clause license of the scripts.

Run every command from the root of this repository, with `GEM5` set to your
gem5 binary:

```bash
export GEM5=/path/to/gem5/build/X86/gem5.opt
```

The commands write to `m5out/`, `checkpoints/` and `simpoints/`, which git
ignores.

## How SimPoint sampling works

A program runs in phases, stretches of its run with similar behavior, and
the code it executes shows which phase it is in. SimPoint builds on this. It
splits the run into intervals of a fixed number of instructions and describes
each interval by its basic block vector (BBV): how many instructions the
interval executed in each basic block of the program. It clusters the
intervals by their BBVs and, from each cluster, picks the interval closest to
the cluster's center. These intervals are the SimPoints. Simulating only the
SimPoints in detail, and weighting each by its cluster's share of all
intervals, estimates the whole run at a small fraction of the cost.

In full system, the run to sample is the benchmark's region of interest
(ROI), which the guest marks. The flow:

| Step | What runs | What it produces |
|---|---|---|
| 1.1 | Boot the guest; checkpoint when the ROI begins | `checkpoints/roi` |
| 1.2 | The ROI on the atomic CPU with the SimPoint probe | `m5out/bbv/simpoint.bb.gz` |
| 2 | SimPoint 3.2 on the BBVs | `simpoints/results.simpoints` and `results.weights` |
| 3 | The ROI on the atomic CPU, stopping at each SimPoint's start | `checkpoints/simpoints/cpt.SimPoint<i>` and `simpoints.json` |
| 4.1 | Each SimPoint checkpoint on a detailed CPU: warm up, measure one interval | `m5out/measure/simpoint-<i>/stats.txt` |
| 4.2 | The weighted sum of the per-SimPoint CPIs | The estimated CPI of the ROI |
| 4.3 | Optional, for a short ROI: the whole ROI on the detailed CPU | The actual CPI, to check the estimate |

## Before you start

You need:

- **An x86-64 Linux host with KVM**, to boot the guest quickly. Without KVM,
  the guest boots on the atomic CPU, which works but is slow.
- **gem5 v26.0, built for x86** on that host:

  ```bash
  git clone https://github.com/gem5/gem5.git
  cd gem5
  git checkout v26.0.0.0
  scons build/X86/gem5.opt -j "$(nproc)"
  ```

  Run `scons` from the gem5 directory: gem5's build resolves `build/X86`
  against the directory that `scons` starts in. gem5 builds KVM support only
  on a host with KVM; otherwise the build warns
  `Cannot enable KVM, host seems to lack KVM support`.
- **An x86 disk image with SPEC CPU2017 installed.** SPEC is licensed, so
  you build this image yourself. This guide assumes an Ubuntu 24.04 image
  built with the gem5 resources recipe
  [`src/ubuntu-generic-diskimages`](https://github.com/gem5/gem5-resources/tree/stable/src/ubuntu-generic-diskimages):
  - Install SPEC CPU2017 from your ISO in the recipe's
    `scripts/install-user-benchmarks.sh`, build the speed benchmarks, and set
    up their run directories, with `runcpu`'s `build` and `runsetup`
    actions.
  - Enlarge the image first: the recipe's image is 5 GB, and its
    `BUILDING.md` explains how to change the partition size and the Packer
    `disk_size`.
  - Build the image with `./build-x86.sh 24.04` on an x86 host. The build
    also copies the image's kernel to
    `x86-disk-image-24.04/vmlinux-x86-ubuntu`; give it to the scripts with
    `--kernel`.

  The image logs in as the `gem5` user, has `gem5-bridge` in
  `/usr/local/bin`, and runs the run script after it boots. (gem5 resources'
  older `src/spec-2017` recipe builds an Ubuntu 18.04 image that runs SPEC
  through `runcpu`, which this guide does not use.)
- **The command line of each benchmark**, from `specinvoke -n`; see
  [Prepare the benchmark's run script](#prepare-the-benchmarks-run-script).
- **SimPoint 3.2**; step 2 shows how to build it.
- **Python 3**, for `scripts/06_weight_results.py`.

With your image, every gem5 command in this guide takes the same workload
options:

```bash
--disk-image /path/to/spec-2017.img \
--kernel /path/to/x86-disk-image-24.04/vmlinux-x86-ubuntu \
--run-script scripts/spec-run-script.sh
```

The steps show only `--disk-image` and `--run-script`. Without `--kernel`,
the scripts boot `x86-linux-kernel-6.8.0-52-generic`, the kernel of gem5
resources' own Ubuntu 24.04 images.

## Choosing the interval, warmup and maxK

Three numbers decide how the sample is drawn. You give the interval when you
collect the BBVs (step 1.2) and again in step 3, the warmup in step 3, and
maxK when you run SimPoint (step 2). Step 4 reads the interval and the
warmups from the `simpoints.json` that step 3 writes.

- **Interval**: the number of instructions in each interval. It is both the
  unit that SimPoint clusters (one BBV per interval) and the length of each
  sample that step 4 simulates in detail. Shorter intervals separate shorter
  program phases and make each detailed run cheaper, but each sample then
  depends more on how well the caches and predictors were warmed up. Longer
  intervals do the opposite. Use the same interval in every step.
- **Warmup**: the number of instructions simulated in detail before each
  sample is measured, so that caches, TLBs and branch predictors are not
  cold when measurement starts. Each SimPoint checkpoint is taken this many
  instructions before its interval begins. More warmup lowers the cold-start
  error and lengthens every detailed run. Do not set it to 0: in gem5 v26.0,
  `SimpointResource` and `SimpointDirectoryResource` raise
  `TypeError: object of type 'method' has no len()` for a warmup of 0.
- **maxK**: the largest number of SimPoints that SimPoint may pick. It tries
  several numbers of clusters up to maxK and keeps the smallest one whose
  clustering scores close to the best (see step 2). More SimPoints usually
  means a smaller sampling error and more detailed simulation. Keep maxK well
  below the number of intervals in the ROI: in the validation, an ROI of 15
  intervals with `-maxK 50` got one SimPoint per interval, which samples
  nothing.

Step 4 costs about (number of SimPoints) × (warmup + interval) instructions
of detailed simulation.

The usual choice in academic work is an interval of 100 million instructions
and one interval (100 million instructions) of warmup. For maxK, pick it by
how many detailed simulations you can afford; 50 is the usual value, and it is
what LoopPoint uses (its `run-looppoint.py` defaults to `-maxK 50`, with
regions of 100 million instructions per thread).

## Prepare the benchmark's run script

In full-system mode the benchmark runs inside the guest. When the guest has
booted, it asks gem5 for a script (gem5 calls this the readfile contents) and
runs it. For SPEC, that script runs one benchmark directly, with its command
line, instead of through `runcpu`. `scripts/spec-run-script.sh` does this for
`619.lbm_s` with its reference input:

```bash
RUN_DIR=/home/gem5/spec2017/benchspec/CPU/619.lbm_s/run/run_base_refspeed_mytest-m64.0000

echo "spec-run-script: started"
cd "$RUN_DIR" || { echo "spec-run-script: cannot cd to $RUN_DIR"; exit 1; }

export OMP_NUM_THREADS=1

echo "spec-run-script: ROI begins"
gem5-bridge hypercall 4
./lbm_s_base.mytest-m64 2000 reference.dat 0 0 200_200_260_ldc.of > lbm.out 2>> lbm.err
gem5-bridge hypercall 5
echo "spec-run-script: ROI ended"
```

Change two things for your benchmark:

- **The run directory.** `runcpu --action=runsetup` creates one for each
  benchmark and input size, under `benchspec/CPU/<benchmark>/run/`, and puts
  the input files there. The benchmark opens its inputs by relative path, so
  the script must `cd` into it first.
- **The command line.** Run `specinvoke -n` in the run directory: it prints
  the commands that `runcpu` would run, without running them. Copy one as it
  is, with the executable name of your build (look in
  `benchspec/CPU/<benchmark>/exe/`). Limaye and Adegbija list these commands
  for every CPU2017 benchmark and input size [(PDF)][spec-commands]. Some
  inputs consist of several commands (the reference input of `602.gcc_s` has
  three). Each command is a separate program run, so give each one its own
  run script and its own pass through this guide.

The other lines stay as they are:

- `OMP_NUM_THREADS=1` keeps a speed benchmark that was built with OpenMP
  (an option for the floating-point ones and `657.xz_s`) on one thread.
  This guide simulates one core and one thread.
- `gem5-bridge hypercall 4` and `gem5-bridge hypercall 5` mark the start and
  the end of the region of interest (ROI). gem5 calls these events
  `WORK_BEGIN` and `WORK_END`. Only the instructions between them are profiled
  and sampled, so put nothing else between them. `gem5-bridge` is the guest
  side of gem5's m5 utility; the Ubuntu 24.04 disk images from gem5 resources
  have it in `/usr/local/bin`.
- The `echo` lines print to the guest's serial console, which gem5 writes to
  `board.pc.com_1.device` in its output directory. Watch that file to see
  whether the guest reached the script and the ROI, which matters when a
  slow boot looks stuck. They sit outside the two hypercalls, so they are
  not part of the ROI.

**Better: mark the ROI inside the benchmark.** With the hypercalls in the
run script, the ROI also holds the shell starting the benchmark, the
benchmark's start-up and exit, and parts of the two `gem5-bridge` calls. It
is best to put the hypercalls in the benchmark's own code, where its actual
work starts and ends, as the NPB binaries in gem5 resources do: NPB IS
makes hypercall 4 just before its timed loop and hypercall 5 just after it.
Then the profile, the SimPoints and the estimate cover only that work.

With Claude's help this should not be hard for a SPEC benchmark:

- find where its work starts and ends;
- add the two calls there;
- rebuild it with gem5's `libm5.a`;
- remove the two `gem5-bridge` lines from the run script.

The
[`src/npb-24.04-imgs`](https://github.com/gem5/gem5-resources/tree/stable/src/npb-24.04-imgs)
recipe in gem5 resources shows how NPB does it:

- its hook file calls `map_m5_mem()` once, then `m5_hypercall_addr(4)` and
  `m5_hypercall_addr(5)`, the address-based calls that also work on KVM;
- its makefiles link `-lm5` with `-no-pie`.

The Ubuntu 24.04 images from gem5 resources already have `libm5.a` in
`/usr/local/lib` and gem5's headers in `/usr/local/include/gem5`.

The scripts take the run script with `--run-script`.

## Step 1: Collect basic block vectors

### 1.1 Take the ROI checkpoint

`scripts/01_take_roi_checkpoint.py` boots the guest, lets the run script
start, and saves one checkpoint at the moment the ROI begins:

```bash
$GEM5 -d m5out/roi-checkpoint scripts/01_take_roi_checkpoint.py \
    --disk-image /path/to/spec-2017.img \
    --run-script scripts/spec-run-script.sh \
    --checkpoint-dir checkpoints/roi
```

It boots on KVM by default. Add `--kvm-no-perf` if the host does not let
gem5 use perf counters, or `--boot-cpu atomic` on a host without KVM. Booting
on the atomic CPU works anywhere but is much slower; add
`--kernel-arg no_systemd=true` to skip systemd, which the Ubuntu 24.04 images
from gem5 resources support. When the guest reaches
`gem5-bridge hypercall 4`, the script's `WORK_BEGIN` handler writes the
checkpoint to `checkpoints/roi` and ends the simulation. If the run script
finishes without reaching the hypercall, the script says so and writes no
checkpoint. To follow the boot, watch
`m5out/roi-checkpoint/board.pc.com_1.device`: the kernel log, then
`Kernel booted, In gem5 init...`, then the run script's `started` and
`ROI begins` lines.

Every later gem5 run starts from this one checkpoint instead of booting
again: steps 1.2, 3 and 4.3 restore it, and step 4.1 restores checkpoints
taken from it. The BBV run (step 1.2) counts instructions from this point,
and the checkpoint run (step 3) stops at instruction counts taken from those
BBVs, so both must start from exactly the same state and execute exactly the
same instructions.
Booting again for each run would not give you that: a KVM boot depends on the
host's timing, so each boot reaches the ROI in a slightly different state,
and the counts would no longer line up.

For the same reason, the parts of the system that a checkpoint stores stay
fixed in `scripts/common.py` for every run: one core, 3 GiB of memory, the
kernel and its command line, and the disk image. The CPU model and the caches
are not stored, so later steps change them.

### 1.2 Profile the ROI with the SimPoint probe

`scripts/02_collect_bbv.py` restores the ROI checkpoint on the atomic CPU,
attaches gem5's SimPoint probe, and runs to the end of the ROI:

```bash
$GEM5 -d m5out/bbv scripts/02_collect_bbv.py \
    --disk-image /path/to/spec-2017.img \
    --run-script scripts/spec-run-script.sh \
    --checkpoint-dir checkpoints/roi \
    --interval 100000000
```

Give it the same workload options as in step 1.1. When the guest reaches
`gem5-bridge hypercall 5`, the script prints the length of the ROI, dumps the
statistics and stops:

```
ROI ends at tick 1752400954557 after 964579674 instructions.
```

The probe is the `SimPoint` probe listener
(`src/cpu/simple/probes/SimPoint.py` in gem5), which `addSimPointProbe()`
attaches to a core. It watches every instruction the core commits, cuts the
run into intervals of `--interval` instructions, and writes one line per
interval to `simpoint.bb.gz` in the output directory:

```
T:1:1 :2:4 :3:46 :4:1 :5:13 :6:15 :7:5 :8:2 ...
```

Each `:id:count` pair is one basic block: `id` numbers the blocks in the
order the probe first met them, and `count` is the number of instructions
the interval executed in that block. This is the input format of the
SimPoint tool.

Four things to know about the probe:

- **It needs the atomic CPU.** It listens to a probe point that only
  AtomicSimpleCPU provides, so neither KVM nor the detailed CPU models can
  profile.
- **It counts every committed instruction on the core, in user and kernel
  mode alike.** In the validation runs, 0.28% (NPB IS) and 0.93% (`gzip`) of
  the ROI's instructions ran in kernel mode; compare `numUserInsts` with
  `numInsts` in `stats.txt`. The instruction counts in step 3 include them
  in the same way, which is why they agree with the BBVs.
- **Interval boundaries are approximate.** An interval closes at the first
  control instruction after it reaches `--interval` instructions, and the
  overshoot is taken off the next interval. Interval *i* therefore starts
  about *i* × interval instructions into the ROI. The instructions after the
  last full interval are not written.
- **It is slow.** The whole ROI runs on the atomic CPU, at about 3 million
  instructions per second in the validation runs (on an Apple M5 laptop). At
  that rate 10<sup>12</sup> instructions take about four days, so profile
  each benchmark once and keep `simpoint.bb.gz`.

## Step 2: Pick SimPoints with the SimPoint tool

Build SimPoint 3.2 from
[AmpereComputing/simpoint](https://github.com/AmpereComputing/simpoint): the
SimPoint 3.2 sources from UC San Diego, with one change that lets them
compile with current compilers.

```bash
git clone https://github.com/AmpereComputing/simpoint.git
make -C simpoint simpoint      # builds simpoint/bin/simpoint
```

SimPoint has its own license (see its `README.txt`): you may use and change
it for educational, non-profit and industry research purposes, but you may
not include it in a commercial product.

Run it on the BBV file from step 1.2:

```bash
scripts/03_run_simpoint.sh simpoint/bin/simpoint m5out/bbv/simpoint.bb.gz simpoints 50
```

The last argument is maxK. The script runs this command and saves its log as
`simpoints/simpoint.log`:

```bash
simpoint/bin/simpoint -loadFVFile m5out/bbv/simpoint.bb.gz -inputVectorsGzipped \
    -maxK 50 \
    -saveSimpoints simpoints/results.simpoints \
    -saveSimpointWeights simpoints/results.weights
```

`-inputVectorsGzipped` is there because gem5 writes the BBV file gzipped
(SimPoint then needs `gzip` on the `PATH`).

What SimPoint does with it: it projects every BBV onto 15 random dimensions,
then runs k-means for a binary search of k values between 1 and maxK, five
times per k from different random starts. It scores each clustering with the
Bayesian information criterion (BIC) and keeps the smallest k whose score is
at least 90% of the way from the worst score to the best. In each cluster,
the interval closest to the cluster's center becomes that cluster's
SimPoint, and the cluster's share of all intervals becomes its weight. For
the validation's 964 intervals this took under half a second and kept k = 20.

It writes two files. `results.simpoints` has one line per SimPoint: the
interval index (counting from 0) and the cluster number.

```
710 0
502 1
872 2
...
```

`results.weights` has the weight of each cluster, in the same order:

```
0.0383817 0
0.00829876 1
0.109959 2
...
```

So interval 710 starts about 710 × interval instructions into the ROI and
stands for cluster 0, which holds 3.8% of all intervals. The weights add up
to 1, since every interval is in one of the clusters. The script also prints
the SimPoints sorted by interval, with their weights:

```
SimPoint picked 20 SimPoints; the log is in simpoints/simpoint.log.
interval index, cluster, weight:
         0   18  0.0052
         3   10  0.0021
        25   16  0.0239
...
```

Two cautions:

- The picks depend on the SimPoint binary. Built on the validation machine,
  it picked different intervals for its own bundled sample than the output
  that ships with it. Build it once and use that binary for a whole study,
  and keep `results.simpoints`, `results.weights` and `simpoint.log` with
  your results.
- If maxK is not well below the number of intervals, SimPoint can return
  every interval as a SimPoint (see
  [Choosing the interval, warmup and maxK](#choosing-the-interval-warmup-and-maxk)).

## Step 3: Take a checkpoint at each SimPoint

### 3.1 From a SimPoint index to an instruction count

A SimPoint is an interval index, and its checkpoint goes one warmup before
the interval starts:

```
start = index × interval − warmup
```

For example, with an interval and a warmup of 1 million instructions, the
SimPoint at interval 3 starts at instruction 2,000,000 of the ROI. Step 4
restores that checkpoint, runs 1 million instructions of warmup, and then
measures interval 3.

`scripts/04_take_simpoint_checkpoints.py` reads the SimPoint files with
gem5's `SimpointDirectoryResource`, which sorts the SimPoints by interval and
computes these starts. When a SimPoint lies less than one warmup into the ROI,
its warmup shrinks to what is there and it starts at instruction 0; in the
validation, the SimPoint at interval 0 had no warmup at all. A SimPoint that
starts at instruction 0 starts exactly at the ROI checkpoint.

```bash
$GEM5 -d m5out/simpoint-checkpoints scripts/04_take_simpoint_checkpoints.py \
    --disk-image /path/to/spec-2017.img \
    --run-script scripts/spec-run-script.sh \
    --checkpoint-dir checkpoints/roi \
    --simpoints-dir simpoints \
    --interval 100000000 --warmup 100000000 \
    --output-dir checkpoints/simpoints
```

The script restores the ROI checkpoint on the atomic CPU, stops at each start
in turn, and saves `checkpoints/simpoints/cpt.SimPoint<i>`, where SimPoint
`i` is the `i`-th SimPoint in order of where it lies in the ROI. It also
writes `checkpoints/simpoints/simpoints.json`, which lists the interval,
weight, start, warmup and checkpoint of every SimPoint; step 4 reads it.
`--stop` chooses how the script stops at an instruction count, as described
in the next two sections.

### 3.2 Option A: the global instruction tracker

gem5 has two probe objects for this, in `src/cpu/probes/InstTracker.py`:

- `GlobalInstTracker` holds a counter and a set of thresholds
  (`inst_thresholds`).
- `LocalInstTracker` attaches to one core, listens to that core's
  `RetiredInsts` probe point, and adds every instruction the core commits to
  the global counter.

When the counter reaches a threshold, the simulation exits with a `MAX_INSTS`
exit event. The counter is not reset at a threshold, so the thresholds are
counts since the trackers began listening. With `--stop global-tracker` (the
default) the script sets them up like this:

```python
tracker = GlobalInstTracker(inst_thresholds=stops)
for each_core in board.get_processor().get_cores():
    each_core.core.probeListener = LocalInstTracker(
        global_inst_tracker=tracker, start_listening=True
    )

simulator = Simulator(
    board=board, on_exit_event={ExitEvent.MAX_INSTS: save_at_each_stop()}
)
```

`save_at_each_stop()` is a generator: at each `MAX_INSTS` exit it saves the
checkpoint of every SimPoint that starts at that count and lets the
simulation go on, until the last one.

What the trackers give you:

- **Counting starts and stops when you say.** With `start_listening=True` the
  trackers count from the start of the run, which here is the ROI
  checkpoint, so the counts are counts into the ROI, like the BBVs. With
  `start_listening=False` nothing is counted until you call
  `startListening()` on every local tracker, for example from a
  `WorkBeginExitHandler` when the ROI begins, and `stopListening()` pauses
  the count. In full system, where the guest runs a lot before the ROI, this
  is how you count only from the beginning of the work.
- **One count for the whole system**: the sum over every core that has a
  local tracker.
- **Control from the script**: `getCounter()`, `resetCounter()`,
  `addThreshold()`, `getThresholds()` and `resetThresholds()`. gem5's
  `configs/example/gem5_library/x86-global-inst-tracker.py` shows them.
- **Exact stops.** The threshold fires as the counted instruction commits.
  In the validation, the counter read exactly 2,000,000, 24,000,000, and so
  on at each of the 19 stops of the `gzip` ROI. Running on from an NPB
  checkpoint to the end of the ROI confirmed that the checkpoint was exactly
  1,000,000 instructions in.

Two limits:

- **It cannot stop at instruction 0.** The counter is incremented before it
  is compared, so a threshold of 0 never fires. The script saves the
  checkpoint of a SimPoint that starts at 0 by copying the ROI checkpoint.
- **It needs a CPU model that fires `RetiredInsts`.** The atomic, timing,
  minor and O3 CPUs do. KVM does not.

### 3.3 Option B: registering the instructions on the core

With `--stop set-simpoint`, the script registers the starts on the first core
and lets that core stop the simulation:

```python
board.get_processor().get_cores()[0]._set_simpoint(
    starts, board_initialized=False
)

simulator = Simulator(
    board=board,
    on_exit_event={
        ExitEvent.SIMPOINT_BEGIN: simpoints_save_checkpoint_generator(
            args.output_dir, simpoint
        )
    },
)
```

(The script wraps the generator to print each stop.)

`_set_simpoint()` is the core method that the stdlib's
`set_se_simpoint_workload()` uses for SE runs. Called before the simulation
starts, it sets the core's `simpoint_start_insts` parameter (sorted, without
duplicates). The CPU then schedules one instruction-count event per start on
the core's first thread, counted from when the CPU starts, which here is the
restored ROI checkpoint. Each event stops the simulation with a
`SIMPOINT_BEGIN` exit. gem5's `simpoints_save_checkpoint_generator` saves
`cpt.SimPoint<i>` at each stop (several, when SimPoints share a start) and
ends the run after the last one.

`Simulator.schedule_simpoint()` is meant to be the public way to do this,
but in gem5 v26.0 it raises
`AttributeError: object 'SimpleCore' has no attribute 'set_simpoint'`.

What registering on the core gives you:

- **Simple code**: no extra SimObjects, and gem5's own checkpoint
  generator.
- **A start of 0 works**: it fires on the first cycle. On the atomic CPU the
  stop is then one instruction in, like every stop (see below).

Its limits:

- **It counts one thread of one core.** That is enough for this guide's
  single core, but it is not a count for the whole system.
- **It cannot be paused.** It counts from the moment the starts are
  registered: before the run, that is from the restored checkpoint, and
  during a run, `_set_simpoint(starts, board_initialized=True)` counts from
  the thread's current instruction. Every instruction after that counts.
- **On the atomic CPU it stops one instruction late.** When the stop fires
  at the start of a cycle, the CPU still executes that cycle's instruction
  before the simulation exits. In the validation, the checkpoint for the
  start at 1,000,000 was 1,000,001 instructions into the ROI.

### 3.4 Which one to use

| | Global tracker (`--stop global-tracker`) | On the core (`--stop set-simpoint`) |
|---|---|---|
| What it counts | all cores that have a local tracker, summed | the first thread of the first core |
| From when | while the trackers are listening; you start and stop them | from when the starts are registered; no pause |
| Exit event | `MAX_INSTS` | `SIMPOINT_BEGIN` |
| A start of 0 | never fires; the script copies the ROI checkpoint | fires on the first cycle |
| Where it stops on the atomic CPU | exactly at the count | one instruction after the count |

Both count every committed instruction, kernel mode included, just as the
BBV probe does, so either one lines up with the BBVs. In the validation, both
saved checkpoints for the same 20 SimPoints of the `gzip` ROI, and at each of
the 19 stops they share, the core's stop came one cycle after the tracker's.
On NPB, running both checkpoints of one SimPoint on to the end of the ROI
showed them exactly one instruction apart. At 100-million-instruction
intervals, one instruction makes no difference to the result.

In this guide's flow (one core, counting from the ROI checkpoint) both work.
The global tracker is the more flexible one in full system: because its
listening can be started and stopped, it can count only the work region,
even in a run that did not start at the ROI, and it stops exactly at the
count. Registering on the core is the shorter code when the run starts at the
ROI checkpoint anyway.

## Step 4: Restore the SimPoints and combine the results

### 4.1 Restore one SimPoint and measure it

`scripts/05_restore_and_measure.py` restores one SimPoint checkpoint on the
detailed system (the same board, now with the O3 CPU and private L1 and L2
caches) and measures one interval:

```bash
$GEM5 -d m5out/measure/simpoint-0 scripts/05_restore_and_measure.py \
    --disk-image /path/to/spec-2017.img \
    --run-script scripts/spec-run-script.sh \
    --simpoint-checkpoints checkpoints/simpoints --simpoint 0
```

Run it once per SimPoint, each with its own output directory,
`m5out/measure/simpoint-<i>`. The runs do not depend on each other, so run
them in parallel. Each run:

1. restores `cpt.SimPoint<i>`, with empty caches and predictors;
2. simulates the SimPoint's warmup, read from `simpoints.json`;
3. resets the statistics;
4. simulates one interval;
5. dumps the statistics and stops, so `stats.txt` describes that interval
   alone.

Both stops use `Simulator.schedule_max_insts()`, which counts instructions
on the core from when it is called: the warmup from the restored checkpoint,
the interval from the end of the warmup. O3 commits several instructions
per cycle, so a measured interval can run a few instructions long
(1,000,004 instead of 1,000,000 in the validation); step 4.2 uses the counts
that were measured. A SimPoint at the very start of the ROI has no warmup and
is measured with cold caches: in the `gzip` validation, the SimPoint at
interval 0 measured a CPI of 1.62, against 0.39 to 1.07 for the other 19.

`--cpu minor` or `--cpu timing` measures with another CPU model. To model
your own system, change the detailed board in `scripts/common.py`
(`build_board(..., with_caches=True)`): the CPU, caches and memory timing can
change freely, as long as there is still one core and 3 GiB of memory, which
the checkpoints hold.

Each run simulates warmup + interval instructions in detail. O3 ran at about
0.7 million instructions per second in the validation, so with 100 million
instructions of each, a SimPoint takes about five minutes.

### 4.2 Weight the per-SimPoint results

```bash
python3 scripts/06_weight_results.py checkpoints/simpoints/simpoints.json m5out/measure
```

This is plain Python 3, not a gem5 script. It reads
`m5out/measure/simpoint-<i>/stats.txt` for every SimPoint, computes each
SimPoint's CPI (the core's cycles divided by the instructions), and combines
them with the weights from `simpoints.json`:

```
estimated CPI = sum over the SimPoints of (weight × CPI of the SimPoint)
```

From the NPB example:

```
SimPoint interval   weight instructions       cycles      CPI
       0        1   0.4000      1000004       789186   0.7892
       1        5   0.1333      1000000       502630   0.5026
       2       10   0.2000      1000000       559365   0.5594
       3       11   0.2667      1000000       558178   0.5582

Estimated CPI of the ROI: 0.6434 (IPC 1.5542)
```

Weighting the CPI is right because each SimPoint stands for the intervals of
its cluster, and every interval has the same number of instructions: the
weights split the ROI's instructions, and the ROI's cycles are the sum of
each part's instructions times its CPI. So average CPI, not IPC; the ROI's
IPC is 1 / estimated CPI. Any other statistic per instruction, such as cache
misses per thousand instructions, combines the same way.

### 4.3 Check the estimate against a full run

For a short ROI you can check the estimate directly: simulate the whole ROI on
the same detailed system and compare. `scripts/07_measure_whole_roi.py`
restores the ROI checkpoint on that system and runs to the end of the ROI:

```bash
$GEM5 -d m5out/baseline scripts/07_measure_whole_roi.py \
    --disk-image /path/to/spec-2017.img \
    --run-script scripts/spec-run-script.sh \
    --checkpoint-dir checkpoints/roi
```

Then give its `stats.txt` to the weighting script:

```bash
python3 scripts/06_weight_results.py checkpoints/simpoints/simpoints.json m5out/measure \
    --baseline m5out/baseline/stats.txt
```

which adds the baseline and the error of the estimate:

```
Estimated CPI of the ROI: 0.7071 (IPC 1.4142)
Baseline CPI of the ROI:  0.6377 (IPC 1.5682), from 963602489 instructions
Error of the estimate:    +10.89%
```

The check simulates every instruction of the ROI in detail, which is what
SimPoints exist to avoid, so it is practical only for a short ROI, such as a
test input or the NPB example.

The validation runs used an interval and a warmup of 1 million instructions:

| ROI | SimPoints | Estimated CPI | Whole-ROI CPI | Error | Instructions simulated in detail |
|---|---|---|---|---|---|
| NPB IS class S | 4 of 15 intervals | 0.6434 | 0.6151 | +4.6% | 8 million instead of 15.8 million |
| `gzip` | 20 of 964 intervals | 0.7071 | 0.6377 | +10.9% | 39 million instead of 964 million |

For `gzip`, the 20 SimPoint runs took under a minute in all (five at a time),
and the whole-ROI run took 28 minutes. Both estimates are high, by 4.6% and
10.9%.
These intervals are a hundredth of the usual 100 million instructions, and
each SimPoint had only 1 million instructions of warmup to fill a 1 MiB L2
cache and the branch predictors, so each measurement started partly cold.
Re-measuring the three heaviest `gzip` SimPoints after 15 to 33 million
instructions of warmup lowered their CPI by 5.7%, 2.1% and 0.2%, so part of
the error is this cold start. The rest has other sources, such as how well
each cluster's SimPoint stands for its cluster, which this check does not
separate. Run the check on a short input of your own setup before you rely on
the estimates.

## Try the flow without SPEC: NPB IS from gem5 resources

The whole flow runs without SPEC on the gem5 resources workload
`x86-ubuntu-24.04-npb-is-s`: NPB IS, class S, on Ubuntu 24.04. gem5 downloads
its kernel and disk image the first time. The NPB binaries mark their own ROI
with hypercalls 4 and 5, and `scripts/npb-run-script.sh` runs the workload's
command with progress lines added. The ROI is only about 16 million
instructions, so this example uses an interval and a warmup of 1 million
instructions and `-maxK 5`. It is how this guide was validated, and a good
first run on a new setup. On an x86 host with KVM, drop `--boot-cpu atomic`.

```bash
NPB=(--workload x86-ubuntu-24.04-npb-is-s --workload-version 3.0.0
     --run-script scripts/npb-run-script.sh --kernel-arg no_systemd=true)

# Step 1.1: boot and checkpoint the ROI (10 to 14 minutes on the atomic CPU).
$GEM5 -d m5out/roi-checkpoint scripts/01_take_roi_checkpoint.py "${NPB[@]}" \
    --boot-cpu atomic --checkpoint-dir checkpoints/roi

# Step 1.2: profile the ROI.
$GEM5 -d m5out/bbv scripts/02_collect_bbv.py "${NPB[@]}" \
    --checkpoint-dir checkpoints/roi --interval 1000000

# Step 2: build SimPoint and pick the SimPoints.
git clone https://github.com/AmpereComputing/simpoint.git
make -C simpoint simpoint
scripts/03_run_simpoint.sh simpoint/bin/simpoint m5out/bbv/simpoint.bb.gz simpoints 5

# Step 3: checkpoint every SimPoint.
$GEM5 -d m5out/simpoint-checkpoints scripts/04_take_simpoint_checkpoints.py \
    "${NPB[@]}" --checkpoint-dir checkpoints/roi --simpoints-dir simpoints \
    --interval 1000000 --warmup 1000000 --output-dir checkpoints/simpoints

# Step 4.1: measure every SimPoint, in parallel.
n=$(python3 -c 'import json; print(len(json.load(open("checkpoints/simpoints/simpoints.json"))["simpoints"]))')
for i in $(seq 0 $((n - 1))); do
    $GEM5 -d m5out/measure/simpoint-$i scripts/05_restore_and_measure.py \
        "${NPB[@]}" --simpoint-checkpoints checkpoints/simpoints --simpoint $i \
        > m5out/measure-$i.log 2>&1 &
done
wait

# Step 4.3: simulate the whole ROI as a baseline; step 4.2 with the check.
$GEM5 -d m5out/baseline scripts/07_measure_whole_roi.py "${NPB[@]}" \
    --checkpoint-dir checkpoints/roi
python3 scripts/06_weight_results.py checkpoints/simpoints/simpoints.json \
    m5out/measure --baseline m5out/baseline/stats.txt
```

In the validation, these commands took 12 minutes on an Apple M5 laptop, 10
of them for the boot on the atomic CPU. The main lines of their output:

```
ROI begins at tick 1165676603553. Saving the ROI checkpoint to checkpoints/roi
ROI ends at tick 1175290629570 after 15844340 instructions.
SimPoint picked 4 SimPoints; the log is in simpoints/simpoint.log.
Saved 4 SimPoint checkpoints in checkpoints/simpoints.
SimPoint interval   weight instructions       cycles      CPI
       0        1   0.4000      1000004       789186   0.7892
       1        5   0.1333      1000000       502630   0.5026
       2       10   0.2000      1000000       559365   0.5594
       3       11   0.2667      1000000       558178   0.5582

Estimated CPI of the ROI: 0.6434 (IPC 1.5542)
Baseline CPI of the ROI:  0.6151 (IPC 1.6257), from 15824625 instructions
Error of the estimate:    +4.60%
```

Your numbers can differ a little, because they depend on everything the guest
runs before the ROI, down to the bytes of the run script. An earlier
validation run with a slightly different run script got 3 SimPoints and an
error of +9.2%.

The guide was also validated through the `--disk-image` path that SPEC uses.
That run used the same disk image, which gem5 downloads to its resource
directory (`~/.cache/gem5` by default) as `x86-ubuntu-24.04-npb-img-5.0.0`,
and this stand-in for a SPEC run script:

```bash
echo "spec-style-run-script: started"
cd /home/gem5 || { echo "spec-style-run-script: cannot cd"; exit 1; }
export OMP_NUM_THREADS=1
echo "spec-style-run-script: ROI begins"
gem5-bridge hypercall 4
gzip -9 -c /usr/bin/bash > /tmp/bash.gz 2>> /tmp/gzip.err
gem5-bridge hypercall 5
echo "spec-style-run-script: ROI ended"
```

Its ROI ran 964,579,674 instructions (964 intervals). With `-maxK 50`,
SimPoint picked 20 SimPoints, and the estimate came within 10.9% of the
whole-ROI CPI (step 4.3). The `gzip` numbers in this guide come from that
run.

## Troubleshooting

- **The boot on the atomic CPU takes very long.** Add
  `--kernel-arg no_systemd=true`, which makes the Ubuntu 24.04 images from
  gem5 resources skip systemd, or boot on KVM. In the validation, booting
  the NPB image to its ROI without systemd took 10 to 14 minutes on the
  atomic CPU; with systemd, the boot was still in systemd after 17 minutes.
- **The boot looks stuck.** Read `board.pc.com_1.device` in the output
  directory: it is the guest's serial console. It shows the kernel log, then
  `Kernel booted, In gem5 init...`, then the run script's `echo` lines.
  Without systemd, `-bash: cannot set terminal process group (-1)` and
  `-bash: no job control in this shell` are normal.
- **"The simulation stopped before the ROI began"** (step 1.1): the guest
  finished the run script without making hypercall 4. Check that the script
  calls `gem5-bridge hypercall 4`, and look on the console for its
  `cannot cd` line.
- **"The simulation stopped before the ROI ended"** (steps 1.2 and 4.3):
  the guest never made hypercall 5. Check the end of the run script.
- **`TypeError: object of type 'method' has no len()`** (step 3): the warmup
  is 0. Give a warmup larger than 0; one interval is the usual choice.
- **`AttributeError: object 'SimpleCore' has no attribute 'set_simpoint'`**:
  something called `Simulator.schedule_simpoint()`, which fails in gem5
  v26.0. Use `--stop set-simpoint`, which calls the core's `_set_simpoint()`
  instead.
- **"No checkpoint for SimPoints [...]"** (step 3): the ROI ended before the
  simulation reached those SimPoints, usually because `--interval` differs
  from step 1.2.
- **SimPoint picked every interval** (step 2): maxK is not well below the
  number of intervals. Lower it, or profile with a shorter interval.
- **gem5 cannot boot on KVM.** If the build printed
  `Cannot enable KVM, host seems to lack KVM support`, the binary has no KVM
  support: build on an x86-64 Linux host with KVM, or boot with
  `--boot-cpu atomic`. If KVM fails because the host does not let gem5 use
  perf counters, add `--kvm-no-perf`.
- **The build went to an unexpected directory.** Run `scons` from the gem5
  directory; it resolves `build/X86` against the directory it starts in.

## References

- T. Sherwood, E. Perelman, G. Hamerly and B. Calder, "Automatically
  Characterizing Large Scale Program Behavior", ASPLOS 2002. The paper
  behind SimPoint.
- G. Hamerly, E. Perelman, J. Lau and B. Calder, "SimPoint 3.0: Faster and
  More Flexible Program Analysis". It ships with the SimPoint sources as
  `MOBS-05-SimPoint3.pdf`.
- The SimPoint 3.2 sources: <https://github.com/AmpereComputing/simpoint>.
- A. Limaye and T. Adegbija, "A Workload Characterization of the SPEC
  CPU2017 Benchmark Suite", ISPASS 2018, and their
  [list of SPEC CPU2017 command lines][spec-commands].
- A. Sabu, H. Patil, W. Heirman and T. E. Carlson, "LoopPoint:
  Checkpoint-driven Sampled Simulation for Multi-threaded Applications",
  HPCA 2022 ([PDF](https://alenks.github.io/pdf/looppoint_hpca2022.pdf)),
  and its tools: <https://github.com/nus-comparch/looppoint>.
- gem5: <https://www.gem5.org> and <https://github.com/gem5/gem5>, release
  v26.0.0.0.
- gem5 resources: <https://resources.gem5.org>, and the disk image recipes
  in <https://github.com/gem5/gem5-resources>.
- SPEC CPU2017: <https://www.spec.org/cpu2017/>.

## License

The scripts in this repository are under the BSD 3-Clause license, in
`LICENSE` (copyright 2026 Zhantong Qiu). SimPoint, SPEC CPU2017, gem5 and
gem5 resources come under their own licenses.

[spec-commands]: https://tosiron.com/papers/2018/SPEC2017_commands.pdf
