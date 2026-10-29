"""Optional local OCR for downloaded menu images (Windows.Media.Ocr via PowerShell, no network/account).

Output is *OCR-derived and unverified*: every row carries status ``ocr_needs_review``. A price is only
proposed (``price_candidate_vnd``) when the text has an unambiguous VND shape; otherwise it stays null.
Nothing here is merged into the verified ``menu_items`` set.
"""
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("ocr_windows.ps1")
_PRICE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+|\d{1,4})\s*(k|K|VN[ĐDđd]|vn[đd]|[đd₫])?(?![\w])")
_UNIT = re.compile(r"(?:VN[ĐDđd]|[đ₫])\s*/\s*([^\s\d]+)", re.I)
_cache = {}


def _powershell():
    return "powershell.exe" if sys.platform == "win32" else None


def run_ocr(image_path, language="", timeout=90):
    exe = _powershell()
    if not exe or not SCRIPT.is_file():
        raise RuntimeError("ocr_unavailable: needs Windows PowerShell with Windows.Media.Ocr")
    cmd = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
           "-ImagePath", str(image_path)] + (["-Language", language] if language else [])
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True, encoding="ascii", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError("ocr_failed: " + (proc.stderr or proc.stdout).strip()[:300])
    return json.loads(proc.stdout)


def engine_info():
    """Language tag the OCR engine will use, or None when unavailable. Cached per process."""
    if "info" not in _cache:
        try:
            probe = Path(__file__).with_name("ocr_probe.png")
            _cache["info"] = {"available": SCRIPT.is_file() and sys.platform == "win32"}
        except OSError:
            _cache["info"] = {"available": False}
    return _cache["info"]


def parse_price(text):
    """Return (price_vnd or None, raw_text or None). Conservative: needs a thousands separator, k or VND marker."""
    found = []
    for m in _PRICE.finditer(text):
        num, suffix = m.group(1), (m.group(2) or "")
        digits = re.sub(r"[.,]", "", num)
        grouped = bool(re.search(r"[.,]\d{3}$", num))
        if suffix.lower() == "k":
            value = int(digits) * 1000 if not grouped else None
        elif grouped:
            value = int(digits)
        elif suffix:  # bare number followed by VND marker, e.g. "45000đ"
            value = int(digits)
        else:
            continue
        if value is not None and 1000 <= value <= 5_000_000:
            found.append((value, m.group(0).strip()))
    # Several price-like numbers in one visual row (multi-column or stylised menus) is ambiguous: keep null.
    return found[0] if len(found) == 1 else (None, None)


def rows_from_ocr(ocr):
    """Group OCR words into visual rows (the engine often splits names and prices into separate lines)."""
    words = [w for line in ocr.get("lines") or [] for w in line.get("words") or []]
    if not words:
        return []
    med = statistics.median(w["h"] for w in words) or 1
    words.sort(key=lambda w: w["y"] + w["h"] / 2)
    rows, cur, cy = [], [], None
    for w in words:
        c = w["y"] + w["h"] / 2
        if cur and abs(c - cy) > med * 0.6:
            rows.append(cur)
            cur = []
        cur.append(w)
        cy = statistics.mean(x["y"] + x["h"] / 2 for x in cur)
    if cur:
        rows.append(cur)
    out = []
    for row in rows:
        row.sort(key=lambda w: w["x"])
        text = " ".join(w["text"] for w in row)
        price, raw = parse_price(text)
        name = text
        if raw:
            name = text.replace(raw, " ")
        unit = _UNIT.search(text)
        name = re.sub(r"(?i)\bVN[ĐDđd]\b\s*/?\s*\S*|[₫đ]\s*/\s*\S*", " ", name)
        name = re.sub(r"\s+", " ", name).strip(" -:.|")
        out.append({"ocr_row_text": text, "name_ocr": name or None, "price_candidate_vnd": price,
                    "price_raw_text": raw, "unit_ocr": unit.group(1) if unit else None,
                    "y": round(min(w["y"] for w in row)), "x": round(min(w["x"] for w in row))})
    return out
