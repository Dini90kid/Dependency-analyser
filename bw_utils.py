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

    return sorted(fms)


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
#  Helper — robust filename match for dependencies logs
# ======================================================================
def _looks_like_dependency_log(filename_lower: str) -> bool:
    """
    Accepts variations like:
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
    # Normalize case-insensitive search
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
def scan_zip_structure(zip_file):
    """
    ZIP structure examples supported:
        Root/UseCase/Provider/Transformations/dependencies_log
        UseCase/Provider/Transformations/dependencies_log
        ... (any additional prefix levels)

    We robustly locate 'Transformations' in the member path and then infer:
        usecase = folder two levels above 'Transformations'
        provider = folder one level above 'Transformations'
    """
    results = []

    for member in zip_file.namelist():
        lower = member.lower()
        # Only consider file-like entries
        if member.endswith("/"):
            continue

        # Flexible match for dependency logs
        if ("depend" in lower and "log" in lower):
            # Split like POSIX path (ZIP uses forward slashes)
            parts = [p for p in member.split("/") if p]

            usecase, provider = _infer_usecase_provider_from_parts(parts)
            if not usecase or not provider:
                # If we cannot infer properly, skip this member
                continue

            # Read and parse file
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
    Recursively scan for files that look like 'dependencies_log*'.
    Infer (usecase, provider) relative to 'Transformations' directory.

    Supports:
        <Root>/<UseCase>/<Provider>/Transformations/dependencies_log*
        <UseCase>/<Provider>/Transformations/dependencies_log*
        and deeper nesting with consistent 'Transformations' anchor.
    """
    results = []

    for dirpath, _, filenames in os.walk(root_path):
        basenames = [fn for fn in filenames if _looks_like_dependency_log(fn.lower())]
        if not basenames:
            continue

        # Build parts relative to root_path for inference
        rel_path = os.path.relpath(dirpath, start=root_path)
        # Guard: os.walk may return '.' for root—skip such cases
        if rel_path == ".":
            parts = []
        else:
            # Normalize to POSIX-like split
            parts = rel_path.replace("\\", "/").split("/")

        # Try to map to (usecase, provider) from the folder parts
        # Append the trailing 'Transformations' if dirpath ends with it, else attempt to locate it case-insensitively
        last_part = parts[-1].lower() if parts else ""
        if last_part != "transformations":
            # Try to find 'transformations' in the chain; if not present but logs found here,
            # we assume this folder is the Transformations folder
            lower_parts = [p.lower() for p in parts]
            if "transformations" in lower_parts:
                # OK as-is
                pass
            else:
                parts = parts + ["Transformations"]

        usecase, provider = _infer_usecase_provider_from_parts(parts)
        if not usecase or not provider:
            # Cannot infer reliably
            continue

        # Parse all matching files in this folder
        for fname in basenames:
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
def build_analysis_outputs(records):
    """
    Build:
        - UseCase → Provider → FM List
        - FM → UseCase list
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

    df_usecase_provider = pd.DataFrame(rows).sort_values(["usecase", "provider"]).reset_index(drop=True)

    df_fm_usecase = pd.DataFrame([
        {"fm": fm, "usecases": ", ".join(sorted(ucs))}
        for fm, ucs in fm_to_usecases.items()
    ]).sort_values("fm").reset_index(drop=True)

    df_unique_fms = pd.DataFrame(sorted(fm_to_usecases.keys()), columns=["fm"])

    # Frequency of FM usage across use cases
