import streamlit as st
import pandas as pd
from app.core.sheets import get_client, fetch_reconciliation_results

FLAG_COLORS = {
    "Matched":           "🟢",
    "Short":             "🔴",
    "Missing GRN":       "🟣",
    "Under Dispatched":  "🟠",
    "Not Dispatched":    "🔴",
    "Missing Dispatch":  "🔵",
    "Out of Period":     "⚪",
    "Human Review":      "🟡",
    "Human Review":      "🟡",
}


def render():
    st.markdown("## 📊 Reconciliation Dashboard")
    st.divider()

    with st.spinner("Fetching latest reconciliation data..."):
        try:
            client = get_client()
            df     = fetch_reconciliation_results(client)
        except Exception as e:
            st.error(f"Failed to fetch data: {e}")
            return

    if df.empty:
        st.info("No reconciliation data yet. Upload a GRN file to get started.")
        if st.button("📤 Upload GRN File", type="primary", use_container_width=True):
            st.session_state["platform"] = "zepto"
            st.rerun()
        return

    # Convert numeric columns
    for col in ["PO Qty", "Dispatch Qty", "GRN Qty", "Difference"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Sort by Dispatch Date — newest first
    if "Dispatch Date" in df.columns:
        df["Dispatch Date"] = pd.to_datetime(df["Dispatch Date"], errors="coerce")
        df = df.sort_values("Dispatch Date", ascending=False)
        df["Dispatch Date"] = df["Dispatch Date"].dt.strftime("%d-%b-%Y")

    # ── KPI Summary ───────────────────────────────────────────────
    total     = len(df)
    matched   = len(df[df["Flag"] == "Matched"])
    short     = len(df[df["Flag"] == "Short"])
    missing   = len(df[df["Flag"] == "Missing GRN"])
    conflicts = total - matched

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Records",   total)
    c2.metric("Matched",         matched)
    c3.metric("Conflicts",       conflicts)
    c4.metric("Short",           short)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Missing GRN",      missing)
    c2.metric("Under Dispatched", len(df[df["Dispatch Status"] == "Under Dispatched"]))
    c3.metric("Not Dispatched",   len(df[df["Dispatch Status"] == "Not Dispatched"]))
    c4.metric("Missing Dispatch", len(df[df["GRN Status"] == "Missing Dispatch"]))

    st.divider()

    # Upload button
    if st.button("📤 Upload New GRN File", type="primary"):
        st.session_state["platform"] = "zepto"
        st.rerun()

    st.divider()

    # ── Filters ───────────────────────────────────────────────────
    st.markdown("### Records")
    c1, c2, c3 = st.columns(3)
    with c1:
        flag_options = ["All"] + sorted(df["Flag"].dropna().unique().tolist())
        flag_filter  = st.selectbox("Flag", flag_options)
    with c2:
        sku_options = ["All"] + sorted(df["SKU Name"].dropna().unique().tolist())
        sku_filter  = st.selectbox("SKU", sku_options)
    with c3:
        po_search = st.text_input("Search PO Number", placeholder="e.g. P4686468")

    filtered = df.copy()
    if flag_filter != "All":
        filtered = filtered[filtered["Flag"] == flag_filter]
    if sku_filter != "All":
        filtered = filtered[filtered["SKU Name"] == sku_filter]
    if po_search.strip():
        filtered = filtered[
            filtered["PO Number"].astype(str).str.contains(po_search.strip(), case=False)
        ]

    st.caption(f"Showing {len(filtered)} of {len(df)} records")

    if len(filtered) == 0:
        st.info("No records match the current filters.")
        return

    # ── Table ─────────────────────────────────────────────────────
    display_cols = [
        "Dispatch Date", "INVOICE #", "PO Number", "Brand",
        "SKU Name", "PO Qty", "Dispatch Qty", "GRN Qty",
        "Difference", "Flag"
    ]
    display_cols = [c for c in display_cols if c in filtered.columns]
    display_df   = filtered[display_cols].copy()

    # Add flag icon
    display_df["Flag"] = display_df["Flag"].apply(
        lambda x: f"{FLAG_COLORS.get(x, '⚪')} {x}"
    )
    display_df = display_df.fillna("—")

    st.dataframe(display_df, use_container_width=True, height=500)
