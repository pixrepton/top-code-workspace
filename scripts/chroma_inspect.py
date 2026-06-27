"""Inspect Chroma collection contents for P1 audit."""
import sys, os, json
sys.path.insert(0, 'rag-chat-asystent/backend')

import config
import chromadb
from chromadb.config import Settings as ChromaSettings

chroma_path = getattr(config, 'CHROMA_DB_DIR', '/app/chroma_clean')
print("Chroma path: %s" % chroma_path)

client = chromadb.PersistentClient(path=chroma_path, settings=ChromaSettings(anonymized_telemetry=False))
collections = client.list_collections()
print("Collections: %s" % [c.name for c in collections])

col = client.get_or_create_collection('hvac_docs')
count = col.count()
print("Total chunks: %d" % count)

if count == 0:
    print("ERROR: Chroma collection is empty!")
    sys.exit(1)

all_data = col.get(limit=count)
print("IDs returned: %d" % len(all_data["ids"]))
print("Metadatas: %d" % len(all_data["metadatas"]))
print("Documents: %d" % len(all_data["documents"]))

# Group by source file
from collections import Counter
sources = Counter()
for m in all_data["metadatas"]:
    if m:
        fname = m.get("filename", m.get("source", m.get("doc_id", "unknown")))
        sources[fname] += 1

print()
print("=== DOCUMENTS IN CHROMA (grouped by source) ===")
print("Unique source files: %d" % len(sources))
for fname, cnt in sources.most_common():
    print("  %s: %d chunks" % (fname, cnt))

# Show metadata and text preview for each unique source
print()
print("=== DETAILED METADATA PER SOURCE ===")
seen = set()
for i, m in enumerate(all_data["metadatas"]):
    if m:
        fname = m.get("filename", m.get("source", m.get("doc_id", "unknown")))
        if fname not in seen:
            seen.add(fname)
            doc = all_data["documents"][i] if all_data["documents"] else ""
            text_preview = doc[:300] if doc else "EMPTY"
            # Get file size from metadata
            fsize = m.get("file_size", m.get("size_bytes", "?"))
            print()
            print("  [%s]" % fname)
            print("    File size from metadata: %s" % fsize)
            print("    Metadata: %s" % json.dumps(m, ensure_ascii=False, default=str)[:600])
            print("    Text preview: %s" % text_preview)
