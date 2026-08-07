"""
ingest.py — LLM Wiki ingest script for JARVIS

Usage:
    python ingest.py <file_in_raw/>

What it does:
    1. Reads the source file from raw/
    2. Reads all current wiki/*.md files
    3. Asks the Groq LLM which wiki files need updating and what to change
    4. Writes the updated wiki files back to disk
    5. Moves the processed file to raw/processed/

Run manually whenever you have new material to absorb into the wiki.
"""

import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent if APP_DIR.name == "backend" else APP_DIR
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"

env_file = PROJECT_ROOT / "config" / ".env"
load_dotenv(env_file if env_file.exists() else PROJECT_ROOT / ".env")

WIKI_DIR      = DATA_DIR / "wiki"
PROCESSED_DIR = RAW_DIR / "processed"
PROCESSED_DIR.mkdir(exist_ok=True)

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_MODEL   = os.getenv("GROK_MODEL", "llama-3.3-70b-versatile")

if not GROK_API_KEY:
    sys.exit("GROK_API_KEY not set in .env")

client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.groq.com/openai/v1")


def read_wiki() -> dict[str, str]:
    """Return {filename: content} for all wiki .md files."""
    result = {}
    for f in sorted(WIKI_DIR.glob("*.md")):
        result[f.name] = f.read_text(encoding="utf-8")
    return result


def build_ingest_prompt(source_text: str, wiki: dict[str, str]) -> str:
    wiki_dump = "\n\n".join(
        f"=== {name} ===\n{content}" for name, content in wiki.items()
    )
    return f"""You are a knowledge curator for a JARVIS voice AI assistant.
The assistant has a wiki folder with these files:
{wiki_dump}

A new source document has been dropped into the inbox:
=== SOURCE ===
{source_text}

Your job:
1. Identify which wiki files should be updated based on the source document.
2. For each file that needs updating, return the COMPLETE new content of that file (not a diff).
3. Only update files where the source contains genuinely new or corrected information.
4. Fill in any <!-- TODO: --> placeholders you can resolve from the source.
5. Do NOT invent information not present in the source.

Respond with ONLY valid JSON in this exact format:
{{
  "updates": [
    {{
      "file": "me.md",
      "content": "... full new content of me.md ..."
    }},
    {{
      "file": "projects.md",
      "content": "... full new content of projects.md ..."
    }}
  ],
  "summary": "One sentence describing what was updated and why."
}}

If nothing needs updating, return: {{"updates": [], "summary": "No new information found."}}"""


def main():
    if len(sys.argv) < 2:
        # List available files if no argument given
        files = [f for f in RAW_DIR.iterdir() if f.is_file() and f.name != ".gitkeep"]
        if not files:
            print("No files in raw/ to process.")
            print("Drop a file into raw/ and run:  python ingest.py <filename>")
        else:
            print("Files available in raw/:")
            for f in files:
                print(f"  {f.name}")
            print(f"\nUsage: python ingest.py <filename>")
        sys.exit(0)

    source_path = RAW_DIR / sys.argv[1]
    if not source_path.exists():
        # Try as full path
        source_path = Path(sys.argv[1])
    if not source_path.exists():
        sys.exit(f"File not found: {sys.argv[1]}")

    print(f"Reading source: {source_path.name}")
    source_text = source_path.read_text(encoding="utf-8", errors="replace")

    print("Reading wiki...")
    wiki = read_wiki()
    if not wiki:
        sys.exit("No wiki files found. Run from the jarvis/ root directory.")

    print(f"Sending to {GROK_MODEL}...")
    prompt = build_ingest_prompt(source_text, wiki)

    response = client.chat.completions.create(
        model=GROK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
        temperature=0.2,
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Failed to parse LLM response as JSON: {e}")
        print("Raw response:")
        print(raw)
        sys.exit(1)

    updates = result.get("updates", [])
    summary = result.get("summary", "")

    if not updates:
        print(f"Nothing to update. {summary}")
    else:
        for update in updates:
            fname = update["file"]
            content = update["content"]
            target = WIKI_DIR / fname
            target.write_text(content, encoding="utf-8")
            print(f"  Updated: {fname}")
        print(f"\nSummary: {summary}")

    # Move processed file
    dest = PROCESSED_DIR / source_path.name
    shutil.move(str(source_path), str(dest))
    print(f"\nMoved to: raw/processed/{source_path.name}")


if __name__ == "__main__":
    main()
