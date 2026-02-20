import streamlit as st
import zipfile
import os
import io
import pandas as pd

import os, sys
# Ensure the app’s folder is first on sys.path so local modules win over any PyPI packages
sys.path.insert(0, os.path.dirname(__file__))

from bw_utils import (
    scan_local_directory,
    scan_zip_structure,
    parse_dependency_logs_from_files,
    build_analysis_outputs,
    create_excel_workbook,
)
# --------------------------------------------------------------
# STREAMLIT CONFIG
# --------------------------------------------------------------
st.set_page_config(page_title="BW Dependency Analyzer", layout="wide")

st.title("BW Dependency Analyzer")
st.write(
    "Upload a ZIP of the full Use Case → Provider → Transformations structure, "
    "upload standalone dependency_log files, or enter a local folder path "
    "(works only in local desktop mode)."
)

# --------------------------------------------------------------
# INPUT MODE SELECTION
# --------------------------------------------------------------
mode = st.radio(
    "Select input mode",
    [
        "Upload ZIP (Full Folder Structure)",
        "Upload dependency_log files",
        "Scan Local Folder (Desktop Only)"
    ]
)

parsed_records = []

# --------------------------------------------------------------
# MODE 1 — ZIP UPLOAD
# --------------------------------------------------------------
if mode == "Upload ZIP (Full Folder Structure)":
    zip_file = st.file_uploader("Upload ZIP containing UseCase → Provider → Transformations", type=["zip"])

    if zip_file:
        zip_bytes = io.BytesIO(zip_file.read())
        with zipfile.ZipFile(zip_bytes, "r") as z:
            parsed_records = scan_zip_structure(z)

# --------------------------------------------------------------
# MODE 2 — MULTIPLE dependency_log FILES
# --------------------------------------------------------------
elif mode == "Upload dependency_log files":
    files = st.file_uploader(
        "Upload one or more dependency_log files",
        type=["txt", "log"],
        accept_multiple_files=True
    )
    
    if files:
        file_dict = {f.name: f.read().decode("utf-8", errors="ignore") for f in files}
        parsed_records = parse_dependency_logs_from_files(file_dict)

# --------------------------------------------------------------
# MODE 3 — LOCAL FOLDER SCAN
# --------------------------------------------------------------
else:
    st.warning("Local path scanning works **only when running locally** (not on Streamlit Cloud).")
    folder_path = st.text_input("Enter local folder path, e.g. C:\\Users\\Dinesh\\Automation Docs for TRFN")

    if folder_path:
        if os.path.exists(folder_path):
            parsed_records = scan_local_directory(folder_path)
        else:
            st.error("Invalid local path — folder not found.")


# --------------------------------------------------------------
# ANALYSIS SECTION WITH PROGRESS MONITOR
# --------------------------------------------------------------
run_analysis = st.button("Start Analysis")

if run_analysis:

    if not parsed_records:
        st.error("No valid dependency logs found. Please check your input.")
        st.stop()

    # Progress bar and status indicator
    progress = st.progress(0)
    status = st.empty()

    # Step 1
    progress.progress(5)
    status.write("🔍 Initializing analysis...")

    # Step 2 — Build analysis tables
    progress.progress(40)
    status.write("📊 Building analysis tables...")

    (
        df_usecase_provider,
        df_fm_usecase,
        df_unique_fms,
        summary_df
    ) = build_analysis_outputs(parsed_records)

    # Step 3 — Display results
    progress.progress(60)
    status.write("📄 Rendering results...")

    st.subheader("Summary")
    st.dataframe(summary_df, use_container_width=True)

    st.subheader("Use Case → Provider → FM List")
    st.dataframe(df_usecase_provider, use_container_width=True)

    st.subheader("FM → Use Case List")
    st.dataframe(df_fm_usecase, use_container_width=True)

    st.subheader("Unique FM List")
    st.dataframe(df_unique_fms, use_container_width=True)

    # Step 4 — Generate Excel + ZIP
    progress.progress(85)
    status.write("📦 Generating Excel & ZIP export...")

    excel_bytes, zip_bytes = create_excel_workbook(
        df_usecase_provider,
        df_fm_usecase,
        df_unique_fms,
        summary_df
    )

    # Step 5 — Ready
    progress.progress(100)
    status.write("✅ Analysis complete!")

    st.download_button(
        "Download Excel (analysis.xlsx)",
        excel_bytes,
        "analysis.xlsx"
    )

    st.download_button(
        "Download Complete ZIP Package",
        zip_bytes,
        "bw_dependency_analysis.zip",
        "application/zip"
    )

else:
    st.info("Upload your data and click **Start Analysis**.")
