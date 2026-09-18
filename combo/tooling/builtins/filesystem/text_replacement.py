from __future__ import annotations


class TextReplacementError(ValueError):
    def __init__(self, *, match_count: int) -> None:
        self.match_count = match_count
        self.code = "old_text_not_found" if match_count == 0 else "old_text_ambiguous"
        super().__init__(
            "old_text was not found in the selected file; read that path again or use rg to locate the exact text"
            if match_count == 0 else
            f"old_text matched {match_count} times; read the target and provide unique context, "
            "or set replace_all=true only when every match should change"
        )


def replace_exact_text(
    content: str, old_text: str, new_text: str, *, replace_all: bool,
) -> tuple[str, int]:
    if not isinstance(old_text, str) or not old_text:
        raise ValueError("old_text must be a non-empty string")
    count = content.count(old_text)
    if count == 0 or (not replace_all and count != 1):
        raise TextReplacementError(match_count=count)
    replacements = count if replace_all else 1
    return content.replace(old_text, new_text, -1 if replace_all else 1), replacements
