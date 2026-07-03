# Regulatory Table Scraper

A production-oriented Python pipeline for extracting, understanding, parsing, validating, and exporting regulatory tariff tables from electricity regulatory PDF documents.

The project is designed around a modular pipeline that combines document understanding, semantic parsing, validation, and Excel generation to produce structured datasets from complex regulatory PDFs.

---

# Features

* Automatic PDF indexing
* Table of Contents (TOC) discovery
* Automatic discovery of supported regulatory parameters
* Interactive parameter selection
* Interactive page-range confirmation
* Multi-page table extraction
* Table normalization
* Document understanding
* Pattern-aware parsing
* Validation pipeline
* Excel workbook generation
* Workspace-based execution with intermediate artifacts

---

# Currently Supported Parameters

* Cross Subsidy Surcharge
* Additional Surcharge
* Wheeling Charge
* Transmission Charge
* Banking Charges

---

# Project Structure

```text
table_scraper/
│
├── config/
├── docs/
├── input/
├── output/
├── requirements.txt
├── workspaces/
│
└── src/
    └── table_scraper/
        ├── adapters/
        ├── config/
        ├── discovery/
        ├── domain/
        ├── entity_recognition/
        ├── export/
        ├── extraction/
        ├── interfaces/
        ├── normalization/
        ├── parsing/
        ├── patterns/
        ├── pipeline/
        ├── storage/
        ├── understanding/
        └── validation/
```

---

# Requirements

* Python 3.11+ (recommended)
* Windows/Linux/macOS

---

# Installation

## 1. Clone the repository

```bash
git clone <repository-url>
cd table_scraper
```

---

## 2. Create a virtual environment

### Windows

```bash
python -m venv scraper
```

Activate:

```bash
scraper\Scripts\activate
```

### Linux / macOS

```bash
python3 -m venv scraper
source scraper/bin/activate
```

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

# Running the Project

## Step 1

Place your regulatory PDF inside the project's `input/` directory.

Example:

```text
input/
    my_document.pdf
```

---

## Step 2

Move into the source directory.

```bash
cd src
```

---

## Step 3

Run the application.

```bash
python -m table_scraper.interfaces.cli.app --profile cerc_ursi_v1
```

---

## Step 4

When prompted:

```text
Enter path to PDF file:
```

Provide the relative path to your PDF.

Example:

```text
../input/my_document.pdf
```

---

## Step 5

The pipeline will automatically perform:

1. Workspace creation
2. PDF indexing
3. TOC discovery
4. Parameter discovery
5. Suggested page-range detection

Example:

```text
Supported Parameters

Cross Subsidy Surcharge
Additional Surcharge
Wheeling Charge
Transmission Charge
Banking Charges
```

---

## Step 6

Select the parameters you want to process.

Example:

```text
all
```

or

```text
cross_subsidy_surcharge
```

or

```text
cross_subsidy_surcharge,wheeling_charge
```

---

## Step 7

The pipeline will suggest page ranges.

Example:

```text
Cross Subsidy Surcharge

Suggested:

46-47
```

Press **Enter** to accept the suggested range, or provide a custom range.

Example:

```text
50-56
```

---

## Step 8

The remaining pipeline executes automatically.

Stages include:

* Table Extraction
* Table Merging
* Normalization
* Document Understanding
* Pattern Classification
* Parsing
* Validation
* Excel Export

---

# Output

Every execution creates a dedicated workspace.

Example:

```text
workspaces/

└── b362c51a89b67ff4/
```

Each workspace contains intermediate artifacts generated during processing.

Typical contents include:

```text
workspaces/
└── <workspace_id>/
    ├── artifacts/
    ├── manifest.json
    ├── page_index.json
    ├── parameter_catalog.json
    ├── raw_tables.json
    ├── merged_tables.json
    ├── normalized_tables.json
    ├── parsed_records.json
    ├── validation_report.json
    └── output/
```

The final Excel workbook(s) are written inside the corresponding workspace output directory.

---

# Typical Workflow

```text
Place PDF
        │
        ▼
Run CLI
        │
        ▼
Provide PDF path
        │
        ▼
Parameter Discovery
        │
        ▼
Select Parameters
        │
        ▼
Confirm Page Ranges
        │
        ▼
Extraction
        │
        ▼
Normalization
        │
        ▼
Parsing
        │
        ▼
Validation
        │
        ▼
Excel Export
```

---

# Supported Profile

Current supported profile:

```text
cerc_ursi_v1
```

Run using:

```bash
python -m table_scraper.interfaces.cli.app --profile cerc_ursi_v1
```

---

# Troubleshooting

## ModuleNotFoundError

Install all required packages:

```bash
pip install -r requirements.txt
```

---

## Unknown profile

Use the supported profile:

```bash
--profile cerc_ursi_v1
```

---

## PDF not found

Ensure the PDF is placed inside the `input/` directory and provide the correct relative path.

Example:

```text
../input/my_document.pdf
```

---

## No output generated

Check:

* The selected page ranges are correct.
* The PDF contains supported parameter tables.
* The workspace contains intermediate artifacts for debugging.

---

# Workspace Cleanup

To start with a fresh run, remove the corresponding workspace directory under:

```text
workspaces/
```

A new workspace will be created automatically during the next execution.

---

# Notes

* Keep the original PDF unchanged during processing.
* Use the provided page suggestions whenever possible.
* Review generated workspaces for intermediate artifacts if debugging is required.
* The project is designed to be extended with additional regulatory profiles and parameter configurations in the future.


