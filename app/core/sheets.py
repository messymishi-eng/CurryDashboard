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
    info  = json.load(open(json_path))
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


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
