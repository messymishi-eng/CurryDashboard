import pandas as pd


def enrich_grn_with_sku(df_grn, df_sku_map):
    """
    GRN-SWIGGY has sku_item_code (numeric, e.g. '93302').
    df_sku_map has item_code -> sku_code (abbreviation) + sku_name.
    """
    enriched = df_grn.merge(
        df_sku_map[["item_code", "sku_code", "sku_name"]],
        left_on="sku_item_code",
        right_on="item_code",
        how="left"
    )
    before = len(enriched)
    enriched = enriched[enriched["sku_code"].notna()].copy()
    after = len(enriched)
    if before != after:
        print(f"  [Swiggy Mapper] Dropped {before - after} GRN rows with unmapped SKU codes")
    return enriched.reset_index(drop=True)


def enrich_dispatch_with_sku(df_dispatch, df_sku_map):
    """
    Dispatch has sku_code already as the abbreviation (column name in melt, e.g. 'GGP').
    Validate it exists in the Swiggy mapping; attach sku_name.
    """
    valid_codes = set(df_sku_map["sku_code"].unique())
    enriched = df_dispatch[df_dispatch["sku_code"].isin(valid_codes)].copy()

    name_lookup = df_sku_map.set_index("sku_code")["sku_name"].to_dict()
    enriched["sku_name"] = enriched["sku_code"].map(name_lookup)

    before = len(df_dispatch)
    after = len(enriched)
    if before != after:
        print(f"  [Swiggy Mapper] Dropped {before - after} dispatch rows with unmapped SKU codes")

    return enriched.reset_index(drop=True)


def build_unified(df_grn_enriched, df_dispatch_enriched):
    """
    Same structure as Zepto's build_unified: aggregate dispatch by PO+SKU,
    split into matched-vs-GRN and no-GRN-match, merge, concat.
    NOTE: dispatch_out (no GRN match) IS included below, tagged 'out_of_period'.
    This carries forward the same known issue flagged for Zepto -- to be
    fixed with date-aware logic once the Zepto fix is finalized and can be
    mirrored here.
    """
    dispatch_agg = (
        df_dispatch_enriched
        .groupby(["po_id", "sku_code"], as_index=False)
        .agg(
            dispatch_qty  = ("dispatch_qty",  "sum"),
            dispatch_date = ("dispatch_date", "min"),
            warehouse     = ("warehouse",     "first"),
            invoice_id_d  = ("invoice_id",    "first"),
            sku_name_d    = ("sku_name",      "first"),
        )
    )

    grn_pos = set(df_grn_enriched["po_id"].unique())
    dispatch_in  = dispatch_agg[dispatch_agg["po_id"].isin(grn_pos)].copy()
    dispatch_out = dispatch_agg[~dispatch_agg["po_id"].isin(grn_pos)].copy()

    grn_clean = df_grn_enriched.rename(columns={"sku_code": "sku_code_grn"})

    unified = grn_clean.merge(
        dispatch_in,
        left_on=["po_id", "sku_code_grn"],
        right_on=["po_id", "sku_code"],
        how="outer"
    )

    unified["sku_code"] = unified["sku_code_grn"].combine_first(
        unified.get("sku_code", pd.Series(dtype=str))
    )

    if "sku_name_x" in unified.columns and "sku_name_y" in unified.columns:
        unified["sku_name"] = unified["sku_name_x"].combine_first(unified["sku_name_y"])
    elif "sku_name_d" in unified.columns:
        unified["sku_name"] = unified.get("sku_name", pd.Series(dtype=str)).combine_first(unified["sku_name_d"])

    if "invoice_id" in unified.columns:
        unified["invoice_id"] = unified["invoice_id"].combine_first(
            unified.get("invoice_id_d", pd.Series(dtype=str))
        )
    elif "invoice_id_d" in unified.columns:
        unified["invoice_id"] = unified["invoice_id_d"]

    unified["grn_qty"]      = pd.to_numeric(unified.get("grn_qty",      0), errors="coerce").fillna(0)
    unified["dispatch_qty"] = pd.to_numeric(unified.get("dispatch_qty", 0), errors="coerce").fillna(0)
    unified["po_qty"]       = 0

    drop = [
        "sku_code_grn","sku_name_x","sku_name_y","sku_name_d",
        "item_code","invoice_id_d"
    ]
    unified.drop(columns=drop, errors="ignore", inplace=True)
    unified["period"] = "in_period"

    dispatch_out = dispatch_out.rename(columns={
        "sku_name_d":   "sku_name",
        "invoice_id_d": "invoice_id"
    })
    dispatch_out["po_qty"]       = 0
    dispatch_out["grn_qty"]      = 0
    dispatch_out["period"]       = "out_of_period"
    dispatch_out["grn_id"]       = None

    final = pd.concat([unified, dispatch_out], ignore_index=True)
    return final.reset_index(drop=True)
