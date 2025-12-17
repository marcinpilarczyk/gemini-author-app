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
st.set_page_config(page_title="Gemini 3 Author Studio (Persistent)", layout="wide")
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
    # Chapters table now includes 'summary' for continuity tracking
    c.execute('''CREATE TABLE IF NOT EXISTS chapters (
                    chapter_num INTEGER PRIMARY KEY,
                    content TEXT,
                    summary TEXT 
                )''')
    
    # Auto-migration for existing databases (adds summary column if missing)
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
    # If summary is empty, try to preserve existing summary to avoid overwriting with blank
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

# Initialize DB
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
    """
    Runs the tactical/narrative analysis prompt.
    """
    if not chapter_text: return ""
    
    prompt = f"""
    You are an expert story analyst.
    Summarize the provided scene text into a two-part breakdown designed for tactical continuity and market alignment.

    ### TEXT TO ANALYZE
    {chapter_text[:10000]} # Truncate if massive to save tokens

    ### THE TASK
    
    **1. The Tactical Database (For AI Continuity)**
    Format: Continuous paragraph.
    Focus: Concrete facts only. List physical positions, specific injuries, weapon/tool inventory, and status of local technology. Explicitly state environment conditions.
    Goal: Prevent hallucinations in future chapters.

    **2. The Narrative Engine (For Pacing)**
    Format: Continuous paragraph.
    Focus: Emotional/Thematic shift. Identify "Micro-Tropes". Track entropy and power dynamics.
    
    **Constraints:**
    Total Word Count: 300-400 words.
    Tone: Serious, analytical.
    """
    
    try:
        # We create a fresh model instance to avoid context pollution
        model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Summary Error: {e}"

# --- HELPER: NUCLEAR TEXT NORMALIZER ---
def normalize_text(text, mode="standard"):
    """
    Splits text by ANY vertical gap and rebuilds it cleanly.
    """
    if not text: return ""
    
    # 1. Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 2. Split by 2+ newlines (paragraph breaks)
    paragraphs = re.split(r'\n\s*\n', text)
    
    # 3. Clean each paragraph
    clean_paragraphs = [p.strip() for p in paragraphs if p.strip()]
    
    # 4. Rejoin based on mode
    if mode == "tight":
        return '\n'.join(clean_paragraphs) # Single spacing
    else:
        return '\n\n'.join(clean_paragraphs) # Standard spacing (one blank line)

# --- HELPER: DOCX BUILDER ---
def create_docx(full_text, title="My Novel"):
    doc = Document()
    doc.add_heading(title, 0)
    
    # Always normalize to standard before export to detect paragraphs correctly
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
            # Split by italics markers *...*
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
    
    # --- SECTION 1: EMERGENCY IMPORT ---
    with st.expander("⚠️ Emergency Import"):
        st.write("Paste full text. I will look for 'Chapter X'.")
        import_text = st.text_area("Paste Text Here", height=300)
        
        if st.button("Force Clean Import"):
            if import_text:
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM chapters")
                
                # Regex for Python 3.13 compliant split
                chunks = re.split(r'(?i)(chapter\s+\d+)', import_text)
                current_chapter_num = 0
                current_content = ""
                
                for chunk in chunks:
                    if re.match(r'(?i)chapter\s+\d+', chunk.strip()):
                        if current_chapter_num > 0:
                            # Save raw content, empty summary for now
                            clean_content = normalize_text(current_content)
                            if clean_content:
                                c.execute("INSERT INTO chapters (chapter_num, content, summary) VALUES (?, ?, ?)", 
                                          (current_chapter_num, clean_content, ""))
                        current_chapter_num += 1
                        current_content = "" 
                    else:
                        current_content += chunk
                
                # Save last chapter
                if current_chapter_num > 0:
                    clean_content = normalize_text(current_content)
                    if clean_content:
                        c.execute("INSERT INTO chapters (chapter_num, content, summary) VALUES (?, ?, ?)", 
                                  (current_chapter_num, clean_content, ""))
                
                conn.commit()
                conn.close()
                st.success(f"Imported {current_chapter_num} chapters! Please run the Backfill tool below.")
                st.rerun()

    st.divider()

    # --- SECTION 2: BACKFILL TOOL ---
    st.write("### 🧠 Memory Management")
    st.info("If you just imported text, click this to generate the 'Tactical Data' so the AI remembers your story.")
    
    if st.button("⚡ Analyze & Index Past Chapters"):
        if not api_key:
            st.error("Need API Key first.")
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
                # Only generate if summary is missing
                if not chap['summary'] or len(chap['summary']) < 10:
                    status_text.text(f"Analyzing Chapter {chap['chapter_num']}...")
                    new_sum = generate_summary(chap['content'])
                    
                    # Update DB
                    up_conn = sqlite3.connect(DB_NAME)
                    up_c = up_conn.cursor()
                    up_c.execute("UPDATE chapters SET summary=? WHERE chapter_num=?", (new_sum, chap['chapter_num']))
                    up_conn.commit()
                    up_conn.close()
                    updated_count += 1
                
                progress_bar.progress((i + 1) / total)
            
            conn.close()
            status_text.text("✅ Indexing Complete!")
            st.success(f"Updated Tactical Data for {updated_count} chapters.")
            st.rerun()

    st.divider()

    if st.button("🔴 Reset All Data"):
        reset_db()
        st.session_state.clear()
        st.rerun()

# --- STATE MANAGEMENT ---
if "editor_mode" not in st.session_state: st.session_state.editor_mode = False

bible_data, chapter_data = load_from_db()
current_concept = bible_data['concept'] if bible_data else ""
current_outline = bible_data['outline'] if bible_data else ""

# BUILD CONTEXTS
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

# --- MAIN APP ---
if not api_key:
    st.warning("Waiting for API Key...")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)

tab1, tab2, tab3 = st.tabs(["1. The Bible", "2. Writer", "3. Full Book"])

# TAB 1: BIBLE
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

# TAB 2: WRITER
with tab2:
    next_chap_num = len(history_list) + 1
    st.header(f"Drafting Chapter {next_chap_num}")

    # AUTO-FETCH
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

    # GENERATE
    if not st.session_state.editor_mode:
        if st.button(f"🚀 Generate Chapter {next_chap_num}", type="primary"):
            with st.spinner("Writing..."):
                cache_name = get_or_create_cache(new_concept, new_outline)
                
                # --- CONTINUITY CONTEXT ---
                smart_context = f"""
                ### STORY LEDGER (TACTICAL & NARRATIVE HISTORY)
                {rolling_summary_context}
                
                ### IMMEDIATE CONTEXT (PREVIOUS CHAPTER END)
                ...[End of Chapter {next_chap_num - 1}]...
                {last_chapter_raw[-3000:] if last_chapter_raw else "Start of book."}
                """
                
                dynamic_prompt = f"""
                ### STORY CONTEXT
                {smart_context}
                
                ### CHAPTER INSTRUCTIONS
                {chapter_instructions}
                
                ### TASK
                Write Chapter {next_chap_num}. 
                **CONTINUITY CHECK:** Consult the Story Ledger above for inventory, injuries, and status.
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
                        # Normalize immediately to standard
                        st.session_state.editor_content = normalize_text(response.text, mode="standard")
                        st.session_state.editor_mode = True
                        st.rerun()
                except Exception as e: st.error(f"Error: {e}")
    else:
        st.info("📝 Edit Mode")
        word_count = len(st.session_state.editor_content.split())
        st.caption(f"📊 **Current Word Count: {word_count} words**")
        
        # FORMATTING CONTROLS
        col_ctrl1, col_ctrl2 = st.columns([1, 1])
        with col_ctrl1:
            spacing_mode = st.radio("Spacing Style", ["Standard (Blank Line)", "Tight (No Blank Line)"], horizontal=True)
        with col_ctrl2:
            st.write("")
            if st.button("✨ Apply Formatting", type="secondary"):
                mode = "tight" if "Tight" in spacing_mode else "standard"
                st.session_state.editor_content = normalize_text(st.session_state.editor_content, mode=mode)
                st.rerun()

        edited_text = st.text_area(f"Editing Ch {next_chap_num}", height=600, key="editor_content")
        
        c1, c2 = st.columns([1,4])
        with c1:
            if st.button("💾 Save & Analyze"):
                with st.spinner("Saving and updating Tactical Database..."):
                    summary = generate_summary(edited_text)
                    save_chapter(next_chap_num, edited_text, summary)
                    st.session_state.editor_mode = False
                    del st.session_state.editor_content
                    st.success("Saved! Continuity updated.")
                    st.rerun()
        with c2:
            if st.button("❌ Discard"):
                st.session_state.editor_mode = False
                del st.session_state.editor_content
                st.rerun()

    if history_list and not st.session_state.editor_mode:
        st.divider()
        st.write("### History & Continuity")
        if st.button("Undo Last Saved Chapter"):
            delete_last_chapter(len(history_list))
            st.rerun()
        
        last = history_list[-1]
        with st.expander(f"Chapter {last['chapter_num']} - View Tactical Data", expanded=True):
            st.info(last['summary'] if last['summary'] else "No summary available.")
            st.text_area("Raw Text", value=last['content'], height=200, disabled=True)

# TAB 3: EXPORT
with tab3:
    st.header("The Full Manuscript")
    col1, col2, col3 = st.columns([1,1,1])
    
    with col1:
        full_spacing_mode = st.radio("Global Spacing", ["Standard (Blank Line)", "Tight (No Blank Line)"], key="full_sp")
    with col2:
        st.write("")
        if st.button("✨ Apply Global Formatting"):
            mode = "tight" if "Tight" in full_spacing_mode else "standard"
            full_text_history = normalize_text(full_text_history, mode=mode)
            st.success("Preview Updated!")
    with col3:
        st.write("")
        if st.button("📄 Download Word Doc (Atticus Ready)"):
            doc = create_docx(full_text_history)
            buffer = BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            st.download_button("Download .docx", buffer, "my_novel.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    st.text_area("Full Text Preview", value=full_text_history, height=600)
