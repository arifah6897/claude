"""
Telegram Brief Generator for April Posts

Reads Telegram post emails from Outlook for April, then uses Claude to generate
a brief for each post using your uploaded brief template.

Usage:
    # Generate briefs for April 2025 (default)
    python generate_april_briefs.py

    # Custom month/year
    python generate_april_briefs.py --month 4 --year 2025

    # Use a custom brief template file
    python generate_april_briefs.py --template my_brief_template.txt

    # Dry run (print briefs without saving)
    python generate_april_briefs.py --dry-run

Environment variables required:
    ANTHROPIC_API_KEY    - Your Anthropic API key
    OUTLOOK_CLIENT_ID    - Azure app client ID
    OUTLOOK_TENANT_ID    - Azure tenant ID (or "common")

Optional:
    BRIEF_TEMPLATE_FILE  - Path to brief template (default: brief_template.txt)
    BRIEFS_OUTPUT_DIR    - Output directory for generated briefs (default: ./briefs)
"""

import os
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser

import anthropic

from outlook_connector import authenticate, fetch_telegram_post_emails

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_TEMPLATE_FILE = "brief_template.txt"
DEFAULT_OUTPUT_DIR = "briefs"
CLAUDE_MODEL = "claude-opus-4-6"


# ── Helpers ───────────────────────────────────────────────────────────────────

class _HTMLStripper(HTMLParser):
    """Strip HTML tags from email body."""
    def __init__(self):
        super().__init__()
        self.text_parts = []

    def handle_data(self, data):
        self.text_parts.append(data)

    def get_text(self) -> str:
        return " ".join(self.text_parts).strip()


def strip_html(html: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


def load_template(template_path: str) -> str:
    path = Path(template_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Brief template not found at: {path}\n"
            "Please upload your brief template to the repository and ensure "
            f"it is saved as '{path}'."
        )
    return path.read_text(encoding="utf-8")


def sanitize_filename(subject: str) -> str:
    """Convert email subject to a safe filename."""
    clean = re.sub(r"[^\w\s-]", "", subject)
    clean = re.sub(r"\s+", "_", clean.strip())
    return clean[:80]


# ── Claude brief generation ───────────────────────────────────────────────────

def generate_brief(
    client: anthropic.Anthropic,
    template: str,
    post_content: str,
    post_subject: str,
    post_date: str,
) -> str:
    """
    Use Claude to generate a brief for a single Telegram post.

    Args:
        client:       Anthropic client
        template:     Brief template text
        post_content: Plain text content of the email (the Telegram post)
        post_subject: Email subject line
        post_date:    Date the email was received

    Returns:
        Generated brief as a string
    """
    prompt = f"""You are a professional content writer creating briefs for Telegram posts.

Here is the brief template you must follow:
<template>
{template}
</template>

Here is the Telegram post to create a brief for:
<post>
Subject: {post_subject}
Date: {post_date}
Content:
{post_content}
</post>

Instructions:
1. Fill in the brief template using information from the Telegram post above
2. Keep the same structure and section headings as the template
3. Write in a professional, concise tone
4. If any template field cannot be filled from the post content, mark it as "N/A"
5. Return only the completed brief — no extra commentary

Generate the brief now:"""

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        return stream.get_final_message().content[-1].text


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(
    month: int = 4,
    year: int = 2025,
    template_file: str = DEFAULT_TEMPLATE_FILE,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    subject_keyword: str = "Telegram",
    dry_run: bool = False,
) -> list[dict]:
    """
    Full pipeline: fetch Telegram post emails → generate briefs → save to files.

    Args:
        month:           Month to process (1-12)
        year:            Year to process
        template_file:   Path to brief template file
        output_dir:      Directory to save generated briefs
        subject_keyword: Keyword to filter Telegram post emails
        dry_run:         If True, print briefs but don't save

    Returns:
        List of result dicts with keys: subject, date, brief_file, status
    """
    # ── Load template ──────────────────────────────────────────────────────
    print(f"Loading brief template from: {template_file}")
    template = load_template(template_file)

    # ── Authenticate with Outlook ──────────────────────────────────────────
    print("\nConnecting to Outlook...")
    token = authenticate()
    print("✓ Outlook connected")

    # ── Fetch emails ───────────────────────────────────────────────────────
    print(f"\nFetching Telegram post emails for {year}-{month:02d}...")
    emails = fetch_telegram_post_emails(
        token=token,
        month=month,
        year=year,
        subject_keyword=subject_keyword,
    )

    if not emails:
        print(f"No emails found matching '{subject_keyword}' for {year}-{month:02d}.")
        print("Check your subject_keyword filter or date range.")
        return []

    # ── Set up output directory ────────────────────────────────────────────
    output_path = Path(output_dir)
    if not dry_run:
        output_path.mkdir(parents=True, exist_ok=True)
        print(f"Saving briefs to: {output_path.resolve()}")

    # ── Init Claude client ─────────────────────────────────────────────────
    claude = anthropic.Anthropic()

    # ── Generate briefs ────────────────────────────────────────────────────
    results = []
    total = len(emails)

    print(f"\nGenerating briefs for {total} posts...\n")

    for i, email in enumerate(emails, 1):
        subject = email["subject"]
        date_str = email["received"][:10]
        post_text = strip_html(email["body"]) or email["body_preview"]

        print(f"[{i}/{total}] {subject[:60]} ({date_str})")

        try:
            brief = generate_brief(
                client=claude,
                template=template,
                post_content=post_text,
                post_subject=subject,
                post_date=date_str,
            )

            if dry_run:
                print(f"\n{'='*60}")
                print(f"BRIEF: {subject}")
                print('='*60)
                print(brief)
                print()
                results.append({"subject": subject, "date": date_str, "brief_file": None, "status": "dry_run"})
            else:
                filename = f"{date_str}_{sanitize_filename(subject)}.txt"
                brief_file = output_path / filename
                brief_file.write_text(brief, encoding="utf-8")
                print(f"  → Saved: {brief_file}")
                results.append({"subject": subject, "date": date_str, "brief_file": str(brief_file), "status": "saved"})

        except Exception as e:
            print(f"  ✗ Error generating brief: {e}")
            results.append({"subject": subject, "date": date_str, "brief_file": None, "status": f"error: {e}"})

    # ── Summary ────────────────────────────────────────────────────────────
    saved = sum(1 for r in results if r["status"] == "saved")
    errors = sum(1 for r in results if r["status"].startswith("error"))

    print(f"\n{'='*60}")
    print(f"Done! {saved}/{total} briefs generated successfully.")
    if errors:
        print(f"  {errors} errors — check output above.")
    if not dry_run and saved:
        print(f"  Briefs saved to: {output_path.resolve()}/")
    print('='*60)

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate Telegram post briefs from Outlook emails using Claude"
    )
    parser.add_argument("--month", type=int, default=4, help="Month number (default: 4 for April)")
    parser.add_argument("--year", type=int, default=2025, help="Year (default: 2025)")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE_FILE, help=f"Brief template file (default: {DEFAULT_TEMPLATE_FILE})")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"Output directory for briefs (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--keyword", default="Telegram", help="Subject keyword to filter emails (default: Telegram)")
    parser.add_argument("--dry-run", action="store_true", help="Print briefs without saving files")

    args = parser.parse_args()

    run(
        month=args.month,
        year=args.year,
        template_file=args.template,
        output_dir=args.output_dir,
        subject_keyword=args.keyword,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
