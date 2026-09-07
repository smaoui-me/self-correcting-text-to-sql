"""Download a versioned Chinook release and validate before atomic installation."""
import argparse
import hashlib
import sqlite3
import sys
import tempfile
import urllib.request
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import Settings, configure_console

URL = "https://github.com/lerocha/chinook-database/releases/download/v1.4.5/Chinook_Sqlite.sqlite"
SHA256 = "bdf635be69850bd3be09c9a2dbeef7ddfb80036bd3ef3381383cd03b61e4a61a"
TABLES = {"Album", "Artist", "Customer", "Employee", "Genre", "Invoice",
          "InvoiceLine", "MediaType", "Playlist", "PlaylistTrack", "Track"}


def validate(path: Path) -> None:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Downloaded database failed integrity check")
        found = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not TABLES <= found:
            raise ValueError("Database does not have the expected Chinook schema")


def setup(path: Path) -> None:
    if path.exists():
        validate(path)
        print(f"Existing Chinook database validated: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".download", delete=False) as output:
            temporary = Path(output.name)
            with urllib.request.urlopen(URL, timeout=60) as response:
                data = response.read(20_000_001)
            if len(data) > 20_000_000:
                raise ValueError("Download exceeds size limit")
            if hashlib.sha256(data).hexdigest() != SHA256:
                raise ValueError("Downloaded database does not match the pinned release checksum")
            output.write(data)
        validate(temporary)
        temporary.replace(path)
        print(f"Installed {path}\nSHA256: {hashlib.sha256(data).hexdigest()}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path)
    args = parser.parse_args()
    setup((args.path or Settings.load().database_path).resolve())


if __name__ == "__main__":
    main()
