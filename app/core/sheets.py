import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import json

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SHEET_URL  = "https://docs.google.com/spreadsheets/d/1B8f1v8efIKwxFoM0muI1GpcO_pyEg3HV9w4U6txRZHQ/edit"
CUTOFF     = pd.Timestamp("2026-04-01")


def get_client(json_path: str = "data/service_account.json"):
    import os

    # 1. Try Streamlit secrets
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            info  = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            return gspread.authorize(creds)
    except Exception:
        pass

    # 2. Try environment variable
    gcp_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if gcp_json:
        info  = json.loads(gcp_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)

    # 3. Try Render secret file paths
    for path in [
        "/etc/secrets/service_account.json",
        "/opt/render/project/src/service_account.json",
        "service_account.json",
        json_path,
    ]:
        if os.path.exists(path):
            info  = json.load(open(path))
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            return gspread.authorize(creds)

    raise FileNotFoundError("No service account credentials found")


def fetch_dispatch_sheet(client) -> pd.DataFrame:
    """
    Fetch DISPATCH tab.
    Row 1 = summary (skip), Row 2 = real headers, Row 3+ = data.
    Filter: Brand == Zepto AND Dispatch Date >= 1 Apr 2026.
    Returns columns: Dispatch Date, INVOICE #, PO Number, Brand
    + all SKU qty columns if present.
    """
    sh  = client.open_by_url(SHEET_URL)
    ws  = sh.worksheet("DISPATCH")
    all_values = ws.get_all_values()

    if len(all_values) < 2:
        return pd.DataFrame()

    headers   = all_values[1]   # Row 2 = real headers
    data_rows = all_values[2:]  # Row 3+ = data

    df = pd.DataFrame(data_rows, columns=headers)

    # Filter Zepto only
    if "Brand" in df.columns:
        df = df[df["Brand"].astype(str).str.strip() == "Zepto"].copy()

    # Parse and filter by date
    if "Dispatch Date" in df.columns:
        df["Dispatch Date"] = pd.to_datetime(
            df["Dispatch Date"], dayfirst=True, errors="coerce"
        )
        df = df[df["Dispatch Date"] >= CUTOFF].copy()

    # Clean PO Number
    if "PO Number" in df.columns:
        df["PO Number"] = df["PO Number"].astype(str).str.strip()
        df = df[df["PO Number"].notna()]
        df = df[df["PO Number"] != ""]
        df = df[df["PO Number"] != "nan"]

    return df.reset_index(drop=True)


def fetch_grn_sheet(client) -> pd.DataFrame:
    """
    Fetch GRN-ZEPTO tab.
    Row 1 = real headers.
    Filter: REPORT DATE >= 1 Apr 2026.
    Returns clean DataFrame with standardized column names:
        grn_id, po_id, sku_code, grn_qty, invoice_id,
        facility, report_date
    """
    sh  = client.open_by_url(SHEET_URL)
    ws  = sh.worksheet("GRN-ZEPTO")
    all_values = ws.get_all_values()

    if len(all_values) < 2:
        return pd.DataFrame()

    headers   = all_values[0]   # Row 1 = real headers
    data_rows = all_values[1:]  # Row 2+ = data

    df = pd.DataFrame(data_rows, columns=headers)

    # Parse and filter by date
    if "REPORT DATE" in df.columns:
        df["REPORT DATE"] = pd.to_datetime(
            df["REPORT DATE"], dayfirst=True, errors="coerce"
        )
        df = df[df["REPORT DATE"] >= CUTOFF].copy()

    # Rename to standard names
    df = df.rename(columns={
        "REPORT DATE":          "report_date",
        "GrnNumber":            "grn_id",
        "PurchaseOrderNumber":  "po_id",
        "FacilityName":         "facility",
        "InvoiceNumber":        "invoice_id",
        "SkuCode":              "sku_code",
        "SkuDescription":       "sku_name",
        "ReceivedQty":          "grn_qty",
    })

    # Keep only needed columns
    keep = [c for c in ["report_date","grn_id","po_id","facility",
                         "invoice_id","sku_code","sku_name","grn_qty"]
            if c in df.columns]
    df = df[keep].copy()

    # Clean
    if "po_id" in df.columns:
        df["po_id"] = df["po_id"].astype(str).str.strip()
        df = df[df["po_id"] != ""]
        df = df[df["po_id"] != "nan"]

    if "grn_qty" in df.columns:
        df["grn_qty"] = pd.to_numeric(df["grn_qty"], errors="coerce").fillna(0)

    if "sku_code" in df.columns:
        df["sku_code"] = df["sku_code"].astype(str).str.strip()

    return df.reset_index(drop=True)


def check_grn_duplicates(new_df: pd.DataFrame,
                          sheet_grn_df: pd.DataFrame) -> dict:
    """
    Check uploaded GRN against GRN-ZEPTO sheet.
    Duplicate = same PO Code (PurchaseOrderNumber).
    Returns:
        new        → rows NOT already in sheet
        duplicates → rows already in sheet
    """
    new_df       = new_df.copy()
    sheet_grn_df = sheet_grn_df.copy()

    if sheet_grn_df.empty or "po_id" not in sheet_grn_df.columns:
        return {"new": new_df, "duplicates": pd.DataFrame()}

    existing_pos = set(sheet_grn_df["po_id"].astype(str).str.strip().tolist())

    # Map new_df po column — could be po_id or PO Code
    po_col = "po_id" if "po_id" in new_df.columns else "PO Code"
    if po_col not in new_df.columns:
        return {"new": new_df, "duplicates": pd.DataFrame()}

    new_df[po_col] = new_df[po_col].astype(str).str.strip()
    is_dup = new_df[po_col].isin(existing_pos)

    return {
        "new":        new_df[~is_dup].copy(),
        "duplicates": new_df[is_dup].copy()
    }
def fetch_conso_po_sheet(client) -> pd.DataFrame:
    """
    Fetch ConsoPO tab.
    Rows 1-3 = blank/title rows (skip), Row 4 = real headers, Row 5+ = data.
    Filter: Channel == Zepto.
    Primary key: PO no. (also carries Invoice No.)
    """
    sh = client.open_by_url(SHEET_URL)
    ws = sh.worksheet("ConsoPO")
    all_values = ws.get_all_values()

    if len(all_values) < 4:
        return pd.DataFrame()

    headers   = all_values[3]   # Row 4 = real headers
    data_rows = all_values[4:]  # Row 5+ = data

    df = pd.DataFrame(data_rows, columns=headers)

    # Filter Zepto only (via Channel, not Brand)
    if "Channel" in df.columns:
        df = df[df["Channel"].astype(str).str.strip() == "Zepto"].copy()

    # Clean PO no. (primary key)
    if "PO no." in df.columns:
        df["PO no."] = df["PO no."].astype(str).str.strip()
        df = df[df["PO no."].notna()]
        df = df[df["PO no."] != ""]
        df = df[df["PO no."] != "nan"]

    return df.reset_index(drop=True)


def fetch_sku_mapping(client) -> pd.DataFrame:
    """
    Fetch SKU mapping from MAPPING tab.
    Filter: Brand == Zepto only.
    MAPPING columns: Brand | Item Code | Item | Item
    Returns DataFrame with: sku_id, sku_code, sku_name
    """
    sh  = client.open_by_url(SHEET_URL)
    ws  = sh.worksheet("MAPPING")
    all_values = ws.get_all_values()

    if len(all_values) < 2:
        return pd.DataFrame()

    # Rename by position since "Item" appears twice
    # Position 0 = Brand, 1 = Item Code, 2 = Item (sku_code), 3 = Item (sku_name)
    data_rows = all_values[1:]
    rows = []
    for row in data_rows:
        if len(row) >= 4:
            rows.append({
                "brand":    row[0].strip(),
                "sku_id":   row[1].strip(),
                "sku_code": row[2].strip(),
                "sku_name": row[3].strip(),
            })

    df = pd.DataFrame(rows)

    # Filter Zepto only
    df = df[df["brand"] == "Zepto"].copy()
    df = df[["sku_id", "sku_code", "sku_name"]].copy()
    df = df[df["sku_id"] != ""].reset_index(drop=True)

    return df


def append_raw_grn_to_sheet(client, df_grn: pd.DataFrame) -> int:
    """
    Append new raw GRN rows to GRN-ZEPTO tab.
    Duplicate key: GRN Code + SKU Code (UUID).
    Fills FacilityName from uploaded file.
    Fills UNIT COST from uploaded file, fallback to sheet lookup.
    Calculates GrnLineValueWithTax = UNIT COST x ReceivedQty.
    """
    sh = client.open_by_url(SHEET_URL)
    ws = sh.worksheet("GRN-ZEPTO")

    existing = ws.get_all_values()

    # Build duplicate key set: GrnNumber + SkuCode (col 1 + col 9)
    existing_keys = set()
    sku_lookup    = {}
    if len(existing) > 1:
        for row in existing[1:]:
            if len(row) > 9:
                grn_code = row[1].strip()
                sku_code = row[9].strip()
                if grn_code and sku_code:
                    existing_keys.add((grn_code, sku_code))
                if len(row) > 12 and sku_code and row[12].strip():
                    if sku_code not in sku_lookup:
                        sku_lookup[sku_code] = {
                            "unit_cost": row[12].strip(),
                            "facility":  row[3].strip() if len(row) > 3 else ""
                        }

    # Load cache
    import os, json as _json
    cache_file = "/tmp/.grn_export_cache.json"
    if os.path.exists(cache_file):
        try:
            cached = _json.load(open(cache_file))
            for k in cached:
                existing_keys.add(tuple(k))
        except Exception:
            pass

    print(f"  [GRN Export] Existing keys: {len(existing_keys)}")

    today = pd.Timestamp.today().strftime("%d-%b-%Y")
    rows  = []
    seen  = set()

    for _, row in df_grn.iterrows():
        grn_id = str(row.get("grn_id", "")).strip()
        sku_id = str(row.get("sku_id", "")).strip()

        if not grn_id or grn_id == "nan":
            continue

        key = (grn_id, sku_id)
        if key in existing_keys or key in seen:
            continue
        seen.add(key)

        grn_qty = int(row.get("grn_qty", 0))

        # Get unit_cost from uploaded file first
        unit_cost_raw = row.get("unit_cost", "")
        if unit_cost_raw == "" or str(unit_cost_raw) == "nan" or str(unit_cost_raw) == "0":
            unit_cost = sku_lookup.get(sku_id, {}).get("unit_cost", "")
        else:
            unit_cost = str(unit_cost_raw)

        # Get facility from uploaded file first
        facility_raw = row.get("facility", "")
        if facility_raw == "" or str(facility_raw) == "nan":
            facility = sku_lookup.get(sku_id, {}).get("facility", "")
        else:
            facility = str(facility_raw)

        # Calculate GrnLineValueWithTax
        try:
            grn_line_value = str(round(float(unit_cost) * grn_qty, 2)) if unit_cost else ""
        except Exception:
            grn_line_value = ""

        rows.append([
            today,
            grn_id,
            str(row.get("po_id", "")),
            facility,
            str(row.get("invoice_id", "")),
            "",
            "",
            "",
            "",
            sku_id,
            str(row.get("product_name", "")),
            str(grn_qty),
            unit_cost,
            grn_line_value,
        ])

    print(f"  [GRN Export] New rows: {len(rows)}")
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        try:
            existing_cache = []
            if os.path.exists(cache_file):
                existing_cache = _json.load(open(cache_file))
            _json.dump(existing_cache + [[r[1], r[9]] for r in rows], open(cache_file, "w"))
        except Exception:
            pass
    return len(rows)


def append_reco_to_sheet(client, df_final: pd.DataFrame):
    """
    Append reconciliation results to Reconciliation data zepto tab.
    Columns: Date | GRN Code | PO Code | Store Name | Invoice Number | SKU ID | GRN Quantity
    """
    sh = client.open_by_url(SHEET_URL)

    # Get or create the sheet
    try:
        ws = sh.worksheet("Reconcilation data zepto")
    except Exception:
        ws = sh.add_worksheet("Reconcilation data zepto", rows=5000, cols=10)

    # Check if headers exist
    existing = ws.get_all_values()
    if not existing or existing[0] != ["Date", "GRN Code", "PO Code", "Store Name",
                                        "Invoice Number", "SKU ID", "GRN Quantity"]:
        ws.update("A1", [["Date", "GRN Code", "PO Code", "Store Name",
                           "Invoice Number", "SKU ID", "GRN Quantity"]])

    today = pd.Timestamp.today().strftime("%d-%b-%Y")

    rows = []
    for _, row in df_final.iterrows():
        grn_id = str(row.get("grn_id", ""))
        if grn_id == "nan":
            grn_id = ""
        rows.append([
            today,
            grn_id,
            str(row.get("po_id", "")),
            str(row.get("facility", row.get("warehouse", ""))),
            str(row.get("invoice_id", "")),
            str(row.get("sku_id", "")),
            str(int(row.get("grn_qty", 0))),
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return len(rows)


def append_reconciliation_results(client, df_final: pd.DataFrame, dispatch_df: pd.DataFrame) -> int:
    """
    Append reconciliation results to Reconciliation Results tab.
    Duplicate key: PO Number + SKU Code.
    """
    sh = client.open_by_url(SHEET_URL)
    ws = sh.worksheet("Reconciliation Results")

    existing = ws.get_all_values()

    # Build existing keys (PO Number + SKU Code) — col 3 + col 6
    existing_keys = set()
    if len(existing) > 1:
        for row in existing[1:]:
            if len(row) >= 7 and row[3].strip() and row[6].strip():
                existing_keys.add((row[3].strip(), row[6].strip()))

    # Build dispatch lookup: po_id -> dispatch_date, invoice_id
    dispatch_lookup = {}
    if "PO Number" in dispatch_df.columns:
        for _, row in dispatch_df.iterrows():
            po = str(row.get("PO Number", "")).strip()
            if po:
                dispatch_lookup[po] = {
                    "dispatch_date": str(row.get("Dispatch Date", ""))[:10],
                    "invoice_id":    str(row.get("INVOICE #", "")),
                }

    today = pd.Timestamp.today().strftime("%d-%b-%Y")
    rows  = []
    seen  = set()

    for _, row in df_final.iterrows():
        period = str(row.get("period", "in_period"))
        if period == "out_of_period":
            continue

        po_id    = str(row.get("po_id", "")).strip()
        sku_code = str(row.get("sku_code", "")).strip()

        if not po_id or not sku_code:
            continue

        key = (po_id, sku_code)
        if key in existing_keys or key in seen:
            continue
        seen.add(key)

        dispatch_info = dispatch_lookup.get(po_id, {})
        grn_qty       = int(row.get("grn_qty", 0))
        dispatch_qty  = int(row.get("dispatch_qty", 0))
        po_qty        = int(row.get("po_qty", 0))
        diff          = grn_qty - dispatch_qty

        rows.append([
            today,
            dispatch_info.get("dispatch_date", ""),
            dispatch_info.get("invoice_id", str(row.get("invoice_id", ""))),
            po_id,
            "Zepto",
            str(row.get("sku_name", "")),
            sku_code,
            str(po_qty),
            str(dispatch_qty),
            str(grn_qty),
            str(diff),
            str(row.get("dispatch_status", "")),
            str(row.get("grn_status", "")),
            str(row.get("status", "")),
            str(row.get("reason", "")),
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return len(rows)


def fetch_reconciliation_results(client) -> pd.DataFrame:
    """
    Fetch all data from Reconciliation Results tab.
    """
    sh = client.open_by_url(SHEET_URL)
    ws = sh.worksheet("Reconciliation Results")

    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return pd.DataFrame()

    headers   = all_values[0]
    data_rows = all_values[1:]
    df = pd.DataFrame(data_rows, columns=headers)
    df = df[df["PO Number"].astype(str).str.strip() != ""].copy()
    return df.reset_index(drop=True)
