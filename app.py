from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import streamlit as st

from author_studio.ai import AuthorAI
from author_studio.db import AuthorStudioDB
from author_studio.export import manuscript_markdown, to_docx
from author_studio.text import normalize_text, split_manuscript, word_count


APP_NAME = "Author Studio"
DB_PATH = Path(os.getenv("AUTHOR_STUDIO_DB", "author_studio.db"))
MODEL_OPTIONS = ["gemini-3.1-pro-preview", "gemini-3.8-flash"]

st.set_page_config(
    page_title=APP_NAME,
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      :root { --studio-border: rgba(128, 128, 128, .22); }
      .block-container { max-width: 1320px; padding-top: 2rem; padding-bottom: 4rem; }
      [data-testid="stSidebar"] { border-right: 1px solid var(--studio-border); }
      .studio-kicker { letter-spacing: .12em; text-transform: uppercase; opacity: .62; font-size: .78rem; }
      .studio-title { font-size: 2.35rem; font-weight: 760; margin: .15rem 0 .4rem; line-height: 1.05; }
      .studio-subtitle { max-width: 760px; opacity: .72; font-size: 1.03rem; margin-bottom: 1.4rem; }
      .studio-card { border: 1px solid var(--studio-border); border-radius: 16px; padding: 1rem 1.1rem; }
      div[data-testid="stMetric"] { border: 1px solid var(--studio-border); border-radius: 14px; padding: .85rem 1rem; }
      div[data-testid="stTabs"] button p { font-size: .96rem; }
      .small-muted { opacity: .65; font-size: .86rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def get_api_key() -> str:
    try:
        return st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return ""


def ai_client(api_key: str, model: str) -> AuthorAI:
    return AuthorAI(api_key=api_key, model=model)


def build_continuity_ledger(chapters) -> str:
    parts = []
    for row in chapters:
        if row["summary"]:
            parts.append(f"Chapter {row['chapter_num']}:\n{row['summary']}")
    return "\n\n".join(parts)


def ensure_book(db: AuthorStudioDB) -> int:
    books = db.list_books()
    if not books:
        return db.create_book("My First Book")
    current = st.session_state.get("active_book_id")
    valid_ids = {int(row["id"]) for row in books}
    if current not in valid_ids:
        current = int(books[0]["id"])
        st.session_state.active_book_id = current
    return int(current)


def replace_exact_text(db: AuthorStudioDB, book_id: int, chapter_number: int, old: str, new: str, ai: AuthorAI) -> bool:
    chapters = db.list_chapters(book_id)
    row = next((r for r in chapters if int(r["chapter_num"]) == int(chapter_number)), None)
    if not row or old.strip() not in row["content"]:
        return False
    updated = row["content"].replace(old.strip(), new.strip(), 1)
    summary = ai.summarize_chapter(updated)
    db.save_chapter(book_id, chapter_number, updated, summary)
    return True


db = AuthorStudioDB(DB_PATH)
active_book_id = ensure_book(db)

with st.sidebar:
    st.markdown("### ✦ Author Studio")
    st.caption("Continuity-aware drafting workspace")

    api_key = get_api_key()
    if not api_key:
        api_key = st.text_input("Gemini API key", type="password", help="Used only for this session unless configured in Streamlit Secrets.")

    model = st.selectbox("Model", MODEL_OPTIONS, index=0)

    st.divider()
    st.caption("LIBRARY")
    books = db.list_books()
    options = {int(row["id"]): row["title"] for row in books}
    selected = st.selectbox(
        "Current book",
        options=list(options),
        index=list(options).index(active_book_id),
        format_func=lambda book_id: options[book_id],
        label_visibility="collapsed",
    )
    if selected != active_book_id:
        st.session_state.active_book_id = int(selected)
        st.session_state.pop("editor_content", None)
        st.rerun()

    with st.popover("＋ New book", use_container_width=True):
        new_title = st.text_input("Book title", placeholder="Untitled novel")
        if st.button("Create book", type="primary", use_container_width=True):
            new_id = db.create_book(new_title)
            st.session_state.active_book_id = new_id
            st.rerun()

    st.divider()
    with st.expander("Backup & import"):
        if DB_PATH.exists():
            st.download_button(
                "Download database",
                data=DB_PATH.read_bytes(),
                file_name=f"author-studio-{dt.date.today().isoformat()}.db",
                mime="application/octet-stream",
                use_container_width=True,
            )

        uploaded_db = st.file_uploader("Restore database", type="db")
        if uploaded_db and st.button("Restore this backup", use_container_width=True):
            DB_PATH.write_bytes(uploaded_db.getvalue())
            st.session_state.clear()
            st.rerun()

        pasted = st.text_area("Import manuscript", placeholder="Paste text with headings such as Chapter 1, Chapter 2…", height=140)
        if st.button("Split and import", use_container_width=True, disabled=not pasted.strip()):
            parsed = split_manuscript(pasted)
            if not parsed:
                st.error("I couldn't find chapter headings like ‘Chapter 1’. No data changed.")
            else:
                db.replace_chapters(active_book_id, parsed)
                st.success(f"Imported {len(parsed)} chapters.")
                st.rerun()

book = db.get_book(active_book_id)
chapters = db.list_chapters(active_book_id)
if not book:
    st.error("The selected book no longer exists.")
    st.stop()

concept = book["concept"] or ""
outline = book["outline"] or ""
chapter_map = {int(row["chapter_num"]): row["content"] for row in chapters}
continuity = build_continuity_ledger(chapters)
full_manuscript = manuscript_markdown(chapters)

st.markdown('<div class="studio-kicker">AI-assisted long-form writing</div>', unsafe_allow_html=True)
st.markdown(f'<div class="studio-title">{book["title"]}</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="studio-subtitle">Draft chapters, maintain continuity, inspect the manuscript as a whole, and export clean copy without losing the story state between sessions.</div>',
    unsafe_allow_html=True,
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Chapters", len(chapters))
m2.metric("Words", f"{word_count(full_manuscript):,}")
m3.metric("Continuity notes", sum(1 for row in chapters if row["summary"]))
m4.metric("Model", model.replace("gemini-", "Gemini "))

if not api_key:
    st.info("Add a Gemini API key in the sidebar to enable generation and analysis. Everything else remains usable locally.")

ai = ai_client(api_key, model) if api_key else None

tab_book, tab_write, tab_manuscript, tab_editor, tab_publish = st.tabs(
    ["Book", "Write", "Manuscript", "Continuity", "Positioning"]
)

with tab_book:
    st.subheader("Story foundation")
    st.caption("The concept and outline are the stable context used by drafting and continuity checks.")
    left, right = st.columns(2, gap="large")
    with left:
        title_value = st.text_input("Title", value=book["title"])
        concept_value = st.text_area("Concept / story bible", value=concept, height=420)
    with right:
        outline_value = st.text_area("Outline", value=outline, height=480)

    if st.button("Save book context", type="primary"):
        db.update_book(active_book_id, title_value, concept_value, outline_value)
        st.success("Book context saved.")
        st.rerun()

with tab_write:
    next_number = max(chapter_map, default=0) + 1
    if "selected_chapter" not in st.session_state:
        st.session_state.selected_chapter = next_number

    top_left, top_right = st.columns([1, 4], gap="large")
    with top_left:
        chapter_number = st.number_input(
            "Chapter",
            min_value=1,
            step=1,
            value=int(st.session_state.selected_chapter),
        )
        st.session_state.selected_chapter = int(chapter_number)
    with top_right:
        existing = chapter_map.get(int(chapter_number), "")
        st.caption("Existing chapter" if existing else "New chapter")
        st.write(f"{word_count(existing):,} words" if existing else "Ready to draft")

    plan_key = f"chapter_plan_{chapter_number}"
    plan = st.text_area(
        "Chapter plan",
        value=st.session_state.get(plan_key, ""),
        height=170,
        placeholder="Write the chapter intent here, or extract it from the outline.",
    )
    st.session_state[plan_key] = plan

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("Extract from outline", use_container_width=True, disabled=not ai or not outline.strip()):
            with st.spinner("Reading the outline…"):
                try:
                    st.session_state[plan_key] = ai.extract_chapter_plan(outline, int(chapter_number))
                    st.rerun()
                except Exception as exc:
                    st.error(f"Gemini error: {exc}")
    with c2:
        if st.button("Draft chapter", type="primary", use_container_width=True, disabled=not ai or not plan.strip()):
            with st.spinner("Drafting with continuity context…"):
                try:
                    previous = chapter_map.get(int(chapter_number) - 1, "")
                    st.session_state.editor_content = ai.draft_chapter(
                        concept=concept,
                        outline=outline,
                        continuity_ledger=continuity,
                        previous_text=previous,
                        chapter_number=int(chapter_number),
                        plan=plan,
                    )
                except Exception as exc:
                    st.error(f"Gemini error: {exc}")
    with c3:
        if st.button("Load existing / start manually", use_container_width=True):
            st.session_state.editor_content = existing

    if "editor_content" in st.session_state:
        st.divider()
        editor_text = st.text_area(
            "Chapter text",
            value=st.session_state.editor_content,
            height=620,
            key="chapter_editor_widget",
        )
        st.caption(f"{word_count(editor_text):,} words")
        save_col, discard_col, _ = st.columns([1, 1, 3])
        with save_col:
            if st.button("Save chapter", type="primary", use_container_width=True):
                with st.spinner("Saving and refreshing continuity…"):
                    try:
                        summary = ai.summarize_chapter(editor_text) if ai else ""
                        db.save_chapter(active_book_id, int(chapter_number), normalize_text(editor_text), summary)
                        st.session_state.pop("editor_content", None)
                        st.session_state.pop("chapter_editor_widget", None)
                        st.success("Chapter saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not save chapter: {exc}")
        with discard_col:
            if st.button("Discard", use_container_width=True):
                st.session_state.pop("editor_content", None)
                st.session_state.pop("chapter_editor_widget", None)
                st.rerun()

    if chapters:
        st.divider()
        st.subheader("Saved chapters")
        for row in reversed(chapters):
            label = f"Chapter {row['chapter_num']} · {word_count(row['content']):,} words"
            with st.expander(label):
                if row["summary"]:
                    st.caption("Continuity ledger")
                    st.write(row["summary"])
                st.markdown(row["content"])

with tab_manuscript:
    if not chapters:
        st.info("Save a chapter and the assembled manuscript will appear here.")
    else:
        export_col, spacing_col = st.columns([1, 3])
        with export_col:
            docx = to_docx(full_manuscript, book["title"])
            st.download_button(
                "Download .docx",
                data=docx.getvalue(),
                file_name=f"{book['title']}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        with spacing_col:
            spacing = st.radio("Reading view", ["Standard spacing", "Tight spacing"], horizontal=True)

        view_text = full_manuscript if spacing == "Standard spacing" else normalize_text(full_manuscript, "tight")
        reading, raw = st.tabs(["Reading view", "Raw text"])
        with reading:
            st.markdown(view_text)
        with raw:
            st.text_area("Full manuscript", value=view_text, height=700, label_visibility="collapsed")

with tab_editor:
    st.subheader("Continuity editor")
    st.caption("Looks for material logic or continuity problems and proposes minimal exact-text fixes. Nothing is changed until you apply a suggestion.")

    if st.button("Run continuity scan", type="primary", disabled=not ai or word_count(full_manuscript) < 100):
        with st.spinner("Checking the manuscript…"):
            try:
                report, fixes = ai.consistency_scan(full_manuscript, concept, outline)
                st.session_state.continuity_report = report
                st.session_state.continuity_fixes = fixes
            except Exception as exc:
                st.error(f"Gemini error: {exc}")

    if report := st.session_state.get("continuity_report"):
        st.markdown(report)

    fixes = st.session_state.get("continuity_fixes", [])
    if fixes:
        st.divider()
        st.subheader("Proposed minimal fixes")
        for index, fix in enumerate(fixes):
            chapter_number = int(fix.get("chapter", 0) or 0)
            with st.expander(f"Chapter {chapter_number} · {fix.get('reason', 'continuity fix')}"):
                st.caption("Find")
                st.code(str(fix.get("find", "")), language=None)
                st.caption("Replace with")
                st.code(str(fix.get("replace", "")), language=None)
                if st.button("Apply this fix", key=f"fix_{index}", disabled=not ai):
                    ok = replace_exact_text(
                        db,
                        active_book_id,
                        chapter_number,
                        str(fix.get("find", "")),
                        str(fix.get("replace", "")),
                        ai,
                    )
                    if ok:
                        st.session_state.continuity_fixes.pop(index)
                        st.success("Fix applied and chapter summary refreshed.")
                        st.rerun()
                    else:
                        st.warning("The exact source text was not found. Nothing changed.")

with tab_publish:
    st.subheader("Reader positioning")
    st.caption("A compact metadata-oriented read of the manuscript — genre, tropes, tone, reader promise and keyword directions.")
    if st.button("Analyze positioning", type="primary", disabled=not ai):
        with st.spinner("Analyzing the book…"):
            try:
                st.session_state.positioning = ai.analyze_market_dna(concept, outline, continuity)
            except Exception as exc:
                st.error(f"Gemini error: {exc}")
    if positioning := st.session_state.get("positioning"):
        st.markdown(positioning)

st.divider()
st.caption("Local-first prototype. Manuscript data stays in the local SQLite database; text is sent to Gemini only when you explicitly run an AI action.")
