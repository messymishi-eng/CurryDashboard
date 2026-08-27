from app.core.sheets import get_client

client = get_client()
sh = client.open_by_url("https://docs.google.com/spreadsheets/d/1B8f1v8efIKwxFoM0muI1GpcO_pyEg3HV9w4U6txRZHQ/edit")
ws = sh.worksheet("Reconcilation data zepto")

ws.clear()
headers = ["Date","GRN Code","PO Code","Store Name","Invoice Number","SKU ID","GRN Quantity"]
ws.update("A1", [headers])
print("✓ Sheet cleared")

# Verify
all_values = ws.get_all_values()
print(f"Rows now: {len(all_values)}")
print(f"Headers: {all_values[0]}")
