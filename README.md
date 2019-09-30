# web-crawler
Didactic Web crawler for Web Search Engines (CS 6913) course at NYU

## Requirements
- Python 3.7
- pip
- virtualenv (optional but recommended)

## Install

```bash
$ pip install -r requirements.txt
```

## Instructions

Crawling query `new york university`:

```bash
$ python crawler.py "new york university"
```

Saving output to file:

```bash
$ python crawler.py "new york university" > output.txt
```

Printing output in real-time:
```bash
$ tail -f output.txt
```

Getting help:

```bash
$ python crawler.py -h
```

## Priority Score

The total priority score is simply the sum of the novelty and importance scores.

Novelty starts at 10 and is decreased by 0.1 each time the domain has been crawled. The minimum value novelty can reach is 0.

Importance starts at 0 and increases by 1 each time the specific URL has been parsed from crawled URLs and 0.01 each time the domain has been parsed out.

```
score = novelty + importance
novelty = max(0, 10 - 0.1*domain)
importance = 1*url + 0.01*domain
```

## Missing features

- MIME type checking
- Overall crawling statistics