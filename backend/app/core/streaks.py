"""Consecutive-occurrence streaks for mistake tags.

Pure + dependency-free so the review service and both (prop/perps) analytics
services can share the one definition without a circular import.
"""


def max_streaks(ordered_tag_iterables) -> dict[str, int]:
    """Given trades in chronological order — each an iterable of its mistake-tag
    strings (or None) — return ``{tag: longest run of consecutive trades carrying
    that tag}``. A trade lacking the tag breaks that tag's current run.
    """
    sequences = [set(tags or ()) for tags in ordered_tag_iterables]
    all_tags = set().union(*sequences) if sequences else set()
    out: dict[str, int] = {}
    for tag in all_tags:
        best = cur = 0
        for s in sequences:
            if tag in s:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        out[tag] = best
    return out
