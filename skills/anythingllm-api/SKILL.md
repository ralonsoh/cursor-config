---
name: anythingllm-api
description: >-
  Interact with the local AnythingLLM instance: list workspaces, browse the
  document library, index (embed) documents into workspaces, perform RAG
  searches, and manage embeddings. Use when the user mentions AnythingLLM,
  knowledge base, RAG, document embedding, vector store, workspace indexing,
  or embedding management.
---

# AnythingLLM API

Two access layers are available: an **MCP server** (limited) and the
**REST API** (full control). Always prefer the MCP tools when they cover
the need; fall back to `curl` against the REST API for operations the MCP
server does not expose.

## Connection Details

Read from the MCP server environment in `~/.cursor/mcp.json`, key
`anythingllm` (or similar):

| Variable | Purpose |
|---|---|
| `ANYTHINGLLM_BASE_URL` | REST base, e.g. `http://localhost:3001/api` |
| `ANYTHINGLLM_API_KEY` | Bearer token for every REST call |
| `ANYTHINGLLM_WORKSPACE` | Default workspace slug for the MCP server |

Every `curl` call requires the header:

```
Authorization: Bearer <ANYTHINGLLM_API_KEY>
```

## Layer 1 — MCP Tools (namespace `user-anythingllm`)

Discover with `GetDynamicTools(namespace="user-anythingllm")`.

| Tool | Purpose | Notes |
|---|---|---|
| `anythingllm_list_workspaces` | List all workspaces | No params |
| `anythingllm_list_documents` | List documents visible to a workspace | `workspace` slug; returns **all** library docs, not just indexed ones |
| `anythingllm_search` | RAG vector search | `query`, optional `workspace` |
| `anythingllm_upload_document` | Upload a new file | `workspace`, `filePath`; auto-embeds |
| `anythingllm_create_workspace` | Create a workspace | `name` |

### MCP Limitations

- **No indexing/embedding tool** — cannot pin existing library documents
  into a workspace.
- **No delete/remove tool** — cannot remove documents or workspaces.
- `anythingllm_list_documents` returns the **global library**, not the
  workspace-specific indexed set; the `pinnedWorkspaces` array on each
  document tells you where it is indexed.
- Large responses are truncated to 8 MB; parse from the REST API instead.

## Layer 2 — REST API (via curl)

Full API docs at `<BASE_URL>/../docs` (Swagger UI).

### List workspaces

```bash
curl -s -H "Authorization: Bearer $KEY" "$BASE/v1/workspaces"
```

Returns `{ "workspaces": [ { slug, name, id, … } ] }`.

### Get workspace details + indexed chunks

```bash
curl -s -H "Authorization: Bearer $KEY" "$BASE/v1/workspace/<slug>"
```

Response includes a `documents` array listing every **chunk** embedded in
the workspace's vector store. Each chunk has:

```
id, docId, filename, docpath, workspaceId, metadata, pinned, watched
```

The chunk count is typically larger than the input document count because
each document is split into multiple pieces for embedding.

### List the document library

```bash
curl -s -H "Authorization: Bearer $KEY" "$BASE/v1/documents"
```

Returns `{ "localFiles": { "items": [ … ] } }` — a tree of folders and
files. Each folder has a `name`, `type: "folder"`, and nested `items[]`.
Files have `name` (e.g. `OSPRH-1234.md-<uuid>.json`) and `type: "file"`.

The document path used by the embedding endpoint is `<folder>/<filename>`,
e.g. `jira-bugs/OSPRH-1234.md-abc123.json`.

### Index (embed) documents into a workspace

```bash
curl -s -X POST \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"adds": ["<folder>/<file>", ...], "deletes": []}' \
  "$BASE/v1/workspace/<slug>/update-embeddings"
```

- `adds` — array of document paths from the library.
- `deletes` — array of document paths to un-embed.
- Returns the updated workspace object.

### Common REST Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/workspaces` | GET | List all workspaces |
| `/v1/workspace/<slug>` | GET | Get workspace details with chunks |
| `/v1/workspace/<slug>/update-embeddings` | POST | Add/remove embeddings |
| `/v1/documents` | GET | List library documents |
| `/v1/system` | GET | Get system configuration |

### Batching large indexing jobs

When indexing thousands of documents, the request can take minutes per
batch and the JSON payload can exceed shell argument limits.

1. **Write payload to a file** — avoid `Argument list too long` errors:
   ```bash
   python3 -c "
   import json
   paths = [...]  # list of doc paths
   with open('/tmp/batch.json', 'w') as f:
       json.dump({'adds': paths, 'deletes': []}, f)
   "
   curl -s -X POST ... -d @/tmp/batch.json "$BASE/v1/workspace/<slug>/update-embeddings"
   ```

2. **Batch size** — use 5,000 documents per request. Larger batches risk
   timeouts; smaller batches add overhead.

3. **Timeouts** — add `--max-time 1800` to curl. Embedding time scales
   roughly linearly: ~90–100 ms per document with the default
   `Xenova/all-MiniLM-L6-v2` engine.

4. **Resume on failure** — track which batches succeeded and restart from
   the failed batch number.

### System settings

```bash
curl -s -H "Authorization: Bearer $KEY" "$BASE/v1/system"
```

Returns LLM provider, embedding engine, model preferences, and feature
flags. Key fields: `EmbeddingEngine`, `EmbeddingModelPref`, `LLMProvider`,
`LLMModel`.

### Remove documents from a workspace

```bash
curl -s -X POST \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"adds": [], "deletes": ["folder/file.json"]}' \
  "$BASE/v1/workspace/<slug>/update-embeddings"
```

## Typical Workflows

### List what is indexed in each workspace

```python
import json, subprocess

KEY = "<api_key>"
BASE = "http://localhost:3001/api"

# Get workspaces
ws_resp = json.loads(subprocess.check_output([
    "curl", "-s", "-H", f"Authorization: Bearer {KEY}",
    f"{BASE}/v1/workspaces"
]))

for ws in ws_resp["workspaces"]:
    slug = ws["slug"]
    detail = json.loads(subprocess.check_output([
        "curl", "-s", "-H", f"Authorization: Bearer {KEY}",
        f"{BASE}/v1/workspace/{slug}"
    ]))
    docs = detail.get("workspace", [{}])
    if isinstance(docs, list):
        docs = docs[0]
    chunks = docs.get("documents", [])
    print(f"{slug}: {len(chunks)} chunks indexed")
```

### Bulk-index documents by category

1. Fetch library: `GET /v1/documents` → parse folder tree.
2. Filter by folder name or filename prefix (e.g. `OSPRH-`, `FDP-`).
3. Build path list: `"<folder>/<filename>"` per document.
4. Split into batches of 5,000.
5. POST each batch to `update-embeddings`, writing payload to a temp file.
6. Monitor progress; resume from the failed batch on timeout.

### Error handling examples

```bash
# Check HTTP status
curl -s -w "\nHTTP Status: %{http_code}\n" \
  -H "Authorization: Bearer $KEY" \
  "$BASE/v1/workspace/<slug>/update-embeddings"

# Parse JSON response for errors
curl -s -H "Authorization: Bearer $KEY" \
  "$BASE/v1/workspace/<slug>/update-embeddings" | jq 'select(.error != null)'

# Handle rate limits with retry
for i in {1..3}; do
  response=$(curl -s -H "Authorization: Bearer $KEY" \
    "$BASE/v1/workspace/<slug>/update-embeddings")
  if echo "$response" | jq -e '.error' > /dev/null 2>&1; then
    echo "Retry $i: Rate limited, waiting..."
    sleep 5
  else
    echo "$response"
    break
  fi
done
```

### Python helper class

```python
import json
import subprocess
from pathlib import Path

class AnythingLLMAPI:
    def __init__(self, base_url="http://localhost:3001/api", api_key=None):
        self.base_url = base_url
        self.api_key = api_key or subprocess.check_output(
            ["sh", "-c", "echo $ANYTHINGLLM_API_KEY"]
        ).decode().strip()
    
    def _request(self, endpoint, method="GET", data=None):
        headers = ["-H", f"Authorization: Bearer {self.api_key}"]
        if data:
            headers.extend(["-H", "Content-Type: application/json"])
        
        cmd = ["curl", "-s"] + headers
        if method == "POST":
            cmd.extend(["-X", "POST"])
        if data:
            cmd.extend(["-d", json.dumps(data)])
        cmd.append(f"{self.base_url}{endpoint}")
        
        result = subprocess.check_output(cmd)
        return json.loads(result)
    
    def list_workspaces(self):
        return self._request("/v1/workspaces")
    
    def get_workspace(self, slug):
        return self._request(f"/v1/workspace/{slug}")
    
    def update_embeddings(self, slug, adds=None, deletes=None):
        adds = adds or []
        deletes = deletes or []
        return self._request(
            f"/v1/workspace/{slug}/update-embeddings",
            method="POST",
            data={"adds": adds, "deletes": deletes}
        )
    
    def list_documents(self):
        return self._request("/v1/documents")
```
