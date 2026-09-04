import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

st.set_page_config(
    page_title="Curry",
    page_icon="🥘",
    layout="wide"
)

if "platform" not in st.session_state:
    st.session_state["platform"] = None

if st.session_state["platform"] == "zepto":
    try:
        from app.pages.zepto_page import render
    except ImportError:
        from pages.zepto_page import render

    if st.button("← Back"):
        st.session_state["platform"] = None
        st.session_state.pop("zepto_final_df", None)
        st.rerun()
    render()

elif st.session_state["platform"] == "swiggy":
    try:
        from app.pages.swiggy_page import render
    except ImportError:
        from pages.swiggy_page import render

    if st.button("← Back"):
        st.session_state["platform"] = None
        st.session_state.pop("swiggy_final_df", None)
        st.rerun()
    render()

else:
    st.markdown("## 🥘 Curry Dashboard")
    st.divider()
    st.markdown("### Select Platform")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🟢 Zepto", use_container_width=True, type="primary"):
            st.session_state["platform"] = "zepto"
            st.rerun()
    with col2:
        if st.button("🟠 Swiggy", use_container_width=True, type="primary"):
            st.session_state["platform"] = "swiggy"
            st.rerun()
