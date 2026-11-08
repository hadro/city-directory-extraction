"""The app_file of the private test Space hadro/cde-finder-timing (space/README.md, "The test
Space"): log the hardware, run results/finder_timing.py at 2 threads and at DuckDB's default, then
start the real app. Copied into the Space as `start.py`, beside app.py, search.py, where.py,
find_address.py, finder_timing.py and the two Parquets. Not for the public Space: the timing adds
~70 s to every start (the copy on the Space on 2026-11-05 ran two queries at the default only).
"""
import os
import platform
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("RECORDS_PARQUET", str(HERE / "records.parquet"))

import spaces  # noqa: E402


@spaces.GPU
def _unused():
    """ZeroGPU stops a Space with no GPU function ("No @spaces.GPU function detected during
    startup"); this one is never called."""


def show(path):
    try:
        return Path(path).read_text().strip()
    except OSError as err:
        return f"({err.__class__.__name__})"


print("python", platform.python_version(), "| os.cpu_count", os.cpu_count(),
      "| affinity", len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else "?",
      "| cgroup cpu.max", show("/sys/fs/cgroup/cpu.max"),
      "| memory.max", show("/sys/fs/cgroup/memory.max"), flush=True)
cpuinfo = show("/proc/cpuinfo").splitlines()
print("cpu:", next((l.split(":", 1)[1].strip() for l in cpuinfo if l.startswith("model name")), "?"),
      "| meminfo:", " ".join(show("/proc/meminfo").splitlines()[:2]), flush=True)

import duckdb  # noqa: E402
print("duckdb", duckdb.__version__, "default threads",
      duckdb.connect().execute("SELECT current_setting('threads')").fetchone()[0], flush=True)

import finder_timing  # noqa: E402

QUERIES = ["155 Franklin", "166 Lefferts pl", "45 Fulton", "62 Euclid av", "1 Wall st", "100 5th av"]
for threads in (["--threads", "2"], []):
    t = time.time()
    print("== finder_timing", threads or "default threads", flush=True)
    finder_timing.main([os.environ["RECORDS_PARQUET"], *QUERIES, *threads])
    print(f"== done in {time.time() - t:.1f} s", flush=True)
    sys.stdout.flush()

import app  # noqa: E402

app.demo.launch(css=app.CSS, head=app.HEAD)
