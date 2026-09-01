import pandas as pd


def reconcile(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["po_qty"]       = pd.to_numeric(df.get("po_qty",       0), errors="coerce").fillna(0)
    df["dispatch_qty"] = pd.to_numeric(df.get("dispatch_qty", 0), errors="coerce").fillna(0)
    df["grn_qty"]      = pd.to_numeric(df.get("grn_qty",      0), errors="coerce").fillna(0)

    df["grn_vs_po_diff"]   = df["grn_qty"] - df["po_qty"]
    df["grn_vs_disp_diff"] = df["grn_qty"] - df["dispatch_qty"]
    df["disp_vs_po_diff"]  = df["dispatch_qty"] - df["po_qty"]

    def get_dispatch_status(row):
        """Did we send what was ordered? (PO vs Dispatch)"""
        po     = row["po_qty"]
        disp   = row["dispatch_qty"]
        period = row.get("period", "in_period")

        if period == "out_of_period":
            return "Out of Period"
        if po == 0 and disp == 0:
            return "—"
        if po > 0 and disp == 0:
            return "Not Dispatched"
        if disp == po:
            return "Fully Dispatched"
        if disp < po:
            return "Under Dispatched"
        if disp > po:
            return "Over Dispatched"
        return "—"

    def get_grn_status(row):
        """Did Zepto receive what we sent? (Dispatch vs GRN)"""
        disp   = row["dispatch_qty"]
        grn    = row["grn_qty"]
        period = row.get("period", "in_period")

        if period == "out_of_period":
            return "Out of Period"
        if disp == 0 and grn == 0:
            return "—"
        if disp == 0 and grn > 0:
            return "Missing Dispatch"
        if grn == 0 and disp > 0:
            return "Missing GRN"
        if grn == disp:
            return "Matched"
        if grn < disp:
            return "Short"
        if grn > disp:
            return "Excess"
        return "—"

    def get_overall_status(row):
        """Combined status for filtering and flagging."""
        period = row.get("period", "in_period")
        if period == "out_of_period":
            return "Out of Period"

        ds  = row["dispatch_status"]
        gs  = row["grn_status"]
        po  = row["po_qty"]
        dis = row["dispatch_qty"]
        grn = row["grn_qty"]

        # Human Review: dispatch > PO qty but GRN matches PO
        # This suggests data inconsistency — needs manual check
        if dis > po and grn == po and po > 0:
            return "Human Review"

        # Human Review: dispatch > PO qty and GRN matches dispatch
        if dis > po and grn == dis and po > 0:
            return "Human Review"

        if gs in ("Short", "Excess", "Missing GRN", "Missing Dispatch"):
            return gs
        if ds in ("Under Dispatched", "Not Dispatched", "Over Dispatched"):
            return ds
        if gs == "Matched" and ds == "Fully Dispatched":
            return "Matched"
        if gs == "Matched":
            return "Matched"
        return "Review"

    def get_reason(row):
        po   = row["po_qty"]
        disp = row["dispatch_qty"]
        grn  = row["grn_qty"]
        ds   = row["dispatch_status"]
        gs   = row["grn_status"]

        parts = []

        if ds == "Under Dispatched":
            parts.append(
                f"PO ordered {int(po)} but only {int(disp)} dispatched "
                f"(under by {int(po - disp)})"
            )
        elif ds == "Not Dispatched":
            parts.append(f"PO ordered {int(po)} but nothing dispatched")
        elif ds == "Over Dispatched":
            parts.append(
                f"PO ordered {int(po)} but {int(disp)} dispatched "
                f"(over by {int(disp - po)})"
            )

        if gs == "Short":
            parts.append(
                f"Zepto received {int(grn)} vs {int(disp)} dispatched "
                f"(short by {int(disp - grn)})"
            )
        elif gs == "Excess":
            parts.append(
                f"Zepto received {int(grn)} vs {int(disp)} dispatched "
                f"(excess by {int(grn - disp)})"
            )
        elif gs == "Missing GRN":
            parts.append(f"Dispatched {int(disp)} but no GRN received")
        elif gs == "Missing Dispatch":
            parts.append(f"GRN shows {int(grn)} received but no dispatch record")
        elif gs == "Matched" and ds == "Fully Dispatched":
            parts.append("All quantities match")
        elif gs == "Matched":
            parts.append(f"GRN matches dispatch ({int(grn)})")

        if gs == "Out of Period":
            parts.append(
                f"Dispatched {int(disp)} — PO not in current GRN file period"
            )

        return " | ".join(parts) if parts else "—"

    df["dispatch_status"] = df.apply(get_dispatch_status, axis=1)
    df["grn_status"]      = df.apply(get_grn_status,      axis=1)
    df["status"]          = df.apply(get_overall_status,   axis=1)
    df["reason"]          = df.apply(get_reason,           axis=1)

    for col in ["po_qty", "dispatch_qty", "grn_qty",
                "grn_vs_po_diff", "grn_vs_disp_diff", "disp_vs_po_diff"]:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)

    return df.reset_index(drop=True)



def get_summary(df: pd.DataFrame) -> dict:
    return {
        "total_records":       len(df),
        "matched":             int((df["status"] == "Matched").sum()),
        "short":               int((df["grn_status"] == "Short").sum()),
        "excess":              int((df["grn_status"] == "Excess").sum()),
        "missing_grn":         int((df["grn_status"] == "Missing GRN").sum()),
        "missing_dispatch":    int((df["grn_status"] == "Missing Dispatch").sum()),
        "under_dispatched":    int((df["dispatch_status"] == "Under Dispatched").sum()),
        "not_dispatched":      int((df["dispatch_status"] == "Not Dispatched").sum()),
        "out_of_period":       int((df["status"] == "Out of Period").sum()),
        "total_conflicts":     int((df["status"].isin([
            "Short", "Excess", "Missing GRN", "Missing Dispatch",
            "Under Dispatched", "Not Dispatched", "Over Dispatched"
        ])).sum()),
        "unique_skus":         int(df["sku_id"].nunique()),
        "unique_pos":          int(df["po_id"].nunique()),
        "total_po_qty":        int(df["po_qty"].sum()),
        "total_grn_qty":       int(df["grn_qty"].sum()),
        "total_dispatch_qty":  int(df["dispatch_qty"].sum()),
    }