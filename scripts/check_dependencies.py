"""Resolve plugin requirements against a protected core dependency snapshot.

Uses the pinned AstrBot wheel's metadata and the versions installed in CI.
This simulates core version protection without booting or installing AstrBot.
"""

import importlib.metadata
import subprocess
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def main():
    wheel = ROOT / "research/framework-check/astrbot-4.29.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(name).decode())
    core = {}
    for line in metadata.get_all("Requires-Dist", []):
        req = Requirement(line)
        if req.marker is None or req.marker.evaluate():
            core[canonicalize_name(req.name)] = req
    protected = []
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        req = Requirement(line)
        if req.marker is not None and not req.marker.evaluate():
            continue
        name = canonicalize_name(req.name)
        if name not in core:
            continue
        version = importlib.metadata.version(req.name)
        if version not in core[name].specifier:
            raise RuntimeError(
                f"{req.name}=={version} does not satisfy AstrBot {core[name]}"
            )
        protected.append(f"{name}=={version}")
    if not protected:
        raise RuntimeError(
            "No shared core dependencies found; check the wheel metadata"
        )
    with tempfile.TemporaryDirectory(prefix="gamewiki-core-constraints-") as directory:
        constraints = Path(directory) / "protected.txt"
        constraints.write_text("\n".join(protected) + "\n")
        print("Protected core snapshot: " + ", ".join(protected), flush=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--ignore-installed",
                "--no-deps",
                "-c",
                str(constraints),
                "-r",
                str(ROOT / "requirements.txt"),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
