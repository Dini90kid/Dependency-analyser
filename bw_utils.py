import os
import zipfile
import io
import csv
import pandas as pd

__all__ = [
    "parse_dependency_csv",
    "parse_dependency_logs_from_files",
    "scan_zip_structure",
    "scan_local_directory",
    "build_analysis_outputs",
    "create_excel_workbook",
]

# ======================================================================
#  PARSE A SINGLE dependencies_log FILE (semicolon-separated)
# ======================================================================
def parse_dependency_csv(text: str):
    """
    ABAP dependency export format (semicolon-separated):
        ranid;Container;Kind;Name;Where;Line;Note

    We extract FM calls where:
        Kind = 'FM'
        Where contains 'CALL FUNCTION'
    """
    fms = set()
    rows = csv.reader(text.splitlines(), delimiter=';')
    # Skip header if present
    try:
        header = next(rows)
        # If first row wasn't a header, reprocess it
        if header and (len(header) < 5 or header[2].strip().upper() != "KIND"):
            # not a header; treat as data
            kind = header[2].strip().upper() if len(header) > 2 else ""
            name = header[3].strip() if len(header) > 3 else ""
            where = header[4].strip().upper() if len(header) > 4 else ""
            if kind == "FM" and "CALL FUNCTION" in where:
                fms.add(name)
    except StopIteration:
        return []

    for row in rows:
        if len(row) < 5:
            continue

        kind = row[2].strip().upper()
        name = row[3].strip()
        where = row[4].strip().upper()

        if kind == "FM" and "CALL FUNCTION" in where:
            fms.add(name)

    return sorted(fms)


# ======================================================================
#  MODE 2 — MULTIPLE FILE UPLOAD (standalone dependency_log files)
# ======================================================================
def parse_dependency_logs_from_files(file_dict: dict):
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
#  Helper — robust filename match for dependencies logs
# ======================================================================
def _looks_like_dependency_log(filename_lower: str) -> bool:
    """
    Accept variations like:
      dependencies_log, Dependencies_Log, dependencylog, dependency_log.txt, .log, no extension
    """
    return (
        "depend" in filename_lower
        and "log" in filename_lower
        and (filename_lower.endswith(".txt") or filename_lower.endswith(".log") or "." not in filename_lower)
    )


# ======================================================================
#  Helper — infer (usecase, provider) relative to 'Transformations' in a path
# ======================================================================
def _infer_usecase_provider_from_parts(parts):
    """
    Given a list of path parts (POSIX-like from ZIP or os.walk),
    find 'Transformations' (case-insensitive) and set:
        provider = part before Transformations
        usecase  = part before provider
    Returns (usecase, provider) or (None, None) if not inferable.
    """
    lower_parts = [p.lower() for p in parts]
    if "transformations" not in lower_parts:
        return (None, None)

    idx = lower_parts.index("transformations")
    if idx - 2 < 0:
        return (None, None)

    usecase = parts[idx - 2]
    provider = parts[idx - 1]
    return (usecase, provider)


# ======================================================================
#  MODE 1 — ZIP UPLOAD (recursively scan folder structure)
# ======================================================================
def scan_zip_structure(zip_file: zipfile.ZipFile):
    """
    ZIP structure examples supported:
        Root/UseCase/Provider/Transformations/dependencies_log*
        UseCase/Provider/Transformations/dependencies_log*

    We anchor on 'Transformations' and infer:
        usecase = folder two levels above 'Transformations'
        provider = folder one level above 'Transformations'
    """
    results = []

    for member in zip_file.namelist():
        # skip directories
        if member.endswith("/"):
            continue

        lower = member.lower()
        if "depend" in lower and "log" in lower:
            # ZIP uses forward slashes
            parts = [p for p in member.split("/") if p]

            usecase, provider = _infer_usecase_provider_from_parts(parts)
            if not usecase or not provider:
                # cannot infer reliably
                continue

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
def scan_local_directory(root_path: str):
    """
    Recursively scan for files that look like 'dependencies_log*'.
    Infer (usecase, provider) relative to 'Transformations' directory.

    Supports:
        <Root>/<UseCase>/<Provider>/Transformations/dependencies_log*
        <UseCase>/<Provider>/Transformations/dependencies_log*
    """
    results = []

    for dirpath, _, filenames in os.walk(root_path):
        # candidate log files in this folder
        candidates = [fn for fn in filenames if _looks_like_dependency_log(fn.lower())]
        if not candidates:
            continue

        # Build parts relative to root_path for inference
        rel_path = os.path.relpath(dirpath, start=root_path)
        parts = [] if rel_path == "." else rel_path.replace("\\", "/").split("/")

        # Ensure 'Transformations' anchor in parts
        last_lower = parts[-1].lower() if parts else ""
        if last_lower != "transformations":
            lower_parts = [p.lower() for p in parts]
            if "transformations" not in lower_parts:
                parts = parts + ["Transformations"]

        usecase, provider = _infer_usecase_provider_from_parts(parts)
        if not usecase or not provider:
            continue

        for fname in candidates:
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except Exception:
                continue

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
def build_analysis_outputs(records: list):
    """
    Build:
        - UseCase -> Provider -> FM List
        - FM -> UseCase list
        - Unique FMs
        - Summary table
    """
    rows = []
    fm_to_usecases = {}

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
            fm_to_usecases.setdefault(fm, set()).add(usecase)

    df_usecase_provider = pd.DataFrame(rows).sort_values(
        ["usecase", "provider"]
    ).reset_index(drop=True)

    df_fm_usecase = pd.DataFrame([
        {"fm": fm, "usecases": ", ".join(sorted(ucs))}
        for fm, ucs in fm_to_usecases.items()
    ]).sort_values("fm").reset_index(drop=True)

    df_unique_fms = pd.DataFrame(sorted(fm_to_usecases.keys()), columns=["fm"])

    # Frequency of FM usage across use cases
    fm_freq = pd.Series({fm: len(ucs) for fm, ucs in fm_to_usecases.items()}).sort_values(ascending=False)

    summary = {
        "Total Use Cases": int(df_usecase_provider["usecase"].nunique()),
        "Total Providers": int(df_usecase_provider["provider"].nunique()),
        "Total Logs Processed": int(len(records)),
        "Total Unique FMs": int(len(df_unique_fms)),
        "Top 5 Most Used FMs": ", ".join(list(fm_freq.head(5).index)),
    }
    summary_df = pd.DataFrame([summary])

    return df_usecase_provider, df_fm_usecase, df_unique_fms, summary_df


# ======================================================================
#  CREATE EXCEL + ZIP EXPORT PACKAGE
# ======================================================================
def create_excel_workbook(df1: pd.DataFrame, df2: pd.DataFrame, df3: pd.DataFrame, df4: pd.DataFrame):
    """
    Creates:
        analysis.xlsx (4 sheets)
        ZIP containing:
            - all CSVs
            - analysis.xlsx
    Returns (excel_bytes, zip_bytes)
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
