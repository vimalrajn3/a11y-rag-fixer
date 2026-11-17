import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
import ollama
from datetime import datetime, timezone
from scanner import generate_project_report, load_rules, scan_file

ollama_client = ollama.Client()
FIXER_MODEL = os.getenv("A11Y_FIXER_MODEL", "ally-fixer")


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Computes cosine similarity between two embedding vectors."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def retrieve_rules(vector_store: list[dict], component_types: list[str], top_k: int = 2) -> str:
    """R (Retrieval): Embeds missing component names and retrieves closest rules via cosine similarity."""
    unique_queries = [f"Component: {comp}" for comp in set(component_types)]
    query_vectors = ollama_client.embed(model="all-minilm", input=unique_queries)["embeddings"]

    retrieved_docs = set()
    for q_vec in query_vectors:
        scored = [
            (cosine_similarity(q_vec, record["embedding"]), record["document"])
            for record in vector_store
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        for _, doc in scored[:top_k]:
            retrieved_docs.add(doc)

    return "\n".join(sorted(retrieved_docs))


def generate_patch(retrieved_rules: str, file_issues: list[dict], source_code: str) -> str:
    """A + G (Augmentation & Generation): Sends retrieved rules + report + code to Ollama."""
    report_lines = "\n".join(
        f"- Line {iss['lineNumber']} | <{iss['componentType']}> (id: {iss['componentId']}) "
        f"| Missing Props: {', '.join(iss['missingProps'])}"
        for iss in file_issues
    )

    prompt = f"""Retrieved Component Rules:
{retrieved_rules}

Missing Attributes Report:
{report_lines}

Source Code:
{source_code}"""

    response = ollama_client.chat(
        model=FIXER_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_output = response["message"]["content"].strip()
    return re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", raw_output).strip()


def find_project_root(target: Path) -> Path:
    """Walks upward from a file to find the nearest folder containing package.json."""
    current = target if target.is_dir() else target.parent
    for parent in [current, *current.parents]:
        if (parent / "package.json").exists():
            return parent
    return current


TOOL_DIR = Path(__file__).resolve().parent

def run_pipeline(target_path_str: str, rules_file: str = "accessibility-component-rules.json"):
    target = Path(target_path_str).resolve()
    rules_path = TOOL_DIR / rules_file
    vector_store_path = TOOL_DIR / "vector_store.json"

    if not target.exists():
        print(f"[ERROR] Path not found: {target}")
        return

    if not vector_store_path.exists():
        print("[ERROR] vector_store.json not found. Run 'python index_rules.py' first.")
        return

    project_root = find_project_root(target)
    comp_rules = load_rules(rules_path)

    # Support BOTH a single file (.tsx/.jsx/.ts/.js) and an entire folder
    if target.is_file():
        issues = scan_file(target, project_root, comp_rules)
        report = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "totalIssues": len(issues),
            "issues": issues,
        }
        report_dir = project_root / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "accessibility-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(f"[SINGLE FILE SCAN] Found {len(issues)} issues in {target.name}")
    else:
        report = generate_project_report(project_root, rules_path)
        issues = report.get("issues", [])

    if not issues:
        print("[DONE] Zero accessibility issues found!")
        return

    issues_by_file = defaultdict(list)
    for issue in issues:
        issues_by_file[issue["filePath"]].append(issue)

    vector_store = json.loads(vector_store_path.read_text(encoding="utf-8"))

    for rel_path, file_issues in issues_by_file.items():
        target_file = (project_root / rel_path).resolve()
        original_code = target_file.read_text(encoding="utf-8")

        print(f"\n[PROCESSING] {rel_path} ({len(file_issues)} issues)...")
        comp_types = [i["componentType"] for i in file_issues]

        rules_context = retrieve_rules(vector_store, comp_types)
        patched_code = generate_patch(rules_context, file_issues, original_code)

        if len(patched_code) < len(original_code) * 0.75:
            print(f"[REVERTED] Output looked truncated for {rel_path}. Original kept.")
            continue

        target_file.write_text(patched_code, encoding="utf-8")
        remaining = scan_file(target_file, project_root, comp_rules)

        if len(remaining) == 0:
            print(f"[VERIFIED & SAVED] {rel_path} -> 0 missing attributes remaining!")
        else:
            target_file.write_text(original_code, encoding="utf-8")
            print(f"[REVERTED] {len(remaining)} issues still remained in {rel_path}.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_fixer.py <path-to-file-or-project-folder>")
        sys.exit(1)

    run_pipeline(sys.argv[1])