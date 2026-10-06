from author_studio.text import normalize_text, split_manuscript, word_count


def test_normalize_text_standard_and_tight():
    raw = "One.\n\n\nTwo.\r\n\r\nThree."
    assert normalize_text(raw) == "One.\n\nTwo.\n\nThree."
    assert normalize_text(raw, "tight") == "One.\nTwo.\nThree."


def test_split_manuscript():
    raw = "Chapter 1\nFirst chapter.\n\nChapter 2\nSecond chapter."
    assert split_manuscript(raw) == [(1, "First chapter."), (2, "Second chapter.")]


def test_split_manuscript_requires_headings():
    assert split_manuscript("Just prose") == []


def test_word_count():
    assert word_count("Don't lose the well-built ship.") == 5
