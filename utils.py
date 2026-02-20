import os
import zipfile
import io
import csv
import pandas as pd


# --------------------------------------------------------
# HELPER: Parse a single dependency_log file
# --------------------------------------------------------
def parse_dependency_csv(text):
    """
    CSV always semicolon-separated.
    FM rows have:
        Kind = 'FM'
        Where = 'CALL FUNCTION'
    Name column contains FM name.
    """
    fms = set()
    rows = csv.reader(text.splitlines(), delimiter=';')
    next(rows, None)  # skip header

    for row in rows:
        if len(row) < 5:
            continue

        kind = row[2].strip().upper()
        name = row[3].strip()
        where = row[4].strip().upper()

        if kind == "FM" and "CALL FUNCTION" in where:
            fms.add(name)

    return list(fms)


# --------------------------------------------------------
# MODE 2: Parse from uploaded dependency files
# --------------------------------------------------------
def parse_dependency_logs_from_files(file_dict):
    """
    file_dict = {filename: text}
    UseCase = filename (without extension)
    Provider is unknown => set to "N/A"
    """
    results = []

    for fname, text in file_dict.items():
        usecase = fname.rsplit(".", 1)[0]
        provider = "N/A"
        fms = parse_dependency_csv(text)

        results.append({
            "usecase": usecase,
            "provider": provider,
            "fms": fms
        })

    return results


# --------------------------------------------------------
# MODE 1: ZIP FOLDER SCAN
# --------------------------------------------------------
def scan_zip_structure(zip_file):
    results = []

    for member in zip_file.namelist():
        if member.lower().endswith("dependencies_log"):
            parts = member.split("/")

            if len(parts) < 4:
                continue

            usecase = parts[0]
            provider = parts[1]

            text = zip_file.read(member).decode("utf-8", errors="ignore")
            fms = parse_dependency_csv(text)

            results.append({
                "usecase": usecase,
                "provider": provider,
                "fms": fms
            })

    return results


# --------------------------------------------------------
# MODE 3: LOCAL DIRECTORY RECURSIVE SCAN
# --------------------------------------------------------
def scan_local_directory(root_path):
    results = []

    for usecase in os.listdir(root_path):
        uc_path = os.path.join(root_path, usecase)
        if not os.path.isdir(uc_path):
            continue

        for provider in os.listdir(uc_path):
            pv_path = os.path.join(uc_path, provider)
            if not os.path.isdir(pv_path):
                continue

            tr_path = os.path.join(pv_path, "Transformations")
            if not os.path.isdir(tr_path):
                continue

            # Find dependency_log
           for f in os.listdir(tr_path):
    fname = f.lower()
    if (
        "depend" in fname
        and "log" in fname
        and fname.endswith((".txt", ".log", ""))  # cover files with no extension too
    ):
                    fpath = os.path.join(tr_path, f)
                    text = open(fpath, "r", encoding="utf-8", errors="ignore").read()
                    fms = parse_dependency_csv(text)

                    results.append({
                        "usecase": usecase,
                        "provider": provider,
                        "fms": fms
                    })

    return results


# --------------------------------------------------------
# BUILD ANALYSIS TABLES
# --------------------------------------------------------
def build_analysis_outputs(records):
    rows = []
    fm_map = {}

    for rec in records:
        usecase = rec["usecase"]
        provider = rec["provider"]
        fms = rec["fms"]

        rows.append({
            "usecase": usecase,
            "provider": provider,
            "fm_list": ", ".join(fms)
        })

        for fm in fms:
            fm_map.setdefault(fm, set()).add(usecase)

    df_usecase_provider = pd.DataFrame(rows)
    df_fm_usecase = pd.DataFrame([
        {"fm": fm, "usecases": ", ".join(sorted(ucs))}
        for fm, ucs in fm_map.items()
    ])
    df_unique_fms = pd.DataFrame(sorted(fm_map.keys()), columns=["fm"])

    summary = {
        "Total Use Cases": len(df_usecase_provider["usecase"].unique()),
        "Total Providers": len(df_usecase_provider["provider"].unique()),
        "Total Logs Processed": len(records),
        "Total Unique FMs": len(df_unique_fms),
        "Top 5 Most Used FMs": ", ".join(
            df_fm_usecase["fm"].value_counts().head(5).index
        )
    }
    summary_df = pd.DataFrame([summary])

    return df_usecase_provider, df_fm_usecase, df_unique_fms, summary_df


# --------------------------------------------------------
# CREATE EXCEL + ZIP
# --------------------------------------------------------
def create_excel_workbook(df1, df2, df3, df4):
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        df1.to_excel(writer, sheet_name="usecase_provider_fm", index=False)
        df2.to_excel(writer, sheet_name="fm_usecase", index=False)
        df3.to_excel(writer, sheet_name="unique_fms", index=False)
        df4.to_excel(writer, sheet_name="summary", index=False)

    # Make ZIP package
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as z:
        z.writestr("usecase_provider_fm.csv", df1.to_csv(index=False))
        z.writestr("fm_usecase.csv", df2.to_csv(index=False))
        z.writestr("unique_fms.csv", df3.to_csv(index=False))
        z.writestr("summary.csv", df4.to_csv(index=False))
        z.writestr("analysis.xlsx", excel_buffer.getvalue())

    return excel_buffer.getvalue(), zip_buffer.getvalue()
