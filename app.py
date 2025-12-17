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
st.title("Drafting with Gemini 3 Pro (Full Studio Edition)")

# --- DATABASE SETUP ---
DB_NAME = "my_novel.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # BOOKS TABLE
    c.execute('''CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT DEFAULT 'Untitled Book',
                    concept TEXT,
                    outline TEXT
                )''')

    # MIGRATION CHECK (Legacy -> Multi-Book)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='book_info'")
    if c.fetchone():
        try:
            c.execute("SELECT concept, outline FROM book_info WHERE id=1")
            row = c.fetchone()
            if row:
                c.execute("INSERT INTO books (id, title, concept, outline) VALUES (1, 'My First Book', ?, ?)", (row[0], row[1]))
            c.execute("DROP TABLE book_info")
        except: pass

    # CHAPTERS TABLE
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chapters'")
    if not c.fetchone():
        c.execute('''CREATE TABLE chapters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        book_id INTEGER,
                        chapter_num INTEGER,
                        content TEXT,
                        summary TEXT,
                        FOREIGN KEY(book_id) REFERENCES books(id)
                    )''')
    else:
        # Check for book_id column
        c.execute("PRAGMA table_info(chapters)")
        cols = [i[1] for i in c.fetchall()]
        if 'book_id' not in cols:
            c.execute("ALTER TABLE chapters RENAME TO chapters_old")
            c.execute('''CREATE TABLE chapters (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            book_id INTEGER,
                            chapter_num INTEGER,
                            content TEXT,
                            summary TEXT,
                            FOREIGN KEY(book_id) REFERENCES books(id)
                        )''')
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

# --- CRITICAL FIX: Missing function added here ---
def get_chapters(book_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM chapters WHERE book_id=? ORDER BY chapter_num ASC", (book_id,))
    chapters = c.fetchall()
    conn.close()
    return chapters
# -------------------------------------------------

def update_book_meta(book_id, title, concept, outline):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE books SET title=?, concept=?, outline=? WHERE id=?", (title, concept, outline, book_id))
    conn.commit()
    conn.close()

def save_chapter(book_id, num, content, summary=""):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, summary FROM chapters WHERE book_id=? AND chapter_num=?", (book_id, num))
    existing = c.fetchone()
    if existing:
        # Update existing chapter (preserve summary if not provided)
        current_sum = summary if summary else (existing[1] if existing[1] else "")
        c.execute("UPDATE chapters SET content=?, summary=? WHERE id=?", (content, current_sum, existing[0]))
    else:
        # Insert new chapter
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

init_db()

# --- HARDCODED ENGINE ---
MODEL_NAME = "gemini-1.5-pro-latest" # Standard stable model name

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- HELPERS ---
def generate_summary(chapter_text):
    if not chapter_text: return ""
    prompt = f"Analyze strictly for continuity:\n{chapter_text[:12000]}\nOutput: 1. Facts/Items/Injuries. 2. Pacing."
    try:
        model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)
        return model.generate_content(prompt).text
    except Exception as e: return f"Error: {e}"

def normalize_text(text, mode="standard"):
    if not text: return ""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    paragraphs = re.split(r'\n\s*\n', text)
    clean_paragraphs = [p.strip() for p in paragraphs if p.strip()]
    if mode == "tight": return '\n'.join(clean_paragraphs)
    else: return '\n\n'.join(clean_paragraphs)

def create_docx(full_text, title):
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
    static_content = f"### BIBLE\n{bible_text}\n\n### OUTLINE\n{outline_text}"
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
    except: return None

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Settings")
    st.caption(f"🚀 Engine: **{MODEL_NAME}**")
    if "GOOGLE_API_KEY" in st.secrets: api_key = st.secrets["GOOGLE_API_KEY"]
    else: api_key = st.text_input("Enter Google API Key", type="password")
    
    st.divider()
    st.subheader("📚 Library")
    
    all_books = get_all_books()
    if not all_books:
        first_id = create_new_book("My First Book")
        st.session_state.active_book_id = first_id
        st.rerun()
    
    if "active_book_id" not in st.session_state:
        st.session_state.active_book_id = all_books[0]['id']

    book_opts = {b['id']: b['title'] for b in all_books}
    sel_id = st.selectbox("Current Book", options=book_opts.keys(), format_func=lambda x: book_opts[x], index=list(book_opts.keys()).index(st.session_state.active_book_id) if st.session_state.active_book_id in book_opts else 0)
    
    if sel_id != st.session_state.active_book_id:
        st.session_state.active_book_id = sel_id
        st.session_state.cache_name = None
        st.rerun()

    with st.popover("➕ New Book"):
        nt = st.text_input("Title", "Untitled")
        if st.button("Create"):
            nid = create_new_book(nt)
            st.session_state.active_book_id = nid
            st.rerun()

    st.divider()
    
    with st.expander("⚠️ Import"):
        imp_txt = st.text_area("Paste Text", height=200)
        if st.button("Import"):
            if imp_txt:
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM chapters WHERE book_id=?", (st.session_state.active_book_id,))
                chunks = re.split(r'(?i)(chapter\s+\d+)', imp_txt)
                cn, cc = 0, ""
                for ch in chunks:
                    if re.match(r'(?i)chapter\s+\d+', ch.strip()):
                        if cn > 0:
                            cl = normalize_text(cc)
                            if cl: c.execute("INSERT INTO chapters (book_id, chapter_num, content, summary) VALUES (?, ?, ?, ?)", (st.session_state.active_book_id, cn, cl, ""))
                        cn += 1
                        cc = ""
                    else: cc += ch
                if cn > 0:
                    cl = normalize_text(cc)
                    if cl: c.execute("INSERT INTO chapters (book_id, chapter_num, content, summary) VALUES (?, ?, ?, ?)", (st.session_state.active_book_id, cn, cl, ""))
                conn.commit()
                conn.close()
                st.success("Imported!")
                st.rerun()

    if st.button("⚡ Backfill Memory"):
        if not api_key: st.error("Need Key")
        else:
            genai.configure(api_key=api_key)
            conn = sqlite3.connect(DB_NAME)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM chapters WHERE book_id=? AND content IS NOT NULL", (st.session_state.active_book_id,))
            rows = c.fetchall()
            bar = st.progress(0)
            for i, r in enumerate(rows):
                if not r['summary'] or len(r['summary']) < 10:
                    s = generate_summary(r['content'])
                    c2 = conn.cursor()
                    c2.execute("UPDATE chapters SET summary=? WHERE id=?", (s, r['id']))
                    conn.commit()
                bar.progress((i+1)/len(rows))
            conn.close()
            st.success("Done!")
            st.rerun()

    if st.button("🔴 Reset DB"):
        reset_db()
        st.session_state.clear()
        st.rerun()

# --- MAIN ---
if not api_key:
    st.warning("👈 Enter API Key")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)

if "editor_mode" not in st.session_state: st.session_state.editor_mode = False

active_book, chapter_data = load_active_book(st.session_state.active_book_id)
current_title = active_book['title']
current_concept = active_book['concept']
current_outline = active_book['outline']

full_text = ""
rolling_sum = ""
last_raw = ""
history_list = []
existing_chapters = {}

for r in chapter_data:
    history_list.append(r)
    existing_chapters[r['chapter_num']] = r['content']
    full_text += f"\n\n## Chapter {r['chapter_num']}\n\n{r['content']}"
    if r['summary']: rolling_sum += f"\n\n**Ch {r['chapter_num']}:**\n{r['summary']}"
    last_raw = r['content']

st.subheader(f"📖 {current_title}")
t1, t2, t3, t4, t5 = st.tabs(["1. Bible", "2. Writer", "3. Manuscript", "4. Publisher", "5. Editor"])

# TAB 1: BIBLE
with t1:
    c1, c2 = st.columns(2)
    with c1:
        nti = st.text_input("Title", value=current_title)
        nc = st.text_area("Concept", value=current_concept, height=400)
    with c2:
        st.write(""); st.write(""); st.write("")
        no = st.text_area("Outline", value=current_outline, height=400)
    if nc!=current_concept or no!=current_outline or nti!=current_title:
        if st.button("💾 Save Bible"):
            update_book_meta(st.session_state.active_book_id, nti, nc, no)
            st.rerun()

# TAB 2: WRITER
with t2:
    # CHAPTER SELECTOR
    default_next = len(history_list) + 1
    
    if "selected_chap" not in st.session_state:
        st.session_state.selected_chap = default_next
        
    c_sel1, c_sel2 = st.columns([1, 4])
    with c_sel1:
        chap_num = st.number_input("Chapter #", min_value=1, value=st.session_state.selected_chap, step=1)
        st.session_state.selected_chap = chap_num
    with c_sel2:
        st.write("")
        st.write("")
        # If chapter exists, show LOAD button
        if chap_num in existing_chapters and not st.session_state.editor_mode:
            if st.button(f"✏️ Load Chapter {chap_num} for Editing"):
                st.session_state.ed_con = existing_chapters[chap_num]
                st.session_state.editor_mode = True
                st.rerun()
    
    st.divider()

    # AUTO-FETCH
    if st.button(f"🔮 Auto-Fetch Plan for Ch {chap_num}"):
        with st.spinner("Fetching..."):
            p = f"Access Outline. Copy section for **Chapter {chap_num}** VERBATIM. Do not summarize."
            try:
                cn = get_or_create_cache(nc, no)
                if cn:
                    co = genai.caching.CachedContent.get(name=cn)
                    cm = genai.GenerativeModel.from_cached_content(cached_content=co)
                    res = cm.generate_content(p)
                else: res = model.generate_content(f"{no}\n\n{p}")
                st.session_state[f"pl_{chap_num}"] = res.text
                st.rerun()
            except: st.error("Error")
    
    cp = st.session_state.get(f"pl_{chap_num}", "")
    ci = st.text_area("Chapter Plan / Instructions", value=cp, height=150)

    # GENERATOR
    if not st.session_state.editor_mode:
        btn_label = f"🚀 Write Chapter {chap_num}" if chap_num not in existing_chapters else f"🔄 Re-Write Chapter {chap_num} (Overwrites)"
        
        if st.button(btn_label, type="primary"):
            with st.spinner("Writing..."):
                cn = get_or_create_cache(nc, no)
                ctx = f"### LEDGER\n{rolling_sum}\n### PREV TEXT\n...{last_raw[-3000:] if last_raw else 'Start.'}"
                dp = f"### CONTEXT\n{ctx}\n### PLAN\n{ci}\n### TASK\nWrite Ch {chap_num}. Use '***' breaks."
                try:
                    if cn:
                        co = genai.caching.CachedContent.get(name=cn)
                        cm = genai.GenerativeModel.from_cached_content(cached_content=co, safety_settings=safety_settings)
                        res = cm.generate_content(dp)
                    else: res = model.generate_content(f"{nc}\n{no}\n{dp}")
                    if res.text:
                        st.session_state.ed_con = normalize_text(res.text, "standard")
                        st.session_state.editor_mode = True
                        st.rerun()
                except: st.error("Error")
    else:
        # EDITOR MODE
        st.info(f"📝 Editing Chapter {chap_num}")
        st.caption(f"Words: {len(st.session_state.ed_con.split())}")
        cm1, cm2 = st.columns([1,1])
        with cm1: sp = st.radio("Spacing", ["Standard", "Tight"], horizontal=True)
        with cm2: 
            st.write("")
            if st.button("✨ Format"):
                m = "tight" if "Tight" in sp else "standard"
                st.session_state.ed_con = normalize_text(st.session_state.ed_con, m)
                st.rerun()
        et = st.text_area("Editor", height=600, key="ed_con")
        c1, c2 = st.columns([1,4])
        with c1:
            if st.button("💾 Save"):
                with st.spinner("Saving..."):
                    sm = generate_summary(et)
                    save_chapter(st.session_state.active_book_id, chap_num, et, sm)
                    st.session_state.editor_mode = False
                    del st.session_state.ed_con
                    st.success(f"Chapter {chap_num} Saved!")
                    st.rerun()
        with c2:
            if st.button("❌ Discard"):
                st.session_state.editor_mode = False
                del st.session_state.ed_con
                st.rerun()

    if history_list and not st.session_state.editor_mode:
        st.divider()
        # Fetch the chapters so 'hist' is defined and valid
        hist = get_chapters(st.session_state.active_book_id) 

        if st.button("Undo Last Added Chapter"):
            delete_last_chapter(st.session_state.active_book_id, len(hist))
            st.rerun()

        # Only try to show the last chapter if 'hist' is not empty
        if hist:
            l = hist[-1]
            with st.expander(f"Ch {l['chapter_num']} View"):
                st.info(l['summary'])
                st.text_area("Read", value=l['content'], height=200, disabled=True)

# TAB 3: MANUSCRIPT
with t3:
    c1, c2, c3 = st.columns([1,1,1])
    with c1: fm = st.radio("Global Sp", ["Standard", "Tight"], key="gsp")
    with c2: 
        st.write("")
        if st.button("✨ Update"):
            m = "tight" if "Tight" in fm else "standard"
            full_text = normalize_text(full_text, m)
            st.success("Updated")
    with c3:
        st.write("")
        if st.button("📄 Word"):
            d = create_docx(full_text, current_title)
            b = BytesIO(); d.save(b); b.seek(0)
            st.download_button("Download", b, f"{current_title}.docx")
    st.text_area("Full Text", value=full_text, height=600)

# TAB 4: PUBLISHER
with t4:
    st.header("🚀 Publisher")
    if "pg" not in st.session_state: st.session_state.pg = ""
    if "pt" not in st.session_state: st.session_state.pt = ""
    if "pto" not in st.session_state: st.session_state.pto = "Serious"

    if st.button("🧬 Analyze DNA"):
        with st.spinner("Analyzing..."):
            dprom = f"Analyze:\n{nc}\n{no}\n{rolling_sum}\nReturn: GENRE: [x]\nTROPES: [x]\nTONE: [x]"
            try:
                res = model.generate_content(dprom).text
                st.session_state.pg = res.split("GENRE:")[1].split("TROPES:")[0].strip()
                st.session_state.pt = res.split("TROPES:")[1].split("TONE:")[0].strip()
                st.session_state.pto = res.split("TONE:")[1].strip()
                st.rerun()
            except: st.error("Error")

    c1, c2 = st.columns(2)
    with c1: pg = st.text_input("Genre", key="pg")
    with c2: pt = st.text_input("Tropes", key="pt"); pto = st.text_input("Tone", key="pto")

    if st.button("⚡ Generate Package"):
        with st.spinner("Generating..."):
            mp = f"Optimize KDP.\nTitle:{current_title}\nGenre:{pg}\nTropes:{pt}\nTone:{pto}\nText:{full_text[:5000]}\nOutput: 7 Keywords + Hybrid Blurb."
            try:
                st.session_state.mres = model.generate_content(mp).text
                st.rerun()
            except: st.error("Error")
    
    if "mres" in st.session_state:
        st.divider(); st.text_area("Result", value=st.session_state.mres, height=600)

# TAB 5: EDITOR
with t5:
    st.header("🧐 The Continuity Editor")
    st.markdown("Scans the entire manuscript for inconsistencies, timeline errors, and plot holes.")
    
    # CRITICAL FIX: Increased max tokens and slightly raised temperature
    strict_config = genai.types.GenerationConfig(
        temperature=0.2,            
        top_p=0.95,
        max_output_tokens=8192
    )

    if st.button("🔍 Run Full Manuscript Scan"):
        if not full_text or len(full_text) < 500:
            st.error("Manuscript too short to scan.")
        else:
            with st.spinner("Reading full text and checking against Bible..."):
                editor_prompt = f"""
                You are a ruthless Continuity Editor. You do not write; you only check logic.
                
                ### THE BIBLE (RULES)
                {current_concept}
                {current_outline}
                
                ### THE MANUSCRIPT (TEXT)
                {full_text}
                
                ### TASK
                Analyze the manuscript for inconsistencies. 
                CRITICAL RULE: You must QUOTE the exact sentence from the text that proves the error. 
                If you cannot find a direct quote to support the error, DO NOT report it.
                
                Look for:
                1. **Character Errors**: Dead people reappearing, eye color changing, names swapping.
                2. **Timeline Errors**: Impossible travel times, day/night confusion.
                3. **Bible Contradictions**: Plot points that violate the outline rules.
                
                ### OUTPUT FORMAT
                If no errors are found, write "NO CRITICAL ERRORS FOUND."
                
                **Severity 1 (Critical Logic Breaks):**
                - [Chapter X]: [Error Summary]
                  *Evidence:* "[Quote from text showing the error]"
                
                **Severity 2 (Minor Inconsistencies):**
                - [Chapter X]: [Error Summary]
                  *Evidence:* "[Quote from text]"
                """
                
                try:
                    cache_name = get_or_create_cache(current_concept, current_outline)
                    if cache_name:
                        c_obj = genai.caching.CachedContent.get(name=cache_name)
                        c_model = genai.GenerativeModel.from_cached_content(cached_content=c_obj)
                        response = c_model.generate_content(editor_prompt, generation_config=strict_config)
                    else:
                        response = model.generate_content(editor_prompt, generation_config=strict_config)
                        
                    # CRITICAL FIX: Graceful handling of empty responses
                    if response.text:
                        st.session_state.editor_report = response.text
                        st.rerun()
                    else:
                        st.warning(f"Scan interrupted. The model finished but returned no text. (Status: {response.candidates[0].finish_reason})")
                
                except Exception as e:
                    st.error(f"Scan failed: {e}")

    if "editor_report" in st.session_state:
        st.divider()
        st.subheader("📋 Editor Report")
        st.markdown(st.session_state.editor_report)
