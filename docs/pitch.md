# Unlocking City Directories for New York City and Beyond

Josh Hadro

2026-08-10

> **⚑ Editing note:** every `⚑ TODO (Josh)` blockquote in this document marks a place where I
> (Claude) either need your judgment or couldn't fill something in from the repo. Grep for `⚑` to
> find them all, and delete this note plus each marker before sending.

## Executive Summary

TLDR: In my spare time I've been [fine-tuning an open model](https://github.com/hadro/city-directory-extraction) to parse NYC city directories, and this work has strong potential to be useful anywhere that city directories were published from the 1780s to the 1930s -- but I've hit a wall where it's becoming prohibitively costly to keep doing as a hobby project.

The immediate next step is small and precisely costed: **~73 H200-hours on a university cluster, or ~$310 of rented GPU time**, to train and evaluate the full model family. With that, the project finishes on a short timeline and produces openly licensed models, CC0 datasets, and public domain–derived code that anyone can use or fine-tune further.

### Support being sought

Either of these -- direct computer or dollars in the form of Hugging Face credits -- unblocks the work. 

The first cost likely comes in the form of NYU administrative sponsorship:

**1. An NYU Torch HPC allocation (preferred).**
NYU's current research cluster is [Torch](https://services.rt.nyu.edu/docs/hpc/). Claude has already written and smoke-tested a self-contained SLURM bundle against Torch's actual constraints — `--constraint=h200` GPU requests, an Apptainer overlay to stay inside the 30K-inode `/home` quota, and fully pre-staged models and data so compute nodes never need outbound internet. It lives in [`hpc/`](https://github.com/hadro/city-directory-extraction/tree/main/hpc) and builds to a ~6 MB tarball.

The only thing missing is an allocation, which requires a sponsor in the HPC projects portal. **H200 access specifically is what matters:** on an H200 the largest run (4B parameters, 500K training examples, 3 epochs) is a *single ~42-hour job* that fits inside one 48-hour allocation. On A100 or L40S hardware the same run becomes a 3–4 link dependent-job chain spanning a week or more of calendar time.

| model | H200 (Torch) | A100 (Torch) | rented GPU |
|---|---|---|---|
| 0.8B | ~8 h | ~17 h | **$30** |
| 2B | ~23 h | ~54 h | **$99** |
| 4B | ~42 h | ~99 h | **$183** |
| **full family** | **~73 GPU-h** | ~170 GPU-h | **~$310** |

*500K examples × 3 epochs. The estimator behind this table ([`hpc/estimate_run.py`](https://github.com/hadro/city-directory-extraction/blob/main/hpc/estimate_run.py)) is calibrated against two runs I actually measured and reproduces both; the 2B and 4B rows are extrapolation until the first smoke job re-anchors them.*

**2. Funds for rented inference compute — ~$310, plus headroom for experiments.**
Most simply via Hugging Face credits, which is built to make exactly this easy. ~$280 of that ~$310 is the 2B and 4B runs; the 0.8B alone is ~$30. Some additional headroom for repeated small training runs would let me settle which training paths are most effective rather than guessing — see "Plan and milestones" below.

> **⚑ TODO (Josh):** if you want to name a specific dollar figure to ask for rather than the bare
> $310 floor, put it here. Something like "$1,500 covers the family plus ~15 exploratory 0.8B runs"
> is a much easier yes than an open range.

---

## The detailed pitch

With a few hours of GPU-accelerated computing power we can fine-tune an open-weight model (Qwen 3.5) with public domain data from open access NYC city directories. Then anyone can use that model to extract structured data from any city directory in the country. Small local history projects will be unlocked and city directory data will no longer be a niche domain of for-profit genealogy websites and academics who often fail to share back the data that serves as the core of their research interests.

This work very much follows in the footsteps of the work that Daniel Van Strien and William J.B. Mattingly have done with the "[Small models for GLAM](https://huggingface.co/small-models-for-glam)" Hugging Face organization.

> **⚑ TODO (Josh):** a short "who I am" paragraph belongs here, and its absence is the biggest
> remaining gap in the document. A reader who doesn't already know you has no basis to judge
> delivery risk. Two or three sentences on your background, plus the fact that five full
> data-composition cycles have already been trained and scored against an 18-volume regression
> panel, would cover it. Worth also saying plainly what spare-time pace means in practice — a
> funder would rather read "roughly a training cycle every two weeks" than infer it.

## Why is this useful?

Once we've done this work and posted the model to Hugging Face, anyone with basic python skills could run the OCR of a city directory through the model with the scripts provided, and get a CSV of structured data in return. Likewise, the better we document the process and the repository and disseminate the results, the easier it will be for others to use and reuse the core elements here.

Once a reliable, high quality model is available, all sorts of useful things become possible:

* Basic data crunching ("What were the most common professions in a given year?" "What were the most popular last names?")
* Historical and sociological research ("What were the most popular last names, and how did this change over the years with immigration and migration?" "How did population density change?" "What were the proportions of professions listed in a given city directory?" Etc.)
* Data visualizations (e.g., "what did common commutes in Cleveland look like in 1895?")
* Mapping activities (e.g., "Where were there clusters of certain professions?"; geocoding, alignment with historical maps, etc.)

## How does this fit with the GLAM-E Lab?

> The GLAM-E Lab works directly with GLAM institutions to develop open access solutions accessible to the wider community of Galleries, Libraries, Archives, and Museums.

The GLAM-E Lab is a joint initiative of the Engelberg Center on Innovation Law & Policy at NYU Law and the Centre for Science, Culture and the Law at the University of Exeter — which is why I'm bringing this here.

Developing a fine-tuned model for parsing city directories is beneficial cultural heritage work premised on openly licensed technologies and which uses public domain materials and data as inputs – all of which dovetail with the GLAM-E Lab messaging above.

Likewise, while many smart people at many institutions are working with tools and processes like the ones I'm proposing here to address local institution-specific problems and challenges, almost no one is solving problems like this and creating open tooling that addresses opportunities at the sector level. There is a lot of low-hanging fruit when it comes to small models that solve problems common to many if not most digital cultural heritage collections.

Training these models typically takes an investment greater than any individual or even individual institution is willing to make — but once trained, running them costs almost nothing, and anyone with a modern laptop can do it. There's an extremely compelling case for a "commons" of small, targeted cultural heritage models for scoped challenges.[^1] I don't know if the GLAM-E Lab is the "home" for work like this, but I think at this point in the maturity of GLAM AI applications, there's absolutely a role for the GLAM-E Lab to get in on the ground floor and promote open access and open licensing as the keys that unlock solutions for GLAM institutions sector-wide.

## Hypotheses

A note on metrics, since the targets below need one: the project's evaluation harness reports three numbers, and they differ a lot for the same model. **Macro-F1** averages per-field quality evenly, so rare fields count as much as common ones — it's the hardest and most honest single number. **Micro-F1** weights each field by how often it actually appears. **Whole-row exact match** requires all 8 fields to be simultaneously correct. The targets below are stated in macro-F1 unless noted.

### Hypothesis A

Using openly available digitized city directories, we can fine-tune a model that can capably parse the entries from any arbitrary volume into structured data at **0.90–0.95 macro-F1**.

* Sub-hypothesis: If this is not possible with a single fine-tuned model, then a small set of 2-4 era-specific models can accomplish the same thing by narrowing the data range.

#### Evaluation

Simple to do at the time of model training: I've already transcribed gold ground truth for many NYC city directories, and the evaluation harnesses for the small models I've already trained can be repurposed here.

### Hypothesis B

Given that there are ~450 city directories for New York City from the 1780s to the 1930s, representing many of the largest publishers which also published city directories using similar conventions and layouts for other cities around the country, this same model trained on all NYC city directories will capably work out of the box for nearly any arbitrary city directory from around the country from that same era at **0.80–0.85 macro-F1**.

* Sub-hypothesis: Even if the NYC fine-tuned model doesn't reach 0.80–0.85, it may be possible to further fine-tune the NYC model with a very small amount of data (a few hundred lines or less) and at very low cost (dozens of dollars).

#### Evaluation

Would need some additional ground-truth generation, but otherwise similarly simple to do at the time of model training given that the evaluation harnesses for the small models I've already trained can be repurposed here.

### Hypothesis C

If we work in public, making novel uses of public domain and open access materials, we can show others how to make use of the models and/or data we're making available, and potentially inspire them to do the same.

#### Evaluation

Likely more qualitative: aside from people blogging and explicitly citing our work as inspirations, which would obviously be ideal, perhaps there's a way to measure repo forks, or Hugging Face model downloads, or dataset downloads, etc. Social media "likes" and reposts are probably not a meaningfully strong signal here, but can probably at least be taken as plaudits for the approach.

## Current work and barriers

I've been working on fine-tuning the smallest available Qwen model, 0.8 billion parameters, on the ground truth I've generated. Five full data-composition cycles have been trained and scored against an 18-volume hand-labeled gold panel (1,169 lines, 1786–1933/34) that serves as the project's regression harness. The current model leads a Gemini 3.1-flash-lite baseline on all three aggregate measures:

| model | macro-F1 | micro-F1 | whole-row exact match |
|---|---|---|---|
| Gemini 3.1-flash-lite (prompt-primed baseline) | 0.790 | 0.844 | 58.0% |
| **qwen-v5 (ours)** | **0.826** | **0.875** | **61.5%** |

Two caveats matter more than that headline, and I'd rather state them than have someone find them in the repo:

1. **That's the *primed* Gemini bar.** An earlier version of this comparison scored Gemini against a stale labeling contract and showed us winning by a much wider margin. Re-priming Gemini with the current contract moved it +0.05 macro-F1 and erased most of the gap.
2. **We trained on the labeling contract; Gemini is zero-shot on it.** That's how each would actually run in a real pipeline, so it's a fair comparison of deployed systems — but it is not a claim about raw model capability. Part of the remaining lead is contract knowledge, which is precisely the point of fine-tuning.

In plain terms: the fine-tuned model gets all 8 fields simultaneously right on 61.5% of lines it has never seen, and scores 0.875 on the appearance-weighted per-field measure.

The fields:

```
name · is_business · spouse_name · race_designation · occupation_role · employer · address · home_address
```

The method so far is the takeaway, and it's cheap: every systematic gap the first full evaluation exposed — dropped ditto marks, collapsed second addresses, era-specific address forms, missing race designations — turned out to be a *training-data coverage* problem rather than a model-capacity problem, and every one was closed by fixing the synthetic data generator and retraining, with no change to model size or architecture. Occupation parsing went from 0.70 to 0.89 F1 that way.

Each training run at this small scale costs ~$7. But the most recent cycle showed diminishing returns, which is the wall. To push macro-F1 above 0.90, I need larger Qwen models trained on larger synthetic datasets — the ~$310 / ~73 H200-hour ask above. Repeated small trainings without worrying about cost would also let me establish which training paths are most effective rather than inferring it from single runs.

Everything I've done so far and all the data gathering and manual transcription for ground truth for a variety of city directories is available on GitHub in the ["city-directory-extraction" repository](https://github.com/hadro/city-directory-extraction).

## Plan and milestones

The work is deliberately sequenced so the cheap experiment answers the expensive question first.

**1. De-risking A/B — ~$15, or ~10 A100-hours.**
Train a 0.8B model on 250K synthetic examples against the current 100K baseline. This answers whether more training data helps *at all* before committing 170 GPU-hours to the larger family. If the answer is no, the diagnosis and the money both change, and we've spent $15 finding out.

**2. Family scale-up — ~73 H200-hours, or ~$310.**
Assuming (1) is positive: 0.8B, 2B, and 4B models at 500K examples × 3 epochs, each scored against the 18-volume regression panel. This is where Hypothesis A gets settled.

**3. Out-of-city evaluation — ground truth generation, minimal compute.**
Hand-label a small panel of non-NYC directories and score the best NYC model against it cold. This settles Hypothesis B, and if it comes in low, tests the cheap-additional-fine-tune sub-hypothesis.

**4. Release and documentation.**
Models and datasets to Hugging Face, the demo Space, a write-up of the method, and the catalog as a standalone reference resource.

> **⚑ TODO (Josh):** add rough calendar time per milestone. "Short timeframe" in the summary is
> doing a lot of unquantified work, and this is the natural place to make it concrete. Even
> "milestones 1–2 within a month of getting access, 3–4 over the following two months" is enough —
> it just needs to be honest about spare-time pace rather than optimistic.

## Proposed project outputs

* One (or more) fine-tuned Qwen 3.5 model(s) hosted with an open license on Hugging Face
* One (or more) CC0 licensed dataset(s) of roughly 500K synthetic training data city directory entries, generated from small samples of ground truth data, posted to Hugging Face
* **A public Hugging Face Space demo** — upload an image of any single city directory page, and the Space runs LLM OCR, pipes the result through the fine-tuned model, and returns that page as structured data. Scoped to single pages rather than whole volumes, this is very doable, and it's the most legible artifact of the project for anyone who won't run python themselves.
* A code repository on GitHub including the following all under an open license:
    * VLM-generated profiles of dozens of NYC city directories, with representative samples of every publisher and era combination
    * Manually generated ground truth for a representative sample of NYC city directories
    * scripts and helpers that generate the synthetic training data based on the ground truth data, evaluate model performance on ground truth data, and other functions as needed
    * A master list of 449 digitized NYC city directories spanning 1786–1967, scanned and made available by the Brooklyn Public Library (186 volumes), The New York Public Library (156), the Allen County Public Library Genealogy Center (78), Columbia University Libraries (27), and the Library of Congress (2)

> **⚑ TODO (Josh):** the catalog's actual span is 1786–1967, with 361 of the 449 volumes at or
> before 1930 — but README.md says "~1786–1925," so one of the two is wrong and it's worth settling
> before this goes out. (The contributing-institution counts above are verified against the
> Internet Archive metadata API and are correct.)

## Scope

I propose focusing first on a fine-tuned model that can parse the text of any NYC city directory into structured data.

There are 449 NYC city directories online, digitized by the Brooklyn Public Library, the New York Public Library, the Allen County Public Library, Columbia University Libraries, and the Library of Congress. This alone is a tremendously rich dataset that has to date never been brought together and released publicly -- while various projects here and there have touched on aspects of this, they either never expanded their scope, or more disappointingly, leveraged public domain data and resources without releasing them publicly.

It's possible that a single model won't be capable of usefully parsing all city directories from the 1780s to the 1930s, in which case plan B would be to break up the directories into segments based on era and publisher. In this case, all other elements remain the same, and the end release is more like 3 models than one single fine-tuned model for NYC city directories.

Meanwhile, if hypothesis B holds true, this gets us all or most of the way to a model that can parse any arbitrary city directory from anywhere in the US. If the quality isn't quite what we hope for other cities, it should be possible to do a slight fine-tune of our own fine-tuned model, which should work for any city directory use case. It should be very straightforward to publish a guide on how to do this, replete with code examples of exactly how to formulate the commands to run.

## Boring statements for clarity

* This is purely a personal project, fully outside the scope of my employment at the Library of Congress – it does not imply any formal affiliation with or connection to any Library of Congress projects, even if some of the city directories may be held among the Library of Congress digital collections
* I don't have strongly held views about where this stuff lives or how various partnerships are presented/represented, as long as the following remain true:
    * All public domain data remains public domain and openly available
    * Any original data or code derived from or used to parse public domain data remains openly licensed to the utmost extent possible
    * I can use and reuse code, data, models, and anything else resulting from this work in subsequent projects, regardless of whether they're continuations of a potential partnership or not

## Prior art

* [NYPL Labs Space/Time Directory](https://wayback.archive-it.org/23478/20241118143457/https://spacetime.nypl.org/)
* [Mapping Historical New York: A Digital Atlas](https://mappinghny.com/?) -- data not made available, as far as I can tell, but uses Space/Time Directory data
* [directoreadr](https://github.com/samwbell/directoreadr) - "Reads and parses business location data from scans of City Directory Yellow Pages" [pre-LLM era effort]
* [Small Models for GLAM](https://huggingface.co/small-models-for-glam)
* [Parsing 3.6 Million Historical Names with Small Models](https://wjbmattingly.com/blog/parsing-3-6-million-historical-names-with-small-models/) - May 3, 2026 By William Mattingly

## Further potential applications

* Business directories -- an enormous category, and a natural follow-on; in some ways, business directories are a more overlooked category than city directories, because they're less obvious fodder for genealogists and family historians
* Alignment of city directory data with historical maps (particularly [Sanborn maps](https://en.wikipedia.org/wiki/Sanborn_maps))

<!-- Footnotes themselves at the bottom. -->
## Notes

[^1]:
     Which is exactly the notion behind the "small models for GLAM" approach on Hugging Face
