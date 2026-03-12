#!/usr/bin/env python3
"""
YouTube → NotebookLM Research Pipeline
Searches YouTube for videos on a topic, then adds them to a NotebookLM notebook.
Uses yt-dlp for scraping and the notebooklm CLI for notebook management.
"""

import argparse
import json
import subprocess
import sys
import time

import yt_dlp


# ── YouTube scraping ──────────────────────────────────────────────────────────

def scrape_youtube(query: str, max_results: int = 25) -> list[dict]:
    """Return video metadata for a YouTube search query."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "ignoreerrors": True,
    }

    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        if not info or "entries" not in info:
            return []

        for entry in info["entries"]:
            if not entry:
                continue
            video_id = entry.get("id", "")
            url = (
                f"https://www.youtube.com/watch?v={video_id}"
                if video_id
                else entry.get("url", "")
            )
            view_count = entry.get("view_count")
            if view_count is not None:
                if view_count >= 1_000_000:
                    views_str = f"{view_count / 1_000_000:.1f}M"
                elif view_count >= 1_000:
                    views_str = f"{view_count / 1_000:.1f}K"
                else:
                    views_str = str(view_count)
            else:
                views_str = "N/A"

            duration_secs = entry.get("duration")
            if duration_secs:
                mins, secs = divmod(int(duration_secs), 60)
                hrs, mins = divmod(mins, 60)
                duration_str = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"
            else:
                duration_str = "N/A"

            videos.append({
                "rank": len(videos) + 1,
                "title": entry.get("title", "Unknown Title"),
                "author": entry.get("uploader") or entry.get("channel", "Unknown"),
                "views": views_str,
                "views_raw": view_count,
                "duration": duration_str,
                "url": url,
                "video_id": video_id,
            })

    return videos


# ── NotebookLM helpers ────────────────────────────────────────────────────────

def run_notebooklm(args: list[str]) -> tuple[int, str, str]:
    """Run a notebooklm CLI command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["notebooklm"] + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def create_notebook(title: str) -> str:
    """Create a new notebook and return its ID."""
    code, stdout, stderr = run_notebooklm(["create", title, "--json"])
    if code != 0:
        raise RuntimeError(f"Failed to create notebook: {stderr}")
    data = json.loads(stdout)
    return data["id"]


def add_source(notebook_id: str, url: str) -> dict | None:
    """Add a YouTube URL as a source to a notebook. Returns source info or None."""
    code, stdout, stderr = run_notebooklm(
        ["source", "add", url, "--notebook", notebook_id, "--json"]
    )
    if code != 0:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(
    query: str,
    max_results: int = 25,
    notebook_title: str | None = None,
    delay: float = 1.0,
) -> dict:
    """
    Full pipeline: search YouTube → create notebook → add sources.

    Returns a summary dict with notebook_id, videos found, and sources added.
    """
    print(f"\n[1/3] Searching YouTube for: '{query}' (max {max_results} results)...")
    videos = scrape_youtube(query, max_results)
    if not videos:
        raise RuntimeError(f"No YouTube results found for query: '{query}'")
    print(f"      Found {len(videos)} videos.")

    title = notebook_title or f"YouTube Research: {query}"
    print(f"\n[2/3] Creating NotebookLM notebook: '{title}'...")
    notebook_id = create_notebook(title)
    print(f"      Notebook created (ID: {notebook_id[:8]}...)")

    print(f"\n[3/3] Adding {len(videos)} YouTube URLs as sources...")
    added = []
    failed = []
    for video in videos:
        result = add_source(notebook_id, video["url"])
        if result:
            added.append({"video": video, "source": result})
            print(f"      + [{video['rank']:02d}] {video['title'][:60]}")
        else:
            failed.append(video)
            print(f"      ! [{video['rank']:02d}] FAILED: {video['title'][:60]}")
        if delay > 0:
            time.sleep(delay)

    summary = {
        "query": query,
        "notebook_id": notebook_id,
        "notebook_title": title,
        "videos_found": len(videos),
        "sources_added": len(added),
        "sources_failed": len(failed),
        "videos": videos,
        "added_sources": added,
        "failed_sources": failed,
    }

    print(f"\nPipeline complete!")
    print(f"  Notebook:       {title}")
    print(f"  Notebook ID:    {notebook_id}")
    print(f"  Videos found:   {len(videos)}")
    print(f"  Sources added:  {len(added)}")
    if failed:
        print(f"  Sources failed: {len(failed)}")
    print(f"\nNext steps:")
    print(f"  notebooklm use {notebook_id[:6]}")
    print(f"  notebooklm ask 'What are the top findings from these videos?'")
    print(f"  notebooklm generate infographic --style sketch-note")

    return summary


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="YouTube → NotebookLM Research Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python yt_to_notebooklm.py "machine learning trends 2025"
  python yt_to_notebooklm.py "Python tutorials" --max 10
  python yt_to_notebooklm.py "AI news" --max 25 --title "AI News Research"
  python yt_to_notebooklm.py "crypto" --max 15 --delay 2 --json
        """,
    )
    parser.add_argument("query", help="YouTube search topic")
    parser.add_argument(
        "--max", "-n", type=int, default=25, metavar="N",
        help="Max YouTube results (1–50, default: 25)",
    )
    parser.add_argument(
        "--title", "-t", default=None,
        help="Custom notebook title (default: 'YouTube Research: <query>')",
    )
    parser.add_argument(
        "--delay", "-d", type=float, default=1.0,
        help="Seconds between source uploads (default: 1.0)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output full pipeline summary as JSON",
    )

    args = parser.parse_args()

    if not (1 <= args.max <= 50):
        print("Error: --max must be between 1 and 50", file=sys.stderr)
        sys.exit(1)

    summary = run_pipeline(
        query=args.query,
        max_results=args.max,
        notebook_title=args.title,
        delay=args.delay,
    )

    if args.json:
        print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
