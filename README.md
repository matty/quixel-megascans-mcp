# Quixel Megascans MCP

A local [MCP](https://modelcontextprotocol.io) server that lets an AI agent search Quixel Megascans on [Fab](https://www.fab.com), build a visual shortlist for you to review, and file what you download into a tidy local library.

You stay in charge of your Epic account: **the agent finds and shortlists, you claim and download on fab.com.** The server has no login, makes no account calls and never downloads asset files.

> Independent project, not affiliated with or endorsed by Epic Games, Fab or Quixel. It contains no Megascans assets. It reads the undocumented JSON endpoints behind Fab's website, because Fab has no public API, so it can break without notice.

## How it works

1. You ask for something: "find mossy cobblestone surfaces for a 4 m courtyard".
2. The agent searches, compares physical size, texel density and maps, and looks at previews.
3. A shortlist page opens in your browser, with a preview, free status, specs and suggested file for each asset, and a link to its Fab page.
4. You open the ones you like, add them to your Fab library and download them.
5. The agent files the downloads: each asset gets its own folder, consistent map names and a `source.json` recording where it came from.

## Tools

| Tool | What it does |
|---|---|
| `search_assets` | Search by keywords, type and source, optionally free assets only |
| `get_asset` | Physical size or scan area, texel density, maps, price, files with sizes, suggested file |
| `get_preview` | Fab's preview image, so the agent can see the asset |
| `create_shortlist` | Write the HTML shortlist and open it in your browser |
| `ingest_downloads` | File downloads into the library; originals stay where they are |
| `list_local` | Search what's already in the library |

## Install

Needs [uv](https://docs.astral.sh/uv/) and Python 3.14.

```powershell
git clone https://github.com/matty/quixel-megascans-mcp
claude mcp add --scope user quixel-megascans -- uv run --directory "<path to clone>" quixel-megascans-mcp
```

For other MCP clients, run the same `uv run` command over stdio.

The optional skill in [`skills/megascans-assets`](skills/megascans-assets/SKILL.md) teaches the agent the workflow. To use it with Claude Code, copy or link that folder into `~/.claude/skills/`.

## Configuration

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `MEGASCANS_LIBRARY` | `~/Megascans` | Where assets are filed |
| `MEGASCANS_DOWNLOADS` | `~/Downloads` | Where `ingest_downloads` looks |
| `MEGASCANS_STATE_DIR` | `%LOCALAPPDATA%\quixel-megascans-mcp` | Cache, shortlists and the record of files seen |

## Licence terms for the assets

Megascans assets are covered by Fab's terms, not by anything in this repository, so read [the Fab EULA](https://www.fab.com/eula) yourself. As of 5 November 2026:

- [Quixel announced](https://quixel.com/news/update-megascans-are-going-free-again) that the full library is going free on Fab, with listings updating until 12 November, and that its terms now allow AI training on Megascans and Megaplants.
- Fab's EULA summary prohibits redistributing assets on their own, so don't commit filed assets to a public repository or share the library.
- Listings can still show `isAiForbidden: true`, and Fab's `robots.txt` says `ai-train=no`. The server reports the flag and has no bulk download or training features.

## Good behaviour

The server identifies itself with its own user agent, sends no credentials, makes at most two catalogue requests a second, caches responses, and looks at listings only when asked. If Fab refuses a request, it reports that and does not try to get around it.

## Known limits

- **Free status** comes from the price of the Personal and Professional licences, because Fab's `isFree` field and `is_free` filter proved unreliable. Search results hold this only in a price tier id, so a format change gives `free: null` rather than a wrong answer.
- **Ingesting real downloads is unproven.** The tests use synthetic zips, because no real Fab zip had been inspected when this was written. Anything unrecognised keeps its original name.
- **Normal maps** are recorded as `unverified`, because Fab's OpenGL or DirectX convention hasn't been confirmed. Check before use.

## Development

```powershell
uv run pytest           # offline tests against a fake Fab
uv run pytest -m live   # also checks the real Fab endpoints still behave
```

All Fab URLs live in [`fab.py`](src/megascans_mcp/fab.py), so an endpoint change is a one-file fix.
