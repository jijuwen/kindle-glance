"""Initialize one private bridge secret, then run the existing collector."""
import os
from pathlib import Path
import secrets

path = Path(os.getenv("COLLECTOR_SECRET_FILE", "/bridge/secret"))
path.parent.mkdir(parents=True, exist_ok=True)
try:
    with open(path, "x", encoding="ascii") as stream:
        os.chmod(path, 0o600)
        stream.write(secrets.token_urlsafe(32))
except FileExistsError:
    if len(path.read_text().strip()) < 32:
        raise RuntimeError("Collector bridge secret is invalid")

if __name__ == "__main__":
    import runpy
    runpy.run_module("service", run_name="__main__")
