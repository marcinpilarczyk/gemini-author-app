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

# --- HELPER: CACHING ---
def get_or_create_cache(bible_text, outline_text):
    """
    Creates a cache specifically for Gemini 3 Pro.
    """
    static_content = f"### THE BIBLE (Static Context)\n{bible_text}\n\n### THE FULL OUTLINE\n{outline_text}"
    
    # Check if existing cache is valid
    if 'cache_name' in st.session_state:
        try:
            cache = genai.caching.CachedContent.get(name=st.session_state.cache_name)
            cache.update(ttl=datetime.timedelta(hours=2))
            return cache.name
        except Exception:
            del st.session_state.cache_name

    # Create New Cache
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
    
    # HISTORY MANAGEMENT
    if st.button("Undo Last Confirmed Chapter", type="secondary"):
        if len(st.session_state.book_history) > 0:
            deleted = st.session_state.book_history.pop()
            # Rebuild full text to keep it clean
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
if "temp_generated_chapter" not in st.session_state:
    st.session_state.temp_generated_chapter = None

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
    # 1. Determine Chapter Number
    next_chap_num = len(st.session_state.book_history) + 1
    
    st.header(f"Drafting Chapter {next_chap_num}")
    
    # 2. AUTO-FETCH
    if st.button(f"🔮 Auto-Fetch Instructions for Ch. {next_chap_num}"):
        if not outline_text:
            st.error("Outline is empty!")
        else:
            with st.spinner("Analyzing outline..."):
                try:
                    prompt = f"Extract the plot summary for Chapter {next_chap_num} from this outline:\n{outline_text}"
                    response = model.generate_content(prompt)
                    if response.text:
                        st.session_state[f"plan_{next_chap_num}"] = response.text
                        st.rerun()
                except Exception as e:
                    st.error(f"Fetch Error: {e}")

    # 3. INSTRUCTIONS
    current_plan = st.session_state.get(f"plan_{next_chap_num}", "")
    chapter_instructions = st.text_area("Chapter Instructions:", value=current_plan, height=150)

    # 4. GENERATION ACTION
    if st.session_state.temp_generated_chapter is None:
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
                    # Try Cached Generation
                    if cache_name:
                        try:
                            cache_obj = genai.caching.CachedContent.get(name=cache_name)
                            cached_model = genai.GenerativeModel.from_cached_content(
                                cached_content=cache_obj, 
                                safety_settings=safety_settings
                            )
                            response = cached_model.generate_content(dynamic_prompt)
                        except:
                            cache_name = None # Fallback
                    
                    # Fallback Standard Generation
                    if not cache_name:
                        full_prompt = f"### BIBLE\n{concept_text}\n### OUTLINE\n{outline_text}\n{dynamic_prompt}"
                        response = model.generate_content(full_prompt)

                    if hasattr(response, 'text') and response.text:
                        # FIX: Auto-Clean the text BEFORE showing it in the editor
                        clean_text = re.sub(r'\n{3,}', '\n\n', response.text)
                        clean_text = clean_text.strip() # Remove start/end spaces
                        
                        st.session_state.temp_generated_chapter = clean_text
                        st.rerun()
                    else:
                        st.error("Empty response (Safety Blocked).")
                        
                except Exception as e:
                    st.error(f"Error: {e}")

    # 5. THE EDITING STAGE
    else:
        st.info("📝 **Edit Mode Active** - Review and polish before saving.")
        
        # UTILITY BUTTON FOR MANUAL CLEANING
        if st.button("🧹 Clean Extra Spaces (Editor)", help="Click if you see big gaps in the text box below"):
            current_draft = st.session_state.temp_generated_chapter
            st.session_state.temp_generated_chapter = re.sub(r'\n{3,}', '\n\n', current_draft).strip()
            st.rerun()

        # The Editor
        edited_text = st.text_area(
            f"Editing Chapter {next_chap_num}...", 
            value=st.session_state.temp_generated_chapter, 
            height=600
        )
        
        col_save, col_discard = st.columns([1, 4])
        
        with col_save:
            if st.button("💾 Confirm & Add to Book", type="primary"):
                st.session_state.book_history.append({
                    "chapter": next_chap_num,
                    "content": edited_text
                })
                st.session_state.full_text += f"\n\n## Chapter {next_chap_num}\n\n{edited_text}"
                
                st.session_state.temp_generated_chapter = None
                st.success("Chapter Saved!")
                st.rerun()
                
        with col_discard:
            if st.button("❌ Discard & Retry"):
                st.session_state.temp_generated_chapter = None
                st.rerun()

    # 6. HISTORY PREVIEW
    if st.session_state.book_history and st.session_state.temp_generated_chapter is None:
        st.divider()
        last = st.session_state.book_history[-1]
        st.caption(f"Last Saved: Chapter {last['chapter']}")
        st.text_area("Read-Only Preview", value=last['content'], height=200, disabled=True)

# --- TAB 3: EXPORT ---
with tab3:
    st.header("The Manuscript")
    
    # Repair Tools
    col_tools1, col_tools2 = st.columns(2)
    with col_tools1:
        if st.button("🧹 Fix Formatting (Remove Extra Lines)"):
            st.session_state.full_text = re.sub(r'\n{3,}', '\n\n', st.session_state.full_text)
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
