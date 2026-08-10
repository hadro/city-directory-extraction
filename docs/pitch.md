## The pitch

## Why is this useful? 

## How does this fit with the Glam-E Lab? 

## Hypothesis

Hypothesis A: Using openly available digitized city directories, we can fine-tune a model that can capably parse the entries from any arbitrary volume into structured data at an accuracy level of 90-95%.
- Sub-hypothesis: If this is not possible with a single fine-tuned model, then a small set of 2-4 era-specific models can accomplish the same thing by narrowing the data range.

Hypothesis B: Given that there are ~450 city directories for New York City from ~1770-1930, representing many of the largest publishers which also published city directories using similar conventions and layouts for other cities around the country, this same model trained on all NYC city directories will capably work out of the box for any arbitrary city directory from around the country from that same era at an accuracy level of >80-85%.
- Sub-hypothesis: Even if the NYC fine-tuned model doesn't work at >80-85% accuracy, it may be possible to further fine-tune the NYC model with a very small amount of data (a few hundred lines or less) and at very low cost (dozens of dollars).



## Scope

I propose focusing first on a fine-tuned model that can parse the text of any NYC city directory into structured data. 

There are 450 city directories online digitized by the New York Public Library, Brooklyn Public Library, Columbia University, Allen County Public Library, and others. This alone is a tremendously rich dataset that has to date never been brought together and released publicly -- while various projects here and there have touched on aspects of this, they either never expanded their scope, or more disappointingly, leveraged public domain data and resources without releasing them publicly.

It's possible that a single model won't be capable of usefully parsing all city directories from 1770-1930, in which case plan B would be to break up the . Otherwise, all other elements remain the same, and the end release is more like 3 models than one single fine-tuned model for NYC city directories.

Meanwhile, if hypothesis B holds true


## Needs

Either:

1. $ for inference compute (probably via Hugging Face, which is built for this)
2. Access to GPU compute (very packagable into scripted job bundle)

## Prior art
- [Mapping Historical New YorkA Digital Atlas](https://mappinghny.com/?) -- data not made available, as far as I can tell, but uses Space/Time Directory data
- [NYPL Labs Space/Time Directory](https://wayback.archive-it.org/23478/20241118143457/https://spacetime.nypl.org/) 
- [directoreadr](https://github.com/samwbell/directoreadr) - "Reads and parses business location data from scans of City Directory Yellow Pages"
- [Small Models for Glam](https://huggingface.co/small-models-for-glam)
- [Parsing 3.6 Million Historical Names with Small Models](https://wjbmattingly.com/blog/parsing-3-6-million-historical-names-with-small-models/) - May 3, 2026 By William Mattingly 
