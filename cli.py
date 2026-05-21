#!/usr/bin/env python3
"""
Smart Tool Log Parser — CLI for Fab Engineers

Usage:
    python cli.py ingest <file> [<file> ...]   Parse and store log files
    python cli.py stats [--file <name>]        Show summary statistics
    python cli.py query [filters...]           Query stored log entries
    python cli.py export <output> [filters...] Export to CSV or JSON
    python cli.py analyze [--file <name>]      Run AI analysis on logs
    python cli.py templates                    Manage format templates
    python cli.py clear                        Clear all stored data
    python cli.py generate                     Generate synthetic demo logs
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from database import db
from parser import parse_log, is_valid_log_file


# ── ANSI colors for terminal output ────────────────────────────────────────

class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    CYAN    = "\033[96m"
    MAGENTA = "\033[95m"
    WHITE   = "\033[97m"

    @staticmethod
    def severity(sev: str) -> str:
        return {
            "CRITICAL": C.RED + C.BOLD,
            "ERROR":    C.RED,
            "WARNING":  C.YELLOW,
            "INFO":     C.GREEN,
            "DEBUG":    C.DIM,
        }.get(sev, C.WHITE)


def _print_header(text: str):
    print(f"\n{C.CYAN}{C.BOLD}{'━' * 60}{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  {text}{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}{'━' * 60}{C.RESET}\n")


def _print_table(headers: list[str], rows: list[list[str]], max_widths: list[int] | None = None):
    """Print a formatted ASCII table."""
    if not rows:
        print(f"  {C.DIM}(no data){C.RESET}")
        return

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))

    # Apply max width limits
    if max_widths:
        for i, mw in enumerate(max_widths):
            if mw and i < len(widths):
                widths[i] = min(widths[i], mw)

    # Header
    header_line = "  ".join(f"{C.BOLD}{h:<{widths[i]}}{C.RESET}" for i, h in enumerate(headers))
    print(f"  {header_line}")
    sep = "  ".join("─" * w for w in widths)
    print(f"  {sep}")

    # Rows
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            s = str(cell)
            w = widths[i] if i < len(widths) else 20
            if len(s) > w:
                s = s[:w - 1] + "…"
            cells.append(f"{s:<{w}}")
        print(f"  {'  '.join(cells)}")


# ── Subcommands ────────────────────────────────────────────────────────────

def cmd_ingest(args):
    """Parse and store log files."""
    db.init_db()
    _print_header("Log Ingestion")

    total_stored = 0
    for filepath in args.files:
        if not os.path.isfile(filepath):
            print(f"  {C.RED}✗{C.RESET} File not found: {filepath}")
            continue

        filename = os.path.basename(filepath)
        with open(filepath, "rb") as f:
            content_bytes = f.read()

        # Validate
        if not is_valid_log_file(content_bytes, filename):
            print(f"  {C.RED}✗{C.RESET} Rejected: {filename} (failed validation)")
            continue

        # Parse
        t0 = time.time()
        entries, warnings = parse_log(content_bytes, filename)
        elapsed = time.time() - t0

        if entries:
            n = db.insert_entries(entries)
            total_stored += n
            fmt = entries[0].source_format or "?"
            tools = len(set(e.tool_id for e in entries))
            sevs = {}
            for e in entries:
                sevs[e.severity] = sevs.get(e.severity, 0) + 1

            print(f"  {C.GREEN}✓{C.RESET} {C.BOLD}{filename}{C.RESET}")
            print(f"    Format: {C.CYAN}{fmt}{C.RESET}  |  "
                  f"Records: {C.BOLD}{n}{C.RESET}  |  "
                  f"Tools: {tools}  |  "
                  f"Time: {elapsed:.2f}s")

            sev_parts = []
            for sev in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
                if sev in sevs:
                    sev_parts.append(f"{C.severity(sev)}{sev}:{sevs[sev]}{C.RESET}")
            if sev_parts:
                print(f"    Severity: {' | '.join(sev_parts)}")
        else:
            print(f"  {C.YELLOW}⚠{C.RESET} {filename}: 0 records extracted")

        if warnings and args.verbose:
            for w in warnings[:5]:
                print(f"    {C.DIM}⚠ {w}{C.RESET}")

    print(f"\n  {C.BOLD}Total stored: {total_stored} records{C.RESET}\n")


def cmd_stats(args):
    """Show summary statistics."""
    db.init_db()
    stats = db.get_summary_stats(source_filename=args.file)

    title = f"Statistics: {args.file}" if args.file else "Statistics: All Files"
    _print_header(title)

    metrics = [
        ("Total Records",  str(stats["total"]),    C.BOLD),
        ("Errors",          str(stats["errors"]),   C.RED if stats["errors"] else C.GREEN),
        ("Warnings",        str(stats["warnings"]), C.YELLOW if stats["warnings"] else C.GREEN),
        ("Alarms",          str(stats["alarms"]),   C.RED if stats["alarms"] else C.GREEN),
        ("Unique Tools",    str(stats["tools"]),    C.CYAN),
        ("Recipe Entries",  str(stats["recipes"]),  C.BLUE),
    ]

    for label, value, color in metrics:
        print(f"  {label:20s} {color}{value}{C.RESET}")

    # Tool breakdown
    tools = db.get_distinct_values("tool_id", source_filename=args.file)
    if tools:
        print(f"\n  {C.BOLD}Tools:{C.RESET} {', '.join(tools)}")

    # Severity breakdown
    sevs = db.get_distinct_values("severity", source_filename=args.file)
    if sevs:
        print(f"  {C.BOLD}Severities:{C.RESET} {', '.join(sevs)}")

    # Format breakdown
    fmts = db.get_distinct_values("source_format", source_filename=args.file)
    if fmts:
        print(f"  {C.BOLD}Formats:{C.RESET} {', '.join(fmts)}")

    # File list
    files = db.get_distinct_values("source_filename")
    if files:
        print(f"  {C.BOLD}Files:{C.RESET} {', '.join(files)}")

    print()


def cmd_query(args):
    """Query stored log entries."""
    db.init_db()

    rows = db.query_entries(
        tool_id=args.tool,
        severity=args.severity,
        log_type=args.type,
        start_ts=args.start,
        end_ts=args.end,
        search=args.search,
        source_filename=args.file,
        limit=args.limit,
    )

    title = f"Query Results ({len(rows)} records)"
    _print_header(title)

    if not rows:
        print(f"  {C.DIM}No matching records found.{C.RESET}\n")
        return

    # Format for display
    table_rows = []
    for r in rows:
        sev = r.get("severity", "?")
        sev_color = C.severity(sev)
        table_rows.append([
            r.get("timestamp", "?")[:19],
            r.get("tool_id", "?"),
            f"{sev_color}{sev}{C.RESET}",
            r.get("event_name", r.get("raw_message", "?"))[:50],
            r.get("parameter_name", "") or "",
            str(r.get("parameter_value", "")) if r.get("parameter_value") else "",
            r.get("unit", "") or "",
            r.get("wafer_id", "") or "",
        ])

    _print_table(
        ["Timestamp", "Tool", "Severity", "Event", "Param", "Value", "Unit", "Wafer"],
        table_rows,
        max_widths=[19, 12, 10, 50, 15, 10, 8, 15],
    )
    print()


def cmd_export(args):
    """Export records to CSV or JSON."""
    db.init_db()

    rows = db.query_entries(
        tool_id=args.tool,
        severity=args.severity,
        source_filename=args.file,
        limit=args.limit or 50000,
    )

    if not rows:
        print(f"  {C.YELLOW}No records to export.{C.RESET}")
        return

    output = args.output
    if output.endswith(".json"):
        with open(output, "w") as f:
            json.dump(rows, f, indent=2, default=str)
    elif output.endswith(".csv"):
        import csv
        if rows:
            keys = list(rows[0].keys())
            with open(output, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
    else:
        print(f"  {C.RED}Unsupported format. Use .csv or .json{C.RESET}")
        return

    print(f"  {C.GREEN}✓{C.RESET} Exported {len(rows)} records to {C.BOLD}{output}{C.RESET}")


def cmd_analyze(args):
    """Run AI analysis on logs."""
    db.init_db()

    rows = db.query_entries(
        source_filename=args.file,
        severity=args.severity,
        limit=50,
    )

    if not rows:
        print(f"  {C.YELLOW}No records to analyze.{C.RESET}")
        return

    _print_header("AI Analysis")
    print(f"  Analyzing {len(rows)} records...")

    try:
        from llm import analyzer
        stats = db.get_summary_stats(source_filename=args.file)

        if args.question:
            # Direct question mode
            messages = [{"role": "user", "content": args.question}]
            response = analyzer.chat_with_logs(messages, stats, rows[:30])
            print(f"\n  {C.BOLD}Question:{C.RESET} {args.question}")
            print(f"\n  {C.BOLD}Answer:{C.RESET}")
            for line in response.split("\n"):
                print(f"  {line}")
        else:
            # Default: summarise health
            messages = [{"role": "user", "content": "Summarise the overall health of these logs. Highlight critical issues, recurring patterns, and recommended actions."}]
            response = analyzer.chat_with_logs(messages, stats, rows[:30])
            print(f"\n  {C.BOLD}Health Summary:{C.RESET}")
            for line in response.split("\n"):
                print(f"  {line}")

    except Exception as e:
        print(f"  {C.RED}AI analysis failed: {e}{C.RESET}")
        print(f"  {C.DIM}Ensure OPENAI_API_KEY is set in .env{C.RESET}")

    print()


def cmd_templates(args):
    """Manage format templates."""
    db.init_db()
    _print_header("Format Templates")

    templates = db.list_format_templates()
    if not templates:
        print(f"  {C.DIM}No saved templates.{C.RESET}\n")
        return

    table_rows = []
    for t in templates:
        mapping_keys = list(t.get("field_mapping", {}).keys())
        table_rows.append([
            t["name"],
            t["file_signature"],
            ", ".join(mapping_keys[:5]),
            t.get("created_at", "?")[:19],
        ])

    _print_table(
        ["Name", "Signature", "Fields", "Created"],
        table_rows,
        max_widths=[25, 20, 40, 19],
    )

    if args.delete:
        for t in templates:
            if t["name"] == args.delete or t["id"] == args.delete:
                db.delete_format_template(t["id"])
                print(f"\n  {C.GREEN}✓{C.RESET} Deleted template: {t['name']}")
                break
        else:
            print(f"\n  {C.RED}Template not found: {args.delete}{C.RESET}")

    print()


def cmd_clear(args):
    """Clear all stored data."""
    db.init_db()

    if not args.yes:
        response = input(f"  {C.YELLOW}Delete ALL stored records? [y/N]: {C.RESET}")
        if response.lower() != "y":
            print("  Cancelled.")
            return

    if args.file:
        db.delete_by_filename(args.file)
        print(f"  {C.GREEN}✓{C.RESET} Deleted records for: {args.file}")
    else:
        db.clear_all()
        print(f"  {C.GREEN}✓{C.RESET} All data cleared.")


def cmd_generate(args):
    """Generate synthetic demo log files."""
    db.init_db()
    _print_header("Generating Synthetic Logs")

    from synthetic.generator import generate_sample_files
    output_dir = args.output or "synthetic/samples"
    files = generate_sample_files(output_dir)

    print(f"\n  {C.GREEN}✓{C.RESET} Generated {len(files)} sample files in {C.BOLD}{output_dir}/{C.RESET}")

    if args.ingest:
        print(f"\n  Ingesting generated files...")
        total = 0
        for fmt, path in files.items():
            with open(path, "rb") as f:
                content_bytes = f.read()
            filename = os.path.basename(path)
            entries, _ = parse_log(content_bytes, filename)
            if entries:
                n = db.insert_entries(entries)
                total += n
                print(f"    {C.GREEN}✓{C.RESET} {filename}: {n} records ({entries[0].source_format})")
        print(f"\n  {C.BOLD}Total ingested: {total} records{C.RESET}")

    print()


# ── CLI entrypoint ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="cli",
        description=f"{C.CYAN}{C.BOLD}Smart Tool Log Parser{C.RESET} — CLI for Fab Engineers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{C.BOLD}Examples:{C.RESET}
  python cli.py ingest logs/*.log logs/*.bin       Parse multiple log files
  python cli.py stats                              Show overall statistics
  python cli.py stats --file tool_log_text.txt     Stats for a specific file
  python cli.py query --tool ETCH-01 --severity ERROR
  python cli.py query --search "vacuum" --limit 20
  python cli.py export results.csv --severity ERROR
  python cli.py analyze --question "What caused the pressure faults?"
  python cli.py generate --ingest                  Generate and auto-ingest demo logs
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── ingest ──
    p_ingest = subparsers.add_parser("ingest", help="Parse and store log files")
    p_ingest.add_argument("files", nargs="+", help="Log file paths")
    p_ingest.add_argument("-v", "--verbose", action="store_true", help="Show parser warnings")

    # ── stats ──
    p_stats = subparsers.add_parser("stats", help="Show summary statistics")
    p_stats.add_argument("--file", help="Filter by source filename")

    # ── query ──
    p_query = subparsers.add_parser("query", help="Query stored log entries")
    p_query.add_argument("--tool", help="Filter by tool_id")
    p_query.add_argument("--severity", help="Filter by severity (INFO/WARNING/ERROR/CRITICAL)")
    p_query.add_argument("--type", help="Filter by log_type")
    p_query.add_argument("--start", help="Start timestamp (ISO format)")
    p_query.add_argument("--end", help="End timestamp (ISO format)")
    p_query.add_argument("--search", help="Full-text search in messages")
    p_query.add_argument("--file", help="Filter by source filename")
    p_query.add_argument("--limit", type=int, default=50, help="Max records (default: 50)")

    # ── export ──
    p_export = subparsers.add_parser("export", help="Export to CSV or JSON")
    p_export.add_argument("output", help="Output file path (.csv or .json)")
    p_export.add_argument("--tool", help="Filter by tool_id")
    p_export.add_argument("--severity", help="Filter by severity")
    p_export.add_argument("--file", help="Filter by source filename")
    p_export.add_argument("--limit", type=int, help="Max records")

    # ── analyze ──
    p_analyze = subparsers.add_parser("analyze", help="Run AI analysis on logs")
    p_analyze.add_argument("--file", help="Filter by source filename")
    p_analyze.add_argument("--severity", help="Filter by severity")
    p_analyze.add_argument("-q", "--question", help="Ask a specific question")

    # ── templates ──
    p_templates = subparsers.add_parser("templates", help="Manage format templates")
    p_templates.add_argument("--delete", help="Delete template by name or ID")

    # ── clear ──
    p_clear = subparsers.add_parser("clear", help="Clear stored data")
    p_clear.add_argument("--file", help="Clear only records for this filename")
    p_clear.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # ── generate ──
    p_generate = subparsers.add_parser("generate", help="Generate synthetic demo logs")
    p_generate.add_argument("--output", help="Output directory (default: synthetic/samples)")
    p_generate.add_argument("--ingest", action="store_true", help="Also ingest generated files")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "ingest": cmd_ingest,
        "stats": cmd_stats,
        "query": cmd_query,
        "export": cmd_export,
        "analyze": cmd_analyze,
        "templates": cmd_templates,
        "clear": cmd_clear,
        "generate": cmd_generate,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
