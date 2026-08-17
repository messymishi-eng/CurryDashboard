import streamlit as st
import pandas as pd
from datetime import datetime

from app.ingestion.file_loader import load_file
from app.ingestion.file_detector import detect_all_files
from app.platforms.zepto.parser import parse_sku_mapping
from app.platforms.zepto.mapper import enrich_grn_with_sku, enrich_dispatch_with_sku, build_unified
from app.core.reconciliation import reconcile, get_summary
from app.core.sheets import get_client, fetch_dispatch_sheet, fetch_grn_sheet, check_grn_duplicates

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
    st.markdown("### Upload Files")
    st.caption(
        "Upload 2 files: **GRN file** (from Zepto) and **SKU Mapping** (Excel). "
        "Dispatch data and existing GRN records will be fetched automatically "
        "from the live Google Sheet (from 1 Apr 2026)."
    )

    uploaded = st.file_uploader(
        "Upload GRN file and SKU Mapping",
        type=["xlsx","xls","csv"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

    if not uploaded:
        st.info("📂 Upload GRN file and SKU Mapping to begin.")
        return

    st.success(f"✅ {len(uploaded)} file(s) received")
    for f in uploaded:
        st.write(f"- {f.name}")

    if st.button("🚀 Fetch & Reconcile", type="primary", use_container_width=True):
        _process(uploaded)


def _process(uploaded_files):
    progress = st.progress(0, text="Loading uploaded files...")
    try:
        # Step 1 — Load and detect uploaded files
        loaded   = [load_file(f) for f in uploaded_files]
        detected, undetected = detect_all_files(loaded)

        if undetected:
            st.error(f"Could not identify: {undetected}")
            st.stop()

        missing = [t for t in ["sku_mapping","grn"] if t not in detected]
        if missing:
            st.error(f"Missing: {missing}. Please upload both GRN and SKU Mapping.")
            st.stop()

        progress.progress(15, text="Parsing SKU Mapping...")
        df_sku = parse_sku_mapping(detected["sku_mapping"])

        progress.progress(25, text="Parsing uploaded GRN file...")
        # Parse GRN from uploaded file
        raw_grn_loaded = detected["grn"]
        raw_grn_sheet  = list(raw_grn_loaded["sheets"].values())

        # Find sheet with SKU ID column
        df_grn_uploaded = None
        for df in raw_grn_sheet:
            if "SKU ID" in df.columns:
                df_grn_uploaded = df.copy()
                break
            # Check first row as header
            if len(df) > 0 and "SKU ID" in df.iloc[0].values:
                df.columns = df.iloc[0].astype(str).str.strip()
                df = df.drop(0).reset_index(drop=True)
                df_grn_uploaded = df.copy()
                break

        if df_grn_uploaded is None:
            # Try CSV with different column names
            df_grn_uploaded = list(raw_grn_loaded["sheets"].values())[0].copy()

        df_grn_uploaded.columns = [str(c).strip() for c in df_grn_uploaded.columns]

        # Standardize column names
        col_map = {
            "PO Code":          "po_id",
            "PurchaseOrder":    "po_id",
            "PurchaseOrderNumber": "po_id",
            "SKU ID":           "sku_id",
            "SkuCode":          "sku_id",
            "GRN Quantity":     "grn_qty",
            "ReceivedQty":      "grn_qty",
            "PO Quantity":      "po_qty",
            "GRN Code":         "grn_id",
            "GrnNumber":        "grn_id",
            "Invoice No":       "invoice_id",
            "InvoiceNumber":    "invoice_id",
            "Product Name":     "product_name",
            "SkuDescription":   "product_name",
        }
        df_grn_uploaded = df_grn_uploaded.rename(columns=col_map)

        # Ensure required columns exist
        for col in ["po_id","sku_id","grn_qty"]:
            if col not in df_grn_uploaded.columns:
                df_grn_uploaded[col] = ""

        df_grn_uploaded["po_id"]  = df_grn_uploaded["po_id"].astype(str).str.strip()
        df_grn_uploaded["grn_qty"] = pd.to_numeric(
            df_grn_uploaded["grn_qty"], errors="coerce"
        ).fillna(0)
        if "po_qty" in df_grn_uploaded.columns:
            df_grn_uploaded["po_qty"] = pd.to_numeric(
                df_grn_uploaded["po_qty"], errors="coerce"
            ).fillna(0)
        else:
            df_grn_uploaded["po_qty"] = df_grn_uploaded["grn_qty"]

        progress.progress(40, text="Fetching Google Sheet data...")

        client       = get_client()
        dispatch_df  = fetch_dispatch_sheet(client)
        sheet_grn_df = fetch_grn_sheet(client)

        st.info(
            f"📊 Fetched from Google Sheet: "
            f"{len(dispatch_df)} dispatch rows, "
            f"{len(sheet_grn_df)} existing GRN rows (Apr 2026+)"
        )

        progress.progress(55, text="Checking GRN duplicates...")

        # Check uploaded GRN vs sheet GRN
        dup_result     = check_grn_duplicates(df_grn_uploaded, sheet_grn_df)
        df_grn_new     = dup_result["new"]
        df_grn_dups    = dup_result["duplicates"]

        st.info(
            f"GRN check: {len(df_grn_new)} new records, "
            f"{len(df_grn_dups)} already in sheet (skipped)"
        )

        # Use only new GRN records for reconciliation
        df_grn = df_grn_new.copy() if not df_grn_new.empty else df_grn_uploaded.copy()

        progress.progress(65, text="Processing dispatch data...")

        # Melt dispatch SKU columns
        present_sku = [c for c in SKU_COLS if c in dispatch_df.columns]
        for col in present_sku:
            dispatch_df[col] = pd.to_numeric(
                dispatch_df[col], errors="coerce"
            ).fillna(0)

        id_cols = [c for c in ["Dispatch Date","PO Number","INVOICE #","Warehouse","TQty"]
                   if c in dispatch_df.columns]

        if present_sku:
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
                "TQty":          "total_dispatch_qty"
            })
            melted["po_id"] = melted["po_id"].astype(str).str.strip()
            melted["dispatch_date"] = pd.to_datetime(
                melted["dispatch_date"], errors="coerce"
            )
        else:
            melted = pd.DataFrame()

        progress.progress(78, text="Enriching with SKU data...")

        # The uploaded GRN uses sku_id (UUID) — enrich with sku_code
        df_grn_e = enrich_grn_with_sku(df_grn, df_sku)

        if not melted.empty:
            df_disp_e  = enrich_dispatch_with_sku(melted, df_sku)
            progress.progress(88, text="Building unified view...")
            df_unified = build_unified(df_grn_e, df_disp_e)
        else:
            # No SKU cols in dispatch — use PO-level match
            dispatch_pos = set(dispatch_df["PO Number"].astype(str).str.strip())
            df_grn_e["dispatch_qty"]  = df_grn_e["po_qty"]
            df_grn_e["dispatch_date"] = None
            df_grn_e["invoice_id"]    = df_grn_e.get("invoice_id", "")
            df_grn_e["warehouse"]     = ""
            df_grn_e["period"]        = df_grn_e["po_id"].apply(
                lambda x: "in_period" if x in dispatch_pos else "out_of_period"
            )
            df_unified = df_grn_e.copy()

        progress.progress(93, text="Reconciling...")
        df_final = reconcile(df_unified)
        df_final["platform"]       = "Zepto"
        df_final["processed_date"] = datetime.today().strftime("%d-%b-%Y")

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

    # Info bar
    st.info(
        f"📊 Sheet: {st.session_state.get('dispatch_count',0)} dispatch rows | "
        f"GRN: {st.session_state.get('grn_new_count',0)} new | "
        f"{st.session_state.get('grn_dup_count',0)} duplicates skipped"
    )

    st.markdown("### 📊 Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Records",   summary["total_records"])
    c2.metric("Matched",         summary["matched"])
    c3.metric("Total Conflicts", summary["total_conflicts"])
    c4.metric("Unique SKUs",     summary["unique_skus"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Short (GRN)",      summary["short"])
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

        col_order = ["Dispatch Date","INVOICE #","PO Number","Brand","SKUs","Flag"]
        col_order = [c for c in col_order if c in po_summary.columns]
        st.dataframe(
            po_summary[col_order].fillna("—"),
            use_container_width=True,
            height=380
        )

        st.divider()
        st.markdown("### 🔎 SKU Details")
        selected_po = st.selectbox(
            "Select PO Number",
            po_summary["PO Number"].tolist(),
            label_visibility="collapsed",
            key="po_selector"
        )
        if selected_po:
            po_rows = filtered[
                filtered["po_id"].astype(str) == str(selected_po)
            ]
            st.caption(f"{len(po_rows)} SKU(s) for PO {selected_po}")
            for _, row in po_rows.iterrows():
                with st.expander(
                    str(row.get("sku_name","—")) + " — " +
                    str(row.get("grn_status","—"))
                ):
                    _render_detail_card(row)

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
