import re
from pathlib import Path

_SAFE = re.compile(r"^[A-Za-z0-9_\-]+\.csv$")


class ArchiveStore:
    def __init__(self, archive_dir):
        self.dir = Path(archive_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, filename):
        if not _SAFE.match(filename or ""):
            raise ValueError("invalid filename")
        return self.dir / filename

    def append_chunk(self, filename, start_byte, data):
        path = self._path(filename)
        if start_byte > 0:
            if not path.exists():
                return False, {"error": "missing file for append",
                               "expected": start_byte, "actual": 0}
            cur = path.stat().st_size
            if cur != start_byte:
                return False, {"error": "size mismatch",
                               "expected": start_byte, "actual": cur}
            with path.open("ab") as f:
                f.write(data)
        else:
            with path.open("wb") as f:
                f.write(data)
        return True, {"new_total": path.stat().st_size}

    def list_files(self):
        out = []
        for f in sorted(self.dir.glob("*_backup.csv")):
            out.append({"name": f.name, "size": f.stat().st_size})
        return out