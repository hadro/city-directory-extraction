#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "vllm==0.30.0",
#   # NYU 2026-10-16: vllm 0.30.0 declares transformers>=5.10.4 (open upper bound) but its
#   # pixtral.py imports PixtralRotaryEmbedding, which transformers renamed to
#   # PixtralVisionRotaryEmbedding by 5.19. Unpinned, uv resolved 5.20.1 and the LightOnOCR
#   # architecture failed inspection before the engine started. 5.14.1 still has the old name.
#   "transformers==5.14.1",
#   "pillow==12.3.0",
# ]
# ///
"""
hpc/lightonocr_vllm.py with table output banned in decoding: vLLM's `bad_words` on "|" and
"<table", so the model cannot answer in Markdown or HTML table form. Everything else is that
runner, unchanged and imported, with the same dependency block (so uv on Torch reuses its
environment) and the same arguments; give it its own --tag so its answers sit beside the
first ones instead of replacing them.

    uv run hpc/lightonocr_vllm_notables.py <shard list> --temperature 0 --tag vllm-notables

WHY (PIPELINE #32 (b), LINE_ASSEMBLY_HANDOFF step 5c, 2026-10-25). On about 6% of tiles LightOn
answers as a table, and a cell can hold two entries (~740 more two-person lines across the
abbyy8-damaged tier than plain tiles hold) or get ", " between fields the print does not have
(40,242 there). Splitting cells on the laptop was ruled out; re-reading with tables banned is
the fix to test. Its first run is task 0 (the bench's 138 tiles with gold, and 188 screen
tiles; 11 bench tiles read as tables under vLLM), scored against gold beside the -vllm answers
(reocr_pair.py bench/score) before any table tile of a tier is re-read this way.

A separate file on purpose: lightonocr_vllm.py on Torch carries NYU's transformers pin, and the
tier re-reads run on it, so this test touches nothing they use.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
BANNED = ["|", "<table"]


def main() -> int:
    import vllm
    plain = vllm.SamplingParams

    def banned(*args, **kw):
        kw.setdefault("bad_words", BANNED)
        return plain(*args, **kw)

    # lightonocr_vllm.main imports SamplingParams from vllm when it runs, so it gets this one
    vllm.SamplingParams = banned
    print(f"table output banned: bad_words={BANNED}", flush=True)
    import lightonocr_vllm
    return lightonocr_vllm.main()


if __name__ == "__main__":
    sys.exit(main())
