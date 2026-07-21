from __future__ import annotations

import re

from foundry.store.models import Memory

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def score_memory_item(item: Memory, query_text: str) -> float:
    query_tokens = _tokenize(query_text)
    item_tokens = _tokenize(f"{item.title} {item.body_md}")
    if not query_tokens or not item_tokens:
        return 0.0
    intersection = query_tokens & item_tokens
    union = query_tokens | item_tokens
    return len(intersection) / len(union) if union else 0.0


def select_relevant_memory(
    items: list[Memory], query_text: str, k: int = 5, max_chars: int = 2000
) -> list[Memory]:
    scored = [(item, score_memory_item(item, query_text)) for item in items]
    scored = [(item, score) for item, score in scored if score > 0.0]
    scored.sort(key=lambda pair: (pair[1], pair[0].created_at), reverse=True)

    selected: list[Memory] = []
    total_chars = 0
    for item, _score in scored:
        if len(selected) >= k:
            break
        if selected and total_chars >= max_chars:
            break
        selected.append(item)
        total_chars += len(item.body_md)
    return selected
