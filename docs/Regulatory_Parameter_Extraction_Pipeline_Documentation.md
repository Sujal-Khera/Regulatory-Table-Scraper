# Regulatory Parameter Extraction Pipeline Documentation

> **Purpose:** This document explains the complete evolution of the
> regulatory parameter extraction pipeline, including every phase, the
> reasoning behind each design decision, the observed table patterns,
> and the final architecture.

------------------------------------------------------------------------

# 1. Project Goal

The objective of this project is to automatically extract regulatory
parameters from a large multi-page PDF containing heterogeneous
regulatory tables.

The desired output is a structured data warehouse where each regulatory
parameter is available as machine-readable records.

Challenges include:

-   Mixed Hindi and English text
-   OCR artifacts such as `(cid:###)`
-   Multi-page tables
-   Repeated page headers
-   Parent-child (hierarchical) tables
-   Narrative and numeric tables
-   Different schemas for different parameters

The pipeline therefore evolved incrementally.

------------------------------------------------------------------------

# 2. Overall ETL Architecture

``` text
PDF
 │
 ▼
Locate Parameters
 │
 ▼
Extract Raw Tables
 │
 ▼
Merge Multi-page Tables
 │
 ▼
Normalize Structure
 │
 ▼
Clean OCR/Text
 │
 ▼
Detect Table Pattern
 │
 ▼
Parameter-specific Parser
 │
 ▼
Canonical Records
 │
 ▼
DataFrames
 │
 ▼
Excel Warehouse
```

Every phase solves one specific problem.

------------------------------------------------------------------------

# Phase 1 -- Parameter Discovery

## Objective

Before extracting data, determine where each regulatory parameter exists
inside the PDF.

## Phase 1A

The Table of Contents is extracted from the first pages.

A regular expression identifies entries such as:

    TABLE-5(E): BANKING CHARGES .......... 63

Output:

-   parameter name
-   starting page

Saved as:

-   parameter_catalog.json

## Why?

Hardcoding page numbers is fragile.

The TOC becomes metadata for the pipeline.

------------------------------------------------------------------------

## Phase 1B

The catalog is sorted.

The next parameter's start page defines the current parameter's end
page.

Example:

    Banking
    Start = 63

    Next starts at 75

    Therefore

    End = 74

Output:

parameter_ranges.json

------------------------------------------------------------------------

## Phase 1C

Manual verification.

Each discovered page is previewed.

Purpose:

-   confirm TOC correctness
-   detect page-number offset
-   verify the table really starts there

------------------------------------------------------------------------

## Page Offset Investigation

Many PDFs contain:

-   printed page number
-   PDF page index

They differ.

The project searched for unique phrases such as:

-   Banking Charges
-   Transmission Charges

to determine the actual PDF page index.

This calibration prevented extracting the wrong pages.

------------------------------------------------------------------------

# Phase 2 -- Raw Table Extraction

Goal:

Extract every table exactly as pdfplumber sees it.

Important observation:

One page frequently contains many detected tables.

Example:

    6 tables

    Only one contains actual data.

    Others are
    - borders
    - notes
    - legends

Pattern discovered:

Largest table almost always represents the actual dataset.

Rule adopted:

Always select

    largest_table =
    max(
        tables,
        key=rows × columns
    )

------------------------------------------------------------------------

## Multi-page Tables

Many regulatory tables continue across pages.

Pattern:

    Page 64
    Header
    Rows

    Page 65
    Repeated Header
    More Rows

Solution:

Merge rows across pages.

Remove repeated headers.

------------------------------------------------------------------------

# Phase 3 -- Structural Normalization

The PDF does not explicitly repeat information.

Instead it assumes human readers understand hierarchy.

Example:

    Andhra Pradesh
    APEPDCL
    8%

    APSPDCL

    APCPDCL

The PDF implies:

Both APSPDCL and APCPDCL inherit 8%.

Machines cannot infer this.

The pipeline reconstructs that hierarchy.

## 3A State Propagation

Empty state cells inherit the previous state.

Pattern:

    State
    (blank)
    (blank)

becomes

    State
    State
    State

------------------------------------------------------------------------

## 3B Row Classification

Rows classified into:

-   Master rows
-   Child rows
-   Continuation rows

### Master

Contains:

-   DISCOM
-   Charge

### Child

Contains:

-   DISCOM
-   No charge

Must inherit parent values.

### Continuation

Contains only policy text.

Appends to previous record.

------------------------------------------------------------------------

## 3C Record Reconstruction

Maintains:

    current_master

Children inherit:

-   charge
-   period
-   policy

Continuation rows append policy paragraphs.

------------------------------------------------------------------------

## 3D Group Discovery

Purpose:

Understand hidden hierarchy.

Output example:

    Gujarat

    DGVCL
    MGVCL
    PGVCL
    UGVCL

Confirmed inheritance assumptions.

------------------------------------------------------------------------

## 3E OCR Cleanup

Problems discovered:

-   (cid:341)
-   broken Hindi glyphs
-   inconsistent whitespace

Utilities created:

-   clean_text()
-   extract_state_name()

State names converted to consistent English forms.

------------------------------------------------------------------------

# Phase 4 -- Universal Narrative Parser

The Banking parser became reusable.

Stages:

1.  Extract tables
2.  Merge pages
3.  Propagate state
4.  Detect master rows
5.  Detect child rows
6.  Detect continuation rows
7.  Produce normalized records

Pattern handled:

    Parent
    Children
    Continuation

------------------------------------------------------------------------

# Phase 5 -- Numeric Matrix Discovery

Transmission tables were fundamentally different.

Instead of narrative text they contained numeric matrices.

Observation:

Rows represented hierarchy:

    State
    Utility

Columns represented measurements:

-   Year
-   Long-term charge
-   Units
-   Short-term charge
-   Units

------------------------------------------------------------------------

# Phase 6 -- Generic Numeric Parser

State master introduced.

Instead of keyword matching:

    contains "Pradesh"

state detection became:

    canonical_name in canonical_states

Benefits:

-   scalable
-   maintainable
-   robust

------------------------------------------------------------------------

# Phase 7 -- Production Banking Parser

New improvements:

-   automatic repeated-header removal
-   OCR cleanup
-   garbage filtering
-   canonical state mapping

Narrative parser became production-ready.

------------------------------------------------------------------------

# Phase 8 -- Universal Numeric Parser

Major improvements:

## Header detector

Rows identified by keywords instead of fixed positions.

## Parent detection

Uses canonical state master.

## Payload inheritance

    current_state

    current_payload

Child utilities inherit all numeric values.

------------------------------------------------------------------------

# Phase 9 -- Parameter-specific Parsers

Not all tables share one schema.

Instead:

Parameter Registry maps

    Parameter

    ↓

    Parser

    ↓

    Pages

Example:

    Banking

    ↓

    Narrative Parser

    Transmission

    ↓

    Numeric Parser

This separates configuration from logic.

------------------------------------------------------------------------

## Additional Surcharge

Pattern discovered:

    State

    ↓

    Utility (optional)

    ↓

    Values

Parser supports:

-   state-only records
-   utility-specific records

------------------------------------------------------------------------

# Phase 10 -- Wheeling Parser

New pattern discovered.

Rows contain one utility.

Columns contain voltage levels.

Example:

    Utility

    11kV
    33kV
    66kV
    132kV

Instead of storing one wide record:

    Utility
    11
    33
    66

Pipeline converts to long format:

    Utility
    Voltage
    Charge

One input row becomes multiple normalized records.

This is a classic Wide → Long normalization.

------------------------------------------------------------------------

# Phase 11 -- Warehouse Export

All parsers produce identical output:

    List[Dictionary]

Therefore exporting becomes uniform.

Workbook structure:

-   Banking
-   Transmission
-   Additional Surcharge
-   Wheeling

Each sheet preserves its own schema.

------------------------------------------------------------------------

# Phase 12 -- Formatting

Formatting performed after export.

Enhancements:

-   frozen headers
-   bold titles
-   automatic column width
-   width clamping
-   workbook saved

Formatting never changes data.

Only presentation.

------------------------------------------------------------------------

# Table Patterns Identified

## Pattern 1

Simple Flat Table

    Row
    ↓

    Record

## Pattern 2

Hierarchical Parent → Child

    State

    DISCOM A

    DISCOM B

    DISCOM C

Children inherit parent values.

------------------------------------------------------------------------

## Pattern 3

Continuation Rows

Policy text split across rows.

Continuation rows append to previous record.

------------------------------------------------------------------------

## Pattern 4

Repeated Headers

Every page repeats table header.

Must be detected and discarded.

------------------------------------------------------------------------

## Pattern 5

Multi-page Tables

Rows continue seamlessly across pages.

Pages merged before parsing.

------------------------------------------------------------------------

## Pattern 6

Numeric Matrix

Columns represent measures.

Rows represent entities.

------------------------------------------------------------------------

## Pattern 7

Wide Tables

Multiple measurements inside one row.

Converted into normalized long records.

------------------------------------------------------------------------

# Reusable Design Principles

-   Separation of concerns
-   ETL architecture
-   Configuration-driven parsing
-   Canonical state registry
-   State propagation
-   Parent-child inheritance
-   OCR cleaning
-   Defensive programming
-   Header detection
-   Wide-to-long normalization
-   Standard output interface (List\[dict\])

------------------------------------------------------------------------

# Lessons Learned

1.  Never parse before inspecting the schema.
2.  PDFs are visual documents, not structured databases.
3.  Hierarchy is usually implicit and must be reconstructed.
4.  Cleaning and canonicalization are different tasks.
5.  Configuration should be separated from parsing logic.
6.  Every parser should emit the same record structure.
7.  Build reusable utilities before adding new parameters.
8.  Validate outputs continuously with audits and previews.
9.  Expect OCR imperfections and code defensively.
10. Treat each table family according to its structural pattern, not
    with a single universal parser.

------------------------------------------------------------------------

# Final Pipeline Characteristics

-   Modular
-   Extensible
-   Parameter-driven
-   Schema-aware
-   OCR-tolerant
-   Multi-page capable
-   Hierarchy-aware
-   Suitable for production ETL
