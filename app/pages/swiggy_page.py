import streamlit as st
import pandas as pd
from datetime import datetime

from app.ingestion.file_loader import load_file
from app.core.reconciliation import reconcile, get_summary
from app.core.sheets import (
    get_client,
    fetch_swiggy_dispatch_sheet,
    fetch_swiggy_grn_sheet,
    fetch_swiggy_sku_mapping,
    check_grn_duplicates,
)
from app.platforms.swiggy.mapper import (
    enrich_grn_with_sku,
    enrich_dispatch_with_sku,
    build_unified,
)

SKU_COLS = [
    'CP','GGP','TP','GIN','GAR','MVS','TMS','TDK','KRJ',
    'SAM','HB','CM','BM','GWR','PDKC','BPB','KM','PKM',
    'XAC','TMP','TRS','MSB','GGGTP','SOUPS'
]


def render():
    st.markdown("## 🟠 Swiggy Reconciliation")
    st.divider()

    page = st.session_state.get("swiggy_step", "upload")
    if page == "dashboard" and "swiggy_final_df" not in st.session_state:
        page = "upload"
        st.session_state["swiggy_step"] = "upload"

    if page == "upload":
        _render_upload()
    elif page == "dashboard":
        _render_dashboard()


def _render_upload():
    st.markdown("### Upload GRN File")
    st.caption(
        "Upload the GRN file received from Swiggy. "
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
        loaded = load_file(uploaded_file)
        raw_sheets = list(loaded["sheets"].values())

        df_grn_raw = None
        for df in raw_sheets:
            cols = [str(c).strip() for c in df.columns]
            if "SkuCode" in cols or "PurchaseOrderNumber" in cols:
                df.columns = cols
                df_grn_raw = df.copy()
                break
            if len(df) > 0:
                first_row = [str(v).strip() for v in df.iloc[0].values]
                if "SkuCode" in first_row or "PurchaseOrderNumber" in first_row:
                    df.columns = first_row
                    df = df.drop(0).reset_index(drop=True)
                    df_grn_raw = df.copy()
                    break

        if df_grn_raw is None:
            df_grn_raw = raw_sheets[0].copy()
        df_grn_raw.columns = [str(c).strip() for c in df_grn_raw.columns]

        col_map = {
            "PurchaseOrderNumber":  "po_id",
            "SkuCode":              "sku_item_code",
            "SkuDescription":       "product_name",
            "ReceivedQty":          "grn_qty",
            "GrnNumber":            "grn_id",
            "InvoiceNumber":        "invoice_id",
            "FacilityName":         "facility",
            "CreatedAtDate":        "grn_date",
        }
        df_grn_raw = df_grn_raw.rename(columns=col_map)

        for col in ["po_id", "sku_item_code", "grn_qty"]:
            if col not in df_grn_raw.columns:
                df_grn_raw[col] = ""

        df_grn_raw["po_id"] = df_grn_raw["po_id"].astype(str).str.strip()
        df_grn_raw["sku_item_code"] = df_grn_raw["sku_item_code"].astype(str).str.strip()
        df_grn_raw["grn_qty"] = pd.to_numeric(
            df_grn_raw["grn_qty"], errors="coerce"
        ).fillna(0)

        progress.progress(15, text="Fetching data from Google Sheet...")

        client       = get_client()
        dispatch_df  = fetch_swiggy_dispatch_sheet(client)
        sheet_grn_df = fetch_swiggy_grn_sheet(client)
        df_sku       = fetch_swiggy_sku_mapping(client)

        st.info(
            f"📊 Fetched: {len(dispatch_df)} dispatch rows | "
            f"{len(sheet_grn_df)} existing GRN rows | "
            f"{len(df_sku)} SKU mappings (Swiggy)"
        )

        progress.progress(35, text="Checking GRN duplicates...")

        dup_result  = check_grn_duplicates(df_grn_raw, sheet_grn_df)
        df_grn_new  = dup_result["new"]
        df_grn_dups = dup_result["duplicates"]

        st.info(
            f"GRN: {len(df_grn_new)} new rows | "
            f"{len(df_grn_dups)} duplicates skipped"
        )

        df_grn = df_grn_new.copy() if not df_grn_new.empty else df_grn_raw.copy()

        progress.progress(55, text="Processing dispatch data...")

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

        df_grn_e = enrich_grn_with_sku(df_grn, df_sku)

        progress.progress(75, text="Enriching dispatch with SKU data...")

        df_disp_e = enrich_dispatch_with_sku(melted, df_sku)

        progress.progress(82, text="Building unified view...")

        df_unified = build_unified(df_grn_e, df_disp_e)

        progress.progress(90, text="Reconciling...")

        df_final = reconcile(df_unified)

        df_final["platform"]       = "Swiggy"
        df_final["processed_date"] = datetime.today().strftime("%d-%b-%Y")

        st.session_state["swiggy_final_df"] = df_final
        st.session_state["swiggy_step"]     = "dashboard"

        progress.progress(100, text="Done!")
        st.rerun()

    except Exception as e:
        progress.empty()
        st.error(f"❌ Processing failed: {e}")
        st.exception(e)


def _render_dashboard():
    df = st.session_state.get("swiggy_final_df")
    if df is None or df.empty:
        st.info("No reconciliation data yet.")
        return

    if st.button("← Upload another file"):
        st.session_state["swiggy_step"] = "upload"
        st.rerun()

    summary = get_summary(df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", summary.get("total", len(df)))
    c2.metric("Matched", summary.get("matched", 0))
    c3.metric("Missing GRN", summary.get("missing_grn", 0))
    c4.metric("Short", summary.get("short", 0))

    st.divider()
    st.dataframe(df, use_container_width=True, height=500)
