import re


def normalize_text(text: str, mode: str = "standard") -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r"\n\s*\n", text)
    clean = [p.strip() for p in paragraphs if p.strip()]
    return "\n".join(clean) if mode == "tight" else "\n\n".join(clean)


def split_manuscript(raw_text: str) -> list[tuple[int, str]]:
    """Split a pasted manuscript on headings such as 'Chapter 12'."""
    if not raw_text.strip():
        return []

    pattern = re.compile(r"(?im)^\s*chapter\s+(\d+)\s*$")
    matches = list(pattern.finditer(raw_text))
    if not matches:
        return []

    chapters: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        number = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        content = normalize_text(raw_text[start:end])
        if content:
            chapters.append((number, content))
    return chapters


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+[’'\-]?\w*\b", text or ""))
