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
    from app.pages.zepto_page import render
    if st.button("← Back"):
        st.session_state["platform"] = None
        st.session_state.pop("zepto_final_df", None)
        st.rerun()
    render()

else:
    st.markdown("## 🥘 Curry Dashboard")
    st.divider()
    st.markdown("### Select Platform")
    if st.button("🟢 Zepto", use_container_width=True, type="primary"):
        st.session_state["platform"] = "zepto"
        st.rerun()
