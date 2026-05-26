#!/usr/bin/env python3
"""
========================================================================
THE ASSORTMENT — publish.py
========================================================================
ONE command that takes your private master file and prepares everything
for the web.

WHAT IT DOES, IN ORDER:
  1. Reads data.private.js (your master — local paths + meanings)
  2. Finds every media file referenced (visuals + audio)
  3. Uploads any file NOT already in your B2 bucket (skips duplicates)
  4. Builds data.public.js where:
        - every local media path is replaced with its public CDN URL
        - every `meaning` field is removed entirely
  5. Leaves data.private.js completely untouched

WHAT YOU DO AFTER:
  - git add / commit / push   (deploys data.public.js + site to Vercel)
  - data.private.js never gets pushed (it's in .gitignore)

------------------------------------------------------------------------
ONE-TIME SETUP (do this once, before first run):

  1. Install the libraries:
        pip install b2sdk python-dotenv --break-system-packages

  2. Create a file called  .env  in the project root with:

        B2_KEY_ID=your_application_key_id
        B2_APP_KEY=your_application_key
        B2_BUCKET=theassortment-media
        CDN_BASE=https://media.samarthgoradia.com

     (You'll get these values from the Day 1 guide — B2 dashboard
      gives you the first three, Cloudflare setup gives you CDN_BASE.)

  3. Make sure .env and data.private.js are in .gitignore (the guide
     provides the .gitignore file).

------------------------------------------------------------------------
RUN IT:
        python publish.py

        # Preview what WOULD happen without uploading or writing:
        python publish.py --dry-run
========================================================================
"""

import os
import re
import sys
import json
import hashlib
from pathlib import Path

# ── Third-party libs (installed in one-time setup) ─────────────────────
try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("Missing dependency. Run: pip install python-dotenv --break-system-packages")

try:
    from b2sdk.v2 import InMemoryAccountInfo, B2Api
except ImportError:
    sys.exit("Missing dependency. Run: pip install b2sdk --break-system-packages")


# ── Configuration ──────────────────────────────────────────────────────
load_dotenv()  # reads the .env file into environment variables

B2_KEY_ID  = os.getenv("B2_KEY_ID")
B2_APP_KEY = os.getenv("B2_APP_KEY")
B2_BUCKET  = os.getenv("B2_BUCKET")
CDN_BASE   = os.getenv("CDN_BASE", "").rstrip("/")

# Local folders that hold your media (relative to this script).
# Your data.js uses "../visuals/..." and "../audio/..." — but this script
# sits in the project root alongside those folders, so we look for them
# both with and without the "../" prefix.
LOCAL_MEDIA_DIRS = ["visuals", "audio", "../visuals", "../audio"]

PRIVATE_FILE = "data.private.js"
PUBLIC_FILE  = "data.public.js"

DRY_RUN = "--dry-run" in sys.argv


# ── Helpers ─────────────────────────────────────────────────────────────

def fail(msg):
    sys.exit(f"\n  ERROR: {msg}\n")


def check_config():
    """Make sure the .env values are present before we do anything."""
    missing = [k for k, v in {
        "B2_KEY_ID": B2_KEY_ID,
        "B2_APP_KEY": B2_APP_KEY,
        "B2_BUCKET": B2_BUCKET,
        "CDN_BASE": CDN_BASE,
    }.items() if not v]
    if missing:
        fail("Missing in .env: " + ", ".join(missing))


def find_local_file(referenced_path):
    """
    Given a path from data.js like "../visuals/sparks.jpg", find the actual
    file on disk. Returns a Path object, or None if not found.
    We only care about the filename — we search our known media folders.
    """
    filename = os.path.basename(referenced_path)
    for d in LOCAL_MEDIA_DIRS:
        candidate = Path(d) / filename
        if candidate.exists():
            return candidate
    return None


def b2_object_key(local_path):
    """
    The 'key' (path inside the bucket) we store the file under.
    We preserve the folder structure: visuals/sparks.jpg or audio/song.mp3
    so the bucket stays organised.
    """
    parent = local_path.parent.name  # "visuals" or "audio"
    return f"{parent}/{local_path.name}"


def cdn_url_for(object_key):
    """The final public URL a browser will use to fetch this file."""
    # URL-encode spaces and special chars in filenames so links don't break
    from urllib.parse import quote
    safe_key = "/".join(quote(part) for part in object_key.split("/"))
    return f"{CDN_BASE}/{safe_key}"


def connect_b2():
    """Authenticate with Backblaze and return the bucket object."""
    info = InMemoryAccountInfo()
    api = B2Api(info)
    api.authorize_account("production", B2_KEY_ID, B2_APP_KEY)
    return api.get_bucket_by_name(B2_BUCKET)


def get_existing_keys(bucket):
    """
    List filenames already in the bucket so we never re-upload.
    Returns a set of object keys like {"visuals/sparks.jpg", ...}.
    """
    existing = set()
    for file_version, _ in bucket.ls(recursive=True):
        existing.add(file_version.file_name)
    return existing


# ── Step 1: extract every media path referenced in data.private.js ───────

def extract_media_paths(text):
    """
    Pull out the value of every `media:` and `audio:` field.
    Returns a list of (field_value, full_match) — we keep the raw matched
    string so we can do an exact replacement later.
    Skips null values.
    """
    # Matches:  media:  "../visuals/sparks.jpg"   and   audio: "../audio/x.mp3"
    pattern = re.compile(r'(media|audio)\s*:\s*"([^"]+)"')
    results = []
    for m in pattern.finditer(text):
        field = m.group(1)
        value = m.group(2)
        results.append((field, value))
    return results


# ── Step 2: strip the meaning field for the public file ──────────────────

def strip_meaning(text):
    """
    Remove every `meaning: "..."` line from the file content.
    Handles meanings that contain escaped quotes and span the whole value.
    Also removes a trailing comma/newline left behind cleanly.
    """
    # Matches:  meaning: "....",  (including the optional trailing comma)
    # The [^"\\]*(?:\\.[^"\\]*)* part safely matches escaped quotes inside.
    pattern = re.compile(
        r'\n?\s*meaning\s*:\s*"(?:[^"\\]|\\.)*"\s*,?',
        re.DOTALL
    )
    cleaned = pattern.sub("", text)
    return cleaned


def fix_trailing_commas(text):
    """
    After removing meaning (often the last field in an entry), an entry
    might end with:  ...placeholderColor: "#abc",\n  }
    which is fine. But if meaning was NOT last, removal is clean anyway.
    This is a safety pass to remove any ", }" -> " }" artifacts.
    """
    text = re.sub(r',(\s*})', r'\1', text)   # ", }" -> " }"
    text = re.sub(r',(\s*\])', r'\1', text)  # ", ]" -> " ]"
    return text


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  THE ASSORTMENT — publish")
    if DRY_RUN:
        print("  (DRY RUN — nothing will be uploaded or written)")
    print("=" * 60)

    if not Path(PRIVATE_FILE).exists():
        fail(f"{PRIVATE_FILE} not found. Run this from the project root.")

    check_config()

    # --- Read the master file ---
    private_text = Path(PRIVATE_FILE).read_text(encoding="utf-8")
    media_refs = extract_media_paths(private_text)
    print(f"\n  Found {len(media_refs)} media references in {PRIVATE_FILE}.")

    # --- Map each referenced path to its local file + intended bucket key ---
    # path_map:  referenced_value -> (local_path, object_key, cdn_url)
    path_map = {}
    missing_files = []
    for field, value in media_refs:
        local = find_local_file(value)
        if local is None:
            missing_files.append(value)
            continue
        key = b2_object_key(local)
        path_map[value] = (local, key, cdn_url_for(key))

    if missing_files:
        print("\n  WARNING — these referenced files were not found locally:")
        for mf in missing_files:
            print(f"      {mf}")
        print("  They will be left as-is in the public file.")

    # --- Connect to B2 and see what's already uploaded ---
    if not DRY_RUN:
        print("\n  Connecting to Backblaze B2...")
        bucket = connect_b2()
        existing = get_existing_keys(bucket)
        print(f"  Bucket already contains {len(existing)} files.")
    else:
        bucket = None
        existing = set()

    # --- Upload the new ones ---
    uploaded, skipped = 0, 0
    for value, (local, key, url) in path_map.items():
        if key in existing:
            skipped += 1
            continue
        if DRY_RUN:
            print(f"  [dry-run] would upload: {local}  ->  {key}")
            uploaded += 1
            continue
        print(f"  Uploading: {local}  ->  {key}")
        bucket.upload_local_file(local_file=str(local), file_name=key)
        uploaded += 1

    print(f"\n  Uploaded: {uploaded}   Skipped (already present): {skipped}")

    # --- Build the public file ---
    public_text = private_text

    # Replace each local media path with its CDN URL.
    # We replace the exact quoted string to avoid touching anything else.
    for value, (local, key, url) in path_map.items():
        public_text = public_text.replace(f'"{value}"', f'"{url}"')

    # Strip the private meaning fields.
    public_text = strip_meaning(public_text)
    public_text = fix_trailing_commas(public_text)

    # Remove the original leading /** ... */ documentation block (it
    # describes the meaning field and the private workflow — not needed
    # publicly). We only strip the FIRST block, which is the file header.
    public_text = re.sub(r'^\s*/\*\*.*?\*/\s*', "", public_text, count=1, flags=re.DOTALL)

    # Remove the TEMPLATE comment block at the bottom too, if present
    # (it also documents the meaning field).
    public_text = re.sub(r'/\*\s*─+\s*TEMPLATE.*?\*/\s*$', "", public_text, flags=re.DOTALL)

    # Add a header note so it's obvious this file is generated.
    header = (
        "/* ====================================================\n"
        " * data.public.js  —  AUTO-GENERATED by publish.py\n"
        " * DO NOT EDIT THIS FILE BY HAND.\n"
        " * Edit data.private.js and re-run:  python publish.py\n"
        " * (meanings stripped · media paths point to the CDN)\n"
        " * ==================================================== */\n\n"
    )
    public_text = header + public_text.lstrip()

    if DRY_RUN:
        print(f"\n  [dry-run] would write {PUBLIC_FILE} "
              f"({len(public_text)} chars, meanings stripped).")
        print("\n  Dry run complete.\n")
        return

    Path(PUBLIC_FILE).write_text(public_text, encoding="utf-8")
    print(f"\n  Wrote {PUBLIC_FILE}  (meanings stripped, CDN URLs injected).")

    # --- Final sanity check: make sure no real 'meaning:' field leaked ---
    # We look for an actual data field (meaning : "...") not the word in a
    # comment, so the header documentation doesn't trigger a false alarm.
    leak = re.search(r'meaning\s*:\s*"', Path(PUBLIC_FILE).read_text(encoding="utf-8"))
    if leak:
        print("\n  !!  WARNING: a 'meaning:' field still appears in "
              f"{PUBLIC_FILE}. Inspect it before pushing.")
    else:
        print("  Verified: no 'meaning:' field present in public file.")

    print("\n  Next:  git add . && git commit -m 'new entries' && git push\n")


if __name__ == "__main__":
    main()