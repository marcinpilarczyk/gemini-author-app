import streamlit as st
import google.generativeai as genai
from google.generativeai import caching # <--- NEW IMPORT
import datetime
import time

# ... (Keep your existing setup code) ...

def get_or_create_cache(bible_text, outline_text):
    """
    Creates a cache for the static 'Bible' data if it doesn't exist.
    Refreshes the TTL (Time To Live) if it does.
    """
    # 1. Combine static data
    static_content = f"### THE BIBLE (Static Context)\n{bible_text}\n\n### THE FULL OUTLINE\n{outline_text}"
    
    # 2. Check if cache exists in Session State
    if 'cache_name' in st.session_state:
        try:
            # Verify it's still valid on Google's servers
            cache = genai.caching.CachedContent.get(name=st.session_state.cache_name)
            # Extend life by 2 hours (so it doesn't die while you write)
            cache.update(ttl=datetime.timedelta(hours=2))
            return cache.name
        except Exception:
            st.warning("Cache expired. Creating new one...")
            del st.session_state.cache_name

    # 3. Create New Cache
    # NOTE: Caching requires minimum ~2,000 tokens. 
    # If your bible is too short, we return None and skip caching.
    try:
        cache = genai.caching.CachedContent.create(
            model='models/gemini-1.5-pro-001', # Use explicit version for caching
            display_name="book_bible_v1", 
            system_instruction="You are an expert novelist. Use this bible to write chapters.",
            contents=[static_content],
            ttl=datetime.timedelta(hours=2) # Keep alive for 2 hours
        )
        st.session_state.cache_name = cache.name
        st.success(f"✅ Bible Cached! ({cache.usage_metadata.total_token_count} tokens)")
        return cache.name
    except Exception as e:
        if "400" in str(e): 
            # This usually means content is too short (<2000 tokens)
            return None 
        else:
            st.error(f"Cache Error: {e}")
            return None

# --- INSIDE YOUR 'GENERATE' BUTTON ---
if st.button(f"Generate Chapter {chapter_num}"):
    
    # 1. Try to cache the Bible
    cache_name = get_or_create_cache(concept_text, outline_text)
    
    # 2. Construct Prompt (Dynamic parts only)
    dynamic_prompt = f"""
    ### THE STORY SO FAR
    {st.session_state.full_text}
    
    ### CHAPTER INSTRUCTIONS
    {current_chapter_outline}
    
    ### TASK
    Write Chapter {chapter_num}. Output ONLY the story text.
    """
    
    # 3. Generate with Cache (if valid) or Standard (if too small)
    if cache_name:
        # CHEAPER METHOD
        response = model.generate_content(
            dynamic_prompt, 
            request_options={'cached_content': cache_name}
        )
    else:
        # STANDARD METHOD (Fall back if Bible is <2000 tokens)
        full_prompt = f"{concept_text}\n{outline_text}\n{dynamic_prompt}"
        response = model.generate_content(full_prompt)

    # ... (Save text as normal) ...
