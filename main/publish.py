#!/usr/bin/env python3
"""
========================================================================
THE ASSORTMENT - publish.py
========================================================================
ONE command that takes your private master file and prepares everything
for the web.

WHAT IT DOES, IN ORDER:
  1. Reads data.private.js (your master - local paths + meanings)
  2. For every entry:
        - AUDIO: cuts the [audioStart, audioEnd] slice into a small,
          loudness-normalised clip (EBU R128, two-pass, -14 LUFS, 128 kbps)
          so the browser downloads ~200KB and plays instantly - instead of
          shipping a whole 7-18MB song and seeking into it.
        - VIDEO: remuxes with +faststart (lossless, no re-encode) so the
          moov atom is at the front and it streams from the first byte.
        - IMAGE: uploaded as-is.
  3. Uploads any processed/needed file NOT already in your B2 bucket.
  4. Builds data.public.js where:
        - audio  -> the small clip URL, audioStart -> 0, audioEnd -> clip length
        - video  -> the faststart clip URL
        - image  -> its public CDN URL
        - every `meaning` field is removed entirely
  5. Leaves data.private.js completely untouched.

  Processed files are cached locally (audio/clips/, visuals/web/) and in the
  bucket, so re-runs only touch new or re-trimmed entries.

WHAT YOU DO AFTER:
  - git add / commit / push   (deploys data.public.js + site to Vercel)
  - data.private.js never gets pushed (it's in .gitignore)

------------------------------------------------------------------------
ONE-TIME SETUP (do this once, before first run):

  1. Install the libraries:
        pip install b2sdk python-dotenv --break-system-packages

  2. Install ffmpeg (provides ffmpeg + ffprobe):
        brew install ffmpeg          # macOS

  3. Create a file called  .env  in the project root with:

        B2_KEY_ID=your_application_key_id
        B2_APP_KEY=your_application_key
        B2_BUCKET=theassortment-media
        CDN_BASE=https://media.samarthgoradia.com

  4. Make sure .env and data.private.js are in .gitignore.

------------------------------------------------------------------------
RUN IT (from the main/ folder, where data.private.js lives):
        python publish.py

        # Preview what WOULD happen without processing, uploading or writing:
        python publish.py --dry-run

        # Also delete bucket files the site no longer references (old full
        # songs, superseded clips, the non-faststart video) so B2 stays clean:
        python publish.py --prune-orphans

        # See exactly what prune WOULD delete first, deleting nothing:
        python publish.py --prune-orphans --dry-run
========================================================================
"""

import os
import re
import sys
import json
import shutil
import subprocess
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

# Local folders that hold your media (relative to this script's run dir).
LOCAL_MEDIA_DIRS = ["visuals", "audio", "../visuals", "../audio"]

PRIVATE_FILE = "data.private.js"
PUBLIC_FILE  = "data.public.js"

# ── Audio clip settings (EBU R128 two-pass loudness normalisation) ──────
LOUDNORM_I    = -14    # integrated loudness target (LUFS) - streaming standard
LOUDNORM_TP   = -1.5   # max true peak (dBTP) - headroom against clipping
LOUDNORM_LRA  = 11     # loudness range
AUDIO_BITRATE = "128k"

DRY_RUN = "--dry-run" in sys.argv
PRUNE   = "--prune-orphans" in sys.argv

# Prune only ever touches keys under these prefixes - a safety rail so a bug
# could never delete anything outside the media folders this script manages.
MANAGED_PREFIXES = ("visuals/", "audio/")


# ── Helpers ─────────────────────────────────────────────────────────────

def fail(msg):
    sys.exit(f"\n  ERROR: {msg}\n")


def check_config():
    """Make sure the .env values and ffmpeg are present before we do anything."""
    missing = [k for k, v in {
        "B2_KEY_ID": B2_KEY_ID,
        "B2_APP_KEY": B2_APP_KEY,
        "B2_BUCKET": B2_BUCKET,
        "CDN_BASE": CDN_BASE,
    }.items() if not v]
    if missing:
        fail("Missing in .env: " + ", ".join(missing))

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            fail(f"'{tool}' not found on PATH. Install it (macOS: brew install ffmpeg).")


def find_local_file(referenced_path):
    """
    Given a path from data.js like "../visuals/sparks.jpg", find the actual
    file on disk. Returns a Path object, or None if not found.
    """
    filename = os.path.basename(referenced_path)
    for d in LOCAL_MEDIA_DIRS:
        candidate = Path(d) / filename
        if candidate.exists():
            return candidate
    return None


def b2_object_key(local_path):
    """Bucket key that preserves folder structure: visuals/sparks.jpg etc."""
    parent = local_path.parent.name  # "visuals" or "audio"
    return f"{parent}/{local_path.name}"


def cdn_url_for(object_key):
    """The final public URL a browser will use to fetch this file."""
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
    """Set of object keys already in the bucket, so we never re-upload."""
    existing = set()
    for file_version, _ in bucket.ls(recursive=True):
        existing.add(file_version.file_name)
    return existing


# ── ffmpeg / ffprobe ─────────────────────────────────────────────────────

def probe_duration(path):
    """Return the duration of a media file in seconds (float, 2dp)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return round(float(out.stdout.strip()), 2)
    except ValueError:
        return None


def _seek_args(start, end):
    args = ["-ss", str(start)]
    if end is not None:
        args += ["-to", str(end)]
    return args


def _parse_loudnorm_json(stderr):
    """Pull the loudnorm measurement JSON ffmpeg prints to stderr (pass 1)."""
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', stderr, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    # Silence / unmeasurable input -> skip the linear (measured) second pass.
    if str(d.get("input_i")).lstrip("-").lower() == "inf":
        return None
    return d


def make_audio_clip(src, start, end, out_path):
    """
    Two-pass EBU R128 loudness-normalised trim of [start, end] from `src`.
    The SAME seek window is used in both passes so the measurement matches
    the clip exactly (we never normalise to the whole song's loudness).
    """
    seek = _seek_args(start, end)
    af_base = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"

    # Pass 1 - measure the clip's loudness.
    p1 = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", *seek, "-i", str(src),
         "-af", af_base + ":print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    stats = _parse_loudnorm_json(p1.stderr)

    af = af_base
    if stats:
        af += (
            f":measured_I={stats['input_i']}"
            f":measured_TP={stats['input_tp']}"
            f":measured_LRA={stats['input_lra']}"
            f":measured_thresh={stats['input_thresh']}"
            f":offset={stats['target_offset']}:linear=true"
        )

    # Pass 2 - apply, encode the small clip.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    p2 = subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", *seek, "-i", str(src),
         "-af", af, "-c:a", "libmp3lame", "-b:a", AUDIO_BITRATE, str(out_path)],
        capture_output=True, text=True,
    )
    if p2.returncode != 0:
        raise RuntimeError(f"ffmpeg trim failed for {src}:\n{p2.stderr[-600:]}")


def make_faststart(src, out_path):
    """Lossless remux moving the moov atom to the front (instant streaming)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-i", str(src),
         "-c", "copy", "-movflags", "+faststart", str(out_path)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg faststart failed for {src}:\n{p.stderr[-600:]}")


def _fmt_t(v):
    """Format a seconds value for use inside a filename (3.5 -> '3p5')."""
    if v is None:
        return "end"
    return f"{v:g}".replace(".", "p")


# ── Entry parsing ─────────────────────────────────────────────────────────

ENTRY_ID_RE = re.compile(r'\bid:\s*(\d+)')


def entry_blocks(text):
    """
    Split the file into per-entry text blocks using `id:` as the delimiter.
    Returns [(id, start_idx, end_idx, block_text), ...]. Splitting on the id
    marker (rather than matching braces) is robust to `}` inside meanings.
    """
    matches = list(ENTRY_ID_RE.finditer(text))
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((int(m.group(1)), start, end, text[start:end]))
    return blocks


def field_str(block, name):
    """Value of a quoted string field, or None if it's null/absent."""
    m = re.search(rf'\b{name}:\s*"((?:[^"\\]|\\.)*)"', block)
    return m.group(1) if m else None


def field_num(block, name, default=None):
    """Value of a numeric field, or `default` if it's null/absent."""
    m = re.search(rf'\b{name}:\s*(-?\d+(?:\.\d+)?)', block)
    return float(m.group(1)) if m else default


# ── Public-file rebuild (per-entry, leaves private file untouched) ────────

def replace_field_string(block, name, value):
    return re.sub(
        rf'(\b{name}:\s*")(?:[^"\\]|\\.)*(")',
        lambda m: m.group(1) + value + m.group(2),
        block, count=1,
    )


def replace_field_number(block, name, value):
    return re.sub(
        rf'(\b{name}:\s*)(?:null|-?\d+(?:\.\d+)?)',
        lambda m: m.group(1) + f"{value:g}",
        block, count=1,
    )


def strip_meaning(text):
    """Remove every `meaning: "..."` field (handles escaped quotes)."""
    pattern = re.compile(r'\n?\s*meaning\s*:\s*"(?:[^"\\]|\\.)*"\s*,?', re.DOTALL)
    return pattern.sub("", text)


def fix_trailing_commas(text):
    text = re.sub(r',(\s*})', r'\1', text)
    text = re.sub(r',(\s*\])', r'\1', text)
    return text


HEADER = (
    "/* ====================================================\n"
    " * data.public.js  -  AUTO-GENERATED by publish.py\n"
    " * DO NOT EDIT THIS FILE BY HAND.\n"
    " * Edit data.private.js and re-run:  python publish.py\n"
    " * (meanings stripped · media -> CDN · audio -> trimmed clips)\n"
    " * ==================================================== */\n\n"
)


def build_public(private_text, transforms):
    """
    Rebuild the public file from the private text, applying per-entry
    transforms: id -> {media_url, audio_url, audio_start, audio_end}.
    """
    blocks = entry_blocks(private_text)
    if not blocks:
        fail("Could not find any entries (no `id:` fields) in the private file.")

    out = [private_text[:blocks[0][1]]]  # preamble (doc comment + `const ENTRIES = [`)
    for eid, _start, _end, block in blocks:
        t = transforms.get(eid)
        if t:
            if t.get("media_url"):
                block = replace_field_string(block, "media", t["media_url"])
            if t.get("audio_url"):
                block = replace_field_string(block, "audio", t["audio_url"])
                block = replace_field_number(block, "audioStart", t["audio_start"])
                if t.get("audio_end") is not None:
                    block = replace_field_number(block, "audioEnd", t["audio_end"])
        out.append(block)

    text = "".join(out)
    text = strip_meaning(text)
    text = fix_trailing_commas(text)
    # Drop the leading /** ... */ doc block and any trailing TEMPLATE block.
    text = re.sub(r'^\s*/\*\*.*?\*/\s*', "", text, count=1, flags=re.DOTALL)
    text = re.sub(r'/\*\s*─+\s*TEMPLATE.*?\*/\s*$', "", text, flags=re.DOTALL)
    return HEADER + text.lstrip()


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  THE ASSORTMENT - publish")
    if DRY_RUN:
        print("  (DRY RUN - nothing processed, uploaded or written)")
    print("=" * 60)

    if not Path(PRIVATE_FILE).exists():
        fail(f"{PRIVATE_FILE} not found. Run this from the folder it lives in.")

    check_config()

    private_text = Path(PRIVATE_FILE).read_text(encoding="utf-8")
    blocks = entry_blocks(private_text)
    print(f"\n  Found {len(blocks)} entries in {PRIVATE_FILE}.")

    # --- Connect to B2 (so we can skip files already uploaded) ---
    # We need the bucket for a real run, and also for --prune-orphans (even in
    # dry-run, so we can *list* what would be deleted without deleting it).
    if not DRY_RUN or PRUNE:
        print("\n  Connecting to Backblaze B2...")
        bucket = connect_b2()
        existing = get_existing_keys(bucket)
        print(f"  Bucket already contains {len(existing)} files.")
    else:
        bucket, existing = None, set()

    counts = {"uploaded": 0, "skipped": 0, "trimmed": 0, "faststart": 0, "cached": 0}
    warnings = []
    transforms = {}
    wanted_keys = set()  # every bucket key the site needs after this run

    def ensure_uploaded(local_path, key):
        """Upload `local_path` under `key` unless already present. Returns CDN url."""
        wanted_keys.add(key)
        url = cdn_url_for(key)
        if key in existing:
            counts["skipped"] += 1
            return url
        if DRY_RUN:
            print(f"  [dry-run] would upload: {local_path}  ->  {key}")
            counts["uploaded"] += 1
            return url
        print(f"  Uploading: {key}")
        bucket.upload_local_file(local_file=str(local_path), file_name=key)
        existing.add(key)
        counts["uploaded"] += 1
        return url

    for eid, _s, _e, block in blocks:
        mtype = field_str(block, "mediaType")
        media = field_str(block, "media")
        audio = field_str(block, "audio")
        a_start = field_num(block, "audioStart", 0) or 0
        a_end = field_num(block, "audioEnd", None)

        t = {}

        # ----- VISUAL -----
        if media:
            local = find_local_file(media)
            if local is None:
                warnings.append(f"entry {eid}: media not found locally ({media})")
            elif mtype == "video":
                out = local.parent / "web" / local.name
                key = f"visuals/web/{local.name}"
                if not out.exists() and not DRY_RUN:
                    print(f"  Faststart: entry {eid} ({local.name})")
                    make_faststart(local, out)
                    counts["faststart"] += 1
                elif out.exists():
                    counts["cached"] += 1
                elif DRY_RUN:
                    print(f"  [dry-run] would faststart: {local.name}")
                    counts["faststart"] += 1
                upload_path = out if out.exists() else local
                t["media_url"] = ensure_uploaded(upload_path, key)
            else:  # image (or anything else) - upload as-is
                key = b2_object_key(local)
                t["media_url"] = ensure_uploaded(local, key)

        # ----- AUDIO (trim to a small loudnorm'd clip) -----
        if audio:
            local = find_local_file(audio)
            if local is None:
                warnings.append(f"entry {eid}: audio not found locally ({audio})")
            else:
                clip_name = f"{local.stem}__{_fmt_t(a_start)}_{_fmt_t(a_end)}.mp3"
                out = local.parent / "clips" / clip_name
                key = f"audio/clips/{clip_name}"

                if not out.exists() and not DRY_RUN:
                    print(f"  Trimming: entry {eid}  [{a_start}-{a_end}]  {local.name}")
                    make_audio_clip(local, a_start, a_end, out)
                    counts["trimmed"] += 1
                elif out.exists():
                    counts["cached"] += 1
                elif DRY_RUN:
                    print(f"  [dry-run] would trim: entry {eid} [{a_start}-{a_end}] {local.name}")
                    counts["trimmed"] += 1

                clip_len = probe_duration(out) if out.exists() else (
                    round(a_end - a_start, 2) if a_end is not None else None
                )
                t["audio_url"] = ensure_uploaded(out if out.exists() else local, key)
                t["audio_start"] = 0
                t["audio_end"] = clip_len

        if t:
            transforms[eid] = t

    print(
        f"\n  Trimmed: {counts['trimmed']}   Faststart: {counts['faststart']}   "
        f"Reused local: {counts['cached']}"
    )
    print(f"  Uploaded: {counts['uploaded']}   Skipped (already in bucket): {counts['skipped']}")

    if warnings:
        print("\n  WARNINGS (these entries were left pointing at their original paths):")
        for w in warnings:
            print(f"      {w}")

    # --- Build & write the public file (skipped on a plain dry run) ---
    if not DRY_RUN:
        public_text = build_public(private_text, transforms)
        Path(PUBLIC_FILE).write_text(public_text, encoding="utf-8")
        print(f"\n  Wrote {PUBLIC_FILE}  (meanings stripped, clips + CDN URLs injected).")

        # Sanity check: no private meaning leaked.
        leak = re.search(r'meaning\s*:\s*"', Path(PUBLIC_FILE).read_text(encoding="utf-8"))
        if leak:
            print(f"\n  !!  WARNING: a 'meaning:' field still appears in {PUBLIC_FILE}. "
                  "Inspect it before pushing.")
        else:
            print("  Verified: no 'meaning:' field present in public file.")

    # --- Prune orphans (only with --prune-orphans), done last ---
    if PRUNE:
        prune_orphans(bucket, wanted_keys)

    if DRY_RUN:
        print("\n  Dry run complete - nothing written, uploaded or deleted.\n")
    else:
        print("\n  Next:  git add . && git commit -m 'new entries' && git push\n")


def prune_orphans(bucket, wanted_keys):
    """
    Delete every bucket object under a managed prefix that the site no longer
    references (old full songs, superseded clips, non-faststart videos).
    Respects --dry-run (lists only). Refuses to run on an empty wanted set,
    so a parsing failure can never wipe the bucket.
    """
    print("\n  Prune: scanning for orphaned files...")
    if not wanted_keys:
        print("  Prune SKIPPED: nothing was marked as needed this run "
              "(safety guard - refusing to delete everything).")
        return

    orphans = [
        fv for fv, _ in bucket.ls(recursive=True)
        if fv.file_name not in wanted_keys
        and fv.file_name.startswith(MANAGED_PREFIXES)
    ]

    if not orphans:
        print("  Prune: bucket already clean - no orphans found.")
        return

    print(f"  Prune: {len(orphans)} orphaned file(s)"
          f"{' would be' if DRY_RUN else ''} removed:")
    for fv in orphans:
        print(f"      {'[dry-run] ' if DRY_RUN else ''}{fv.file_name}")
        if not DRY_RUN:
            bucket.delete_file_version(fv.id_, fv.file_name)
    if not DRY_RUN:
        print(f"  Prune: removed {len(orphans)} orphaned file(s).")


if __name__ == "__main__":
    main()
