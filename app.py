import streamlit as st
import google.generativeai as genai
from google.generativeai import caching
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import datetime
import re
import sqlite3
from docx import Document
from io import BytesIO

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Gemini 3 Author Studio", layout="wide")
st.title("Drafting with Gemini 3 Pro (Auto-Save + Rolling Memory)")

# --- DATABASE SETUP ---
DB_NAME = "my_novel.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS book_info (
                    id INTEGER PRIMARY KEY,
                    concept TEXT,
                    outline TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS chapters (
                    chapter_num INTEGER PRIMARY KEY,
                    content TEXT,
                    summary TEXT 
                )''')
    try:
        c.execute("SELECT summary FROM chapters LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE chapters ADD COLUMN summary TEXT")
    conn.commit()
    conn.close()

def load_from_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM book_info WHERE id=1")
    bible = c.fetchone()
    c.execute("SELECT * FROM chapters ORDER BY chapter_num")
    chapters = c.fetchall()
    conn.close()
    return bible, chapters

def save_bible(concept, outline):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO book_info (id, concept, outline) VALUES (1, ?, ?)", (concept, outline))
    conn.commit()
    conn.close()

def save_chapter(num, content, summary=""):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if not summary:
        c.execute("SELECT summary FROM chapters WHERE chapter_num=?", (num,))
        existing = c.fetchone()
        summary = existing[0] if existing else ""
    c.execute("INSERT OR REPLACE INTO chapters (chapter_num, content, summary) VALUES (?, ?, ?)", (num, content, summary))
    conn.commit()
    conn.close()

def delete_last_chapter(num):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM chapters WHERE chapter_num=?", (num,))
    conn.commit()
    conn.close()

def reset_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM chapters")
    c.execute("DELETE FROM book_info")
    conn.commit()
    conn.close()

init_db()

# --- HARDCODED MODEL ---
MODEL_NAME = "gemini-3-pro-preview"
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- AGENT: THE SUMMARIZER ---
def generate_summary(chapter_text):
    if not chapter_text: return ""
    prompt = f"""
    You are an expert story analyst.
    Summarize the provided scene text into a two-part breakdown designed for tactical continuity.
    ### TEXT
    {chapter_text[:12000]}
    ### TASK
    1. **Tactical Database**: List concrete facts, injuries, inventory, and environment status.
    2. **Narrative Engine**: Track emotional shifts and pacing.
    Keep it under 400 words.
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Summary Error: {e}"

# --- HELPER: TEXT NORMALIZER ---
def normalize_text(text, mode="standard"):
    if not text: return ""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    paragraphs = re.split(r'\n\s*\n', text)
    clean_paragraphs = [p.strip() for p in paragraphs if p.strip()]
    if mode == "tight":
        return '\n'.join(clean_paragraphs)
    else:
        return '\n\n'.join(clean_paragraphs)

# --- HELPER: DOCX BUILDER ---
def create_docx(full_text, title="My Novel"):
    doc = Document()
    doc.add_heading(title, 0)
    normalized = normalize_text(full_text, mode="standard")
    paragraphs = normalized.split('\n\n')
    for p_text in paragraphs:
        if not p_text.strip(): continue
        if p_text.startswith("## Chapter"):
            doc.add_heading(p_text.replace("## ", "").strip(), level=1)
        elif p_text.startswith("## "):
            doc.add_heading(p_text.replace("## ", "").strip(), level=2)
        else:
            p = doc.add_paragraph()
            parts = re.split(r'(\*[^*]+\*)', p_text)
            for part in parts:
                if part.startswith('*') and part.endswith('*') and len(part) > 2:
                    p.add_run(part[1:-1]).italic = True
                else:
                    p.add_run(part)
    return doc

# --- CACHING ---
def get_or_create_cache(bible_text, outline_text):
    static_content = f"### THE BIBLE (Static Context)\n{bible_text}\n\n### THE FULL OUTLINE\n{outline_text}"
    if 'cache_name' in st.session_state:
        try:
            cache = genai.caching.CachedContent.get(name=st.session_state.cache_name)
            cache.update(ttl=datetime.timedelta(hours=2))
            return cache.name
        except: del st.session_state.cache_name
    try:
        cache = genai.caching.CachedContent.create(
            model=MODEL_NAME, display_name="book_bible_v1", contents=[static_content], ttl=datetime.timedelta(hours=2)
        )
        st.session_state.cache_name = cache.name
        return cache.name
    except Exception: return None

# --- SIDEBAR ---
with st.sidebar:
    st.header("Settings")
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        api_key = st.text_input("Enter Google API Key", type="password")

    st.divider()
    
    with st.expander("⚠️ Emergency Import"):
        st.write("Paste full text. I will look for 'Chapter X'.")
        import_text = st.text_area("Paste Text Here", height=300)
        
        if st.button("Force Clean Import"):
            if import_text:
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM chapters")
                chunks = re.split(r'(?i)(chapter\s+\d+)', import_text)
                current_chapter_num = 0
                current_content = ""
                for chunk in chunks:
                    if re.match(r'(?i)chapter\s+\d+', chunk.strip()):
                        if current_chapter_num > 0:
                            clean_content = normalize_text(current_content)
                            if clean_content:
                                c.execute("INSERT INTO chapters (chapter_num, content, summary) VALUES (?, ?, ?)", 
                                          (current_chapter_num, clean_content, ""))
                        current_chapter_num += 1
                        current_content = "" 
                    else:
                        current_content += chunk
                if current_chapter_num > 0:
                    clean_content = normalize_text(current_content)
                    if clean_content:
                        c.execute("INSERT INTO chapters (chapter_num, content, summary) VALUES (?, ?, ?)", 
                                  (current_chapter_num, clean_content, ""))
                conn.commit()
                conn.close()
                st.success(f"Imported {current_chapter_num} chapters!")
                st.rerun()

    st.write("### 🧠 Memory Management")
    if st.button("⚡ Analyze & Index Past Chapters"):
        if not api_key:
            st.error("Need API Key.")
        else:
            genai.configure(api_key=api_key)
            conn = sqlite3.connect(DB_NAME)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM chapters WHERE content IS NOT NULL")
            all_chaps = c.fetchall()
            progress_bar = st.progress(0)
            status_text = st.empty()
            updated_count = 0
            total = len(all_chaps)
            for i, chap in enumerate(all_chaps):
                if not chap['summary'] or len(chap['summary']) < 10:
                    status_text.text(f"Analyzing Chapter {chap['chapter_num']}...")
                    new_sum = generate_summary(chap['content'])
                    up_conn = sqlite3.connect(DB_NAME)
                    up_c = up_conn.cursor()
                    up_c.execute("UPDATE chapters SET summary=? WHERE chapter_num=?", (new_sum, chap['chapter_num']))
                    up_conn.commit()
                    up_conn.close()
                    updated_count += 1
                progress_bar.progress((i + 1) / total)
            conn.close()
            status_text.text("✅ Indexing Complete!")
            st.success(f"Updated {updated_count} chapters.")
            st.rerun()

    if st.button("🔴 Reset All Data"):
        reset_db()
        st.session_state.clear()
        st.rerun()

# --- MAIN APP ---
if not api_key:
    st.warning("Waiting for API Key...")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)

if "editor_mode" not in st.session_state: st.session_state.editor_mode = False

bible_data, chapter_data = load_from_db()
current_concept = bible_data['concept'] if bible_data else ""
current_outline = bible_data['outline'] if bible_data else ""
full_text_history = ""
rolling_summary_context = ""
last_chapter_raw = ""
history_list = []

for row in chapter_data:
    history_list.append(row)
    full_text_history += f"\n\n## Chapter {row['chapter_num']}\n\n{row['content']}"
    if row['summary']:
        rolling_summary_context += f"\n\n**Chapter {row['chapter_num']} Analysis:**\n{row['summary']}"
    last_chapter_raw = row['content']

tab1, tab2, tab3, tab4 = st.tabs(["1. The Bible", "2. Writer", "3. Full Book", "4. Publisher"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        new_concept = st.text_area("Concept", value=current_concept, height=400, key="concept_in")
    with col2:
        new_outline = st.text_area("Outline", value=current_outline, height=400, key="outline_in")
    if new_concept != current_concept or new_outline != current_outline:
        if st.button("💾 Save Bible Changes"):
            save_bible(new_concept, new_outline)
            st.rerun()

with tab2:
    next_chap_num = len(history_list) + 1
    st.header(f"Drafting Chapter {next_chap_num}")
    if st.button(f"🔮 Auto-Fetch Ch. {next_chap_num}"):
        with st.spinner("Fetching raw instructions..."):
            prompt = f"Access the Outline. Copy the section for **Chapter {next_chap_num}** VERBATIM. Do not summarize."
            try:
                cache_name = get_or_create_cache(new_concept, new_outline)
                if cache_name:
                    c_obj = genai.caching.CachedContent.get(name=cache_name)
                    c_model = genai.GenerativeModel.from_cached_content(cached_content=c_obj)
                    res = c_model.generate_content(prompt)
                else:
                    res = model.generate_content(f"{new_outline}\n\n{prompt}")
                st.session_state[f"plan_{next_chap_num}"] = res.text
                st.rerun()
            except Exception as e: st.error(f"Error: {e}")

    current_plan = st.session_state.get(f"plan_{next_chap_num}", "")
    chapter_instructions = st.text_area("Instructions:", value=current_plan, height=200)

    if not st.session_state.editor_mode:
        if st.button(f"🚀 Generate Chapter {next_chap_num}", type="primary"):
            with st.spinner("Writing..."):
                cache_name = get_or_create_cache(new_concept, new_outline)
                smart_context = f"""
                ### STORY LEDGER (TACTICAL HISTORY)
                {rolling_summary_context}
                ### IMMEDIATE CONTEXT
                ...[End of Chapter {next_chap_num - 1}]...
                {last_chapter_raw[-3000:] if last_chapter_raw else "Start of book."}
                """
                dynamic_prompt = f"""
                ### STORY CONTEXT
                {smart_context}
                ### INSTRUCTIONS
                {chapter_instructions}
                ### TASK
                Write Chapter {next_chap_num}. 
                **CONTINUITY CHECK:** Use the Ledger for status/items.
                **FORMATTING:** Use '***' for scene breaks.
                """
                try:
                    if cache_name:
                        c_obj = genai.caching.CachedContent.get(name=cache_name)
                        c_model = genai.GenerativeModel.from_cached_content(cached_content=c_obj, safety_settings=safety_settings)
                        response = c_model.generate_content(dynamic_prompt)
                    else:
                        response = model.generate_content(f"{new_concept}\n{new_outline}\n{dynamic_prompt}")
                    if response.text:
                        st.session_state.editor_content = normalize_text(response.text, mode="standard")
                        st.session_state.editor_mode = True
                        st.rerun()
                except Exception as e: st.error(f"Error: {e}")
    else:
        st.info("📝 Edit Mode")
        word_count = len(st.session_state.editor_content.split())
        st.caption(f"📊 Words: {word_count}")
        col_ctrl1, col_ctrl2 = st.columns([1, 1])
        with col_ctrl1:
            spacing_mode = st.radio("Spacing", ["Standard", "Tight"], horizontal=True)
        with col_ctrl2:
            st.write("")
            if st.button("✨ Apply Format"):
                mode = "tight" if "Tight" in spacing_mode else "standard"
                st.session_state.editor_content = normalize_text(st.session_state.editor_content, mode=mode)
                st.rerun()
        edited_text = st.text_area(f"Editing Ch {next_chap_num}", height=600, key="editor_content")
        c1, c2 = st.columns([1,4])
        with c1:
            if st.button("💾 Save"):
                with st.spinner("Saving..."):
                    summary = generate_summary(edited_text)
                    save_chapter(next_chap_num, edited_text, summary)
                    st.session_state.editor_mode = False
                    del st.session_state.editor_content
                    st.success("Saved!")
                    st.rerun()
        with c2:
            if st.button("❌ Discard"):
                st.session_state.editor_mode = False
                del st.session_state.editor_content
                st.rerun()

    if history_list and not st.session_state.editor_mode:
        st.divider()
        if st.button("Undo Last"):
            delete_last_chapter(len(history_list))
            st.rerun()
        last = history_list[-1]
        with st.expander(f"Chapter {last['chapter_num']} Data"):
            st.info(last['summary'])
            st.text_area("Raw", value=last['content'], height=200, disabled=True)

with tab3:
    st.header("Manuscript")
    col1, col2, col3 = st.columns([1,1,1])
    with col1:
        full_spacing_mode = st.radio("Global Spacing", ["Standard", "Tight"], key="full_sp")
    with col2:
        st.write("")
        if st.button("✨ Apply Global"):
            mode = "tight" if "Tight" in full_spacing_mode else "standard"
            full_text_history = normalize_text(full_text_history, mode=mode)
            st.success("Updated!")
    with col3:
        st.write("")
        if st.button("📄 Download Word Doc"):
            doc = create_docx(full_text_history)
            buffer = BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            st.download_button("Download .docx", buffer, "novel.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    st.text_area("Preview", value=full_text_history, height=600)

# --- TAB 4: PUBLISHER (MARKETING AGENT) ---
with tab4:
    st.header("🚀 The Algorithmic Publisher")
    st.markdown("Based on *The Algorithmic Copywriter* (Rufus/A9 Optimized).")
    
    # Initialize Session Keys if they don't exist
    if "pub_genre" not in st.session_state: st.session_state.pub_genre = ""
    if "pub_tropes" not in st.session_state: st.session_state.pub_tropes = ""
    if "pub_tone" not in st.session_state: st.session_state.pub_tone = "Serious"

    # --- AUTO-DETECT BUTTON ---
    if st.button("🧬 Auto-Analyze Book DNA (Extract Genre & Tropes)"):
        with st.spinner("Reading Bible & Summaries..."):
            dna_prompt = f"""
            Analyze the following Book Bible and Chapter Summaries.
            
            ### BIBLE
            {current_concept}
            {current_outline}
            
            ### SUMMARIES
            {rolling_summary_context}
            
            ### TASK
            Identify the following for a KDP marketing campaign:
            1. **Sub-Genre:** Specific commercial sub-genre (e.g., "Military Sci-Fi", "Regency Romance").
            2. **Core Tropes:** Top 5 tropes comma-separated (e.g., "Enemies to lovers, forced proximity").
            3. **Tone:** One word (Dark, Serious, Balanced, Hopeful, Humorous).
            
            Output strictly in this format:
            GENRE: [Genre]
            TROPES: [Tropes]
            TONE: [Tone]
            """
            try:
                dna_model = genai.GenerativeModel("gemini-1.5-pro")
                res = dna_model.generate_content(dna_prompt).text
                
                # Parse
                g = res.split("GENRE:")[1].split("TROPES:")[0].strip()
                tr = res.split("TROPES:")[1].split("TONE:")[0].strip()
                to = res.split("TONE:")[1].strip()
                
                st.session_state.pub_genre = g
                st.session_state.pub_tropes = tr
                st.session_state.pub_tone = to
                st.success("DNA Extracted!")
                st.rerun()
            except Exception as e:
                st.error(f"Analysis Failed: {e}")

    # --- INPUTS (Now Auto-Filled) ---
    col1, col
