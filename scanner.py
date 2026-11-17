import json
import re
from datetime import datetime, timezone
from pathlib import Path

IGNORE_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage", "__tests__"}
TARGET_EXTENSIONS = {".jsx", ".tsx", ".js", ".ts"}


def load_rules(rules_path: Path) -> dict[str, list[str]]:
    """Maps each component name to its deduplicated list of required props."""
    raw_rules = json.loads(rules_path.read_text(encoding="utf-8"))
    comp_map: dict[str, list[str]] = {}
    for _, config in raw_rules.items():
        for comp in config["components"]:
            existing = comp_map.get(comp, [])
            comp_map[comp] = list(dict.fromkeys(existing + config["props"]))
    return comp_map


def get_severity(missing_props: list[str]) -> str:
    if any(p in missing_props for p in ("accessibilityLabel", "accessibilityRole")):
        return "HIGH"
    if "accessibilityHint" in missing_props:
        return "MEDIUM"
    return "LOW"


def find_jsx_elements(source: str) -> list[tuple[str, int, dict[str, str]]]:
    """Pure-Python JSX opening/self-closing tag parser (handles multi-line tags & nested braces)."""
    elements = []
    # Match <ComponentName followed by whitespace, /, or >
    tag_start_re = re.compile(r"<([A-Z][A-Za-z0-9_.]*)\b(?=[\s/>])")

    for match in tag_start_re.finditer(source):
        tag_name = match.group(1)
        start_idx = match.start()
        line_num = source.count("\n", 0, start_idx) + 1

        # Walk forward tracking brace/quote depth to find the closing '>' of this opening tag
        i = match.end()
        n = len(source)
        brace_depth = 0
        quote_char = None

        while i < n:
            ch = source[i]
            if quote_char:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == quote_char:
                    quote_char = None
            else:
                if ch in ('"', "'", "`"):
                    quote_char = ch
                elif ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth = max(0, brace_depth - 1)
                elif ch == ">" and brace_depth == 0:
                    break
            i += 1

        tag_body = source[match.end():i]

        # Extract attribute names and string values from tag_body
        attrs: dict[str, str] = {}
        attr_re = re.compile(
            r"""\b([A-Za-z_:][A-Za-z0-9_.:-]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|\{[^}]*\}))?"""
        )
        for attr_match in attr_re.finditer(tag_body):
            attr_name = attr_match.group(1)
            attr_val = attr_match.group(2) or attr_match.group(3) or ""
            attrs[attr_name] = attr_val

        elements.append((tag_name, line_num, attrs))

    return elements


def scan_file(file_path: Path, project_root: Path, comp_rules: dict[str, list[str]]) -> list[dict]:
    """Scans a single JSX/TSX file and returns all missing-attribute issues."""
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    issues = []

    rel_path = str(file_path.relative_to(project_root)).replace("\\", "/")
    screen_name = file_path.stem

    for tag_name, line_num, existing_attrs in find_jsx_elements(source):
        required_props = comp_rules.get(tag_name)

        # Fallback heuristics for generic elements
        if not required_props:
            comp_id_guess = existing_attrs.get("testID") or existing_attrs.get("id") or ""
            if "onPress" in existing_attrs or comp_id_guess.startswith("btn_"):
                required_props = ["accessibilityLabel", "accessibilityRole", "accessibilityHint"]
            elif comp_id_guess.startswith("input-"):
                required_props = ["accessible", "accessibilityLabel", "accessibilityHint"]
            elif comp_id_guess.startswith("dropdown_"):
                required_props = ["accessibilityLabel", "accessibilityRole", "accessibilityHint"]

        if required_props:
            missing = [p for p in required_props if p not in existing_attrs]
            if missing:
                comp_id = (
                    existing_attrs.get("testID")
                    or existing_attrs.get("data-testid")
                    or existing_attrs.get("accessibilityLabel")
                    or existing_attrs.get("nativeID")
                    or existing_attrs.get("id")
                    or "unknown"
                )
                issues.append({
                    "screenName": screen_name,
                    "filePath": rel_path,
                    "lineNumber": line_num,
                    "componentType": tag_name,
                    "componentId": comp_id,
                    "missingProps": missing,
                    "severity": get_severity(missing),
                })

    return issues


def generate_project_report(project_root: Path, rules_path: Path) -> dict:
    """Scans an entire project directory and writes reports/accessibility-report.json."""
    comp_rules = load_rules(rules_path)
    all_issues = []

    for path in project_root.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in TARGET_EXTENSIONS:
            all_issues.extend(scan_file(path, project_root, comp_rules))

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalIssues": len(all_issues),
        "issues": all_issues,
    }

    report_dir = project_root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / "accessibility-report.json"
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"[SCAN] Found {len(all_issues)} issues -> {report_file}")
    return report
