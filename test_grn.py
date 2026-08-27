from app.ingestion.file_loader import load_file

class FakeFile:
    def __init__(self, path):
        self.name = path.split('/')[-1]
        self._data = open(path, 'rb').read()
    def read(self):
        return self._data

loaded = load_file(FakeFile('data/sample/Zepto_GRN_01-31_Jul.xlsx'))
for sheet, df in loaded['sheets'].items():
    print(f"Sheet: {sheet}")
    print(f"Columns: {list(df.columns)}")
    if len(df) > 0:
        print(f"Row 0: {df.iloc[0].to_dict()}")
    print()
