import streamlit as st
import zipfile
import os
import io
import pandas as pd
from utils import (
    scan_local_directory,
    scan_zip_structure,
    parse_dependency_logs_from_files,
    build_analysis_outputs,
    create_excel_workbook,
)

st.set_page_config(page_title="BW Dependency Analyzer", layout="wide")

st.title("BW Dependency Analyzer")
st.write(
    "Upload a ZIP of the entire Use Case structure, upload multiple dependency logs, "
    "or enter a local folder path (local mode only). The app automatically extracts "
    "UseCase → Provider → FM dependencies and generates Excel + ZIP outputs."
)

# ---------------------------------------------
# INPUT METHOD SELECTION
# ---------------------------------------------
mode = st.radio(
    "Select input mode",
    ["Upload ZIP", "Upload dependency_log files", "Scan Local Folder (Desktop Only)"]
)

parsed_records = []

# ---------------------------------------------
# MODE 1: UPLOAD ZIP
# ---------------------------------------------
if mode == "Upload ZIP":
    zip_file = st.file_uploader("Upload ZIP containing entire Use Case structure", type=["zip"])

    if zip_file:
        zip_bytes = io.BytesIO(zip_file.read())
        with zipfile.ZipFile(zip_bytes, "r") as z:
            parsed_records = scan_zip_structure(z)

# ---------------------------------------------
# MODE 2: MULTIPLE FILES
# ---------------------------------------------
elif mode == "Upload dependency_log files":
    files = st.file_uploader(
        "Upload one or more dependency_log files",
        type=["txt", "log"],
        accept_multiple_files=True
    )
    
    if files:
        file_dict = {f.name: f.read().decode("utf-8", errors="ignore") for f in files}
        parsed_records = parse_dependency_logs_from_files(file_dict)

# ---------------------------------------------
# MODE 3: LOCAL DIRECTORY SCAN
# ---------------------------------------------
else:
    st.warning("Local path scanning only works when running Streamlit locally.")
    folder_path = st.text_input("Enter a local folder path")

    if folder_path and os.path.exists(folder_path):
        parsed_records = scan_local_directory(folder_path)
    elif folder_path:
        st.error("Invalid path. Ensure the folder exists on your machine.")

# ---------------------------------------------
# PROCESS RESULTS
# ---------------------------------------------
if parsed_records:
    (
        df_usecase_provider,
        df_fm_usecase,
        df_unique_fms,
        summary_df
    ) = build_analysis_outputs(parsed_records)

    st.subheader("Summary")
    st.dataframe(summary_df, use_container_width=True)

    st.subheader("Use Case → Provider → FM List")
    st.dataframe(df_usecase_provider, use_container_width=True)

    st.subheader("FM → Use Case List")
    st.dataframe(df_fm_usecase, use_container_width=True)

    st.subheader("Unique FM List")
    st.dataframe(df_unique_fms, use_container_width=True)

    # Create ZIP + Excel
    excel_bytes, zip_bytes = create_excel_workbook(
        df_usecase_provider,
        df_fm_usecase,
        df_unique_fms,
        summary_df
    )

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
    st.info("Awaiting input...")
