import pandas as pd
import io

# These are the SKU abbreviation columns in the Dispatch file.
# Each column represents one product and contains qty dispatched.
SKU_COLS = [
    'CP', 'GGP', 'TP', 'GIN', 'GAR', 'MVS', 'TMS', 'TDK',
    'KRJ', 'SAM', 'HB', 'CM', 'BM', 'GWR', 'PDKC', 'BPB',
    'KM', 'PKM', 'XAC', 'TMP', 'TRS', 'MSB', 'GGGTP', 'SOUPS'
]


def parse_sku_mapping(loaded: dict) -> pd.DataFrame:
    """
    Reads the SKU mapping file.
    Returns a clean table with columns:
        sku_id   → the UUID used in the GRN file
        sku_code → short abbreviation used in the Dispatch file
        sku_name → full product name
    """
    # Take the first sheet
    df = list(loaded["sheets"].values())[0].copy()

    # Clean column names
    df.columns = [str(c).strip() for c in df.columns]

    # Rename to our standard names
    df = df.rename(columns={
        "Item Code": "sku_id",
        "Item":      "sku_code",
        "Item.1":    "sku_name",
        "Brand":     "brand"
    })

    # Keep only what we need
    df = df[["sku_id", "sku_code", "sku_name"]].copy()

    # Remove blank rows
    df = df.dropna(subset=["sku_id"])

    # Remove duplicate SKU IDs
    df = df.drop_duplicates(subset=["sku_id"])

    # Clean whitespace
    df["sku_id"]   = df["sku_id"].str.strip()
    df["sku_code"] = df["sku_code"].str.strip()
    df["sku_name"] = df["sku_name"].str.strip()

    return df.reset_index(drop=True)


def parse_grn(loaded: dict) -> pd.DataFrame:
    """
    Reads the GRN Excel file.
    The GRN file has two sheets:
        Sheet1 → PO-level summary (we skip this)
        Sheet2 → SKU-level detail (this is what we use)
    Returns a clean table with columns:
        po_id, sku_id, product_name,
        po_qty, grn_qty, grn_id, invoice_id
    """
    # Find the sheet that has SKU ID column
    detail_df = None
    for sheet_name, df in loaded["sheets"].items():
        if "SKU ID" in df.columns:
            detail_df = df.copy()
            break

    if detail_df is None:
        raise ValueError(
            "GRN file: Could not find a sheet with 'SKU ID' column. "
            "Please check the file."
        )

    # Clean column names
    detail_df.columns = [str(c).strip() for c in detail_df.columns]

    # Rename to standard names
    detail_df = detail_df.rename(columns={
        "PO Code":      "po_id",
        "SKU ID":       "sku_id",
        "Product Name": "product_name",
        "PO Quantity":  "po_qty",
        "GRN Quantity": "grn_qty",
        "GRN Code":     "grn_id",
        "Invoice No":   "invoice_id"
    })

    # Keep only needed columns
    cols = ["po_id", "sku_id", "product_name",
            "po_qty", "grn_qty", "grn_id", "invoice_id"]
    detail_df = detail_df[cols].copy()

    # Remove rows with no PO or SKU
    detail_df = detail_df.dropna(subset=["po_id", "sku_id"])

    # Convert quantities to numbers
    detail_df["po_qty"]  = pd.to_numeric(detail_df["po_qty"],  errors="coerce").fillna(0)
    detail_df["grn_qty"] = pd.to_numeric(detail_df["grn_qty"], errors="coerce").fillna(0)

    return detail_df.reset_index(drop=True)


def parse_dispatch(loaded: dict) -> pd.DataFrame:
    """
    Reads the Dispatch CSV file.
    The file has SKU quantities spread across columns (GGP, TP, GIN etc).
    We convert this wide format into long format:
        one row per PO + SKU combination.
    Returns a clean table with columns:
        po_id, invoice_id, dispatch_date,
        warehouse, sku_code, dispatch_qty
    """
    # Get the single sheet
    raw = list(loaded["sheets"].values())[0].copy()

    # Fix headers — the real header is in the first data row
    raw.columns = [str(c).strip() for c in raw.columns]

    if "Dispatch Date" not in raw.columns:
        # First row contains real headers
        raw.columns = raw.iloc[0].astype(str).str.strip()
        raw = raw.drop(0).reset_index(drop=True)

    raw.columns = [str(c).strip() for c in raw.columns]

    # Keep only Zepto rows
    if "Brand" in raw.columns:
        raw = raw[raw["Brand"].astype(str).str.strip() == "Zepto"].copy()

    # Find which SKU columns exist in this file
    present_sku_cols = [c for c in SKU_COLS if c in raw.columns]

    # Convert SKU columns to numeric
    for col in present_sku_cols:
        raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0)

    # Remove rows with no PO Number
    raw = raw.dropna(subset=["PO Number"])
    raw["PO Number"] = raw["PO Number"].astype(str).str.strip()

    # Define which columns to keep as identifiers
    id_cols = [c for c in ["Dispatch Date", "PO Number", "INVOICE #",
                            "Warehouse", "TQty"] if c in raw.columns]

    # Melt: wide → long
    # Before: one row per PO with many SKU columns
    # After:  one row per PO + SKU combination
    melted = raw[id_cols + present_sku_cols].melt(
        id_vars=id_cols,
        value_vars=present_sku_cols,
        var_name="sku_code",
        value_name="dispatch_qty"
    )

    # Remove rows where nothing was dispatched
    melted = melted[melted["dispatch_qty"] > 0].copy()

    # Rename to standard names
    melted = melted.rename(columns={
        "Dispatch Date": "dispatch_date",
        "PO Number":     "po_id",
        "INVOICE #":     "invoice_id",
        "Warehouse":     "warehouse",
        "TQty":          "total_dispatch_qty"
    })

    # Clean up
    melted["po_id"]      = melted["po_id"].astype(str).str.strip()
    melted["invoice_id"] = melted["invoice_id"].astype(str).str.strip()
    melted["dispatch_date"] = pd.to_datetime(
        melted["dispatch_date"], format="%d-%b-%y", errors="coerce"
    )

    return melted.reset_index(drop=True)