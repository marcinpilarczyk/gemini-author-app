import streamlit as st
import google.generativeai as genai

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Gemini 3 Author Studio", layout="wide")

st.title("Drafting with Gemini 3 Pro")
st.markdown("Advanced Chapter Drafting using the 'Deep Think' Architecture.")

# --- SIDEBAR: SETTINGS ---
with st.sidebar:
    st.header("Settings")
    
    # 1. API KEY MANAGEMENT (Secrets or Manual)
    # Checks if the key is stored in Streamlit Secrets, otherwise asks user
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        st.success("✅ API Key loaded securely from Secrets.")
    else:
        api_key = st.text_input("Enter Google API Key", type="password")
        st.caption("Tip: Add this to Secrets to skip this step.")
    
    # 2. MODEL SELECTION
    # Updated to include the latest 3.0 series
    model_name = st.selectbox(
        "Select Model", 
        ["gemini-3-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"]
    )
    
    st.info(f"Currently using: **{model_name}**")
    
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

# 1. SETUP TAB
tab1, tab2, tab3 = st.tabs(["1. The Bible (Setup)", "2. Write Chapter", "3. Read Book"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Concept Document")
        concept_text = st.text_area(
            "Paste your World Rules, Characters, and Tone guide here:",
            height=400,
            placeholder="Genre: Cyberpunk.\nProtagonist: Kael, a gritty hacker..."
        )
    with col2:
        st.subheader("Full Outline")
        outline_text = st.text_area(
            "Paste your full book outline here:",
            height=400,
            placeholder="Chapter 1: Kael wakes up..."
        )

with tab2:
    st.header("Chapter Generator")
    
    chapter_num = len(st.session_state.book_history) + 1
    st.markdown(f"**Drafting Chapter {chapter_num}**")
    
    current_chapter_outline = st.text_area(
        f"Specific Instructions for Chapter {chapter_num}",
        placeholder="What specifically happens in this chapter? Copy relevant part from outline.",
        height=150
    )
    
    # New Feature: Reasoning Toggle
    use_deep_think = st.checkbox("Enable Deep Think (Slower, better logic)", value=True)
    
    if st.button(f"Generate Chapter {chapter_num}", type="primary"):
        if not concept_text or not outline_text or not current_chapter_outline:
            st.error("Please ensure Concept, Full Outline, and Current Chapter Outline are filled.")
        else:
            with st.spinner("Gemini 3 Pro is thinking deeply... (This may take 60+ seconds)"):
                try:
                    # PROMPT CONSTRUCTION
                    # We encourage the model to "Plan" before writing if Deep Think is on
                    prompt_intro = ""
                    if use_deep_think:
                        prompt_intro = "First, think step-by-step about the pacing and character motivations. Then, write the chapter."

                    prompt = f"""
                    You are an expert novelist. {prompt_intro}
                    
                    ### THE BIBLE (Static Context)
                    {concept_text}
                    
                    ### THE FULL OUTLINE
                    {outline_text}
                    
                    ### THE STORY SO FAR (Context)
                    {st.session_state.full_text}
                    
                    ### CHAPTER INSTRUCTIONS
                    Focus ONLY on this part of the outline:
                    {current_chapter_outline}
                    
                    ### TASK
                    Write Chapter {chapter_num}. Output ONLY the story text.
                    """
                    
                    response = model.generate_content(prompt)
                    generated_text = response.text
                    
                    # Store results
                    st.session_state.book_history.append({
                        "chapter": chapter_num,
                        "content": generated_text
                    })
                    st.session_state.full_text += f"\n\n## Chapter {chapter_num}\n\n{generated_text}"
                    
                    st.success(f"Chapter {chapter_num} Complete!")
                    st.rerun() 
                    
                except Exception as e:
                    st.error(f"An error occurred: {e}")

    # Preview Area
    if st.session_state.book_history:
        last_chapter = st.session_state.book_history[-1]
        st.markdown("---")
        st.subheader(f"Preview: Chapter {last_chapter['chapter']}")
        st.markdown(last_chapter['content'])

with tab3:
    st.header("The Full Manuscript")
    st.markdown(st.session_state.full_text)
    
    st.download_button(
        label="Download Book as .txt",
        data=st.session_state.full_text,
        file_name="my_gemini_novel.txt",
        mime="text/plain"
    )