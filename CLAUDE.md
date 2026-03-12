# YouTube → NotebookLM Research Pipeline

Automated research pipeline connecting Claude Code to Google NotebookLM via YouTube metadata scraping.

## Quick Start

> **Authentication required before first use.** See [Authentication](#authentication) below.

```
Use the yt-research skill to find the 25 latest trending videos on [YOUR TOPIC].
Once we have those videos, send them over to NotebookLM using the notebooklm skill.
Give me its analysis on the top findings, then have NotebookLM create an infographic
in a handwritten / chalkboard style depicting that analysis.
```

If you give that command **without a topic**, Claude will ask:
> "What topic would you like me to research on YouTube?"

---

## Skills

### `yt-research` — YouTube Metadata Scraper

Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp). Searches YouTube and returns structured metadata for each result.

**Activation phrases:**
- `/yt-research`
- "find YouTube videos about [topic]"
- "search YouTube for [topic]"
- "find the top/latest/trending videos on [topic]"
- "use the yt-research skill"

**Underlying script:** `yt_research.py`

```bash
# Basic usage
python yt_research.py "machine learning 2025"

# Custom count + text output
python yt_research.py "Python tutorials" --max 10 --format text

# JSON output (default)
python yt_research.py "AI news" --max 25
```

**Returns per video:** title, author/channel, views, duration, URL, video ID, description snippet, upload date.

---

### `notebooklm` — Google NotebookLM Integration

Powered by [notebooklm-py](https://github.com/teng-lin/notebooklm-py) (unofficial API). Full programmatic access to NotebookLM.

**Activation phrases:**
- `/notebooklm`
- "create a podcast about X"
- "add these to NotebookLM"
- "generate an infographic"
- "make flashcards from my research"

**Key commands:**
```bash
notebooklm create "Research: [topic]"          # Create notebook
notebooklm source add "https://youtube.com/…"  # Add YouTube source
notebooklm ask "What are the top findings?"    # Chat with content
notebooklm generate infographic --style sketch-note  # Chalkboard style
notebooklm generate slide-deck                  # Slide deck
notebooklm generate flashcards                  # Flashcards
notebooklm artifact list                        # Check generation status
notebooklm download infographic ./output.png    # Download result
```

---

### Combined Pipeline Script: `yt_to_notebooklm.py`

Runs the full YouTube-to-NotebookLM pipeline in one command:

```bash
python yt_to_notebooklm.py "your topic" --max 25
```

Options:
| Flag | Default | Description |
|------|---------|-------------|
| `--max N` | 25 | Number of YouTube results |
| `--title "..."` | Auto-generated | Custom notebook title |
| `--delay N` | 1.0 | Seconds between source uploads |
| `--json` | off | Print full summary as JSON |

---

## Authentication

### First-Time Setup

NotebookLM requires Google OAuth authentication. **This must be done once in a separate terminal:**

```bash
# Open a NEW terminal window and run:
notebooklm login
```

This opens a browser window for Google sign-in. After authenticating, credentials are saved to `~/.notebooklm/storage_state.json` and reused automatically.

### Verify Authentication

```bash
notebooklm status        # Should show "Authenticated as: your@email.com"
notebooklm list --json   # Should return valid JSON
```

If either fails, re-run `notebooklm login`.

---

## Example Workflows

### 1. Full Research-to-Infographic Pipeline

```
"Use the yt-research skill to find the 25 latest trending videos on quantum computing.
Once we have those videos, send them over to NotebookLM using the notebooklm skill.
Give me its analysis on the top findings, then create an infographic in a
handwritten / chalkboard style."
```

Claude will:
1. Run `yt_research.py "quantum computing" --max 25`
2. Create a NotebookLM notebook
3. Add all YouTube URLs as sources
4. Wait for indexing
5. Ask NotebookLM for analysis
6. Generate infographic with `--style sketch-note` (chalkboard style)

### 2. Research Only

```
"Find me the top 10 YouTube videos on climate change."
```

### 3. NotebookLM Only (existing notebook)

```
"Generate flashcards from my current NotebookLM notebook."
```

---

## Infographic Styles

For the chalkboard/handwritten style, use:
```bash
notebooklm generate infographic --style sketch-note
```

All available styles:
| Style | Description |
|-------|-------------|
| `sketch-note` | Handwritten / chalkboard look |
| `professional` | Clean, corporate style |
| `bento-grid` | Modern card layout |
| `editorial` | Magazine-style layout |
| `instructional` | Educational diagram style |
| `bricks` | Block-based layout |
| `clay` | 3D clay-render aesthetic |
| `anime` | Anime-inspired illustration |
| `kawaii` | Cute/playful Japanese style |
| `scientific` | Academic diagram style |

---

## Installed Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `yt-dlp` | 2026.3.3+ | YouTube metadata scraping |
| `notebooklm-py` | 0.3.4+ | NotebookLM Python API |
| `playwright` | latest | Browser-based authentication |
| Chromium | latest | OAuth login browser |

### Reinstall if needed:
```bash
pip install yt-dlp
pip install "notebooklm-py[browser]"
playwright install chromium
notebooklm skill install
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Auth error | Run `notebooklm login` in a new terminal |
| No YouTube results | Try a different/broader search query |
| Source add fails | Check auth; retry after a moment |
| Infographic generation fails | Rate limit—wait 5–10 min and retry |
| `notebooklm` not found | Run `pip install notebooklm-py` |
| `yt_dlp` not found | Run `pip install yt-dlp` |

For detailed error diagnosis:
```bash
notebooklm auth check --test
notebooklm --version
python -c "import yt_dlp; print(yt_dlp.version.__version__)"
```
