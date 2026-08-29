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
}


def render():
    st.markdown("## 📊 Reconciliation Dashboard")
    st.divider()

    # Fetch data
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

    # ── KPI Summary ───────────────────────────────────────────────
    total     = len(df)
    matched   = len(df[df["Flag"] == "Matched"])
    short     = len(df[df["Flag"] == "Short"])
    missing   = len(df[df["Flag"] == "Missing GRN"])
    conflicts = total - matched

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Records",   total)
    c2.metric("Matched",         matched)
    c3.metric("Total Conflicts", conflicts)
    c4.metric("Short",           short)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Missing GRN",      missing)
    c2.metric("Under Dispatched", len(df[df["Dispatch Status"] == "Under Dispatched"]))
    c3.metric("Not Dispatched",   len(df[df["Dispatch Status"] == "Not Dispatched"]))
    c4.metric("Missing Dispatch", len(df[df["GRN Status"] == "Missing Dispatch"]))

    st.divider()

    # ── Upload button ─────────────────────────────────────────────
    if st.button("📤 Upload New GRN File", type="primary"):
        st.session_state["platform"] = "zepto"
        st.rerun()

    st.divider()

    # ── Filters ───────────────────────────────────────────────────
    st.markdown("### 🔍 Filter Records")
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

    # ── Table ─────────────────────────────────────────────────────
    if len(filtered) == 0:
        st.info("No records match the current filters.")
    else:
        # PO level summary
        po_summary = (
            filtered.groupby(["PO Number", "INVOICE #", "Dispatch Date"], as_index=False)
            .agg(
                SKUs        = ("SKU Name", "count"),
                Flag        = ("Flag", lambda x: (
                    "Short"            if "Short"            in x.values else
                    "Missing GRN"      if "Missing GRN"      in x.values else
                    "Under Dispatched" if "Under Dispatched" in x.values else
                    "Not Dispatched"   if "Not Dispatched"   in x.values else
                    "Missing Dispatch" if "Missing Dispatch"  in x.values else
                    "Matched"
                ))
            )
        )
        po_summary["Brand"] = "Zepto"

        # Header
        h = st.columns([2, 2, 2, 1, 1, 2, 1])
        for label, col in zip(
            ["Dispatch Date","INVOICE #","PO Number","Brand","SKUs","Flag",""],
            h
        ):
            col.markdown(f"**{label}**")
        st.markdown("---")

        review_po = st.session_state.get("dash_review_po", None)

        for i, (_, po_row) in enumerate(po_summary.iterrows()):
            po_num = str(po_row.get("PO Number", "—"))
            flag   = str(po_row.get("Flag", "—"))
            icon   = FLAG_COLORS.get(flag, "⚪")

            c = st.columns([2, 2, 2, 1, 1, 2, 1])
            c[0].markdown(f"<small>{str(po_row.get('Dispatch Date','—'))[:10]}</small>", unsafe_allow_html=True)
            c[1].markdown(f"<small>{str(po_row.get('INVOICE #','—'))}</small>", unsafe_allow_html=True)
            c[2].markdown(f"<small>{po_num}</small>", unsafe_allow_html=True)
            c[3].markdown(f"<small>Zepto</small>", unsafe_allow_html=True)
            c[4].markdown(f"<small>{str(po_row.get('SKUs','—'))}</small>", unsafe_allow_html=True)
            c[5].markdown(f"<small>{icon} {flag}</small>", unsafe_allow_html=True)

            if c[6].button("🔍", key=f"dash_rev_{i}", help="View SKU details"):
                if review_po == po_num:
                    del st.session_state["dash_review_po"]
                    review_po = None
                else:
                    st.session_state["dash_review_po"] = po_num
                    review_po = po_num
                st.rerun()

            # Show SKU details inline
            if review_po == po_num:
                po_rows = filtered[filtered["PO Number"] == po_num]
                with st.container():
                    st.markdown(f"**📋 {po_num}** — {len(po_rows)} SKU(s)")
                    for _, row in po_rows.iterrows():
                        with st.expander(f"{row.get('SKU Name','—')} — {row.get('Flag','—')}"):
                            c1, c2 = st.columns(2)
                            with c1:
                                st.markdown(f"**SKU Code:** {row.get('SKU Code','—')}")
                                st.markdown(f"**SKU Name:** {row.get('SKU Name','—')}")
                                st.markdown(f"**Dispatch Status:** {row.get('Dispatch Status','—')}")
                                st.markdown(f"**GRN Status:** {row.get('GRN Status','—')}")
                            with c2:
                                st.markdown(f"**PO Qty:** {row.get('PO Qty',0)}")
                                st.markdown(f"**Dispatch Qty:** {row.get('Dispatch Qty',0)}")
                                st.markdown(f"**GRN Qty:** {row.get('GRN Qty',0)}")
                                st.markdown(f"**Difference:** {row.get('Difference',0)}")
                            st.info(str(row.get("Reason","—")))

            st.markdown("<hr style='margin:2px 0'>", unsafe_allow_html=True)
