import re
from pathlib import Path

from fastapi import HTTPException


SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str) -> str:
    safe_name = Path(filename).name
    safe_name = SAFE_FILENAME_RE.sub("_", safe_name)
    return safe_name or "document.bin"


def validate_extension(filename: str, allowed_extensions: set[str]) -> None:
    extension = Path(filename).suffix.lower()
    if extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="unsupported_file_type")
