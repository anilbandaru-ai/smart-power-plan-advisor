"""Local OCR and per-page audit; no provider calls or source-file mutations."""
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import tiktoken

from backend.knowledge.models import DocumentReviewRequired


def page_text(page, settings):
    from backend.knowledge.documents import extract_page
    text = extract_page(page)
    if len(tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=())) >= 20 or getattr(page, "objects", None) == {}:
        return text, "native"
    if not settings.ocr_enabled:
        return text, "ocr_disabled"
    command = shutil.which(settings.ocr_command)
    if not command:
        raise DocumentReviewRequired("OCR unavailable: configure a local Tesseract executable")
    if page.width * page.height > 2000000:
        raise DocumentReviewRequired("Page exceeds OCR image-size limit")
    with tempfile.TemporaryDirectory() as temporary:
        image = Path(temporary) / "page.png"
        page.to_image(resolution=200).save(str(image))
        result = subprocess.run([command, str(image), "stdout", "--psm", "3"],
                                capture_output=True, timeout=60, check=False)
        if result.returncode:
            raise DocumentReviewRequired("Local OCR failed; review page manually")
        return result.stdout.decode("utf-8", errors="strict").strip(), "ocr"


def audit_corpus(settings, selected):
    from backend.knowledge.documents import digest
    root = settings.data_dir.resolve()
    selected = {Path(p).resolve() for p in selected}
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "files": [], "failed": 0}
    encoding = tiktoken.get_encoding("cl100k_base")
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() != ".pdf":
            continue
        entry = {"filename": path.relative_to(root).as_posix(), "pages": [], "status": "excluded"}
        report["files"].append(entry)
        if not path.resolve().is_relative_to(root):
            entry.update(status="failed", reason="Source path escapes data root")
            report["failed"] += 1
            continue
        if path.resolve() not in selected:
            entry["reason"] = "Not selected for this corpus (including reserved _txu cache)"
            continue
        entry["status"] = "ready"
        seen = {}
        try:
            with pdfplumber.open(path) as pdf:
                for number, page in enumerate(pdf.pages, 1):
                    item = {"page": number, "status": "failed"}
                    entry["pages"].append(item)
                    try:
                        item["tables_detected"] = len(page.find_tables())
                        text, mode = page_text(page, settings)
                        count = len(encoding.encode(text, disallowed_special=()))
                        item.update(tokens=count, extraction=mode, extracted_characters=len(text),
                                    native_characters=len(page.chars), image_objects=len(page.images),
                                    table_rows=sum(len(t.extract()) for t in page.find_tables()))
                        if not text and getattr(page, "objects", None) == {}:
                            item["status"] = "blank_skipped"
                        elif not 20 <= count <= 1800:
                            item["reason"] = "Unreadable, short or oversized page; review required"
                        elif digest(text.encode()) in seen:
                            item.update(status="duplicate_skipped", duplicate_of=seen[digest(text.encode())])
                        else:
                            seen[digest(text.encode())] = number
                            item["status"] = "extracted"
                            if mode == "ocr":
                                item["warning"] = "OCR text and table alignment require review"
                            elif page.images:
                                item["warning"] = "Page includes images; native text extraction does not establish image-content completeness"
                    except Exception as error:
                        item["reason"] = type(error).__name__
                if not seen or any(p["status"] == "failed" for p in entry["pages"]):
                    entry["status"] = "failed"
        except Exception as error:
            entry.update(status="failed", reason=type(error).__name__)
        report["failed"] += int(entry["status"] == "failed")
    return report


def write_audit(report, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
