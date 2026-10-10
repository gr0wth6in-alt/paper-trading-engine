import base64

import pytest
from fastapi.testclient import TestClient

from paper_engine.api import create_app
from tests.conftest import TOKEN

AUTH = {"Authorization": f"Bearer {TOKEN}"}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1cAAAAASUVORK5CYII="
)


def test_memes_are_authenticated_and_optional(settings, tmp_path):
    assert hasattr(settings, "memes_dir"), "Configurable local meme directory is missing"
    settings.memes_dir = tmp_path / "memes"
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/memes").status_code == 401
        assert client.get("/api/v1/memes/profit/test.png").status_code == 401
        assert client.get("/api/v1/memes", headers=AUTH).json() == {
            "profit": [],
            "loss": [],
            "entry": [],
        }
        folder = settings.memes_dir / "profit"
        folder.mkdir(parents=True)
        (folder / "win.png").write_bytes(PNG)
        (folder / "bad.svg").write_text('<svg onload="alert(1)"/>')
        (folder / "fake.png").write_text("not an image")
        (folder / "huge.png").write_bytes(PNG + b"x" * (5 * 1024 * 1024))
        assert client.get("/api/v1/memes", headers=AUTH).json()["profit"] == ["win.png"]
        response = client.get("/api/v1/memes/profit/win.png", headers=AUTH)
        assert response.content == PNG
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-content-type-options"] == "nosniff"
        for path in [
            "profit/fake.png",
            "profit/bad.svg",
            "profit/huge.png",
            "entry/missing.png",
            "other/win.png",
            "profit/..%5Cwin.png",
        ]:
            assert client.get(f"/api/v1/memes/{path}", headers=AUTH).status_code == 404
        (folder / "win.png").unlink()
        assert client.get("/api/v1/memes", headers=AUTH).json()["profit"] == []


def test_memes_list_capped_at_50(settings, tmp_path):
    assert hasattr(settings, "memes_dir"), "Configurable local meme directory is missing"
    settings.memes_dir = tmp_path / "memes"
    folder = settings.memes_dir / "entry"
    folder.mkdir(parents=True)
    for i in range(52):
        (folder / f"{i:02}.png").write_bytes(PNG)
    with TestClient(create_app(settings)) as client:
        assert len(client.get("/api/v1/memes", headers=AUTH).json()["entry"]) == 50


@pytest.mark.parametrize(
    "name,data,mime",
    [
        ("frog.JPG", b"\xff\xd8\xff" + b"test", "image/jpeg"),
        ("frog.gif", b"GIF89a" + b"test", "image/gif"),
        ("frog.webp", b"RIFF1234WEBP" + b"test", "image/webp"),
    ],
)
def test_supported_signatures_have_explicit_content_types(settings, tmp_path, name, data, mime):
    settings.memes_dir = tmp_path / "memes"
    folder = settings.memes_dir / "loss"
    folder.mkdir(parents=True)
    (folder / name).write_bytes(data)
    with TestClient(create_app(settings)) as client:
        response = client.get(f"/api/v1/memes/loss/{name}", headers=AUTH)
        assert response.status_code == 200
        assert response.headers["content-type"] == mime
        assert response.headers["cache-control"] == "no-store"


def test_traversal_alternate_streams_and_links_are_rejected(settings, tmp_path, monkeypatch):
    from pathlib import Path

    from paper_engine.memes import read_meme
    from paper_engine.models import EngineError

    root = tmp_path / "memes"
    folder = root / "entry"
    folder.mkdir(parents=True)
    (folder / "frog.png").write_bytes(PNG)
    for name in ["../frog.png", "..\\frog.png", "C:\\secret.png", "frog.png:secret", ""]:
        with pytest.raises(EngineError):
            read_meme(root, "entry", name)
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "frog.png")
    with pytest.raises(EngineError):
        read_meme(root, "entry", "frog.png")
