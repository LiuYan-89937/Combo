from __future__ import annotations


SKILLHUB_SEARCH_QUERY_MAX_CHARS = 96
SKILLHUB_SEARCH_QUERY_PATTERN = r"^\S{1,32}(?:\s+\S{1,32}){0,2}$"


def normalize_skillhub_search_query(query: str) -> str:
    keywords = str(query or "").strip().split()
    if not 1 <= len(keywords) <= 3:
        raise ValueError("SkillHub search requires one to three short keywords")
    if any(len(keyword) > 32 for keyword in keywords):
        raise ValueError("each SkillHub search keyword must be at most 32 characters")
    normalized = " ".join(keywords)
    if len(normalized) > SKILLHUB_SEARCH_QUERY_MAX_CHARS:
        raise ValueError("SkillHub search query is too long")
    return normalized
