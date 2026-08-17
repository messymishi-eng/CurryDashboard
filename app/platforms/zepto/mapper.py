import pandas as pd


def enrich_grn_with_sku(df_grn, df_sku):
    return df_grn.merge(
        df_sku[["sku_id", "sku_code", "sku_name"]],
        on="sku_id",
        how="left"
    )


def enrich_dispatch_with_sku(df_dispatch, df_sku):
    enriched = df_dispatch.merge(
        df_sku[["sku_id", "sku_code", "sku_name"]],
        on="sku_code",
        how="left"
    )
    before = len(enriched)
    enriched = enriched[enriched["sku_id"].notna()].copy()
    after = len(enriched)
    if before != after:
        print(f"  [Mapper] Dropped {before - after} rows with unmapped SKUs (CP, GGGTP, SOUPS etc)")
    return enriched.reset_index(drop=True)


def build_unified(df_grn_enriched, df_dispatch_enriched):
    dispatch_agg = (
        df_dispatch_enriched
        .groupby(["po_id", "sku_code"], as_index=False)
        .agg(
            dispatch_qty  = ("dispatch_qty",  "sum"),
            dispatch_date = ("dispatch_date", "min"),
            warehouse     = ("warehouse",     "first"),
            invoice_id_d  = ("invoice_id",    "first"),
            sku_id_d      = ("sku_id",        "first"),
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
    elif "sku_name_x" in unified.columns:
        unified["sku_name"] = unified["sku_name_x"]
    elif "sku_name_y" in unified.columns:
        unified["sku_name"] = unified["sku_name_y"]

    if "sku_id_x" in unified.columns:
        unified["sku_id"] = unified["sku_id_x"].combine_first(unified.get("sku_id_d", pd.Series(dtype=str)))
    elif "sku_id_d" in unified.columns:
        unified["sku_id"] = unified["sku_id_d"]

    if "invoice_id" in unified.columns:
        unified["invoice_id"] = unified["invoice_id"].combine_first(
            unified.get("invoice_id_d", pd.Series(dtype=str))
        )
    elif "invoice_id_d" in unified.columns:
        unified["invoice_id"] = unified["invoice_id_d"]

    unified["po_qty"]       = pd.to_numeric(unified.get("po_qty",       0), errors="coerce").fillna(0)
    unified["grn_qty"]      = pd.to_numeric(unified.get("grn_qty",      0), errors="coerce").fillna(0)
    unified["dispatch_qty"] = pd.to_numeric(unified.get("dispatch_qty", 0), errors="coerce").fillna(0)

    drop = [
        "sku_code_grn","sku_code_x","sku_code_y",
        "sku_name_x","sku_name_y","sku_name_d",
        "sku_id_x","sku_id_y","sku_id_d",
        "invoice_id_d"
    ]
    unified.drop(columns=drop, errors="ignore", inplace=True)
    unified["period"] = "in_period"

    dispatch_out = dispatch_out.rename(columns={
        "sku_id_d":     "sku_id",
        "sku_name_d":   "sku_name",
        "invoice_id_d": "invoice_id"
    })
    dispatch_out["po_qty"]       = 0
    dispatch_out["grn_qty"]      = 0
    dispatch_out["period"]       = "out_of_period"
    dispatch_out["grn_id"]       = None
    dispatch_out["product_name"] = None

    final = pd.concat([unified, dispatch_out], ignore_index=True)
    return final.reset_index(drop=True)
