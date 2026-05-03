#!/usr/bin/env bash
# Setup script for deploying this pipeline on a new machine.
set -euo pipefail

cd "$(dirname "$0")"

echo "1. Installing Python dependencies..."
pip3 install --user youtube-transcript-api

echo ""
echo "2. Creating credentials.env (mode 600)..."
if [ ! -f credentials.env ]; then
  cp credentials.env.example credentials.env
  chmod 600 credentials.env
  echo "   Created credentials.env from example. EDIT IT to fill in real values."
else
  echo "   credentials.env already exists; not overwriting."
fi

echo ""
echo "3. Creating runtime directories..."
mkdir -p runs backups data

echo ""
echo "4. Installing Claude Code skill..."
SKILL_DIR="$HOME/.claude/skills/dr-meir-content-update"
mkdir -p "$SKILL_DIR"
cp skills/dr-meir-content-update/SKILL.md "$SKILL_DIR/SKILL.md"
echo "   Installed at $SKILL_DIR/SKILL.md"

echo ""
echo "Done. Next steps:"
echo "  - Edit credentials.env with your WordPress App Password"
echo "  - Test: python3 seo_pipeline.py list"
echo "  - Read: SKILL.md and README.md"
