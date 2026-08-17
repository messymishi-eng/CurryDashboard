from app.core.sheets import get_client, fetch_dispatch_sheet, fetch_grn_sheet

client = get_client()

print("=== DISPATCH ===")
dispatch = fetch_dispatch_sheet(client)
print("Rows:", len(dispatch))
print("Columns:", list(dispatch.columns))
print(dispatch.head(2).to_string())

print()
print("=== GRN-ZEPTO ===")
grn = fetch_grn_sheet(client)
print("Rows:", len(grn))
print("Columns:", list(grn.columns))
print(grn.head(2).to_string())
