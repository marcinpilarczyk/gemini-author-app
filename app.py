import streamlit as st
import google.generativeai as genai
from google.generativeai import caching
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import datetime
import re
import sqlite3

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
    text = re.sub(r'\n\s*\n', '\n\n', text) # The nuclear spacer fixer
    return text.strip()

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
    
    # RESTORE TOOL
    with st.expander("⚠️ Emergency Import"):
        st.write("Lost your session? Paste your backup text here to restore history.")
        import_text = st.text_area("Paste Full Book Text")
        if st.button("Import & Rebuild"):
            if import_text:
                # Basic splitter by "## Chapter X"
                chapters = re.split(r'## Chapter \d+', import_text)
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM chapters") # Clear current
                for i, content in enumerate(chapters):
                    if content.strip():
                        c.execute("INSERT INTO chapters (chapter_num, content) VALUES (?, ?)", (i, content.strip()))
                conn.commit()
                conn.close()
                st.success("Book Restored! Please refresh.")

# --- STATE MANAGEMENT ---
if "editor_mode" not in st.session_state: st.session_state.editor_mode = False

# LOAD DATA FROM DB
bible_data, chapter_data = load_from_db()

# Rebuild Session State from DB
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

# TAB 1: BIBLE (Auto-Saves)
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
                Write Chapter {next_chap_num}. Use '***' for scene breaks.
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
        if st.button("🧹 Re-Clean Formatting"):
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

# TAB 3: EXPORT
with tab3:
    st.header("The Full Manuscript")
    st.text_area("Full Book", value=full_text_history, height=600)
    st.download_button("Download .txt", full_text_history, "my_book.txt")
