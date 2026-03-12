#!/usr/bin/env python3
"""
YouTube Research Tool
Uses yt-dlp to scrape YouTube video metadata based on a search query.
Outputs structured JSON results.
"""

import argparse
import json
import sys

import yt_dlp


def scrape_youtube(query: str, max_results: int = 25, output_format: str = "json") -> list[dict]:
    """
    Search YouTube and return video metadata.

    Args:
        query: Search term or topic
        max_results: Maximum number of videos to retrieve (default 25)
        output_format: 'json' or 'text'

    Returns:
        List of dicts with video metadata
    """
    search_url = f"ytsearch{max_results}:{query}"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "ignoreerrors": True,
    }

    videos = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_url, download=False)

        if not info or "entries" not in info:
            return []

        for entry in info["entries"]:
            if not entry:
                continue

            video_id = entry.get("id", "")
            url = f"https://www.youtube.com/watch?v={video_id}" if video_id else entry.get("url", "")

            duration_secs = entry.get("duration")
            if duration_secs:
                mins, secs = divmod(int(duration_secs), 60)
                hrs, mins = divmod(mins, 60)
                if hrs:
                    duration_str = f"{hrs}:{mins:02d}:{secs:02d}"
                else:
                    duration_str = f"{mins}:{secs:02d}"
            else:
                duration_str = "N/A"

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

            videos.append({
                "rank": len(videos) + 1,
                "title": entry.get("title", "Unknown Title"),
                "author": entry.get("uploader") or entry.get("channel", "Unknown"),
                "views": views_str,
                "views_raw": view_count,
                "duration": duration_str,
                "url": url,
                "video_id": video_id,
                "description": (entry.get("description") or "")[:200],
                "upload_date": entry.get("upload_date", ""),
                "live_status": entry.get("live_status", ""),
            })

    return videos


def format_text_output(videos: list[dict], query: str) -> str:
    """Format results as readable text."""
    lines = [
        f"YouTube Research Results: '{query}'",
        f"Found {len(videos)} videos",
        "=" * 60,
        "",
    ]

    for v in videos:
        lines.append(f"#{v['rank']}. {v['title']}")
        lines.append(f"   Author:   {v['author']}")
        lines.append(f"   Views:    {v['views']}")
        lines.append(f"   Duration: {v['duration']}")
        lines.append(f"   URL:      {v['url']}")
        if v["description"]:
            lines.append(f"   Desc:     {v['description'][:100]}...")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Search YouTube and return video metadata",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python yt_research.py "machine learning tutorials" --max 10
  python yt_research.py "Python programming" --max 25 --format text
  python yt_research.py "AI news 2025" --max 5 --format json
        """,
    )
    parser.add_argument("query", help="YouTube search query or topic")
    parser.add_argument(
        "--max",
        "-n",
        type=int,
        default=25,
        metavar="N",
        help="Maximum number of results (default: 25)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["json", "text"],
        default="json",
        help="Output format: json (default) or text",
    )

    args = parser.parse_args()

    if args.max < 1 or args.max > 50:
        print("Error: --max must be between 1 and 50", file=sys.stderr)
        sys.exit(1)

    videos = scrape_youtube(args.query, args.max)

    if not videos:
        print(json.dumps({"error": "No results found", "query": args.query}))
        sys.exit(1)

    if args.format == "text":
        print(format_text_output(videos, args.query))
    else:
        result = {
            "query": args.query,
            "count": len(videos),
            "videos": videos,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
