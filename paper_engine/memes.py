from pathlib import Path

from paper_engine.models import EngineError

CATEGORIES = ("profit", "loss", "entry")
TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MAX_BYTES = 5 * 1024 * 1024


def read_meme(root: Path, category: str, name: str) -> tuple[bytes, str]:
    if category not in CATEGORIES or not name or any(c in name for c in "/\\:"):
        raise EngineError("meme_not_found", "Image not found", 404)
    folder = root.resolve() / category
    path = folder / name
    try:
        if folder.is_symlink() or folder.is_junction() or path.is_symlink():
            raise ValueError("Links are not served")
        if path.resolve().parent != folder or path.suffix.lower() not in TYPES:
            raise ValueError("Unsupported file")
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError("Image too large")
        with path.open("rb") as file:
            data = file.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            raise ValueError("Image too large")
        suffix = path.suffix.lower()
        valid = (
            (suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
            or (suffix in (".jpg", ".jpeg") and data.startswith(b"\xff\xd8\xff"))
            or (suffix == ".gif" and data[:6] in (b"GIF87a", b"GIF89a"))
            or (suffix == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        )
        if not valid:
            raise ValueError("Invalid image signature")
        return data, TYPES[suffix]
    except (OSError, ValueError) as exc:
        raise EngineError("meme_not_found", "Image not found", 404) from exc


def list_memes(root: Path) -> dict[str, list[str]]:
    result = {category: [] for category in CATEGORIES}
    for category in CATEGORIES:
        folder = root / category
        try:
            entries = sorted(folder.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for path in entries:
            try:
                read_meme(root, category, path.name)
            except EngineError:
                continue
            result[category].append(path.name)
            if len(result[category]) == 50:
                break
    return result
