# Cross-Subsidy Surcharge Scraping Pipeline
## Post-OCR Table Indexing, Page Discovery, Table Normalization, and Query Routing

This document explains the cross-subsidy surcharge scraping process in detail, focusing on the method used after OCR-related experimentation. The main idea is not to rely on image OCR as the primary path, but to build a PDF-aware table pipeline that:

1. indexes the full PDF by page,
2. detects table-bearing pages and table titles,
3. identifies the correct section for cross-subsidy surcharge,
4. extracts structured tables with `pdfplumber`,
5. normalizes table blocks into state-based structures,
6. supports retrieval and querying over those structured blocks.

The point of the pipeline is not just to extract rows. The point is to turn a chaotic regulatory PDF into a searchable, structured warehouse.

---

# 1. What problem this pipeline solves

The source PDF contains many different regulatory tables:

- cross subsidy surcharge
- additional surcharge
- wheeling charge
- transmission charge
- banking charges
- return on equity
- reliability of supply
- green energy open access
- and more

These tables are not laid out like a clean CSV. They are spread across pages, often with repeated headers, nested sub-sections, and state-specific blocks.

The cross-subsidy surcharge section is especially important because it sits inside the broader open access charge block. The relevant section starts at page 50 and continues through page 56 in the current indexing workflow.

---

# 2. The core philosophy

The pipeline is built around a simple principle:

> Do not parse the table blindly. First discover where the table is, what its title is, how its pages are distributed, and what structure it actually has.

That is why this process uses:

- page indexing
- table-title detection
- table-page anchoring
- structured table extraction
- state-block segmentation
- query engine routing

This is more reliable than jumping straight to OCR, because OCR can easily introduce noise, wrong boundaries, and broken text. The post-OCR path instead uses the PDF's own text and table structure whenever possible.

---

# 3. Phase 2.3: Table-title indexing and section discovery

This phase creates a searchable index of the PDF.

## 3.1 Why indexing is needed

A PDF is not automatically a dataset. It is a container of pages, text, and tables. To extract one parameter such as cross-subsidy surcharge, you first need to know:

- which page contains the table title,
- which pages belong to that section,
- whether the same section continues across multiple pages,
- and whether multiple table titles appear on the same page.

For example, page 50 contains:

- `Table-5(a): Cross Subsidy Surcharge`
- `Table-5: Open Access Charges`

So the section is not a single isolated page. It is a multi-page block that belongs to a larger open access charge family.

---

## 3.2 Page-level index creation

The script reads the full PDF and processes every page one by one.

For each page it stores:

- `page_number`
- `page_text`
- `table_titles`
- `contains_table`
- `text_length`

The table title detection uses a regex pattern that looks for text like:

```text
TABLE-5(a): Cross Subsidy Surcharge
```

This is important because table titles are the anchors for the rest of the pipeline.

---

## 3.3 Why the page index matters

Without a page index, you would have to manually scan the PDF every time you want a table.

With the index, you can ask:

- which pages mention `cross subsidy surcharge`
- which pages mention `wheeling charge`
- which pages mention `banking charges`

That turns the PDF into a searchable database-like object.

---

## 3.4 Table pages discovered

The index reveals the major table-bearing pages around the open access section:

- page 50: cross subsidy surcharge / open access charges
- page 57: additional surcharge
- page 59: wheeling charge
- page 62: transmission charge
- page 64: banking charges

This is the first important discovery.

The PDF is not a random list of pages. It has a parameter family structure.

---

# 4. FTS5 search over the page index

## 4.1 Why FTS5 was used

The page index is inserted into a SQLite database with an FTS5 virtual table. That gives fast full-text search over:

- page text
- table titles

This makes the PDF searchable like a document search engine.

Instead of manually opening page 50 and page 56, the system can answer queries such as:

- "cross subsidy surcharge"
- "wheeling charge"
- "banking charges"
- "open access"

---

## 4.2 What the search test showed

The search engine maps the query to the correct table title and then returns the section pages.

For cross subsidy surcharge, it identified:

- matched table: `Table-5(a): Cross Subsidy Surcharge`
- section start: 50
- section end: 56
- pages: 50 to 56

That is the key routing result.

The same indexing logic also works for:

- additional surcharge → 57 to 58
- wheeling charge → 59 to 61
- transmission charge → 62 to 63
- banking charges → 64 to 75

This means the pipeline can route a user query to the correct PDF block without OCR.

---

# 5. Why not use OCR as the primary method

OCR was explored separately, but for the cross-subsidy surcharge workflow the stronger method is the text-and-table route.

OCR is useful when:

- the text is embedded as images,
- the PDF text extraction fails,
- or the page is scanned.

But OCR is also noisy:

- broken glyphs,
- wrong characters,
- weak table boundaries,
- row misalignment,
- merged-cell confusion.

The post-OCR pipeline avoids depending on OCR unless absolutely necessary. It uses `pdfplumber`, table titles, and page indexing to preserve the PDF's internal structure.

In other words:

- OCR is a fallback
- indexing + structured extraction is the main path

---

# 6. Phase 4: Table extraction from the cross-subsidy section

## 6.1 Extraction strategy

Once the right pages are identified, the pipeline extracts tables from those pages using `pdfplumber`.

For the open access block around pages 50 to 56, the table extraction summary showed:

- page 50 → one table, 25 × 12
- page 51 → one table, 57 × 16
- page 52 → one table, 58 × 21
- page 53 → one table, 56 × 14
- page 54 → one table, 54 × 21
- page 55 → one table, 58 × 19

That tells us these pages are not small notes. They are dense, structured regulatory matrices.

---

## 6.2 Why the largest table is selected

In regulatory PDFs, a page may contain:

- the main table,
- footnotes,
- borders,
- captions,
- decoration,
- or minor embedded sub-tables.

To avoid picking the wrong object, the pipeline chooses the largest table on the page using a size heuristic.

The heuristic is effectively:

```text
rows × columns
```

The largest table is usually the real data table.

This is an approximation, but it works well when the PDF is visually consistent.

---

## 6.3 What the extracted rows look like

Once page 50 is extracted, the raw table rows show a highly structured open-access matrix.

The first rows include:

- Andhra Pradesh
- category row
- utility columns like APSPDCL, APEPDCL, APCPDCL
- subsequent HT category rows
- tariff values in different columns

This is crucial.

The cross-subsidy/open-access region is not a narrative table like Banking Charges. It is a matrix table: states, utilities, categories, and tariff numbers arranged in a grid.

That means the parsing logic must be matrix-aware rather than narrative-aware.

---

# 7. Phase 4 normalization: removing empty columns and empty rows

The raw extracted tables often include:

- empty columns between meaningful columns,
- blank rows,
- alignment padding,
- structural gaps created by merged cells.

To make the table easier to process, the pipeline normalizes it by:

1. removing columns that contain no meaningful data,
2. removing rows that are completely empty.

This step does not interpret the table. It only cleans its geometry.

This is the difference between:

- structural cleanup
- semantic parsing

Structural cleanup answers: “What cells are actually occupied?”
Semantic parsing answers: “Which state or utility does this row belong to?”

---

# 8. Phase 4 state block segmentation

## 8.1 Why state blocks are needed

The open access / cross-subsidy surcharge section contains multiple state-specific blocks.

Each block begins with a row that identifies a state, often with a date or year in the same row.

The system uses a year pattern such as:

```text
20xx-xx
```

to help locate the start of a state block.

This is a key point.

The parser is not looking for image boundaries. It is looking for **table grammar**.

---

## 8.2 How a state block is detected

The logic looks for a row containing:

- a state-like label
- a financial year such as `2026-27`
- and a recognizable structure in the row text

That row becomes the start of a new block.

For example, one block begins with:

- Andhra Pradesh / 2026-27

Then the rows after it belong to Andhra Pradesh until the next state starter is found.

This produces a state-block structure like:

```text
State: Andhra Pradesh
Rows: [...]
```

---

## 8.3 Why this is powerful

This is the same idea as turning a flat spreadsheet into a grouped dataset.

Instead of having rows floating around without context, the pipeline says:

- these rows belong to Andhra Pradesh
- these rows belong to Goa
- these rows belong to Haryana
- these rows belong to Odisha

That grouping is later used by the search and query engines.

---

# 9. State catalog and retrieval

## 9.1 Why a state catalog was built

The extraction pipeline eventually needs a way to answer questions such as:

- show Andhra Pradesh
- show Goa
- show Haryana
- show Delhi

To make that possible, a state catalog is built.

The catalog maps a state name to a block ID, and the block ID points to a table block in `state_blocks_v2.json`.

This is important because it decouples the query layer from the raw PDF.

The query layer does not need to know how the PDF was parsed. It only needs:

- the state name
- the block mapping
- the normalized rows

---

## 9.2 What the retrieval function does

The function:

1. searches the state catalog for a matching state,
2. locates the block ID,
3. loads the block from the JSON structure,
4. returns the rows for that state.

This is a clean separation of concerns.

The parser builds the structure.
The retrieval layer uses the structure.

---

# 10. Query engine layer

## 10.1 Why a query engine is useful

Once the structured blocks exist, the next step is search.

The query engine takes a natural-language query like:

- Andhra Pradesh Railway Traction
- Delhi Non Domestic
- Goa HT Level

It then:

1. detects the state,
2. extracts keywords,
3. searches the state-specific structured data,
4. ranks the matches,
5. returns the most relevant rows.

---

## 10.2 Query engine components

### State detection

The state detector uses a state list and checks whether the state name appears in the query.

### Keyword extraction

It removes stop words such as:

- extract
- show
- find
- charges
- charge
- open
- access

Then it keeps the informative words.

### Search scoring

Each row is scored against the keywords.

If the query is:

```text
Andhra Pradesh Railway Traction
```

the keywords are:

- railway
- traction

The search engine then looks for those words in section names and row categories.

This is why the engine can return precise matches like:

- HT IV(D) Railway Traction

---

# 11. What is special about cross-subsidy surcharge?

Cross-subsidy surcharge is not isolated in the PDF. It appears inside the open access charge family.

The structure is:

- Table-5: Open Access Charges
  - Table-5(a): Cross Subsidy Surcharge
  - Table-5(b): Additional Surcharge
  - Table-5(c): Wheeling Charge
  - Table-5(d): Transmission Charge
  - Table-5(e): Banking Charges

This family structure matters because the section boundaries are inherited from the table-title indexing.

In practical terms:

- the section starts at page 50
- the cross-subsidy surcharge logic is part of that section
- the section ends before the next family begins

So the page index is what enables the correct scraping target.

---

# 12. Why the non-OCR path is better here

The non-OCR path has several advantages:

- It preserves actual text when the PDF already contains searchable text.
- It captures table titles and section boundaries accurately.
- It lets the parser work with page-level metadata.
- It supports reusable state and block logic.
- It is easier to debug than OCR-only extraction.

OCR should be treated as a fallback, not the foundation, for this document.

---

# 13. Table patterns discovered in the cross-subsidy region

The cross-subsidy/open access section reveals several table patterns.

## Pattern A: section family with sub-tables

One parent table title contains multiple child titles.

Example:

```text
Table-5: Open Access Charges
Table-5(a): Cross Subsidy Surcharge
Table-5(b): Additional Surcharge
```

## Pattern B: state-based matrix rows

Rows begin with a state name and then carry utility columns.

## Pattern C: repeated category rows

Many tables repeat category names such as:

- HT
- LT
- EHT
- Industrial
- Domestic
- Non-Domestic

## Pattern D: merged multi-row headers

The top rows often contain multi-level column labels that span several columns.

## Pattern E: state blocks

The same state may span many rows and many subcategories.

---

# 14. Why the pipeline uses JSON, CSV, and SQLite

Different intermediate formats serve different jobs:

- CSV is easy for quick inspection.
- JSON preserves nested table structures.
- SQLite with FTS5 provides searchable indexing.
- Excel is the final human-readable warehouse.

The pipeline therefore uses multiple storage formats because no single format is ideal for every step.

---

# 15. Summary of the process

The cross-subsidy surcharge scraping pipeline works like this:

1. Build a page index for the full PDF.
2. Detect pages with table titles.
3. Search for `cross subsidy surcharge`.
4. Identify the section pages, mainly page 50 to 56.
5. Extract the tables from those pages with `pdfplumber`.
6. Normalize the tables by removing empty rows and columns.
7. Segment the rows into state blocks.
8. Store the blocks in JSON and catalog files.
9. Expose retrieval by state.
10. Allow the query engine to search within the state blocks.

That is the real post-OCR workflow.

---

# 16. What to notice when extending the pipeline

When you add another parameter, check:

- Is it a narrative table or a matrix table?
- Does it have repeated headers?
- Does it have state blocks?
- Does it have utilities underneath the state?
- Does it need wide-to-long expansion?
- Does it need canonical state matching?
- Does it need a separate query vocabulary?

If the answer to these questions changes, the parser strategy changes too.

That is why the framework evolved into multiple parser families instead of one monolithic script.

---

# 17. Final takeaway

The main lesson from the cross-subsidy surcharge workflow is simple:

> The best extraction pipeline is not the one that starts with OCR.  
> The best extraction pipeline is the one that first understands the PDF's internal structure, builds an index, discovers the right section, and only then parses the rows.

That is what makes the pipeline stable, explainable, and reusable.
