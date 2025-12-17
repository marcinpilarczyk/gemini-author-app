# TAB 5: EDITOR
with t5:
    st.header("🧐 The Continuity Editor")
    st.markdown("Scans the entire manuscript for inconsistencies, timeline errors, and plot holes.")
    
    # FIX: Increase limits and raise temperature slightly to prevent repetition loops
    strict_config = genai.types.GenerationConfig(
        temperature=0.2,             # 0.2 is strict but prevents "infinite loop" bugs
        top_p=0.95,
        max_output_tokens=8192       # Doubled the token limit for long reports
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
                    # Check cache
                    cache_name = get_or_create_cache(current_concept, current_outline)
                    if cache_name:
                        c_obj = genai.caching.CachedContent.get(name=cache_name)
                        c_model = genai.GenerativeModel.from_cached_content(cached_content=c_obj)
                        response = c_model.generate_content(editor_prompt, generation_config=strict_config)
                    else:
                        response = model.generate_content(editor_prompt, generation_config=strict_config)
                    
                    # FIX: Handle cases where the model stops early or gets blocked
                    if response.text:
                        st.session_state.editor_report = response.text
                        st.rerun()
                    else:
                        st.warning("The editor finished but returned no text. (Finish Reason: " + str(response.candidates[0].finish_reason) + ")")

                except Exception as e:
                    # Catch the "Invalid operation" error specifically
                    st.error(f"Scan interrupted: The model output was too large or was filtered. Try scanning fewer chapters at a time. (Error: {e})")

    if "editor_report" in st.session_state:
        st.divider()
        st.subheader("📋 Editor Report")
        st.markdown(st.session_state.editor_report)
