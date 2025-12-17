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
    c.execute('''CREATE TABLE IF NOT EXISTS book_info (
                    id INTEGER PRIMARY KEY,
                    concept TEXT,
                    outline TEXT
                )''')
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

# --- HELPER: "STRIP & REBUILD" TEXT CLEANER (The Fix) ---
def clean_text_formatting(text):
    """
    Splits text into lines, removes ALL whitespace-only lines,
    and rejoins them with exactly one blank line (Markdown standard).
    """
    if not text: return ""
    
    # 1. Split into individual lines
    lines = text.split('\n')
    
    # 2. Strip whitespace from every line & discard empty ones
    clean_lines = [line.strip() for line in lines if line.strip()]
    
    # 3. Join back together with exactly two newlines (Markdown paragraph break)
    # If you prefer TIGHTER text (no blank line), change '\n\n' to '\n' below.
    return '\n\n'.join(clean_lines)

# --- HELPER: DOCX BUILDER ---
def create_docx(full_text, title="My Novel"):
    doc = Document()
    doc.add_heading(title, 0)
    lines = full_text.split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
            
        if line.startswith("## Chapter"):
            doc.add_heading(line.replace("## ", "").strip(), level=1)
        elif line.startswith("## "):
            doc.add_heading(line.replace("## ", "").strip(), level=2)
        else:
            p = doc.add_paragraph()
            parts = re.split(r'(\*[^*]+\*)', line)
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
    
    # --- ROBUST IMPORTER ---
    with st.expander("⚠️ Emergency Import (Word Doc Fix)"):
        st.write("Paste full text. I will look for 'Chapter X'.")
        import_text = st.text_area("Paste Text Here", height=300)
        
        if st.button("Force Clean Import"):
            if import_text:
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM chapters")
                
                # Fixed Regex for Python 3.13
                chunks = re.split(r'(?i)(chapter\s+\d+)', import_text)
                
                current_chapter_num = 0
                current_content = ""
                
                for chunk in chunks:
                    if re.match(r'(?i)chapter\s+\d+', chunk.strip()):
                        if current_chapter_num > 0:
                            clean_content = clean_text_formatting(current_content)
                            if clean_content:
                                c.execute("INSERT INTO chapters (chapter_num, content) VALUES (?, ?)", 
                                          (current_chapter_num, clean_content))
                        current_chapter_num += 1
                        current_content = "" 
                    else:
                        current_content += chunk

                if current_chapter_num > 0:
                    clean_content = clean_text_formatting(current_content)
                    if clean_content:
                        c.execute("INSERT INTO chapters (chapter_num, content) VALUES (?, ?)", 
                                  (current_chapter_num, clean_content))

                conn.commit()
                conn.close()
                st.success(f"Imported {current_chapter_num} chapters! Refreshing...")
                st.rerun()

    if st.button("🔴 DANGER: Reset All Data"):
        reset_db()
        st.session_state.clear()
        st.rerun()

# --- STATE MANAGEMENT ---
if "editor_mode" not in st.session_state: st.session_state.editor_mode = False

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

    if st.button(f"🔮 Auto-Fetch Ch. {next_chap_num}"):
        with st.spinner("Fetching raw instructions..."):
            prompt = f"""
            Access the Outline. Copy the section for **Chapter {next_chap_num}** VERBATIM.
            Do not summarize. Extract specific Scene headers, POV, and details exactly as written.
            """
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
    chapter_instructions = st.text_area("Instructions:", value=current_plan, height=250)

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
                        # Clean BEFORE entering editor
                        st.session_state.editor_content = clean_text_formatting(response.text)
                        st.session_state.editor_mode = True
                        st.rerun()
                except Exception as e: st.error(f"Error: {e}")
    else:
        st.info("📝 Edit Mode")
        # UTILITY TO FIX SPACING MANUALLY
        if st.button("🧹 Strip & Rebuild Paragraphs (Fix Spacing)"):
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

    if history_list and not st.session_state.editor_mode:
        st.divider()
        st.write("### History")
        if st.button("Undo Last Saved Chapter"):
            delete_last_chapter(len(history_list))
            st.rerun()
        last = history_list[-1]
        st.caption(f"Last Saved: Chapter {last['chapter']}")
        st.text_area("Preview", value=last['content'], height=200, disabled=True)

# TAB 3: EXPORT
with tab3:
    st.header("The Full Manuscript")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧹 Clean Full Book"):
            full_text_history = clean_text_formatting(full_text_history)
            st.rerun()
    with col2:
        if st.button("📄 Download Word Doc (Best for Atticus)"):
            doc = create_docx(full_text_history)
            buffer = BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            st.download_button("Download .docx", buffer, "my_novel.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    st.text_area("Plain Text Preview", value=full_text_history, height=600)
