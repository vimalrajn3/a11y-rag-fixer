import json
from pathlib import Path
import ollama

ollama_client = ollama.Client()


def index_rules(rules_file: str = "accessibility-component-rules.json"):
    rules_data = json.loads(Path(rules_file).read_text(encoding="utf-8"))
    vector_records = []

    texts = []
    meta = []
    for category, details in rules_data.items():
        props_str = ", ".join(details["props"])
        for comp in details["components"]:
            texts.append(
                f"Component: {comp} | Category: {category} | "
                f"Required Accessibility Props: {props_str}"
            )
            meta.append({
                "id": f"{category}_{comp}",
                "category": category,
                "component": comp,
            })

    print(f"Generating embeddings for {len(texts)} rules via all-minilm...")
    embeddings = ollama_client.embed(model="all-minilm", input=texts)["embeddings"]

    for item_meta, text, vec in zip(meta, texts, embeddings):
        vector_records.append({
            **item_meta,
            "document": text,
            "embedding": vec,
        })

    Path("vector_store.json").write_text(json.dumps(vector_records, indent=2), encoding="utf-8")
    print(f"[VECTOR DB] Saved {len(vector_records)} embeddings to vector_store.json")


if __name__ == "__main__":
    index_rules()