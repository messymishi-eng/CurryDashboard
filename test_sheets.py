from app.core.sheets import get_client, fetch_sku_mapping

client = get_client()
df = fetch_sku_mapping(client)
print("Zepto SKU rows:", len(df))
print(df.to_string())
