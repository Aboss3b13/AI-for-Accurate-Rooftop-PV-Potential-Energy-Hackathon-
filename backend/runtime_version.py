"""Fingerprint backend source so launchers cannot silently reuse obsolete code."""
import hashlib
from pathlib import Path


def source_revision():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]
