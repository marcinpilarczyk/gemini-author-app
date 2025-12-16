import streamlit as st
import google.generativeai as genai
from google.generativeai import caching
import datetime
import time

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Gemini 3 Author Studio", layout="wide")

st.title("Drafting with Gemini 3 Pro")
st.markdown("Advanced Chapter Drafting using Context Caching & Deep Reasoning.")

# --- HELPER FUNCTION: CACHING ---
def get_or_create_cache(bible_text, outline_text):
    """
    Creates a cache for the static 'Bible' data if it doesn't exist.
    Refreshes the TTL (Time To Live) if it does.
    """
    # 1. Combine static data into one block
    static_content = f"### THE BIBLE (Static Context)\n{bible_text}\n\n### THE FULL OUTLINE\n{outline_text}"
    
    # 2. Check if cache exists in Session State
    if 'cache_name' in st.session_state:
        try:
            # Verify it's still valid on Google's servers
            cache = genai.caching.CachedContent.get(name=st.session_state.cache_name)
            # Extend life by 2 hours
            cache.update(ttl=datetime.timedelta(hours=2))
            return cache.name
        except Exception:
            # If invalid (expired), clear it and recreate
            del st.session_state.cache_name

    # 3. Create New Cache
    # NOTE: Caching requires minimum ~2,000 tokens.
    try:
        # We use a standard model for the cache creation reference
        cache = genai.caching.CachedContent.create(
            model='models/gemini-1.5-pro-001', 
            display_name="book_bible_v1", 
            system_instruction="You are an expert novelist. Use this bible to write chapters.",
            contents=[static_content],
            ttl=datetime.timedelta(hours=2)
        )
        st.session_state.cache_name = cache.name
        st.toast(f"✅ Bible Cached! ({cache.usage_metadata.total_token_count} tokens)", icon="💾")
        return cache.name
    except Exception as e:
        if "400" in str(e): 
            # Content too short (<2000 tokens) to cache. This is normal for testing.
            return None 
        else:
            st.error(f"Cache Error: {e}")
            return None

# --- SIDEBAR: SETTINGS ---
with st.sidebar:
    st.header("Settings")
    
    # API Key Check
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        st.success("✅ API Key loaded securely.")
    else:
        api_key = st.text_input("Enter Google API Key", type="password")
        st.caption("Tip: Add to Secrets to skip this.")
    
    # Model Selection
    model_name = st.selectbox(
        "Select Model", 
        [
            "gemini-3-pro-preview",           # PAID (High Quality)
            "gemini-2.0-flash-thinking-exp",  # FREE (High Quality Experimental)
            "gemini-2.0-flash-exp",           # FREE (Fast)
        ]
    )
    
    st.info(f"Active Model: **{model_name}**")
    
    if "gemini-3" in model_name:
        st.warning("⚠️ Note: Gemini 3 Pro requires a Billing Account (Credit Card) on Google Cloud.")

    if st.button("Reset / Clear All Memory"):
        st.session_state.clear()
        st.rerun()

# --- SESSION STATE INITIALIZATION ---
if "book_history" not in st.session_state:
    st.session_state.book_history = [] 
if "full_text" not in st.session_state:
    st.session_state.full_text = ""

# --- MAIN APP LOGIC ---

if not api_key:
    st.warning("Waiting for API Key...")
    st.stop()

# Configure Gemini
genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name)

# TABS
tab1, tab2, tab3 = st.tabs(["1. The Bible (Setup)", "2. Write Chapter", "3. Read Book"])

# --- TAB 1: THE BIBLE ---
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Concept Document")
        concept_text = st.text_area(
            "Paste your World Rules, Characters, and Tone guide here:",
            height=400,
            placeholder="Genre: Cyberpunk.\nProtagonist: Kael..."
        )
    with col2:
        st.subheader("Full Outline")
        outline_text = st.text_area(
            "Paste your full book outline here:",
            height=400,
            placeholder="Chapter 1: Kael wakes up..."
        )

# --- TAB 2: WRITING STUDIO ---
with tab2:
    st.header("Chapter Generator")
    
    # 1. CALCULATE CHAPTER NUMBER FIRST (Fixes the Name
