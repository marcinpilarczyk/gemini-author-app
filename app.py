import streamlit as st
import google.generativeai as genai
from google.generativeai import caching
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import datetime
import re
import sqlite3
from docx import Document
from io import BytesIO
import time

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Gemini 3 Author Studio", layout="wide")
st.title("Drafting with Gemini 3 Pro (Multi-Book Library)")

# --- DATABASE SETUP ---
DB_NAME = "my_novel.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 1. CREATE BOOKS TABLE (Replaces old book_info)
    c.execute('''CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT DEFAULT 'Untitled Book',
                    concept TEXT,
                    outline TEXT
                )''')

    # 2. CHECK FOR LEGACY DATA (book_info) AND MIGRATE
    # If the user has the old 'book_info' table, we move it to 'books' table as Book 1
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='book_info'")
    if c.fetchone():
        st.toast("Migrating database to Multi-Book format...", icon="📦")
        # Copy Concept/Outline
        try:
            c.execute("SELECT concept, outline FROM book_info WHERE id=1")
            row = c.fetchone()
            if row:
                c.execute("INSERT INTO books (id, title, concept, outline) VALUES (1, 'My First Book', ?, ?)", (row[0], row[1]))
            # Drop old table
            c.execute("DROP TABLE book_info")
        except Exception as e:
            print(f"Migration Note: {e}")

    # 3. CREATE/UPDATE CHAPTERS TABLE
    # We need to handle the schema change from (chapter_num PK) to (id PK, book_id, chapter_num)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chapters'")
    if not c.fetchone():
        # Fresh install
        c.execute('''CREATE TABLE chapters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        book_id INTEGER,
                        chapter_num INTEGER,
                        content TEXT,
                        summary TEXT,
                        FOREIGN KEY(book_id) REFERENCES books(id)
                    )''')
    else:
        # Check if book_id column exists
        c.execute("PRAGMA table_info(chapters)")
        columns = [info[1] for info in c.fetchall()]
        if 'book_id' not in columns:
            # LEGACY MIGRATION: Old table -> New Table
            st.toast("Upgrading chapters structure...", icon="⚙️")
            c.execute("ALTER TABLE chapters RENAME TO chapters_old")
            c.execute('''CREATE TABLE chapters (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            book_id INTEGER,
                            chapter_num INTEGER,
                            content TEXT,
                            summary TEXT,
                            FOREIGN KEY(book_id) REFERENCES books(id)
                        )''')
            # Move data, assigning everything to Book ID 1
            c.execute("INSERT INTO chapters (book_id, chapter_num, content, summary) SELECT 1, chapter_num, content, summary FROM chapters_old")
            c.execute("DROP TABLE chapters_old")

    conn.commit()
    conn.close()

def get_all_books():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, title FROM books ORDER BY id")
    books = c.fetchall()
    conn.close()
    return books

def create_new_book(title):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO books (title, concept, outline) VALUES (?, '', '')", (title,))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id

def load_active_book(book_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM books WHERE id=?", (book_id,))
    book = c.fetchone()
    c.execute("SELECT * FROM chapters WHERE book_id=? ORDER BY chapter_num", (book_id,))
    chapters = c.fetchall()
    conn.close()
    return book, chapters

def update_book_meta(book_id, title, concept, outline):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE books SET title=?, concept=?, outline=? WHERE id=?", (title, concept, outline, book_id))
    conn.commit()
    conn.close()

def save_chapter(book_id, num, content, summary=""):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Check if exists
    c.execute("SELECT id, summary FROM chapters WHERE book_id=? AND chapter_num=?", (book_id, num))
    existing = c.fetchone()
    
    if existing:
        # Update
        current_sum = summary if summary else (existing[1] if existing[1] else "")
        c.execute("UPDATE chapters SET content=?, summary=? WHERE id=?", (content, current_sum, existing[0]))
    else:
        # Insert
        c.execute("INSERT INTO chapters (book_id, chapter_num, content, summary) VALUES (?, ?, ?, ?)", 
                  (book_id, num, content, summary))
    conn.commit()
    conn.close()

def delete_last_chapter(book_id, num):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM chapters WHERE book_id=? AND chapter_num=?", (book_id, num))
    conn.commit()
    conn.close()

def reset_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS books")
    c.execute("DROP TABLE IF EXISTS chapters")
    conn.commit()
    conn.close()

# Initialize DB (Run Migrations)
init_db()

# --- HARDCODED ENGINE ---
MODEL_NAME = "gemini-3-pro-preview"

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- AGENTS & HELPERS ---
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
    except Exception as e: return f"Summary Error: {e}"

def normalize_text(text, mode="standard"):
    if not text: return ""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    paragraphs = re.split(r'\n\s*\n', text)
    clean_paragraphs = [p.strip() for p in paragraphs if p.strip()]
    if mode == "tight": return '\n'.join(clean_paragraphs)
    else: return '\n\n'.join(clean_paragraphs)

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
                else: p.add_run(part)
    return doc

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

# --- SIDEBAR & NAVIGATION ---
with st.sidebar:
    st.header("🔑 Settings")
    st.caption(f"🚀 Engine: **{MODEL_NAME}**")
    
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        api_key = st.text_input("Enter Google API Key", type="password")

    st.divider()
    
    # --- BOOK MANAGER ---
    st.subheader("📚 Library")
    
    # Initialize active book state
    all_books = get_all_books()
    if not all_books:
        # Create default if empty DB
        first_id = create_new_book("My First Book")
        st.session_state.active_book_id = first_id
        st.rerun()
    
    # Helper to sync selectbox with session state
    if "active_book_id" not in st.session_state:
        st.session_state.active_book_id = all_books[0]['id']

    # Book Selector
    book_options = {b['id']: b['title'] for b in all_books}
    selected_id = st.selectbox(
        "Current Book", 
        options=book_options.keys(), 
        format_func=lambda x: book_options[x],
        index=list(book_options.keys()).index(st.session_state.active_book_id) if st.session_state.active_book_id in book_options else 0
    )
    
    if selected_id != st.session_state.active_book_id:
        st.session_state.active_book_id = selected_id
        st.session_state.cache_name = None # Clear cache when switching books
        st.rerun()

    # New Book Button
    with st.popover("➕ New Book"):
        new_title = st.text_input("Book Title", "Untitled Book")
        if st.button("Create"):
            new_id = create_new_book(new_title)
            st.session_state.active_book_id = new_id
            st.session_state.cache_name = None
            st.success("Created!")
            time.sleep(0.5)
            st.rerun()

    st.divider()
    
    # --- IMPORT/EXPORT TOOLS ---
    with st.expander("⚠️ Emergency Import"):
        st.write("Paste text. Splits by 'Chapter X'.")
        import_text = st.text_area("Paste Text", height=200)
        if st.button("Force Import"):
            if import_text:
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                # Clear ONLY active book chapters
                c.execute("DELETE FROM chapters WHERE book_id=?", (st.session_state.active_book_id,))
                
                chunks = re.split(r'(?i)(chapter\s+\d+)', import_text)
                cur_n = 0
                cur_c = ""
                for chunk in chunks:
                    if re.match(r'(?i)chapter\s+\d+', chunk.strip()):
                        if cur_n > 0:
                            cl = normalize_text(cur_c)
                            if cl: c.execute("INSERT INTO chapters (book_id, chapter_num, content, summary) VALUES (?, ?, ?, ?)", (st.session_state.active_book_id, cur_n, cl, ""))
                        cur_n += 1
                        cur_c = "" 
                    else: cur_c += chunk
                if cur_n > 0:
                    cl = normalize_text(cur_c)
                    if cl: c.execute("INSERT INTO chapters (book_id, chapter_num, content, summary) VALUES (?, ?, ?, ?)", (st.session_state.active_book_id, cur_n, cl, ""))
                conn.commit()
                conn.close()
                st.success(f"Imported {cur_n} chapters to active book!")
                st.rerun()

    if st.button("⚡ Backfill Memories"):
        if not api_key: st.error("Need Key")
        else:
            genai.configure(api_key=api_key)
            conn = sqlite3.connect(DB_NAME)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            # Only Active Book
            c.execute("SELECT * FROM chapters WHERE book_id=? AND content IS NOT NULL", (st.session_state.active_book_id,))
            rows = c.fetchall()
            bar = st.progress(0)
            cnt = 0
            for i, r in enumerate(rows):
                if not r['summary'] or len(r['summary']) < 10:
                    s = generate_summary(r['content'])
                    c2 = conn.cursor()
                    c2.execute("UPDATE chapters SET summary=? WHERE id=?", (s, r['id']))
                    conn.commit()
                    cnt += 1
                bar.progress((i+1)/len(rows))
            conn.close()
            st.success(f"Updated {cnt} memories.")
            st.rerun()
            
    if st.button("🔴 Nuklear Reset (All Data)"):
        reset_db()
        st.session_state.clear()
        st.rerun()

# --- MAIN APP LOGIC ---
if not api_key:
    st.warning("👈 Please enter your API Key in the sidebar.")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)

if "editor_mode" not in st.session_state: st.session_state.editor_mode = False

# LOAD ACTIVE BOOK DATA
active_book, chapter_data = load_active_book(st.session_state.active_book_id)

current_title = active_book['title']
current_concept = active_book['concept']
current_outline = active_book['outline']

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

# --- TABS ---
st.subheader(f"📖 {current_title}")
tab1, tab2, tab3, tab4 = st.tabs(["1. The Bible", "2. Writer", "3. Full Book", "4. Publisher"])

# TAB 1: BIBLE
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        # Title Edit
        new_title_in = st.text_input("Title", value=current_title)
        new_concept = st.text_area("Concept", value=current_concept, height=400)
    with col2:
        st.write("") # Spacer to align with title input
        st.write("")
        st.write("") # Spacer
        new_outline = st.text_area("Outline", value=current_outline, height=400)
    
    if new_concept != current_concept or new_outline != current_outline or new_title_in != current_title:
        if st.button("💾 Save Bible Changes"):
            update_book_meta(st.session_state.active_book_id, new_title_in, new_concept, new_outline)
            st.rerun()

# TAB 2: WRITER
with tab2:
    next_chap_num = len(history_list) + 1
    st.header(f"Drafting Chapter {next_chap_num}")
    
    if st.button(f"🔮 Auto-Fetch Ch. {next_chap_num}"):
        with st.spinner("Fetching..."):
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
    chapter_instructions = st.text_area("Instructions:", value=current_plan, height=150)

    if not st.session_state.editor_mode:
        if st.button(f"🚀 Generate Chapter {next_chap_num}", type="primary"):
            with st.spinner("Writing..."):
                cache_name = get_or_create_cache(new_concept, new_outline)
                smart_context = f"### STORY LEDGER\n{rolling_summary_context}\n### PREVIOUS TEXT\n...{last_chapter_raw[-3000:] if last_chapter_raw else 'Start.'}"
                dynamic_prompt = f"### CONTEXT\n{smart_context}\n### PLAN\n{chapter_instructions}\n### TASK\nWrite Chapter {next_chap_num}. Use '***' for breaks."
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
        st.caption(f"Count: {len(st.session_state.editor_content.split())} words")
        
        c_ctrl1, c_ctrl2 = st.columns([1,1])
        with c_ctrl1:
            sp_mode = st.radio("Spacing", ["Standard", "Tight"], horizontal=True)
        with c_ctrl2:
            st.write("")
            if st.button("✨ Apply Format"):
                m = "tight" if "Tight" in sp_mode else "standard"
                st.session_state.editor_content = normalize_text(st.session_state.editor_content, mode=m)
                st.rerun()

        edited_text = st.text_area(f"Editing Ch {next_chap_num}", height=600, key="editor_content")
        
        c1, c2 = st.columns([1,4])
        with c1:
            if st.button("💾 Save"):
                with st.spinner("Saving..."):
                    sm = generate_summary(edited_text)
                    save_chapter(st.session_state.active_book_id, next_chap_num, edited_text, sm)
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
            delete_last_chapter(st.session_state.active_book_id, len(history_list))
            st.rerun()
        last = history_list[-1]
        with st.expander(f"Chapter {last['chapter_num']} View"):
            st.info(last['summary'])
            st.text_area("Read", value=last['content'], height=200, disabled=True)

# TAB 3: MANUSCRIPT
with tab3:
    c1, c2, c3 = st.columns([1,1,1])
    with c1:
        f_mode = st.radio("Global Spacing", ["Standard", "Tight"], key="glob_sp")
    with c2:
        st.write("")
        if st.button("✨ Update Preview"):
            m = "tight" if "Tight" in f_mode else "standard"
            full_text_history = normalize_text(full_text_history, mode=m)
            st.success("Updated!")
    with c3:
        st.write("")
        if st.button("📄 Word Export"):
            doc = create_docx(full_text_history, current_title)
            buf = BytesIO()
            doc.save(buf)
            buf.seek(0)
            st.download_button("Download .docx", buf, f"{current_title}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    st.text_area("Full Text", value=full_text_history, height=600)

# TAB 4: PUBLISHER
with tab4:
    st.header("🚀 Algorithmic Publisher")
    st.markdown("Generates A9/Rufus-optimized metadata.")
    
    if "pub_genre" not in st.session_state: st.session_state.pub_genre = ""
    if "pub_tropes" not in st.session_state: st.session_state.pub_tropes = ""
    if "pub_tone" not in st.session_state: st.session_state.pub_tone = "Serious"

    if st.button("🧬 Analyze Book DNA"):
        with st.spinner("Analyzing..."):
            d_prompt = f"Analyze:\n{current_concept}\n{current_outline}\n{rolling_summary_context}\nReturn: GENRE: [x]\nTROPES: [x]\nTONE: [x]"
            try:
                # Agent uses main model (3 Pro)
                res = model.generate_content(d_prompt).text
                try:
                    g = res.split("GENRE:")[1].split("TROPES:")[0].strip()
                    tr = res.split("TROPES:")[1].split("TONE:")[0].strip()
                    to = res.split("TONE:")[1].strip()
                    st.session_state.pub_genre = g
                    st.session_state.pub_tropes = tr
                    st.session_state.pub_tone = to
                    st.success("Done!")
                    st.rerun()
                except: st.error("Format error")
            except Exception as e: st.error(str(e))

    c1, c2 = st.columns(2)
    with c1:
        p_genre = st.text_input("Genre", key="pub_genre")
    with c2:
        p_tropes = st.text_input("Tropes", key="pub_tropes")
        p_tone = st.text_input("Tone", key="pub_tone")

    if st.button("⚡ Generate Package"):
        if not full_text_history: st.error("Write content first!")
        else:
            with st.spinner("Generating..."):
                m_prompt = f"""
                Optimize for KDP/Rufus.
                Title: {current_title}
                Genre: {p_genre}
                Tropes: {p_tropes}
                Tone: {p_tone}
                Sample: {full_text_history[:5000]}
                TASK 1: 7 Semantic Keywords.
                TASK 2: Hybrid Blurb (Hook, Context, Heart, Selling).
                """
                try:
                    res = model.generate_content(m_prompt)
                    st.session_state.marketing_result = res.text
                    st.rerun()
                except Exception as e: st.error(str(e))

    if "marketing_result" in st.session_state:
        st.divider()
        st.text_area("Result", value=st.session_state.marketing_result, height=600)
