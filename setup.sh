#!/usr/bin/env bash
# Setup script for YouTube → NotebookLM Research Pipeline
# Installs all required dependencies with correct versions.

set -e

echo "Installing yt-dlp..."
pip install yt-dlp --quiet

echo "Installing notebooklm-py with browser support..."
pip install "notebooklm-py[browser]" --quiet

# Pin playwright to the version that matches the pre-installed Chromium (1194).
# playwright 1.56.x targets chromium-1194; newer versions require a different revision.
echo "Installing playwright 1.56.0 (matches pre-installed Chromium 1194)..."
pip install "playwright==1.56.0" --quiet

echo "Installing Chromium browser..."
playwright install chromium

echo "Installing notebooklm skill for Claude Code..."
notebooklm skill install

echo ""
echo "Setup complete!"
echo ""
echo "Next step: authenticate with Google NotebookLM."
echo ""
echo "  Option A – headed browser (requires a display or VNC):"
echo "    notebooklm login"
echo ""
echo "  Option B – virtual framebuffer (headless, interactive via VNC):"
echo "    xvfb-run --auto-servernum notebooklm login"
echo ""
echo "  Option C – supply existing credentials:"
echo "    Copy storage_state.json from a machine where you've logged in to:"
echo "    ~/.notebooklm/storage_state.json"
echo "    Or set: export NOTEBOOKLM_AUTH_JSON='\$(cat storage_state.json)'"
echo ""
echo "Verify auth after login:"
echo "    notebooklm auth check --test"
