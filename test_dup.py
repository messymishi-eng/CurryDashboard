from app.core.sheets import get_client

client = get_client()
sh = client.open_by_url("https://docs.google.com/spreadsheets/d/1B8f1v8efIKwxFoM0muI1GpcO_pyEg3HV9w4U6txRZHQ/edit")
ws = sh.worksheet("Reconcilation data zepto")

all_values = ws.get_all_values()
print(f"Total rows in sheet: {len(all_values)}")

# Check what keys exist
existing_keys = set()
if len(all_values) > 1:
    for row in all_values[1:]:
        if len(row) >= 6 and row[2].strip() and row[5].strip():
            key = (row[2].strip(), row[5].strip())
            existing_keys.add(key)

print(f"Unique PO+SKU keys: {len(existing_keys)}")
print(f"Sample keys:")
for k in list(existing_keys)[:3]:
    print(f"  {k}")
