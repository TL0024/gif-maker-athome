"""Enforce security-version floors for runtime dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

MINIMUM_RUNTIME_VERSIONS = {
    "pillow": Version("12.3"),
}
_FLOOR_OPERATORS = {">=", ">", "~=", "==", "==="}


def dependency_policy_errors(
    requirements_path: Path,
    installed_versions: Mapping[str, str] | None = None,
) -> list[str]:
    requirements: dict[str, Requirement] = {}
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        requirement = Requirement(line)
        requirements[canonicalize_name(requirement.name)] = requirement

    errors: list[str] = []
    for package_name, minimum in MINIMUM_RUNTIME_VERSIONS.items():
        configured_requirement = requirements.get(package_name)
        if configured_requirement is None:
            errors.append(f"{package_name} is missing from {requirements_path.name}.")
            continue

        floors: list[Version] = []
        for specifier in configured_requirement.specifier:
            if specifier.operator not in _FLOOR_OPERATORS:
                continue
            try:
                floors.append(Version(specifier.version))
            except InvalidVersion:
                errors.append(f"{package_name} has an invalid version floor: {specifier}.")
        if not floors or max(floors) < minimum:
            errors.append(
                f"{package_name} must require version {minimum} or newer; found {configured_requirement.specifier}."
            )

        try:
            installed = (
                installed_versions[package_name]
                if installed_versions is not None
                else version(package_name)
            )
            if Version(installed) < minimum:
                errors.append(
                    f"Installed {package_name} {installed} is below the required security floor {minimum}."
                )
        except (KeyError, PackageNotFoundError):
            errors.append(f"{package_name} is not installed.")

    return errors


def main() -> None:
    requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    errors = dependency_policy_errors(requirements_path)
    if errors:
        raise SystemExit("\n".join(errors))
    print("Runtime dependency security policy passed.")


if __name__ == "__main__":
    main()
