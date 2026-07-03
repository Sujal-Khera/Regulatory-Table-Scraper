"""CLI entry point — index, discover, extract, run subcommands."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from table_scraper.storage.workspace import Workspace
from table_scraper.config.loader import load_settings
from table_scraper.domain.enums import SessionStage
from table_scraper.pipeline.session import PipelineSession
from table_scraper.pipeline.runner import run_pipeline
from table_scraper.interfaces.cli.prompts import build_user_selection


def main() -> None:
    """Dispatch CLI subcommands for the pipeline."""
    parser = argparse.ArgumentParser(description="DeFi Wallet & Regulatory PDF Table Scraper CLI")
    parser.add_argument("pdf_path", type=str, nargs="?", help="Path to input PDF file")
    parser.add_argument("--profile", type=str, default="default", help="Active profile name")
    parser.add_argument("--output", type=str, help="Excel output path override")

    args = parser.parse_args()

    # 1. PDF selection
    pdf_path_str = args.pdf_path
    if not pdf_path_str:
        try:
            pdf_path_str = input("Enter path to PDF file: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(0)

    if not pdf_path_str:
        print("Error: Valid PDF file path is required.")
        sys.exit(1)

    pdf_file = Path(pdf_path_str).expanduser().resolve()
    if not pdf_file.is_file():
        print(f"Error: PDF file does not exist: {pdf_file}")
        sys.exit(1)

    # 2. Workspace & Session initialization
    try:
        workspace = Workspace.open(pdf_file, args.profile)
        settings = load_settings(pdf_file, args.profile)
        session = PipelineSession(workspace=workspace, settings=settings)
        print(f"Initialized Workspace {workspace.workspace_id} under: {workspace.root}")
    except Exception as e:
        print(f"Error initializing workspace: {e}")
        sys.exit(1)

    # 3. Automatic discovery (Index + Discover stages)
    print("\n[1/3] Running Indexing and Discovery Engine...")
    try:
        run_pipeline(session, [SessionStage.INDEX, SessionStage.DISCOVER])
    except Exception as e:
        print(f"Error during discovery: {e}")
        sys.exit(1)

    if not session.catalog or not session.catalog.parameters:
        print("Error: No parameters discovered in the PDF.")
        sys.exit(1)

    # 4. User selection prompts
    print("\n[2/3] Parameter and Page Range Confirmation")
    try:
        user_sel = build_user_selection(session.catalog)
        if args.output:
            user_sel = replace_output_path(user_sel, args.output)
        session.user_selection = user_sel
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"Error during parameter selection: {e}")
        sys.exit(1)

    # 5. Execute pipeline execution
    print("\n[3/3] Executing extraction, parsing, validation, and Excel export...")
    try:
        result = run_pipeline(
            session,
            [
                SessionStage.SELECT,
                SessionStage.EXTRACT,
                SessionStage.NORMALIZE,
                SessionStage.CLASSIFY,
                SessionStage.PARSE,
                SessionStage.VALIDATE,
                SessionStage.EXPORT,
            ],
        )
    except Exception as e:
        print(f"Error executing pipeline: {e}")
        sys.exit(1)

    # 6. Report final output location
    print("\nPipeline run completed successfully!")
    if result.export_results:
        for idx, res in enumerate(result.export_results):
            if isinstance(res.workbook, bytes):
                print(f"Workbook {idx + 1} written as binary data ({len(res.workbook)} bytes).")
            else:
                print(f"Workbook {idx + 1} written to: {res.workbook.path}")
    else:
        print("No worksheets exported.")


def replace_output_path(selection: Any, output_path: str) -> Any:
    """Helper to update export_path override in UserSelection."""
    from dataclasses import replace
    return replace(selection, export_path=output_path)


if __name__ == "__main__":
    main()
