#!/usr/bin/env python3
"""
download_ncert.py
=================
Downloads NCERT Class 11 & 12 Physics, Chemistry, and Mathematics
textbooks from the official NCERT website (ncert.nic.in).

Usage:
    python download_ncert.py

PDFs are saved to:  <project-root>/textbooks/{subject}_{grade}/

After running this, run:
    python ingest.py
"""

import sys
import os
import time
import zipfile
import requests
from pathlib import Path
from io import BytesIO

# ─── Output directory (project-root/textbooks) ───────────────────────────────
TEXTBOOKS_DIR = Path(__file__).parent.parent / "textbooks"

# ─── NCERT book catalogue ─────────────────────────────────────────────────────
# Format: (name, subject, grade, url_pattern)
# NCERT zip files contain chapter-wise PDFs — we download & extract them all.

NCERT_BOOKS = [
    # Class 11
    ("Physics Part 1",    "physics",     11, "https://ncert.nic.in/textbook/pdf/keph1.zip"),
    ("Physics Part 2",    "physics",     11, "https://ncert.nic.in/textbook/pdf/keph2.zip"),
    ("Chemistry Part 1",  "chemistry",   11, "https://ncert.nic.in/textbook/pdf/kech1.zip"),
    ("Chemistry Part 2",  "chemistry",   11, "https://ncert.nic.in/textbook/pdf/kech2.zip"),
    ("Mathematics",       "mathematics", 11, "https://ncert.nic.in/textbook/pdf/kemh1.zip"),
    # Class 12
    ("Physics Part 1",    "physics",     12, "https://ncert.nic.in/textbook/pdf/leph1.zip"),
    ("Physics Part 2",    "physics",     12, "https://ncert.nic.in/textbook/pdf/leph2.zip"),
    ("Chemistry Part 1",  "chemistry",   12, "https://ncert.nic.in/textbook/pdf/lech1.zip"),
    ("Chemistry Part 2",  "chemistry",   12, "https://ncert.nic.in/textbook/pdf/lech2.zip"),
    ("Mathematics Part 1","mathematics", 12, "https://ncert.nic.in/textbook/pdf/lemh1.zip"),
    ("Mathematics Part 2","mathematics", 12, "https://ncert.nic.in/textbook/pdf/lemh2.zip"),
]

# Browser-like headers to avoid bot detection
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/pdf,*/*",
    "Referer": "https://ncert.nic.in/",
}

TIMEOUT   = 120   # seconds
RETRY_MAX = 3


def _download_zip(url: str, dest_dir: Path) -> int:
    """
    Download a zip from *url* and extract all PDFs into *dest_dir*.
    Returns the number of PDFs extracted, or 0 on failure.
    """
    for attempt in range(1, RETRY_MAX + 1):
        try:
            print(f"    Attempt {attempt}: GET {url}")
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
            if response.status_code == 404:
                print(f"    ✗ 404 Not Found — skipping.")
                return 0
            response.raise_for_status()

            content = BytesIO(response.content)
            with zipfile.ZipFile(content) as zf:
                pdf_names = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
                if not pdf_names:
                    print(f"    ✗ No PDFs found inside zip.")
                    return 0

                extracted = 0
                for pdf_name in pdf_names:
                    safe_name = Path(pdf_name).name  # strip any path inside zip
                    out_path  = dest_dir / safe_name
                    with zf.open(pdf_name) as src, open(out_path, "wb") as dst:
                        dst.write(src.read())
                    extracted += 1

            print(f"    ✓ Extracted {extracted} PDF(s) to {dest_dir.name}/")
            return extracted

        except zipfile.BadZipFile:
            print(f"    ✗ Bad zip file — skipping.")
            return 0
        except requests.exceptions.Timeout:
            print(f"    ⚠ Timeout on attempt {attempt}.")
            time.sleep(3 * attempt)
        except Exception as exc:
            print(f"    ✗ Error: {exc}")
            if attempt < RETRY_MAX:
                time.sleep(3 * attempt)

    return 0


def _try_chapter_downloads(subject: str, grade: int, dest_dir: Path) -> int:
    """
    Fallback: try downloading individual chapter PDFs when the zip fails.
    NCERT chapter URL format: keph101.pdf = Class11 Physics Part1 Chapter01
    """
    # Map subject + grade to NCERT book codes
    CODES = {
        ("physics",     11): ["keph1", "keph2"],
        ("chemistry",   11): ["kech1", "kech2"],
        ("mathematics", 11): ["kemh1"],
        ("physics",     12): ["leph1", "leph2"],
        ("chemistry",   12): ["lech1", "lech2"],
        ("mathematics", 12): ["lemh1", "lemh2"],
    }
    codes = CODES.get((subject, grade), [])
    downloaded = 0

    for code in codes:
        for chapter in range(1, 16):  # up to 15 chapters per part
            url      = f"https://ncert.nic.in/textbook/pdf/{code}{chapter:02d}.pdf"
            out_path = dest_dir / f"{code}{chapter:02d}.pdf"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=60)
                if resp.status_code == 200 and b"%PDF" in resp.content[:10]:
                    out_path.write_bytes(resp.content)
                    downloaded += 1
                    print(f"      ✓ {out_path.name}")
                elif resp.status_code == 404:
                    break  # no more chapters in this part
            except Exception:
                break

    return downloaded


def main():
    print("=" * 60)
    print("  NCERT Textbook Downloader  |  Class 11 & 12 PCM")
    print("=" * 60)
    TEXTBOOKS_DIR.mkdir(parents=True, exist_ok=True)

    total_pdfs   = 0
    failed_books = []

    for name, subject, grade, url in NCERT_BOOKS:
        dest_dir = TEXTBOOKS_DIR / f"{subject}_{grade}"
        dest_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n▶ Class {grade} {name}")
        count = _download_zip(url, dest_dir)

        if count == 0:
            print(f"  ZIP failed — trying chapter-by-chapter fallback …")
            count = _try_chapter_downloads(subject, grade, dest_dir)

        if count == 0:
            failed_books.append(f"Class {grade} {name}")
            print(f"  ✗ Could not download. Place PDFs manually in: {dest_dir}")
        else:
            total_pdfs += count

        time.sleep(1)  # be polite to the server

    print("\n" + "=" * 60)
    print(f"  Download complete — {total_pdfs} PDFs saved to {TEXTBOOKS_DIR}")
    if failed_books:
        print("\n  ⚠ Failed books (manual download required):")
        for b in failed_books:
            print(f"    • {b}")
        print(
            "\n  Download them from: https://ncert.nic.in/textbook.php"
            "\n  and place the PDFs in the matching textbooks/ sub-folder."
        )
    print("=" * 60)
    print("\n  Next step:  python ingest.py")


if __name__ == "__main__":
    main()
