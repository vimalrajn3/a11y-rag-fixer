import os
import ollama

client = ollama.Client()
MODEL_NAME = os.getenv("A11Y_FIXER_MODEL", "ally-fixer")

SYSTEM_PROMPT = """You are an automated React and React Native accessibility code fixer.
Your ONLY task is to add the missing accessibility props listed in the report to the specified JSX elements using the Retrieved Rules.

Strict Rules:
1. Output ONLY the complete, valid updated JSX/TSX code. Do NOT include markdown fences (```), explanations, or comments.
2. Preserve all existing props, imports, formatting, indentation, and logic untouched.
3. For boolean props like `accessible`, write `accessible={true}` or `accessible`.
4. For `accessibilityRole`, use valid React Native roles (e.g., "button", "link", "checkbox", "radio", "tab", "header", "image", "text").
5. Derive meaningful, human-readable `accessibilityLabel` and `accessibilityHint` strings from visible text, placeholder, or handler names.
"""

def setup():
    print(f"Registering custom '{MODEL_NAME}' model in Ollama...")
    response = client.create(
        model=MODEL_NAME,
        from_="qwen2.5-coder:3b",
        system=SYSTEM_PROMPT,
        parameters={
            "temperature": 0.1,  # Deterministic output
            "num_ctx": 4096,     # Fits full component files comfortably within 16GB RAM
        },
    )
    print("Status:", response.status)

if __name__ == "__main__":
    setup()