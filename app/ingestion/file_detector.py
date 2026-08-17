import pandas as pd

SIGNATURES = {
    "sku_mapping": {
        "required": ["Item Code", "Item"],
    },
    "grn": {
        "required_any": [
            ["PO Code", "SKU ID", "GRN Quantity", "PO Quantity"],
            ["PO Code", "SKU ID", "GRN Qty", "PO Qty"],
            ["PO Number", "SKU ID", "GRN Quantity"],
            ["PO Code", "SKU ID"],
        ]
    },
    "dispatch": {
        "required": ["PO Number", "INVOICE #", "TQty"],
    }
}


def _get_all_columns(loaded: dict) -> set:
    all_columns = set()
    for df in loaded["sheets"].values():
        all_columns.update([str(c).strip() for c in df.columns.tolist()])
        if len(df) > 0:
            all_columns.update([str(v).strip() for v in df.iloc[0].tolist()])
        if len(df) > 0 and len(df.columns) > 0:
            all_columns.update([str(v).strip() for v in df.iloc[:, 0].tolist()[:5]])
    return all_columns


def detect_file_type(loaded: dict) -> str:
    all_columns = _get_all_columns(loaded)

    for file_type, sig in SIGNATURES.items():
        # Standard required check
        if "required" in sig:
            required = sig["required"]
            matched  = sum(1 for col in required if col in all_columns)
            if matched == len(required):
                return file_type

        # Any-of-these-sets check (for GRN with varying column names)
        if "required_any" in sig:
            for req_set in sig["required_any"]:
                matched = sum(1 for col in req_set if col in all_columns)
                if matched == len(req_set):
                    return file_type

    return "unknown"


def detect_all_files(loaded_files: list) -> tuple:
    detected   = {}
    undetected = []
    for loaded in loaded_files:
        file_type = detect_file_type(loaded)
        if file_type != "unknown":
            detected[file_type] = loaded
        else:
            undetected.append(loaded["filename"])
    return detected, undetected
