"""Build an uploadable plugin ZIP, excluding research and development files."""

import zipfile
from pathlib import Path

import yaml


def main():
    root = Path(__file__).resolve().parents[1]
    metadata = yaml.safe_load((root / "metadata.yaml").read_text(encoding="utf-8"))
    for field in ("name", "display_name", "desc", "version", "author", "repo"):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise ValueError(f"metadata.yaml missing field: {field}")
    version = metadata["version"]
    destination = root / "dist" / f"{metadata['name']}-{version}.zip"
    destination.parent.mkdir(exist_ok=True)
    files = [
        root / p
        for p in (
            "main.py",
            "metadata.yaml",
            "requirements.txt",
            "_conf_schema.json",
            "README.md",
            "CHANGELOG.md",
            "HANDOFF.MD",
            "LICENSE",
        )
    ]
    files += sorted((root / "wiki").glob("*.py"))
    files += sorted((root / "docs").glob("*.md"))
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(
                path,
                Path("astrbot_plugin_gamewiki") / path.relative_to(root),
            )
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(files)
    print(destination)
    print(f"{len(files)} files, {destination.stat().st_size} bytes")
    if destination.stat().st_size >= 16 * 1024 * 1024:
        raise ValueError("Plugin ZIP exceeds AstrBot market's 16 MiB limit")


if __name__ == "__main__":
    main()
