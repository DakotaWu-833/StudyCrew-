"""Executable guardrails for StudyCrew's directed module boundaries."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
DOMAIN_PACKAGES = {"accounts", "activity", "integrations", "meetings", "projects", "tasks", "campus", "coordination", "operations", "recruiting", "documents_store", "learning_exchange", "project_chat", "offline_sync", "productivity"}
HTTP_CLIENT_PACKAGES = {"aiohttp", "httpx", "requests"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class ArchitectureBoundaryTests(SimpleTestCase):
    def test_directed_module_boundaries(self):
        violations: list[str] = []
        source_packages = DOMAIN_PACKAGES | {"api", "web"}

        for package in sorted(source_packages):
            for path in (ROOT / package).rglob("*.py"):
                relative = path.relative_to(ROOT)
                if "migrations" in relative.parts or "tests" in relative.parts:
                    continue
                imports = imported_modules(path)
                imported_roots = {module.split(".", 1)[0] for module in imports}

                if package in DOMAIN_PACKAGES:
                    forbidden_interfaces = imported_roots & {"api", "web"}
                    if forbidden_interfaces:
                        violations.append(
                            f"{relative} imports HTTP interface package(s) {sorted(forbidden_interfaces)}"
                        )

                if path.name == "models.py":
                    sibling_domains = imported_roots & (DOMAIN_PACKAGES - {package})
                    if sibling_domains:
                        violations.append(
                            f"{relative} model imports sibling domain(s) {sorted(sibling_domains)}"
                        )

                if package != "integrations":
                    external_clients = imported_roots & HTTP_CLIENT_PACKAGES
                    if external_clients:
                        violations.append(
                            f"{relative} bypasses the integrations boundary with {sorted(external_clients)}"
                        )

        frontend_root = ROOT / "frontend" / "src"
        for path in (*frontend_root.rglob("*.ts"), *frontend_root.rglob("*.tsx")):
            relative = path.relative_to(ROOT)
            if ".test." in path.name:
                continue
            source = path.read_text(encoding="utf-8")
            if re.search(r"\bfetch\s*\(", source) and relative.as_posix() != "frontend/src/api/client.ts":
                violations.append(f"{relative} bypasses the shared Fetch client")
            if "/api/v1" in source and "frontend/src/api/" not in relative.as_posix():
                violations.append(f"{relative} embeds an API route outside the API module")

        self.assertEqual(violations, [], "\n".join(violations))
