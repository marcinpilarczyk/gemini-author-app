from __future__ import annotations

import json

from google import genai
from google.genai import types


class AuthorAI:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def _generate(self, prompt: str, *, temperature: float = 0.35, max_tokens: int = 8192) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        return (response.text or "").strip()

    def summarize_chapter(self, chapter_text: str) -> str:
        if len(chapter_text.strip()) < 50:
            return ""
        return self._generate(
            """Create a compact continuity ledger for this fiction chapter.

Return exactly three sections:
Narrative summary — what changed in the story.
Continuity facts — characters, items, injuries, locations, promises, reveals.
Pacing — how intensity changes from start to finish.

Chapter:
"""
            + chapter_text[:14000],
            temperature=0.15,
        )

    def extract_chapter_plan(self, outline: str, chapter_number: int) -> str:
        return self._generate(
            f"""Extract only the outline material that applies to Chapter {chapter_number}.
Do not invent missing beats. If the outline contains no Chapter {chapter_number} section, say so plainly.

OUTLINE
{outline}
""",
            temperature=0.0,
            max_tokens=4096,
        )

    def draft_chapter(
        self,
        *,
        concept: str,
        outline: str,
        continuity_ledger: str,
        previous_text: str,
        chapter_number: int,
        plan: str,
    ) -> str:
        return self._generate(
            f"""You are drafting Chapter {chapter_number} of a novel.

Follow the supplied plan and established continuity. Do not add commentary before or after the chapter. Produce prose only.

BOOK CONCEPT
{concept}

OUTLINE
{outline}

CONTINUITY LEDGER
{continuity_ledger}

END OF PREVIOUS CHAPTER
{previous_text[-4000:]}

CHAPTER PLAN
{plan}
""",
            temperature=0.75,
            max_tokens=20000,
        )

    def analyze_market_dna(self, concept: str, outline: str, continuity_ledger: str) -> str:
        return self._generate(
            f"""Analyze this book as a publishing metadata problem, not as a review.

Return concise sections for:
- likely genre / subgenre
- strongest tropes
- tone and reader promise
- comparable-reader positioning (describe the audience, do not invent sales data)
- useful KDP keyword directions

CONCEPT
{concept}

OUTLINE
{outline}

CURRENT CONTINUITY
{continuity_ledger}
""",
            temperature=0.25,
        )

    def consistency_scan(self, manuscript: str, concept: str, outline: str) -> tuple[str, list[dict]]:
        raw = self._generate(
            f"""Act as a meticulous fiction continuity editor.
Find only material continuity or logic problems. Prefer minimal fixes over rewrites.

Return a short narrative report, then this exact delimiter and a JSON array:
---FIX_BLOCK---
[{{"chapter": 1, "find": "exact text from manuscript", "replace": "minimal replacement text", "reason": "why"}}]
---END_FIX_BLOCK---

If no safe exact-text fix is appropriate, return an empty array.

BOOK CONCEPT
{concept}

OUTLINE
{outline}

MANUSCRIPT
{manuscript[:120000]}
""",
            temperature=0.1,
            max_tokens=24000,
        )

        report = raw.split("---FIX_BLOCK---", 1)[0].strip()
        fixes: list[dict] = []
        if "---FIX_BLOCK---" in raw and "---END_FIX_BLOCK---" in raw:
            payload = raw.split("---FIX_BLOCK---", 1)[1].split("---END_FIX_BLOCK---", 1)[0].strip()
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, list):
                    fixes = [item for item in parsed if isinstance(item, dict)]
            except json.JSONDecodeError:
                fixes = []
        return report, fixes
