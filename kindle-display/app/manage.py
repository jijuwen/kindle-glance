"""Local administrator utilities; run inside the board container."""
import argparse
import json
import os
from pathlib import Path
from app import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["setup-code", "renew-setup-code", "check"])
    args = parser.parse_args()
    directory = Path(os.getenv("DATA_DIR", "/app/data"))
    if args.command == "renew-setup-code":
        print(settings.renew_setup_code(directory))
    elif args.command == "setup-code":
        code = settings.read_json(directory / "setup-code.json")
        print(code["code"])
        print("Expires (Unix UTC):", code["expires_at"])
    else:
        current = settings.load(directory)
        print(json.dumps({"schema_version": current["schema_version"], "setup_state": current["setup_state"],
                          "revision": current["revision"]}))


if __name__ == "__main__":
    main()
