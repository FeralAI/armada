#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$ROOT" <<'PY'
import ast
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
controller_type = root / "system_files/usr/libexec/armada/controller-type"
devices = root / "system_files/usr/share/inputplumber/devices"
udev_rules = root / "system_files/usr/lib/udev/rules.d/70-armada-inputplumber.rules"

module = ast.parse(controller_type.read_text(encoding="utf-8"))
profile_names = None
for node in module.body:
    if not isinstance(node, ast.Assign):
        continue
    if any(isinstance(target, ast.Name) and target.id == "ARMADA_PROFILE_NAMES" for target in node.targets):
        profile_names = ast.literal_eval(node.value)
if profile_names is None:
    raise SystemExit("controller-type has no ARMADA_PROFILE_NAMES assignment")

shipped_names = set()
passthrough_paths = set()
for profile in sorted(devices.glob("*.yaml")):
    text = profile.read_text(encoding="utf-8")
    match = re.search(r"^name:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        raise SystemExit(f"{profile.relative_to(root)} has no top-level name")
    profile_name = match.group(1)
    shipped_names.add(profile_name)

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "passthrough: true":
            continue
        source_indent = len(line) - len(line.lstrip())
        phys_path = None
        for previous in reversed(lines[:index]):
            indent = len(previous) - len(previous.lstrip())
            if previous.strip().startswith("phys_path:"):
                phys_path = previous.split(":", 1)[1].strip()
                break
            if previous.strip() and indent < source_indent:
                break
        if not phys_path:
            raise SystemExit(f"{profile.relative_to(root)} has passthrough without phys_path")
        passthrough_paths.add(phys_path)

missing_names = sorted(shipped_names - profile_names)
if missing_names:
    raise SystemExit(f"controller-type is missing profile names: {', '.join(missing_names)}")

rules = udev_rules.read_text(encoding="utf-8")
missing_rules = sorted(path for path in passthrough_paths if path not in rules)
if missing_rules:
    raise SystemExit(f"udev rules are missing passthrough paths: {', '.join(missing_rules)}")

print(
    f"controller profile test passed "
    f"({len(shipped_names)} profiles, {len(passthrough_paths)} passthrough paths)"
)
PY
