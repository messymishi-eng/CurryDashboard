import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

st.set_page_config(
    page_title="Curry Dashboard",
    layout="wide"
)

if "platform" not in st.session_state:
    st.session_state["platform"] = "dashboard"

if st.session_state["platform"] == "zepto":
    from app.pages.zepto_page import render
    if st.button("← Back to Dashboard"):
        st.session_state["platform"] = "dashboard"
        st.session_state.pop("zepto_final_df", None)
        st.rerun()
    render()

else:
    from app.pages.dashboard_page import render
    render()
