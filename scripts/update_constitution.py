"""Update AGENT_CONSTITUTION.md to reference correct tool names."""
import os

constitution_path = "gmail-agent/docs/core/AGENT_CONSTITUTION.md"

with open(constitution_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace old tool names with new generic ones
replacements = [
    # tool_allowlist -> Allowlist narzędzi (so the code can parse it)
    ("## tool_allowlist", "## Allowlist narzędzi"),
    
    # Replace old tool names in allowlist
    ("- `search_gmail_thread`", "- `query_anything`"),
    ("- `generate_draft_reply`", "- `propose_mutation`"),
    ("- `propose_new_case`", "- `propose_mutation`"),
    ("- `propose_case_link`", "- `propose_plan`"),
    ("- `propose_artifact`", "- `propose_plan`"),
    ("- `search_similar_cases`", "- `query_anything`"),
    ("- `recall_entity_facts`", "- `query_anything`"),
    
    # Remove duplicates if any
    # Add note about generic usage
]

for old, new in replacements:
    content = content.replace(old, new)

# Add usage notes for generic tools
notes_section = """

## Uwagi o generycznych narzędziach

- `propose_mutation` — użyj z parametrami: `operation` (create_case, generate_draft, update_case_status, schedule_visit, send_email), `target` (np. case_id), `payload` (dane operacji), `reasoning_pl` (uzasadnienie).
- `propose_plan` — użyj do złożonych sekwencji (merge_cases, link_case_to_case, add_deadline).
- `query_anything` — użyj z parametrami: `query` (treść zapytania), `sources` (lista: rag, temporal, similar, mail).
"""

content += notes_section

with open(constitution_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated: %s" % constitution_path)
print("New file size: %d bytes" % len(content))
