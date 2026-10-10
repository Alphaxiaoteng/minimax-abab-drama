# Offline Fixtures

`fixtures/feeds/**` lets `netintel-mcp` run with zero network access. Start the server with
`NETINTEL_OFFLINE=1` (or `--offline`) and every source adapter reads a JSON fixture instead of
calling the live API. This is what `npm run smoke` and `tests/**` rely on for fully deterministic,
reproducible runs on any machine.

## Layout

```
fixtures/feeds/
  hackernews/
    _default.json                            # fallback, raw HN Algolia shape
    hackernews|<16hex>.json                  # per-query recordings (see keys below)
    index.json                               # human-readable manifest
  github/    … same structure
  arxiv/     … same structure
```

- `<sourceId>` ∈ `hackernews | github | arxiv`.
- `_default.json` is the deterministic fallback: when no exact-key fixture exists for a query,
  the adapter MUST serve `_default.json`, so offline runs always return data.
- Per-query files are byte-for-byte the **raw upstream response body** of the corresponding API
  call — NOT the server's internal `RawItem` shape. The adapters themselves parse them, exactly
  as they would parse a live response.
- `index.json` lists every fixture in the directory with its query, limit and a note.

## Fixture file names: the cache-key algorithm

A fixture file is named after the key `ResponseCache.key()` computes for the query
(contract §7 / §15). The algorithm, implemented once in `src/net/cache.ts`:

1. Parts: `[sourceId, query, limit, since, tags]` — `tags` is the tag list joined with `,`
   (`[]` → `""`), `since` is the ISO string or omitted.
2. Map every part to a string; `undefined` → `""`.
3. Join the parts with the ASCII unit separator U+001F (escape ``, byte `0x1F`).
4. FNV-1a 64-bit over the UTF-8 bytes:
   - `offset = 14695981039346656037` (0xcbf29ce484222325)
   - `prime  = 1099511628211` (0x00000100000001b3)
   - for each byte: `h = (h XOR byte) * prime mod 2^64`
5. Render as **16 lowercase hex digits** (zero-padded).
6. Prefix with `parts[0] + "|"` → final key, e.g. `hackernews|187bf5d898beb744`.

The file on disk is `<fixtureDir>/<sourceId>/<key>.json` — the `|` is a literal character in the
file name.

### Current recordings

| source     | query                  | limit | key (file name without `.json`)  |
|------------|------------------------|-------|----------------------------------|
| hackernews | `mcp server`           | 10    | `hackernews|187bf5d898beb744`    |
| hackernews | `agent framework`      | 10    | `hackernews|03f79166111bb404`    |
| github     | `mcp`                  | 10    | `github|d94ab8f2706e8315`        |
| github     | `agent framework`      | 10    | `github|6ea845c444a2ec3e`        |
| arxiv      | `model context protocol` | 10  | `arxiv|08dd6d2434ed1262`         |

Queries with any other `limit`/`since`/`tags` fall through to `_default.json` — this is expected
and exercised by `scripts/smoke.js` (`limit: 5`).

## Raw upstream shapes (what each adapter parses)

### `hackernews/*.json` — Algolia API

```
GET https://hn.algolia.com/api/v1/search?query=…&tags=story&hitsPerPage=…
```

```json
{
  "hits": [
    {
      "objectID": "42000101",
      "title": "…",
      "url": "https://…",
      "author": "…",
      "created_at": "2026-10-09T06:12:00.000Z",
      "story_text": "… (optional)",
      "points": 412,
      "num_comments": 87,
      "_tags": ["story", "show_hn"]
    }
  ]
}
```

### `github/*.json` — GitHub repository search

```
GET https://api.github.com/search/repositories?q=…&per_page=…
```

```json
{
  "total_count": 10,
  "items": [
    {
      "id": 900001,
      "full_name": "modelcontextprotocol/servers",
      "html_url": "https://github.com/modelcontextprotocol/servers",
      "description": "…",
      "owner": { "login": "modelcontextprotocol" },
      "created_at": "2024-11-25T00:00:00Z",
      "stargazers_count": 72100,
      "topics": ["mcp", "ai"]
    }
  ]
}
```

### `arxiv/*.json` — arXiv Atom feed

```
GET http://export.arxiv.org/api/query?search_query=all:…&max_results=…
```

```json
{ "xml": "<?xml version=\"1.0\"…><feed xmlns=\"http://www.w3.org/2005/Atom\">…</feed>" }
```

The Atom XML is a single JSON string. The curated fixtures deliberately exercise every parser
feature `src/net/xml.ts` must handle: CDATA, self-closing `<link/>`, the `&amp;` entity,
an XML comment, attributes, and nested `<author>/<name>` + `<category term=…>`.

## Re-recording from the live APIs

The checked-in fixtures are curated (hand-tuned for determinism); to regenerate real recordings:

```sh
cd "$(git rev-parse --show-toplevel)"

# 1. Hacker News — Algolia search (no auth required)
curl -sS 'https://hn.algolia.com/api/v1/search?query=mcp%20server&tags=story&hitsPerPage=10' \
  > /tmp/hn-live.json

# 2. GitHub — repository search (needs a token)
GH_TOKEN=ghp_… \
curl -sS -H "Accept: application/vnd.github+json" -H "Authorization: Bearer $GH_TOKEN" \
  'https://api.github.com/search/repositories?q=mcp&sort=stars&per_page=10' \
  > /tmp/gh-live.json

# 3. arXiv — Atom query (no auth; XML is wrapped in {"xml": …})
curl -sS 'http://export.arxiv.org/api/query?search_query=all:%22model%20context%20protocol%22&start=0&max_results=10' \
  | node -e 'let d="";process.stdin.on("data",c=>d+=c).on("end",()=>process.stdout.write(JSON.stringify({xml:d},null,2)+"\n"))' \
  > /tmp/ax-live.json
```

Then compute the destination file names with the key algorithm above. A one-off way to get the
key from the built server (after `npm run build`):

```sh
node -e '
const { ResponseCache } = require("./dist/src/net/cache.js");
const [source, query, limit] = process.argv.slice(1);
console.log(source + "|" + ResponseCache.key([source, query, limit, undefined, ""]).split("|")[1] + ".json");
' hackernews "mcp server" 10
```

Copy the live payload to `fixtures/feeds/<source>/<that-file>`, append its `{key, query, limit,
since, note}` entry to the matching `index.json`, and re-run `npm run smoke` to prove it still
parses offline. Keep `_default.json` in place as the fallback for unmatched queries.

## Editing rules

- Every file ends with exactly one trailing newline.
- Per-query fixtures must be structurally identical to `_default.json` (same keys, same order
  convention); only the entries are a subset.
- Determinism: no wall-clock-dependent values (`created_at` timestamps are fixed). The server's
  own `generatedAt` in `index.json` is pinned to `2026-10-10T00:00:00.000Z`.