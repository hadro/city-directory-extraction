# Unlocking City Directories for New York City and Beyond

Josh Hadro
2026-08-10


## Executive Summary

TLDR: In my spare time I've been [fine-tuning an open model](https://github.com/hadro/city-directory-extraction) to parse NYC city directories, and this work has strong potential to be useful anywhere that city directories were published from the 1780s to the 1920s -- but I've hit a wall where it's becoming prohibitively costly to keep doing as a hobby project.

The immediate next step is achievable in partnership: **~73 H200-hours on a university cluster, or ~$500 for rented GPU time**, to train and evaluate a full model family. With that, the project finishes on a short timeline and produces openly licensed models, CC0 datasets, and public domain–derived code that anyone can use or fine-tune further.


---


## The detailed pitch

With access to GPU-accelerated computing power I can finish fine-tuning an open-weight model (Qwen 3.5) with public domain data from open access NYC city directories. Then anyone can use that model to extract structured data from any city directory in the country. Small local history projects will be unlocked and city directory data will no longer be a niche domain of locked down genealogy websites and academics who often fail to share back the data that serves as the core of their research interests.

This work very much follows in the footsteps of the work that Daniel Van Strien and William J.B. Mattingly have done with the "[Small models for GLAM](https://huggingface.co/small-models-for-glam)" Hugging Face organization.


### Who am I, why me?

I’m a librarian and technologist who has been working at the intersection of technology, policy, and digital collections for nearly 20 years. The demonstration of useful and just plain fun things that can be done with open data and public domain collections has been at the heart of my professional work at the New York Public Library (specifically NYPL Labs), at the helm of the International Image Interoperability Framework (IIIF) Consortium, and in the Digital Strategy Directorate at the Library of Congress. I [wrote about the idea of “Manufacturing Impact“ for a talk at the Smithsonian in 2017](https://hadro.github.io/blog/manufacturing-impact/), and that framework still shapes how I think about the potential of digital collections.

In my spare time, I build open data utilities like the [Directory Pipeline](https://github.com/hadro/directory-pipeline) which lets me in turn build useful public digital scholarship interfaces. My most recent effort is [a data viewer for the Green Books and other related travel guides for Black motorists](https://hadro.github.io/green-books/all-volumes), synthesizing 45 volumes across seven publications spanning 1930 to 1966.

Meanwhile, city directories have always been close to my heart, and I recently created [an example viewer for the 1921 Tulsa City Directory](https://hadro.github.io/tulsa-city-directories/1921#about) which was published just months before the Tulsa Race Massacre that destroyed the Greenwood district. That was a one-off city directory effort, but working on that gave insight into the fact that city directories from all over follow a relatively narrow set of publishing conventions while holding countless stories of American population change and evolution.


## The support I’m seeking

Either direct compute or funding in the form of Hugging Face credits would unblock the work.

The first is probably best understood as a matter of NYU administrative sponsorship:

**1. An NYU Torch HPC allocation (preferred).** NYU's current research cluster is [Torch](https://services.rt.nyu.edu/docs/hpc/). 
I’ve already asked Claude to write a self-contained SLURM bundle against Torch's documented constraints — `--constraint=h200` GPU requests, an Apptainer overlay to stay inside the 30K-inode `/home` quota, and fully pre-staged models and data so compute nodes never need outbound internet. It lives in <code>[hpc/](https://github.com/hadro/city-directory-extraction/tree/main/hpc)</code> in my existing “city-directory-extraction” repository, which includes a smoke job to validate against the real cluster on day one and in all builds to a ~6 MB tarball.

The only thing missing is an allocation, which requires a sponsor in the HPC projects portal. **H200 access specifically is what matters:** on an H200 the largest run (4B parameters, 500K training examples, 3 epochs) is a *single ~42-hour job* that fits inside one 48-hour allocation. On A100 or L40S hardware the same run becomes a 3–4 link dependent-job chain spanning a week or more of calendar time.


<table>
  <tr>
   <td><strong>model</strong>
   </td>
   <td><strong>H200 (Torch)</strong>
   </td>
   <td><strong>A100 (Torch)</strong>
   </td>
   <td><strong>rented GPU</strong>
   </td>
  </tr>
  <tr>
   <td>0.8B
   </td>
   <td>~8 h
   </td>
   <td>~17 h
   </td>
   <td><strong>$30</strong>
   </td>
  </tr>
  <tr>
   <td>2B
   </td>
   <td>~23 h
   </td>
   <td>~54 h
   </td>
   <td><strong>$99</strong>
   </td>
  </tr>
  <tr>
   <td>4B
   </td>
   <td>~42 h
   </td>
   <td>~99 h
   </td>
   <td><strong>$183</strong>
   </td>
  </tr>
  <tr>
   <td><strong>full family</strong>
   </td>
   <td><strong>~73 GPU-h</strong>
   </td>
   <td>~170 GPU-h
   </td>
   <td><strong>~$310</strong>
   </td>
  </tr>
</table>


*500K examples × 3 epochs. The estimator behind this table (<code>[hpc/estimate_run.py](https://github.com/hadro/city-directory-extraction/blob/main/hpc/estimate_run.py)</code>) is calibrated against two runs I actually measured and reproduces both; the 2B and 4B rows are extrapolated until the first smoke job re-anchors them.*

The other path accomplishes the same thing, but makes use of Hugging Face infrastructure: 

**2. Funds for rented inference compute — ~$500, including headroom for experiments.** The simplest route is Hugging Face credits, for a platofrm which is built to make this kind of thing straight-forward. ~$280 of this is the 2B and 4B runs; the 0.8B alone is ~$30. Some additional headroom for repeated small training runs would let me settle which training paths are most effective rather than guessing — see "Plan and milestones" below.


## Why is this useful?

Once we've done this work and posted the model to Hugging Face, anyone with basic python skills (or even someone with no python skills but with an LLM assistant like Claude or ChatGPT) could run the OCR of a city directory through the model with the scripts provided, and get a CSV of structured data in return. Likewise, the better we document the process and the repository and disseminate the results, the easier it will be for others to use and reuse the core elements here.

Once a reliable, high quality model is available, all sorts of useful things become possible:



* Basic data crunching ("What were the most common professions in a given year?" "What were the most popular last names?")
* Historical and sociological research ("What were the most popular last names, and how did this change over the years with immigration and migration?" "How did population density change?" "What were the proportions of professions listed in a given city directory?" Etc.)
* Data visualizations (e.g., "what did common commutes in Cleveland look like in 1895?")
* Mapping activities (e.g., "Where were there clusters of certain professions?"; geocoding, alignment with historical maps, etc.)


## How does this fit with the GLAM-E Lab?

From the website: “The GLAM-E Lab works directly with GLAM institutions to develop open access solutions accessible to the wider community of Galleries, Libraries, Archives, and Museums.”

Developing a fine-tuned model for parsing city directories is beneficial cultural heritage work premised on openly licensed technologies and which uses public domain materials and data as inputs – all of which dovetail with the GLAM-E Lab messaging above.

Likewise, while many smart people at many institutions are working with tools and processes like the ones I'm proposing here to address local institution-specific problems and challenges, almost no one is solving problems like this and creating open tooling that addresses opportunities at the sector level. There is a lot of low-hanging fruit when it comes to small models that solve problems common to many if not most digital cultural heritage collections.

Training these models typically takes an investment greater than any individual or even individual institution is likely to make — but once trained, running them costs almost nothing, and anyone with a modern laptop can do it. There's an extremely compelling case for a "commons" of small, targeted cultural heritage models for scoped challenges.[^1] I don't know if the GLAM-E Lab is the long-term "home" for commons work like this, but I think at this point in the maturity of GLAM AI applications, there's absolutely a role for the GLAM-E Lab to get in on the ground floor and promote open access and open licensing as the keys that unlock solutions for GLAM institutions sector-wide.


## Formal hypotheses


### Hypothesis A

Using openly available digitized city directories, we can fine-tune a model that can capably parse the entries from any arbitrary volume into structured data at **0.90–0.95 macro-F1**[^2].



* Sub-hypothesis: If this is not possible with a single fine-tuned model, then a small set of 2-4 era-specific models can accomplish the same thing by narrowing the data range.


#### Evaluation

Simple to do at the time of model training: I've already transcribed gold ground truth for many NYC city directories, and the evaluation harnesses for the small models I've already trained can be repurposed here.


### Hypothesis B

Given that there are ~330 city directories for New York City from the 1780s to the 1920s, representing many of the largest publishers which also published city directories using similar conventions and layouts for other cities around the country, this same model trained on all NYC city directories will capably work out of the box for nearly any arbitrary city directory from around the country from that same era at **0.80–0.85 macro-F1**.



* Sub-hypothesis: Even if the NYC fine-tuned model doesn't reach 0.80–0.85, it may be possible to further fine-tune the NYC model with a very small amount of data (a few hundred lines or less) and at very low cost (dozens of dollars).


#### Evaluation

Would need some additional ground-truth generation, but otherwise similarly simple to do at the time of model training given that the evaluation harnesses for the small models I've already trained can be repurposed here.


### Hypothesis C

If we work in public, making novel uses of public domain and open access materials, we can show others how to make use of the models and/or data we're making available, and potentially inspire them to do the same.


#### Evaluation

Likely more qualitative: aside from people blogging and explicitly citing our work as inspirations, which would obviously be ideal, perhaps there's a way to measure repo forks, or Hugging Face model downloads, or dataset downloads, etc. Social media "likes" and reposts are probably not a meaningfully strong signal here, but can probably at least be taken as plaudits for the approach.


## Scope

I propose focusing first on a fine-tuned model that can parse the text of any NYC city directory into structured data.

There are ~330 NYC city directories online spanning 1786–1925, scanned and made available by The New York Public Library (146 volumes), the Brooklyn Public Library (79), the Allen County Public Library Genealogy Center (77), Columbia University Libraries (27), and the Library of Congress (1). This alone is a tremendously rich dataset that has to date never been brought together and released publicly -- while various projects here and there have touched on aspects of this, they either never expanded their scope, or more disappointingly, leveraged public domain data and resources without releasing them publicly.

It's possible that a single model won't be capable of usefully parsing all city directories from the 1780s to the 1920s, in which case plan B would be to break up the directories into segments based on era and publisher. In this case, all other elements remain the same, and the end release is more like 3 models than one single fine-tuned model for NYC city directories.

Meanwhile, if hypothesis B holds true, this gets us all or most of the way to a model that can parse any arbitrary city directory from anywhere in the US. If the quality isn't quite what we hope for in other cities, it should be possible to do a slight fine-tune of our own fine-tuned model, which should work for any city directory use case. It should be very straightforward to publish a guide on how to do this, replete with code examples of exactly how to formulate the commands to run.


## Current work and barriers

I've been working on fine-tuning the smallest available Qwen model, 0.8 billion parameters, on the ground truth I've generated. All city directory entries are parsed into the following eight fields: 

name · is_business · spouse_name · race_designation · occupation_role · employer · address · home_address

The current model I’ve trained leads a Gemini 3.1-flash-lite baseline on all three aggregate measures[^3]:


<table>
  <tr>
   <td><strong>model</strong>
   </td>
   <td><strong>macro-F1</strong>
   </td>
   <td><strong>micro-F1</strong>
   </td>
   <td><strong>whole-row exact match</strong>
   </td>
  </tr>
  <tr>
   <td>Gemini 3.1-flash-lite (prompt-primed baseline)
   </td>
   <td>0.790
   </td>
   <td>0.844
   </td>
   <td>58.0%
   </td>
  </tr>
  <tr>
   <td><strong>qwen-v5 (ours)</strong>
   </td>
   <td><strong>0.826</strong>
   </td>
   <td><strong>0.875</strong>
   </td>
   <td><strong>61.5%</strong>
   </td>
  </tr>
</table>


In plain terms: the fine-tuned model gets all 8 fields simultaneously right on 61.5% of lines it has never seen, and scores 0.875 on the appearance-weighted per-field measure.

Each training run at this small scale costs ~$7, which I’ve been happy to self-fund. But the most recent cycle showed diminishing returns. To push macro-F1 above 0.90, I need larger Qwen models trained on larger synthetic datasets — the ~$500 / ~73 H200-hour request above. Repeated small trainings without worrying about cost would also let me establish which training paths are most effective rather than inferring it from single runs.

Everything I've done so far including all existing evals and all the data gathering and manual transcription for ground truth for a variety of city directories is available on GitHub in the ["city-directory-extraction" repository](https://github.com/hadro/city-directory-extraction).


## Plan and milestones

The work is deliberately sequenced so the cheap experiment answers the expensive question first.

**1. De-risking A/B — ~$15, or ~10 A100-hours.** Train a 0.8B model on 250K synthetic examples against the current 100K baseline. This answers whether more training data helps *at all* before committing 170 GPU-hours to the larger family. If the answer is no, the diagnosis and the money both change, and we've spent $15 finding out.

**2. Family scale-up — ~73 H200-hours, or ~$310.** Assuming (1) is positive: 0.8B, 2B, and 4B models at 500K examples × 3 epochs, each scored against an 18-volume panel. This is where Hypothesis A gets settled.

**3. Out-of-city evaluation — ground truth generation, minimal compute.** Hand-label a small panel of non-NYC directories and score the best NYC model against it cold. This settles Hypothesis B, and if it comes in low, tests the cheap-additional-fine-tune sub-hypothesis.

**4. Release and documentation.** Models and datasets to Hugging Face, the demo Space (see outputs below), a write-up of the method, and the catalog as a standalone reference resource.

Milestones: a lot of this would depend on the ease or complexity of getting access to either HPC GPU or inference credits, and whether I can run those jobs myself versus teeing them up for mediated access, etc. But at a high level I believe the initial model runs can be completed in a few months, and likewise the dissemination work can be done in a matter of months as well depending strongly on how many people are involved in review and sign-off. Even with just me working on this in the evenings, I’m confident that the scope here is doable in roughly four months.


## Proposed project outputs



* One (or more) fine-tuned Qwen 3.5 model(s) hosted with an open license on Hugging Face
* One (or more) CC0 licensed dataset(s) of roughly 500K synthetic training data city directory entries, generated from small samples of ground truth data, posted to Hugging Face
* A public Hugging Face Space demo — upload an image of any single city directory page, and the Space runs LLM OCR, pipes the result through the fine-tuned model, and returns that page as structured data. Scoped to single pages rather than whole volumes, this is very doable, and it's perhaps the easiest demonstration of the project for anyone who can’t/won't run python themselves.
* A code repository on GitHub including the following all under an open license:
    * VLM-generated profiles of dozens of NYC city directories, with representative samples of every publisher and era combination
    * Manually generated ground truth for a representative sample of NYC city directories
    * scripts and helpers that generate the synthetic training data based on the ground truth data, evaluate model performance on ground truth data, and other functions as needed
    * A master list of 330 digitized NYC city directories spanning 1786–1925, scanned and made available by The New York Public Library (146 volumes), the Brooklyn Public Library (79), the Allen County Public Library Genealogy Center (77), Columbia University Libraries (27), and the Library of Congress (1)


## Boring statements for clarity



* This is purely a personal project, fully outside the scope of my employment at the Library of Congress – it does not imply any formal affiliation with or connection to any Library of Congress projects, even if some of the city directories may be held among the Library of Congress digital collections
* I don't have strongly held views about where this stuff lives or how various partnerships are presented/represented, as long as the following remain true:
    * All public domain data remains public domain and openly available
    * Any original data or code derived from or used to parse public domain data remains openly licensed to the utmost extent possible
    * Things are published and described in such a way that others can make use and reuse of them
    * I can use and reuse code, data, models, and anything else resulting from this work in subsequent projects, regardless of whether they're continuations of a potential partnership or not


## Prior art



* [NYPL Labs Space/Time Directory](https://wayback.archive-it.org/23478/20241118143457/https://spacetime.nypl.org/)
* [Mapping Historical New York: A Digital Atlas](https://mappinghny.com/?) -- data not made available, as far as I can tell, but acknowledges use of Space/Time Directory data
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

[^2]:
     A note on metrics: the project's evaluation harness reports three numbers, and they differ a lot for the same model. **Macro-F1** averages per-field quality evenly, so rare fields count as much as common ones — it's the hardest and most “honest” single number. **Micro-F1** weights each field by how often it actually appears. **Whole-row exact match** requires all 8 fields to be simultaneously correct. The targets above are stated in macro-F1 unless noted.

[^3]:
     Many more details on these evaluation measures are available in the existing repository 