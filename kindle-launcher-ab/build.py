"""Build and verify the two-file KUAL launcher experiment using only stdlib."""
from pathlib import Path
import hashlib
import json
import shlex
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parent
RELEASE = "kindleglance-launcher-1.1.0"
DEVICE_DIR = "extensions/kindle-board-ab"
FILES = (f"{DEVICE_DIR}/config.xml", f"{DEVICE_DIR}/menu.json")


def validate(payloads: dict[str, bytes]) -> None:
    if set(payloads) != set(FILES):
        raise ValueError("Archive must contain exactly the two launcher files")
    for name, data in payloads.items():
        if data.startswith(b"\xef\xbb\xbf") or b"\r" in data:
            raise ValueError(f"Expected UTF-8 without BOM and LF newlines: {name}")
        data.decode("utf-8")

    extension = ET.fromstring(payloads[FILES[0]])
    if extension.tag != "extension":
        raise ValueError("Invalid KUAL extension root")
    if extension.findtext("information/id") != "kindle-board-launcher-ab":
        raise ValueError("Unexpected extension identity")
    menu_ref = extension.find("menus/menu")
    if menu_ref is None or menu_ref.text != "menu.json" or menu_ref.get("type") != "json":
        raise ValueError("Extension must reference its local JSON menu")

    menu = json.loads(payloads[FILES[1]])
    if len(menu["items"]) != 1 or len(menu["items"][0]["items"]) != 2:
        raise ValueError("Expected one submenu with exactly A and B")
    normal, no_framework = menu["items"][0]["items"]
    for entry in (normal, no_framework):
        if set(entry) != {"name", "priority", "action", "params", "status", "internal"}:
            raise ValueError("Unexpected menu action fields")
        if entry["action"] != "/mnt/us/koreader/koreader.sh" or entry["status"] is not False:
            raise ValueError("Both entries must invoke the installed official launcher")
        if entry["internal"] != f"status {entry['name']}":
            raise ValueError("Internal KUAL command must only label the selected entry")
    if shlex.split(normal["params"]) != ["--kual"]:
        raise ValueError("A must use normal KUAL launch")
    if shlex.split(no_framework["params"]) != ["--kual", "--framework_stop"]:
        raise ValueError("B must add only the official framework-stop flag")


def main() -> None:
    payloads = {name: (ROOT / name).read_bytes() for name in FILES}
    validate(payloads)
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    target = out / f"{RELEASE}.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name in FILES:
            entry = ZipInfo(name, date_time=(2026, 9, 6, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, payloads[name])
    with ZipFile(target) as archive:
        if archive.namelist() != list(FILES) or archive.testzip() is not None:
            raise ValueError("Archive contents or CRC failed verification")
        extracted = {name: archive.read(name) for name in FILES}
        validate(extracted)
        if extracted != payloads:
            raise ValueError("Archived content differs from source")
    sums = [(hashlib.sha256(target.read_bytes()).hexdigest(), target.name)]
    sums.extend((hashlib.sha256(payloads[name]).hexdigest(), name) for name in FILES)
    (out / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for digest, name in sums),
        encoding="ascii", newline="\n",
    )
    print(json.dumps({
        "archive": str(target),
        "device_files": list(FILES),
        "sha256": sums[0][0],
        "verified": "XML, JSON, official launch arguments, allowlist, CRC, source parity",
        "device_test": "pending",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
