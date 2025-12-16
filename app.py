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
st.title("Drafting with Gemini 3 Pro (Auto-Save Enabled)")

# --- DATABASE SETUP ---
DB_NAME = "my_novel.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Table for the Book Info
    c.execute('''CREATE TABLE IF NOT EXISTS book_info (
                    id INTEGER PRIMARY KEY,
                    concept TEXT,
                    outline TEXT
                )''')
    # Table for Chapters
    c.execute('''CREATE TABLE IF NOT EXISTS chapters (
                    chapter_num INTEGER PRIMARY KEY,
                    content TEXT
                )''')
    conn.commit()
    conn.close()

def load_from_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Load Bible
    c.execute("SELECT * FROM book_info WHERE id=1")
    bible = c.fetchone()
    
    # Load Chapters
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

def save_chapter(num, content):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO chapters (chapter_num, content) VALUES (?, ?)", (num, content))
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

# --- HELPER: TEXT CLEANER ---
def clean_text_formatting(text):
    if not text: return ""
    # The nuclear spacer fixer: replaces any chunk of vertical whitespace with exactly 2 newlines
    text = re.sub(r'\n\s*\n', '\n\n', text) 
    return text.strip()

# --- HELPER: DOCX BUILDER ---
def create_docx(full_text, title="My Novel"):
    doc = Document()
    doc.add_heading(title, 0)

    # Split into lines to process them one by one
    lines = full_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue # Skip empty lines to let Word handle spacing via styles
            
        # Detect Headers
        if line.startswith("## Chapter"):
            clean_header = line.replace("## ", "").strip()
            doc.add_heading(clean_header, level=1)
        elif line.startswith("## "):
            clean_header = line.replace("## ", "").strip()
            doc.add_heading(clean_header, level=2)
        else:
            # Create a standard paragraph
            p = doc.add_paragraph()
            
            # PARSE MARKDOWN ITALICS: *text*
            # We split by the asterisks to separate normal text from italic text
            # Regex captures the delimiters so we don't lose them
            parts = re.split(r'(\*[^*]+\*)', line)
            
            for part in parts:
                if part.startswith('*') and part.endswith('*') and len(part) > 2:
                    # Italic content (remove stars, apply style)
                    clean_part = part[1:-1]
                    run = p.add_run(clean_part)
                    run.italic = True
                else:
                    # Normal content
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

# --- SIDEBAR & SETUP ---
with st.sidebar:
    st.header("Settings")
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        api_key = st.text_input("Enter Google API Key", type="password")

    st.divider()
    
    # --- ROBUST IMPORTER (FIXED FOR PYTHON 3.13) ---
    with st.expander("⚠️ Emergency Import (Word Doc Fix)"):
        st.write("Paste your full text (Chapters 1-7). I will strictly look for 'Chapter X' headers.")
        import_text = st.text_area("Paste Text Here", height=300)
        
        if st.button("Force Clean Import"):
            if import_text:
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                
                # 1. Wipe database to prevent duplicates
                c.execute("DELETE FROM chapters")
                
                # 2. Advanced Split: FIX APPLIED HERE
                chunks = re.split(r'(?i)(chapter\s+\d+)', import_text)
                
                current_chapter_num = 0
                current_content = ""
                
                for chunk in chunks:
                    if re.match(r'(?i)chapter\s+\d+', chunk.strip()):
                        # SAVE PREVIOUS CHAPTER
                        if current_chapter_num > 0:
                            clean_content = clean_text_formatting(current_content)
                            if clean_content:
                                c.execute("INSERT INTO chapters (chapter_num, content) VALUES (?, ?)", 
                                          (current_chapter_num, clean_content))
                        
                        # START NEW CHAPTER
                        current_chapter_num += 1
                        current_content = "" 
                    else:
                        current_content += chunk

                # SAVE FINAL CHAPTER
                if current_chapter_num > 0:
                    clean_content = clean_text_formatting(current_content)
                    if clean_content:
                        c.execute("INSERT INTO chapters (chapter_num, content) VALUES (?, ?)", 
                                  (current_chapter_num, clean_content))

                conn.commit()
                conn.close()
                st.success(f"Successfully imported {current_chapter_num} chapters! Refreshing...")
                st.rerun()

    if st.button("🔴 DANGER: Reset All Data"):
        reset_db()
        st.session_state.clear()
        st.rerun()

# --- STATE MANAGEMENT ---
if "editor_mode" not in st.session_state: st.session_state.editor_mode = False

# LOAD DATA FROM DB
bible_data, chapter_data = load_from_db()

current_concept = bible_data['concept'] if bible_data else ""
current_outline = bible_data['outline'] if bible_data else ""
full_text_history = ""
history_list = []

for row in chapter_data:
    history_list.append({"chapter": row['chapter_num'], "content": row['content']})
    full_text_history += f"\n\n## Chapter {row['chapter_num']}\n\n{row['content']}"

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
            prompt = f"""
            Access the Outline. Copy the section for **Chapter {next_chap_num}** VERBATIM.
            Do not summarize. Extract specific Scene headers, POV, and details exactly as written.
            """
            try:
                # Use cache if available
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

    # INSTRUCTIONS
    current_plan = st.session_state.get(f"plan_{next_chap_num}", "")
    chapter_instructions = st.text_area("Instructions:", value=current_plan, height=250)

    # GENERATE
    if not st.session_state.editor_mode:
        if st.button(f"🚀 Generate Chapter {next_chap_num}", type="primary"):
            with st.spinner("Writing..."):
                cache_name = get_or_create_cache(new_concept, new_outline)
                dynamic_prompt = f"""
                ### STORY SO FAR
                {full_text_history}
                ### CHAPTER INSTRUCTIONS
                {chapter_instructions}
                ### TASK
                Write Chapter {next_chap_num}. Output ONLY the story text.
                **FORMATTING RULE:** Use '***' on a separate line to indicate scene breaks.
                """
                try:
                    if cache_name:
                        c_obj = genai.caching.CachedContent.get(name=cache_name)
                        c_model = genai.GenerativeModel.from_cached_content(cached_content=c_obj, safety_settings=safety_settings)
                        response = c_model.generate_content(dynamic_prompt)
                    else:
                        response = model.generate_content(f"{new_concept}\n{new_outline}\n{dynamic_prompt}")

                    if response.text:
                        st.session_state.editor_content = clean_text_formatting(response.text)
                        st.session_state.editor_mode = True
                        st.rerun()
                except Exception as e: st.error(f"Error: {e}")
    else:
        st.info("📝 Edit Mode")
        if st.button("🧹 Force Clean Formatting"):
            st.session_state.editor_content = clean_text_formatting(st.session_state.editor_content)
            st.rerun()
            
        edited_text = st.text_area(f"Editing Ch {next_chap_num}", height=600, key="editor_content")
        
        c1, c2 = st.columns([1,4])
        with c1:
            if st.button("💾 Save to Disk"):
                save_chapter(next_chap_num, edited_text)
                st.session_state.editor_mode = False
                del st.session_state.editor_content
                st.success("Saved to Database!")
                st.rerun()
        with c2:
            if st.button("❌ Discard"):
                st.session_state.editor_mode = False
                del st.session_state.editor_content
                st.rerun()

    # HISTORY & UNDO
    if history_list and not st.session_state.editor_mode:
        st.divider()
        st.write("### History")
        if st.button("Undo Last Saved Chapter"):
            delete_last_chapter(len(history_list))
            st.rerun()
        
        last = history_list[-1]
        st.caption(f"Last Saved: Chapter {last['chapter']}")
        st.text_area("Preview", value=last['content'], height=200, disabled=True)

# TAB 3: EXPORT (With DOCX Fix)
with tab3:
    st.header("The Full Manuscript")
    st.write("Use the **Word Doc** button below to preserve Italics for Atticus/Vellum.")
    
    col_tools1, col_tools2 = st.columns(2)
    with col_tools1:
        if st.button("🧹 Clean All Formatting"):
            full_text_history = clean_text_formatting(full_text_history)
            st.rerun()
    with col_tools2:
        if st.button("📄 Prepare Word Doc (Preserves Italics)"):
            # Generate the doc object
            doc = create_docx(full_text_history)
            
            # Save to memory buffer
            buffer = BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            
            st.download_button(
                label="⬇️ Download .docx (Atticus Ready)",
                data=buffer,
                file_name="my_novel.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

    st.text_area("Plain Text Preview", value=full_text_history, height=600)
