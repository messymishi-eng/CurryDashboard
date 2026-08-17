import pandas as pd
import io


def load_file(uploaded_file) -> dict:
    """
    Takes one Streamlit uploaded file.
    Returns a dict like:
    {
        "filename": "Zepto_GRN.xlsx",
        "extension": "xlsx",
        "sheets": {
            "Sheet1": DataFrame,
            "Sheet2": DataFrame
        }
    }
    For CSV files, the single sheet key is "csv".
    """

    filename  = uploaded_file.name
    extension = filename.rsplit(".", 1)[-1].lower()
    raw_bytes = uploaded_file.read()

    result = {
        "filename":  filename,
        "extension": extension,
        "sheets":    {}
    }

    if extension in ("xlsx", "xls"):
        excel_file = pd.ExcelFile(io.BytesIO(raw_bytes))
        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(io.BytesIO(raw_bytes), sheet_name=sheet_name)
            result["sheets"][sheet_name] = df

    elif extension == "csv":
        df = pd.read_csv(io.BytesIO(raw_bytes))
        result["sheets"]["csv"] = df

    else:
        raise ValueError(f"Unsupported file type: {extension}")

    return result


def load_all_files(uploaded_files: list) -> list:
    """
    Takes a list of Streamlit uploaded files.
    Returns a list of loaded file dicts.
    """
    loaded = []
    for f in uploaded_files:
        loaded.append(load_file(f))
    return loaded