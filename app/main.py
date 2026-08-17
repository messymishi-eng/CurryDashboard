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
    st.title("🥘 Curryit")
    st.subheader("Reconciliation & Insights Platform")
    st.write("Select a quick-commerce platform to begin.")
    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🟢 Zepto")
        st.write("Upload operational files and identify reconciliation conflicts.")
        if st.button("Open Zepto", use_container_width=True, type="primary"):
            st.session_state["platform"] = "zepto"
            st.rerun()

    with col2:
        st.markdown("### 🔒 Blinkit")
        st.write("Coming Soon")
        st.button("Coming Soon", disabled=True, use_container_width=True, key="blinkit_btn")

    col3, col4 = st.columns(2)

    with col3:
        st.markdown("### 🔒 Swiggy")
        st.write("Coming Soon")
        st.button("Coming Soon", disabled=True, use_container_width=True, key="swiggy_btn")

    with col4:
        st.markdown("### 🔒 Instamart")
        st.write("Coming Soon")
        st.button("Coming Soon", disabled=True, use_container_width=True, key="instamart_btn")