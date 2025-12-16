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
    
    # 1. CALCULATE CHAPTER NUMBER FIRST (Fixes the NameError)
    chapter_num = len(st.session_state.book_history) + 1
    st.markdown(f"**Drafting Chapter {chapter_num}**")
    
    # 2. AUTO-FETCH BUTTON
    if st.button(f"🔮 Auto-Fetch Chapter {chapter_num} Plan"):
        if not outline_text:
            st.error("Please paste your Full Outline in the 'Bible' tab first!")
        else:
            with st.spinner("Scanning outline..."):
                # Use a cheap fast model to find the outline part
                finder_model = genai.GenerativeModel("gemini-2.0-flash-exp") 
                finder_prompt = f"Extract plot points for Chapter {chapter_num} from:\n{outline_text}"
                try:
                    plan = finder_model.generate_content(finder_prompt).text
                    st.session_state[f"plan_{chapter_num}"] = plan
                    st.rerun()
                except Exception as e:
                    st.error(f"Fetch failed: {e}")

    # 3. CHAPTER INSTRUCTIONS INPUT
    default_plan = st.session_state.get(f"plan_{chapter_num}", "")
    current_chapter_outline = st.text_area(
        f"Specific Instructions for Chapter {chapter_num}",
        value=default_plan,
        height=150,
        placeholder="Click 'Auto-Fetch' above or type instructions manually."
    )
    
    # 4. GENERATE BUTTON
    if st.button(f"Generate Chapter {chapter_num}", type="primary"):
        if not concept_text or not outline_text or not current_chapter_outline:
            st.error("Missing Concept, Outline, or Instructions!")
        else:
            with st.spinner(f"Writing Chapter {chapter_num} with {model_name}..."):
                try:
                    # A. Try to cache the Bible
                    cache_name = get_or_create_cache(concept_text, outline_text)
                    
                    # B. Construct Prompt
                    # If we have a cache, we ONLY send the dynamic parts
                    dynamic_prompt = f"""
                    ### STORY SO FAR
                    {st.session_state.full_text}
                    
                    ### CHAPTER INSTRUCTIONS
                    {current_chapter_outline}
                    
                    ### TASK
                    Write Chapter {chapter_num}. Output ONLY the story text.
                    """
                    
                    # C. Generate
                    if cache_name:
                        # Optimized path (Cheaper/Faster for large context)
                        response = model.generate_content(
                            dynamic_prompt, 
                            request_options={'cached_content': cache_name}
                        )
                    else:
                        # Standard path (Fallback if cache too small)
                        full_prompt = f"### BIBLE\n{concept_text}\n### OUTLINE\n{outline_text}\n{dynamic_prompt}"
                        response = model.generate_content(full_prompt)

                    # D. Save Result
                    generated_text = response.text
                    st.session_state.book_history.append({
                        "chapter": chapter_num,
                        "content": generated_text
                    })
                    st.session_state.full_text += f"\n\n## Chapter {chapter_num}\n\n{generated_text}"
                    
                    st.success(f"Chapter {chapter_num} Complete!")
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Generation Error: {e}")

    # Preview Most Recent Chapter
    if st.session_state.book_history:
        last_chapter = st.session_state.book_history[-1]
        st.markdown("---")
        st.subheader(f"Preview: Chapter {last_chapter['chapter']}")
        st.markdown(last_chapter['content'])

# --- TAB 3: READ & EXPORT ---
with tab3:
    st.header("The Full Manuscript")
    st.markdown(st.session_state.full_text)
    
    st.download_button(
        label="Download Book as .txt",
        data=st.session_state.full_text,
        file_name="my_gemini_novel.txt",
        mime="text/plain"
    )
