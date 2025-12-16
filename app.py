import streamlit as st
import google.generativeai as genai
from google.generativeai import caching
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import datetime
import re

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Gemini 3 Author Studio", layout="wide")

st.title("Drafting with Gemini 3 Pro")
st.markdown("Advanced Chapter Drafting with **Edit Mode** & **Context Caching**.")

# --- HARDCODED MODEL ---
MODEL_NAME = "gemini-3-pro-preview"

# --- SAFETY SETTINGS ---
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- HELPER: TEXT CLEANER ---
def clean_text_formatting(text):
    """
    Aggressive cleaner:
    1. Replaces any sequence of newlines (with or without spaces) with exactly two newlines.
    2. Strips leading/trailing whitespace.
    """
    if not text: return ""
    # Regex explanation: \n followed by any amount of whitespace (\s*) followed by \n
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

# --- HELPER: CACHING ---
def get_or_create_cache(bible_text, outline_text):
    static_content = f"### THE BIBLE (Static Context)\n{bible_text}\n\n### THE FULL OUTLINE\n{outline_text}"
    
    if 'cache_name' in st.session_state:
        try:
            cache = genai.caching.CachedContent.get(name=st.session_state.cache_name)
            cache.update(ttl=datetime.timedelta(hours=2))
            return cache.name
        except Exception:
            del st.session_state.cache_name

    try:
        cache = genai.caching.CachedContent.create(
            model=MODEL_NAME, 
            display_name="book_bible_v1", 
            system_instruction="You are an expert novelist. Use this bible to write chapters.",
            contents=[static_content],
            ttl=datetime.timedelta(hours=2)
        )
        st.session_state.cache_name = cache.name
        st.toast(f"✅ Bible Cached for {MODEL_NAME}!", icon="💾")
        return cache.name
    except Exception as e:
        print(f"Cache Warning: {e}")
        return None

# --- SIDEBAR ---
with st.sidebar:
    st.header("Settings")
    
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        st.success("✅ API Key loaded securely.")
    else:
        api_key = st.text_input("Enter Google API Key", type="password")
    
    st.info(f"⚡ Using Model: **{MODEL_NAME}**")
    
    st.divider()
    
    if st.button("Undo Last Confirmed Chapter", type="secondary"):
        if len(st.session_state.book_history) > 0:
            deleted = st.session_state.book_history.pop()
            st.session_state.full_text = ""
            for chap in st.session_state.book_history:
                st.session_state.full_text += f"\n\n## Chapter {chap['chapter']}\n\n{chap['content']}"
            st.toast(f"🗑️ Deleted Chapter {deleted['chapter']}", icon="undo")
            st.rerun()
        else:
            st.error("No history to undo!")

    if st.button("⚠️ Reset Entire Book", type="primary"):
        st.session_state.clear()
        st.rerun()

# --- INITIALIZATION ---
if "book_history" not in st.session_state:
    st.session_state.book_history = [] 
if "full_text" not in st.session_state:
    st.session_state.full_text = ""
if "editor_mode" not in st.session_state:
    st.session_state.editor_mode = False

# --- APP START ---
if not api_key:
    st.warning("Waiting for API Key...")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)

tab1, tab2, tab3 = st.tabs(["1. The Bible", "2. Writer (Edit Mode)", "3. Full Book"])

# --- TAB 1: BIBLE ---
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Concept / Style")
        concept_text = st.text_area("Style Guide, Characters, World:", height=400, key="concept", value=st.session_state.get("concept", ""))
    with col2:
        st.subheader("Master Outline")
        outline_text = st.text_area("Full Outline:", height=400, key="outline", value=st.session_state.get("outline", ""))

# --- TAB 2: WRITER ---
with tab2:
    next_chap_num = len(st.session_state.book_history) + 1
    st.header(f"Drafting Chapter {next_chap_num}")
    
    # 2. AUTO-FETCH (FIXED PROMPT)
    if st.button(f"🔮 Auto-Fetch Instructions for Ch. {next_chap_num}"):
        if not outline_text:
            st.error("Outline is empty!")
        else:
            with st.spinner("Scanning outline..."):
                try:
                    # NEW PROMPT: Forces verbatim extraction
                    prompt = f"""
                    Access the Full Outline provided in the context.
                    Locate the section for **Chapter {next_chap_num}**.
                    
                    **TASK:** Copy the content for Chapter {next_chap_num} EXACTLY as it appears. 
                    Include all Scene headers, POVs, Word Counts, Settings, and details.
                    DO NOT summarize. DO NOT shorten. Just extract the raw text block.
                    """
                    
                    # We use the CACHE here if possible to ensure it sees the full outline
                    cache_name = get_or_create_cache(concept_text, outline_text)
                    if cache_name:
                        cache_obj = genai.caching.CachedContent.get(name=cache_name)
                        cached_model = genai.GenerativeModel.from_cached_content(cached_content=cache_obj)
                        response = cached_model.generate_content(prompt)
                    else:
                        response = model.generate_content(f"{outline_text}\n\n{prompt}")

                    if response.text:
                        st.session_state[f"plan_{next_chap_num}"] = response.text
                        st.rerun()
                except Exception as e:
                    st.error(f"Fetch Error: {e}")

    # 3. INSTRUCTIONS
    current_plan = st.session_state.get(f"plan_{next_chap_num}", "")
    chapter_instructions = st.text_area("Chapter Instructions:", value=current_plan, height=300)

    # 4. GENERATION ACTION
    if not st.session_state.editor_mode:
        if st.button(f"🚀 Generate Chapter {next_chap_num}", type="primary"):
            with st.spinner("Gemini 3 is writing..."):
                try:
                    cache_name = get_or_create_cache(concept_text, outline_text)
                    
                    dynamic_prompt = f"""
                    ### STORY SO FAR
                    {st.session_state.full_text}
                    
                    ### CHAPTER INSTRUCTIONS
                    {chapter_instructions}
                    
                    ### TASK
                    Write Chapter {next_chap_num}. Output ONLY the story text.
                    **FORMATTING RULE:** Use '***' on a separate line to indicate scene breaks.
                    """
                    
                    response = None
                    if cache_name:
                        try:
                            cache_obj = genai.caching.CachedContent.get(name=cache_name)
                            cached_model = genai.GenerativeModel.from_cached_content(
                                cached_content=cache_obj, 
                                safety_settings=safety_settings
                            )
                            response = cached_model.generate_content(dynamic_prompt)
                        except:
                            cache_name = None 
                    
                    if not cache_name:
                        full_prompt = f"### BIBLE\n{concept_text}\n### OUTLINE\n{outline_text}\n{dynamic_prompt}"
                        response = model.generate_content(full_prompt)

                    if hasattr(response, 'text') and response.text:
                        # CLEAN IMMEDIATELY using the nuclear option
                        clean_text = clean_text_formatting(response.text)
                        
                        st.session_state.editor_content = clean_text 
                        st.session_state.editor_mode = True 
                        st.rerun()
                    else:
                        st.error("Empty response (Safety Blocked).")
                        
                except Exception as e:
                    st.error(f"Error: {e}")

    # 5. THE EDITING STAGE
    else:
        st.info("📝 **Edit Mode Active**")
        
        # Utility to re-clean if user pastes something messy
        if st.button("🧹 Force Clean Formatting"):
            st.session_state.editor_content = clean_text_formatting(st.session_state.editor_content)
            st.rerun()

        edited_text = st.text_area(
            f"Editing Chapter {next_chap_num}...", 
            height=600,
            key="editor_content" 
        )
        
        col_save, col_discard = st.columns([1, 4])
        
        with col_save:
            if st.button("💾 Confirm & Add to Book", type="primary"):
                st.session_state.book_history.append({
                    "chapter": next_chap_num,
                    "content": edited_text
                })
                st.session_state.full_text += f"\n\n## Chapter {next_chap_num}\n\n{edited_text}"
                st.session_state.editor_mode = False 
                del st.session_state.editor_content 
                st.success("Chapter Saved!")
                st.rerun()
                
        with col_discard:
            if st.button("❌ Discard & Retry"):
                st.session_state.editor_mode = False
                if 'editor_content' in st.session_state:
                    del st.session_state.editor_content
                st.rerun()

    # 6. HISTORY PREVIEW
    if st.session_state.book_history and not st.session_state.editor_mode:
        st.divider()
        last = st.session_state.book_history[-1]
        st.caption(f"Last Saved: Chapter {last['chapter']}")
        st.text_area("Read-Only Preview", value=last['content'], height=200, disabled=True)

# --- TAB 3: EXPORT ---
with tab3:
    st.header("The Manuscript")
    
    col_tools1, col_tools2 = st.columns(2)
    with col_tools1:
        if st.button("🧹 Fix Full Book Formatting"):
            st.session_state.full_text = clean_text_formatting(st.session_state.full_text)
            st.rerun()
            
    with col_tools2:
        if st.button("📏 Single Spaced Mode"):
            st.session_state.full_text = re.sub(r'\n+', '\n', st.session_state.full_text)
            st.rerun()

    st.text_area("Full Text (Ctrl+A to Copy)", value=st.session_state.full_text, height=600)
    
    st.download_button(
        "Download .txt", 
        data=st.session_state.full_text, 
        file_name="gemini_novel.txt"
    )
