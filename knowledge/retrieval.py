"""Small-corpus BM25 retrieval, including Chinese character bigrams."""
import math
import re
import unicodedata
from collections import Counter

STOP_WORDS = frozenset("a an and are as at be by can do for from how i in is it me of on or our please "
                       "project show tell that the their this to was we what when where which who with you".split())


def tokens(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    terms = [word for word in re.findall(r"[a-z0-9_]+", text) if word not in STOP_WORDS]
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.extend(run[index:index + 2] for index in range(max(1, len(run) - 1)))
    return terms


def chunks(text, size=900, overlap=150):
    text = text.replace("\x00", "").strip()
    for start in range(0, len(text), size - overlap):
        yield text[start:start + size]
        if start + size >= len(text):
            break


def rank(question, rows, limit):
    query = set(tokens(question))
    if not query or not rows:
        return []
    bags = [Counter(tokens(row["title"] + " " + row["excerpt"])) for row in rows]
    lengths = [sum(bag.values()) for bag in bags]
    average = sum(lengths) / len(rows) or 1
    frequency = Counter(term for bag in bags for term in bag)
    scored = []
    for index, (row, bag, length) in enumerate(zip(rows, bags, lengths)):
        score = 0.0
        for term in query & bag.keys():
            inverse = math.log(1 + (len(rows) - frequency[term] + .5) / (frequency[term] + .5))
            score += inverse * bag[term] * 2.5 / (bag[term] + 1.5 * (.25 + .75 * length / average))
        if score > 0:
            scored.append((score, index, row))
    scored.sort(key=lambda value: (-value[0], value[1]))
    # Limit near-duplicate chunks from one source so other evidence can surface.
    counts = Counter()
    result = []
    for _, _, row in scored:
        identity = (row["kind"], row["source_id"])
        if counts[identity] >= 2:
            continue
        counts[identity] += 1
        result.append({**row, "citation": f"S{len(result) + 1}"})
        if len(result) == limit:
            break
    return result
