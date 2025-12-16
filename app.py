import streamlit as st
import google.generativeai as genai
from google.generativeai import caching
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import datetime
import time

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Gemini Author Studio", layout="wide")

st.title("Drafting with Gemini")
st.markdown("Advanced Chapter Drafting using Context Caching.")

# --- SAFETY SETTINGS (CRITICAL FOR HORROR/ACTION) ---
# We disable safety filters so the AI can write about zombies, combat, and dark themes.
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- HELPER FUNCTION: CACHING ---
def get_or_create_cache(bible_text, outline_text, model_name):
    """
    Creates a cache for the static 'Bible' data using the ACTIVE model.
    """
    static_content = f"### THE BIBLE (Static Context)\n{bible_text}\n\n### THE FULL OUTLINE\n{outline_text}"
    
    # Check if cache exists and matches the current model
    if 'cache_name' in st.session_state and st.session_state.get('cache_model') == model_name:
        try:
            # Check if valid
            cache = genai.caching.CachedContent.get(name=st.session_state.cache_name)
            cache.update(ttl=datetime.timedelta(hours=2))
            return cache.name
        except Exception:
            del st.session_state.cache_name

    # Create New Cache
    try:
        cache = genai.caching.CachedContent.create(
            model=model_name, 
            display_name="book_bible_v1", 
            system_instruction="You are an expert novelist. Use this bible to write chapters.",
            contents=[static_content],
            ttl=datetime.timedelta(hours=2)
        )
        st.session_state.cache_name = cache.name
        st.session_state.cache_model = model_name 
        st.toast(f"✅ Bible Cached for {model_name}!", icon="💾")
        return cache.name
    except Exception as e:
        print(f"Cache Warning: {e}")
        return None

# --- SIDEBAR: SETTINGS ---
with st.sidebar:
    st.header("Settings")
    
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        st.success("✅ API Key loaded securely.")
    else:
        api_key = st.text_input("Enter Google API Key", type="password")
    
    model_name = st.selectbox(
        "Select Model", 
        [
            "gemini-1.5-pro",             # Most Stable
            "gemini-3-pro-preview",       # Smartest (Paid)
            "gemini-2.0-flash-exp",       # Fast Experimental
            "gemini-1.5-flash",           # Cheapest
        ]
    )
    
    st.info(f"Active Model: **{model_name}**")
    
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

genai.configure(api_key=api_key)
# Standard model for non-cached tasks (like Auto-Fetch)
model = genai.GenerativeModel(model_name, safety_settings=safety_settings)

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
            value=st.session_state.get("concept_text", ""), 
            key="concept_input"
        )
    with col2:
        st.subheader("Full Outline")
        outline_text = st.text_area(
            "Paste your full book outline here:",
            height=400,
            value=st.session_state.get("outline_text", ""), 
            key="outline_input"
        )

# --- TAB 2: WRITING STUDIO ---
with tab2:
    st.header("Chapter Generator")
    
    if 'book_history' in st.session_state:
        chapter_num = len(st.session_state.book_history) + 1
    else:
        chapter_num = 1
        
    st.markdown(f"**Drafting Chapter {chapter_num}**")
    
    # AUTO-FETCH BUTTON
    if st.button(f"🔮 Auto-Fetch Chapter {chapter_num} Plan", key="fetch_btn"):
        if not outline_text:
            st.error("Please paste your Full Outline in the 'Bible' tab first!")
        else:
            with st.spinner(f"Scanning outline with {model_name}..."):
                try:
                    finder_prompt = f"Extract plot points for Chapter {chapter_num} from:\n{outline_text}"
                    response = model.generate_content(finder_prompt)
                    if response.text:
                        st.session_state[f"plan_{chapter_num}"] = response.text
                        st.rerun()
                    else:
                        st.error("⚠️ Model refused to generate plan (Safety Filter).")
                except Exception as e:
                    st.error(f"Fetch failed: {e}")

    default_plan = st.session_state.get(f"plan_{chapter_num}", "")
    current_chapter_outline = st.text_area(
        f"Specific Instructions for Chapter {chapter_num}",
        value=default_plan,
        height=150
    )
    
    # GENERATE BUTTON
    if st.button(f"Generate Chapter {chapter_num}", type="primary", key="gen_btn"):
        if not concept_text or not outline_text or not current_chapter_outline:
            st.error("Missing Concept, Outline, or Instructions!")
        else:
            with st.spinner(f"Writing Chapter {chapter_num} with {model_name}..."):
                try:
                    # A. Try to cache the Bible
                    cache_name = get_or_create_cache(concept_text, outline_text, model_name)
                    
                    dynamic_prompt = f"""
                    ### STORY SO FAR
                    {st.session_state.full_text}
                    
                    ### CHAPTER INSTRUCTIONS
                    {current_chapter_outline}
                    
                    ### TASK
                    Write Chapter {chapter_num}. Output ONLY the story text.
                    """
                    
                    # B. Generate
                    response = None
                    
                    # 1. Cached Path (The Fix)
                    if cache_name:
                        try:
                            # Retrieve the cache object
                            cache_obj = genai.caching.CachedContent.get(name=cache_name)
                            # Create a temporary model LINKED to this cache
                            cached_model = genai.GenerativeModel.from_cached_content(
                                cached_content=cache_obj,
                                safety_settings=safety_settings # Apply safety here too!
                            )
                            response = cached_model.generate_content(dynamic_prompt)
                        except Exception as e:
                            print(f"Cache failed, falling back: {e}")
                            cache_name = None # Trigger fallback below
                            
                    # 2. Standard Path (Fallback)
                    if not cache_name:
                        full_prompt = f"### BIBLE\n{concept_text}\n### OUTLINE\n{outline_text}\n{dynamic_prompt}"
                        response = model.generate_content(full_prompt)

                    # C. Save Result
                    if hasattr(response, 'text') and response.text:
                        generated_text = response.text
                        st.session_state.book_history.append({
                            "chapter": chapter_num,
                            "content": generated_text
                        })
                        st.session_state.full_text += f"\n\n## Chapter {chapter_num}\n\n{generated_text}"
                        st.success(f"Chapter {chapter_num} Complete!")
                        st.rerun()
                    else:
                        st.error("⚠️ Generation Empty! The model refused the prompt (Safety Block).")
                        if hasattr(response, 'candidates'):
                            st.json(response.candidates[0].safety_ratings)
                    
                except Exception as e:
                    st.error(f"Generation Error: {e}")

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
