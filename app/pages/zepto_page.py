import streamlit as st
import pandas as pd
from datetime import datetime

from app.ingestion.file_loader import load_file
from app.core.reconciliation import reconcile, get_summary
from app.core.sheets import (
    append_reconciliation_results,
    get_client,
    fetch_dispatch_sheet,
    fetch_grn_sheet,
    fetch_sku_mapping,
    check_grn_duplicates,
    append_raw_grn_to_sheet,
)

SKU_COLS = [
    'CP','GGP','TP','GIN','GAR','MVS','TMS','TDK','KRJ',
    'SAM','HB','CM','BM','GWR','PDKC','BPB','KM','PKM',
    'XAC','TMP','TRS','MSB','GGGTP','SOUPS'
]


def render():
    st.markdown("## 🟢 Zepto Reconciliation")
    st.divider()

    page = st.session_state.get("zepto_step", "upload")
    if page == "dashboard" and "zepto_final_df" not in st.session_state:
        page = "upload"
        st.session_state["zepto_step"] = "upload"

    if page == "upload":
        _render_upload()
    elif page == "dashboard":
        _render_dashboard()


def _render_upload():
    st.markdown("### Upload GRN File")
    st.caption(
        "Upload the GRN file received from Zepto. "
        "SKU Mapping and Dispatch data will be fetched automatically from the Google Sheet."
    )

    uploaded = st.file_uploader(
        "Upload GRN file",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=False,
        label_visibility="collapsed"
    )

    if not uploaded:
        st.info("📂 Upload GRN file to begin.")
        return

    st.success(f"✅ {uploaded.name} received")

    if st.button("🚀 Fetch & Reconcile", type="primary", use_container_width=True):
        _process(uploaded)


def _process(uploaded_file):
    progress = st.progress(0, text="Loading GRN file...")
    try:
        # ── Load GRN file ─────────────────────────────────────────
        loaded = load_file(uploaded_file)
        raw_sheets = list(loaded["sheets"].values())

        # Find sheet with correct columns
        df_grn_raw = None
        for df in raw_sheets:
            cols = [str(c).strip() for c in df.columns]
            if "SKU ID" in cols or "PO Code" in cols:
                df.columns = cols
                df_grn_raw = df.copy()
                break
            # Check first row as header
            if len(df) > 0:
                first_row = [str(v).strip() for v in df.iloc[0].values]
                if "SKU ID" in first_row or "PO Code" in first_row:
                    df.columns = first_row
                    df = df.drop(0).reset_index(drop=True)
                    df_grn_raw = df.copy()
                    break

        if df_grn_raw is None:
            df_grn_raw = raw_sheets[0].copy()
        df_grn_raw.columns = [str(c).strip() for c in df_grn_raw.columns]

        # Standardize column names
        col_map = {
            "PO Code":              "po_id",
            "PurchaseOrder":        "po_id",
            "PurchaseOrderNumber":  "po_id",
            "SKU ID":               "sku_id",
            "SkuCode":              "sku_id",
            "GRN Quantity":         "grn_qty",
            "ReceivedQty":          "grn_qty",
            "PO Quantity":          "po_qty",
            "GRN Code":             "grn_id",
            "GrnNumber":            "grn_id",
            "Invoice No":           "invoice_id",
            "InvoiceNumber":        "invoice_id",
            "Product Name":         "product_name",
            "SkuDescription":       "product_name",
            "FacilityName":         "facility",
            "To Store Name":        "facility",
            "Cost Price":           "unit_cost",
            "UNIT COST":            "unit_cost",
            "GRN Date":             "grn_date",
        }
        df_grn_raw = df_grn_raw.rename(columns=col_map)

        for col in ["po_id", "sku_id", "grn_qty"]:
            if col not in df_grn_raw.columns:
                df_grn_raw[col] = ""

        df_grn_raw["po_id"]  = df_grn_raw["po_id"].astype(str).str.strip()
        df_grn_raw["sku_id"] = df_grn_raw["sku_id"].astype(str).str.strip()
        df_grn_raw["grn_qty"] = pd.to_numeric(
            df_grn_raw["grn_qty"], errors="coerce"
        ).fillna(0)
        if "po_qty" in df_grn_raw.columns:
            df_grn_raw["po_qty"] = pd.to_numeric(
                df_grn_raw["po_qty"], errors="coerce"
            ).fillna(0)
        else:
            df_grn_raw["po_qty"] = df_grn_raw["grn_qty"]

        progress.progress(15, text="Fetching data from Google Sheet...")

        # ── Fetch all data from Google Sheet ──────────────────────
        client       = get_client()
        dispatch_df  = fetch_dispatch_sheet(client)
        sheet_grn_df = fetch_grn_sheet(client)
        df_sku       = fetch_sku_mapping(client)

        st.info(
            f"📊 Fetched: {len(dispatch_df)} dispatch rows | "
            f"{len(sheet_grn_df)} existing GRN rows | "
            f"{len(df_sku)} SKU mappings (Zepto)"
        )

        progress.progress(35, text="Checking GRN duplicates...")

        # ── Check duplicates ──────────────────────────────────────
        dup_result  = check_grn_duplicates(df_grn_raw, sheet_grn_df)
        df_grn_new  = dup_result["new"]
        df_grn_dups = dup_result["duplicates"]

        st.info(
            f"GRN: {len(df_grn_new)} new rows | "
            f"{len(df_grn_dups)} duplicates skipped"
        )

        # Raw GRN export handled after reconciliation (with dedup guard)

        # Use new GRN rows for reconciliation
        df_grn = df_grn_new.copy() if not df_grn_new.empty else df_grn_raw.copy()

        progress.progress(55, text="Processing dispatch data...")

        # ── Melt dispatch SKU columns ─────────────────────────────
        present_sku = [c for c in SKU_COLS if c in dispatch_df.columns]
        for col in present_sku:
            dispatch_df[col] = pd.to_numeric(
                dispatch_df[col], errors="coerce"
            ).fillna(0)

        id_cols = [c for c in ["Dispatch Date","PO Number","INVOICE #","Warehouse"]
                   if c in dispatch_df.columns]

        melted = dispatch_df[id_cols + present_sku].melt(
            id_vars=id_cols,
            value_vars=present_sku,
            var_name="sku_code",
            value_name="dispatch_qty"
        )
        melted = melted[melted["dispatch_qty"] > 0].copy()
        melted = melted.rename(columns={
            "Dispatch Date": "dispatch_date",
            "PO Number":     "po_id",
            "INVOICE #":     "invoice_id",
            "Warehouse":     "warehouse",
        })
        melted["po_id"] = melted["po_id"].astype(str).str.strip()
        melted["dispatch_date"] = pd.to_datetime(
            melted["dispatch_date"], errors="coerce"
        )

        progress.progress(68, text="Enriching GRN with SKU data...")

        # ── Enrich GRN with SKU mapping ───────────────────────────
        # GRN has sku_id (UUID) → join with mapping on sku_id
        df_grn_e = df_grn.merge(
            df_sku[["sku_id","sku_code","sku_name"]],
            on="sku_id",
            how="left"
        )

        progress.progress(75, text="Enriching dispatch with SKU data...")

        # ── Enrich dispatch with SKU mapping ──────────────────────
        # Dispatch has sku_code (abbreviation) → join with mapping on sku_code
        df_disp_e = melted.merge(
            df_sku[["sku_id","sku_code","sku_name"]],
            on="sku_code",
            how="left"
        )
        # Drop unmapped
        before = len(df_disp_e)
        df_disp_e = df_disp_e[df_disp_e["sku_id"].notna()].copy()
        after = len(df_disp_e)
        if before != after:
            print(f"  [Mapper] Dropped {before-after} unmapped dispatch rows")

        progress.progress(82, text="Building unified view...")

        # ── Build unified DataFrame ───────────────────────────────
        from app.platforms.zepto.mapper import build_unified
        df_unified = build_unified(df_grn_e, df_disp_e)

        progress.progress(90, text="Reconciling...")

        df_final = reconcile(df_unified)
        df_final["platform"]       = "Zepto"
        df_final["processed_date"] = datetime.today().strftime("%d-%b-%Y")

        # ── Append raw GRN to GRN-ZEPTO sheet ────────────────────
        progress.progress(90, text="Saving raw GRN to Google Sheet...")
        if not df_grn_new.empty:
            grn_export_rows = append_raw_grn_to_sheet(client, df_grn_new)
            st.success(f"✅ {grn_export_rows} new GRN rows saved to GRN-ZEPTO sheet")

        # ── Export to Reconciliation Results sheet ────────────────
        progress.progress(95, text="Saving reconciliation results...")
        reco_rows = append_reconciliation_results(client, df_final, dispatch_df)
        st.success(f"✅ {reco_rows} reconciliation rows saved to sheet")

        progress.progress(100, text="Done!")

        st.session_state["zepto_final_df"]  = df_final
        st.session_state["grn_dup_count"]   = len(df_grn_dups)
        st.session_state["grn_new_count"]   = len(df_grn_new)
        st.session_state["dispatch_count"]  = len(dispatch_df)
        st.session_state["zepto_step"]      = "dashboard"
        st.rerun()

    except Exception as e:
        st.error(f"❌ Failed: {e}")
        import traceback
        st.code(traceback.format_exc())


def _render_dashboard():
    df      = st.session_state["zepto_final_df"]
    summary = get_summary(df)

    st.info(
        f"📊 Dispatch: {st.session_state.get('dispatch_count',0)} rows | "
        f"GRN new: {st.session_state.get('grn_new_count',0)} | "
        f"Duplicates skipped: {st.session_state.get('grn_dup_count',0)}"
    )

    st.markdown("### 📊 Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Records",   summary["total_records"])
    c2.metric("Matched",         summary["matched"])
    c3.metric("Total Conflicts", summary["total_conflicts"])
    c4.metric("Unique SKUs",     summary["unique_skus"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Short",            summary["short"])
    c2.metric("Missing GRN",      summary["missing_grn"])
    c3.metric("Under Dispatched", summary["under_dispatched"])
    c4.metric("Not Dispatched",   summary["not_dispatched"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Total PO Qty",       f"{summary['total_po_qty']:,}")
    c2.metric("Total Dispatch Qty", f"{summary['total_dispatch_qty']:,}")
    c3.metric("Total GRN Qty",      f"{summary['total_grn_qty']:,}")

    st.divider()

    st.markdown("### 🔍 Filter Records")
    c1, c2, c3 = st.columns(3)
    with c1:
        status_filter = st.multiselect(
            "Status",
            options=["Matched","Short","Excess","Missing GRN","Missing Dispatch",
                     "Under Dispatched","Not Dispatched","Out of Period"],
            default=["Short","Missing GRN","Missing Dispatch",
                     "Under Dispatched","Not Dispatched"]
        )
    with c2:
        sku_options = ["All"] + sorted(df["sku_name"].dropna().unique().tolist())
        sku_filter = st.selectbox("SKU", sku_options)
    with c3:
        po_search = st.text_input(
            "Search PO ID",
            placeholder="e.g. P4686468",
            key="po_search_dash"
        )

    filtered = df.copy()
    if status_filter:
        filtered = filtered[filtered["status"].isin(status_filter)]
    if sku_filter != "All":
        filtered = filtered[filtered["sku_name"] == sku_filter]
    if po_search.strip():
        filtered = filtered[
            filtered["po_id"].astype(str).str.contains(
                po_search.strip(), case=False
            )
        ]

    st.caption(f"Showing {len(filtered)} of {len(df)} records")

    if len(filtered) == 0:
        st.info("No records match the current filters.")
    else:
        # PO-level summary table
        po_summary = (
            filtered.groupby(["po_id"], as_index=False)
            .agg(
                invoice_id    = ("invoice_id",    "first"),
                dispatch_date = ("dispatch_date", "first"),
                sku_count     = ("sku_name",      "count"),
                overall_flag  = ("status", lambda x: (
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
        po_summary = po_summary.rename(columns={
            "po_id":         "PO Number",
            "invoice_id":    "INVOICE #",
            "dispatch_date": "Dispatch Date",
            "sku_count":     "SKUs",
            "overall_flag":  "Flag"
        })

        # Compact table header
        h = st.columns([2, 2, 2, 1, 2, 1])
        for label, col in zip(
            ["Dispatch Date","INVOICE #","PO Number","SKUs","Flag",""],
            h
        ):
            col.markdown(f"<small><b>{label}</b></small>", unsafe_allow_html=True)
        st.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)

        review_po = st.session_state.get("review_po", None)

        for i, (_, po_row) in enumerate(po_summary.iterrows()):
            po_num = str(po_row.get("PO Number","—"))
            flag   = str(po_row.get("Flag","—"))
            flag_icon = {
                "Short": "🔴", "Missing GRN": "🟣",
                "Under Dispatched": "🟠", "Not Dispatched": "🔴",
                "Missing Dispatch": "🔵", "Matched": "🟢"
            }.get(flag, "⚪")

            c = st.columns([2, 2, 2, 1, 2, 1])
            c[0].markdown(f"<small>{str(po_row.get('Dispatch Date','—'))[:10]}</small>", unsafe_allow_html=True)
            c[1].markdown(f"<small>{str(po_row.get('INVOICE #','—'))}</small>", unsafe_allow_html=True)
            c[2].markdown(f"<small>{po_num}</small>", unsafe_allow_html=True)
            c[3].markdown(f"<small>{str(po_row.get('SKUs','—'))}</small>", unsafe_allow_html=True)
            c[4].markdown(f"<small>{flag_icon} {flag}</small>", unsafe_allow_html=True)
            if c[5].button("🔍", key=f"review_{i}", help="View SKU details"):
                if review_po == po_num:
                    del st.session_state["review_po"]
                    review_po = None
                else:
                    st.session_state["review_po"] = po_num
                    review_po = po_num
                st.rerun()

            # Show review card immediately below this row
            if review_po == po_num:
                po_rows = filtered[filtered["po_id"].astype(str) == po_num]
                with st.container():
                    st.markdown(f"**📋 {po_num}** — {len(po_rows)} SKU(s)")
                    for _, row in po_rows.iterrows():
                        with st.expander(
                            str(row.get("sku_name","—")) + " — " + str(row.get("grn_status","—"))
                        ):
                            _render_detail_card(row)

            st.markdown("<hr style='margin:2px 0'>", unsafe_allow_html=True)

    st.divider()
    if st.button("🔄 Start Over", use_container_width=True):
        for key in ["zepto_final_df","zepto_step","grn_dup_count",
                    "grn_new_count","dispatch_count"]:
            st.session_state.pop(key, None)
        st.rerun()


def _render_detail_card(row):
    grn_id = str(row.get("grn_id","—"))
    if grn_id == "nan":
        grn_id = "—"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Status:** {row.get('status','—')}")
        st.markdown(f"**Dispatch Status:** {row.get('dispatch_status','—')}")
        st.markdown(f"**GRN Status:** {row.get('grn_status','—')}")
        st.markdown(f"**SKU Code:** {row.get('sku_code','—')}")
        st.markdown(f"**SKU Name:** {row.get('sku_name','—')}")
        st.markdown(f"**SKU ID:** {row.get('sku_id','—')}")
    with c2:
        st.markdown(f"**PO ID:** {row.get('po_id','—')}")
        st.markdown(f"**GRN ID:** {grn_id}")
        st.markdown(f"**Invoice ID:** {row.get('invoice_id','—')}")
        st.markdown(f"**PO Qty:** {int(row.get('po_qty',0))}")
        st.markdown(f"**Dispatch Qty:** {int(row.get('dispatch_qty',0))}")
        st.markdown(f"**GRN Qty:** {int(row.get('grn_qty',0))}")
        st.markdown(f"**Dispatch Date:** {str(row.get('dispatch_date','—'))[:10]}")
    st.info(str(row.get("reason","—")))
