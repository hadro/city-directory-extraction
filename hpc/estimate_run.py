#!/usr/bin/env python3
"""
Estimate VRAM, wall-clock, and (for rented GPUs) dollars for a city-directory fine-tune,
across model sizes / dataset sizes / GPUs. Stdlib only — runs anywhere, no deps.

    python3 hpc/estimate_run.py                      # the full scaling table
    python3 hpc/estimate_run.py --n 500000 --size 4B --gpu a100
    python3 hpc/estimate_run.py --measured 12.4      # re-anchor on YOUR smoke-run throughput

WHY THIS EXISTS: the project's cost estimates for the 2B/4B family were extrapolated by hand
("~5x the 0.8B") and drifted. This grounds them in the two things actually measured on this
workload (see docs/HANDOFF.md "Training speed") plus the one architectural fact that dominates
memory here — the 248k vocabulary.

EVERYTHING EXCEPT THE TWO MEASURED THROUGHPUTS IS AN ESTIMATE. The honest use of this script is
to run the smoke job, read the real samples/sec off its log, and pass it to --measured.
"""
from __future__ import annotations

import argparse

# ---- measured on THIS workload (0.8B, YAML target, batch 64, unpacked) ------------------------
# Source: docs/HANDOFF.md "Training speed — what we tried". These two numbers are real; the rest
# of this script scales off them.
MEASURED = {"a100": 21.1, "rtx-pro-6000": 31.4}   # samples/sec
PACKING_SPEEDUP = 1.20                            # measured ~20% on the smoke probe

# Qwen3.5 shapes, read from the cached configs. vocab_size is the load-bearing one.
VOCAB = 248_320
ARCH = {
    #        hidden  layers   total params (B)   weight GB @ bf16
    "0.8B": (1024,   24,      0.8),
    "2B":   (2048,   24,      2.2),
    "4B":   (2560,   36,      4.3),      # shape estimated — 4B config not cached locally
}

# GPU relative throughput vs a100 on THIS workload, VRAM (GB), precision, rented $/hr.
#
# The GPU set is NYU **Torch**'s (Greene was decommissioned 2026-01-30): 232x H200, 272x L40S,
# 60x H100, 172x A100, 16x RTX Pro 6000. Counts from the Torch spec sheet.
#
# Only the rtx-pro-6000 ratio is MEASURED (31.4/21.1 on our own workload — and Torch happens to
# have that exact card, so it is a direct anchor, not an extrapolation). The Hopper and L40S
# ratios are estimates, deliberately conservative: this workload runs on a slow torch-fallback
# kernel path and is launch-bound rather than FLOP-bound, so newer cards deliver much less than
# their spec-sheet multiple. L40S is additionally penalised for memory bandwidth (~864 GB/s vs
# the A100's ~2 TB/s) because the giant logits tensor makes this workload bandwidth-heavy.
GPUS = {
    "h200":         (2.0,  141, "bf16", None),    # ESTIMATE (spec ratio is higher; fallback-bound)
    "h100":         (1.8,   80, "bf16", None),    # ESTIMATE
    "rtx-pro-6000": (1.49,  96, "bf16", 2.75),    # MEASURED 31.4/21.1
    "a100":         (1.0,   80, "bf16", 2.50),    # MEASURED anchor (Torch A100 may be 40GB — verify)
    "l40s":         (0.65,  48, "bf16", None),    # ESTIMATE — bandwidth-limited here
}

SEQ_LEN = 512


def logits_gb(batch: int) -> float:
    """The dominant memory term, and the reason batch size — not model size — sets the VRAM wall.

    The loss/entropy path materialises a [batch, seq, vocab] tensor and upcasts it to fp32.
    With a 248k vocab that is enormous: at batch 64 the bf16 copy alone is 16 GB, and the fp32
    upcast is another 32 GB. Crucially this term is INDEPENDENT OF MODEL SIZE, which is why
    going 0.8B -> 4B costs far less VRAM than people expect.

    Counts one bf16 copy + one fp32 copy + ~0.5 for softmax intermediates.
    """
    elems = batch * SEQ_LEN * VOCAB
    return elems * (2 + 4 + 1) / 1e9


def weights_gb(size: str) -> float:
    """bf16 weights. Note Qwen3.5 is multimodal — the vision tower is LOADED even though
    exclude_modules keeps LoRA off it, so it occupies VRAM. Padded ~15% for that."""
    return ARCH[size][2] * 2 * 1.15


def activations_gb(size: str, batch: int) -> float:
    """Rough: hidden x layers x batch x seq, bf16, with a fudge for the hybrid attention path."""
    hidden, layers, _ = ARCH[size]
    return hidden * layers * batch * SEQ_LEN * 2 * 8 / 1e9


def vram_gb(size: str, batch: int) -> float:
    return weights_gb(size) + logits_gb(batch) + activations_gb(size, batch)


def compute_ratio(size: str) -> float:
    """Per-sample compute relative to 0.8B.

    Not just the parameter ratio: with a 248k vocab the embedding and lm_head are a large,
    slowly-growing share of the total, so a 2.75x parameter jump is less than a 2.75x compute
    jump. Split the model into (a) transformer body, which scales with hidden^2 * layers, and
    (b) the two vocab projections, which scale with hidden only.
    """
    def parts(s):
        hidden, layers, _ = ARCH[s]
        return 12 * hidden * hidden * layers, 2 * hidden * VOCAB
    b0, v0 = parts("0.8B")
    b, v = parts(size)
    return (b + v) / (b0 + v0)


def best_batch(size: str, gpu: str, cap: int = 64) -> int:
    """Largest power-of-two batch fitting in the VRAM budget.

    The 0.90 factor is CALIBRATED, not guessed: the proven config is 0.8B at batch 64 on an
    80 GB a100-large, which this model puts at ~72 GB. Anything tighter would reject a config
    we have actually run. Treat the output as +/-25% — transformers does not necessarily hold
    all three logits copies live at once, and the fallback kernels fragment unpredictably. The
    smoke job is the real test; if it OOMs, halve the batch and double grad-accum."""
    budget = GPUS[gpu][1] * 0.90
    b = cap
    while b > 1 and vram_gb(size, b) > budget:
        b //= 2
    return b


def estimate(size: str, gpu: str, n: int, epochs: float, packing: bool, measured: float | None):
    base = measured if measured else MEASURED["a100"] * GPUS[gpu][0]
    sps = base / compute_ratio(size) * (PACKING_SPEEDUP if packing else 1.0)
    batch = best_batch(size, gpu)
    # Below batch 64 (what the measurement used) throughput degrades — less work per kernel
    # launch in an already launch-bound fallback regime. Mild penalty, not proportional.
    if batch < 64:
        sps *= (batch / 64) ** 0.25
    hours = (n * epochs) / sps / 3600
    rate = GPUS[gpu][3]
    return dict(size=size, gpu=gpu, batch=batch, vram=vram_gb(size, batch), cap=GPUS[gpu][1],
                sps=sps, hours=hours, cost=(hours * rate if rate else None),
                precision=GPUS[gpu][2])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=0, help="training examples (default: table over 100k+500k)")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--size", choices=list(ARCH), default=None)
    ap.add_argument("--gpu", choices=list(GPUS), default=None)
    ap.add_argument("--no-packing", action="store_true")
    ap.add_argument("--measured", type=float, default=None,
                    help="samples/sec observed in YOUR smoke run — overrides the built-in anchor "
                         "(read it off the trainer's progress line)")
    ap.add_argument("--wall-limit", type=float, default=48.0,
                    help="cluster max wall-clock hours per job, for the chained-job count")
    args = ap.parse_args()

    sizes = [args.size] if args.size else list(ARCH)
    gpus = [args.gpu] if args.gpu else ["h200", "a100", "l40s", "rtx-pro-6000"]
    ns = [args.n] if args.n else [100_000, 500_000]
    packing = not args.no_packing

    print(f"\nQwen3.5 city-directory SFT — LoRA, YAML target, {args.epochs:g} epochs, "
          f"packing={'on' if packing else 'off'}, vocab={VOCAB:,}")
    if args.measured:
        print(f"anchored on YOUR measured {args.measured} samples/sec")
    else:
        print("anchored on measured 0.8B @ batch 64: a100 21.1 samp/s, rtx-pro-6000 31.4 samp/s")

    for n in ns:
        print(f"\n=== {n:,} examples x {args.epochs:g} epochs = {int(n*args.epochs):,} samples ===")
        print(f"{'model':6} {'gpu':14} {'prec':5} {'batch':>5} {'VRAM':>10} {'samp/s':>7} "
              f"{'hours':>7} {'jobs':>5} {'$ (rented)':>11}")
        print("-" * 82)
        for size in sizes:
            for gpu in gpus:
                e = estimate(size, gpu, n, args.epochs, packing, args.measured)
                jobs = max(1, -(-int(e["hours"]) // int(args.wall_limit)))
                cost = f"${e['cost']:,.0f}" if e["cost"] else "free (HPC)"
                print(f"{size:6} {gpu:14} {e['precision']:5} {e['batch']:>5} "
                      f"{e['vram']:>6.0f}/{e['cap']:<3.0f} {e['sps']:>7.1f} "
                      f"{e['hours']:>7.1f} {jobs:>5} {cost:>11}")

    print(f"\nnotes")
    print(f"  VRAM shown is at the chosen batch; the [batch x {SEQ_LEN} x {VOCAB:,}] logits tensor")
    print(f"  dominates and does NOT scale with model size — batch, not parameters, sets the wall.")
    print(f"  'jobs' = chained SLURM submissions needed at a {args.wall_limit:g}h wall-clock limit")
    print(f"  (hpc/50_chain_train.sh); requires --resume-from-checkpoint auto, already wired in.")
    print(f"  Rented $ uses HF Jobs list rates; HPC time is free but costs queue + calendar days.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
