import os
import zipfile
import io
import csv
import pandas as pd


# ======================================================================
#  PARSE A SINGLE dependencies_log FILE (semicolon-separated)
# ======================================================================
def parse_dependency_csv(text):
    """
    ABAP dependency export format:
        ranid;Container;Kind;Name;Where;Line;Note

    We extract FM calls where:
        Kind = 'FM'
        Where contains 'CALL FUNCTION'
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


# ======================================================================
#  MODE 2 — MULTIPLE FILE UPLOAD (standalone dependency_log files)
# ======================================================================
def parse_dependency_logs_from_files(file_dict):
    """
    file_dict = {filename: text}
    UseCase = filename (without extension)
    Provider = 'N/A'
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


# ======================================================================
#  MODE 1 — ZIP UPLOAD (recursively scan folder structure)
# ======================================================================
def scan_zip_structure(zip_file):
    """
    ZIP structure:
        UseCase/
            Provider/
                Transformations/
                    Dependencies_Log  (any naming variations)

    Robust matching: any filename containing "depend" + "log".
    """
    results = []

    for member in zip_file.namelist():
        lower = member.lower()

        # Match variations:
        #   dependencies_log
        #   Dependencies_Log
        #   dependencylog
        #   dependency_log.txt
        if "depend" in lower and "log" in lower:
            parts = member.split("/")

            # Expected: UseCase / Provider / Transformations / file
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


# ======================================================================
#  MODE 3 — LOCAL DIRECTORY SCANNING (Desktop only)
# ======================================================================
def scan_local_directory(root_path):
    """
    Recursively scan:
        root_path / UseCase / Provider / Transformations / dependencies_log*
    """
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

            # Find dependency_log variations inside Transformations/
            for f in os.listdir(tr_path):
                fname = f.lower()

                if (
                    "depend" in fname
                    and "log" in fname
                    and (fname.endswith(".txt") or fname.endswith(".log") or "." not in fname)
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


# ======================================================================
#  BUILD ANALYSIS TABLES
# ======================================================================
def build_analysis_outputs(records):
    """
    Build:
        - UseCase → Provider → FM List
        - FM → UseCase list
        - Unique FMs
        - Summary table
    """
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

        # Reverse mapping: FM → UseCases
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


# ======================================================================
#  CREATE EXCEL + ZIP EXPORT PACKAGE
# ======================================================================
def create_excel_workbook(df1, df2, df3, df4):
    """
    Creates:
        analysis.xlsx (4 sheets)
        ZIP containing:
            - all CSVs
            - analysis.xlsx
    """
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        df1.to_excel(writer, sheet_name="usecase_provider_fm", index=False)
        df2.to_excel(writer, sheet_name="fm_usecase", index=False)
        df3.to_excel(writer, sheet_name="unique_fms", index=False)
        df4.to_excel(writer, sheet_name="summary", index=False)

    # Build ZIP package
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as z:
        z.writestr("usecase_provider_fm.csv", df1.to_csv(index=False))
        z.writestr("fm_usecase.csv", df2.to_csv(index=False))
        z.writestr("unique_fms.csv", df3.to_csv(index=False))
        z.writestr("summary.csv", df4.to_csv(index=False))
        z.writestr("analysis.xlsx", excel_buffer.getvalue())

    return excel_buffer.getvalue(), zip_buffer.getvalue()
