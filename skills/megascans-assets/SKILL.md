---
name: megascans-assets
description: Find Quixel Megascans assets on Fab and shortlist them for the user to review - photoscanned surfaces, rocks, ground, plants, decals, 3D scans; "find me Megascans for", "shortlist some textures or assets", filing Fab downloads. Uses the quixel-megascans MCP tools; the user claims and downloads on fab.com. CC0 sources with direct downloads (pbr-texture-sources); values, packing and look-dev (pbr-texturing).
---

# Megascans assets

Search the Megascans catalogue, shortlist candidates in a page the user reviews, then file what they download. The tools can't claim or download anything: that stays with the user on fab.com.

Requires the `quixel-megascans` MCP server. Don't reach for other ways to fetch Fab files, such as the browser or scripted calls, unless the user asks.

## Which source

| Need | Use |
|---|---|
| The user asks for Megascans, or wants scanned 3D assets, plants or a wide choice | This skill |
| Files fetched with no clicks, or assets that must be CC0 | `pbr-texture-sources` |

## 1. Pin down the brief

Get what the search can't guess, from the request or the project: the surface or object, its real-world size, the view distance and the target resolution. Ask only if the answer would change the picks.

Call `list_local` first: the asset may already be on disk.

## 2. Search widely

- Run several `search_assets` calls with different words and types. "cobblestone", "cobble path" and "stone paving" return different results.
- Use `asset_type: "surface"` for tiling materials. Plants are under `source: "megaplants"`, and some are in the main catalogue as `3d`.
- Fab's search is loose, so results can be off-topic. Judge each one.
- Until 12 Nov 2026 some listings are still being made free. Leave them in if they fit, marked "not free yet", or use `free_only` if the user wants only what's free today.

## 3. Choose

Use `get_asset` on promising hits, and `get_preview` on the ones that pass, so you've seen each asset you recommend.

| Check | Why |
|---|---|
| Scan area or physical size close to the real surface | A 2 m scan across a 10 m wall tiles visibly, and its detail ends up the wrong scale |
| Texel density at the view distance | Needs to hold up up close, and is wasted far away |
| The maps you need are listed | Some maps are limited to some tiers; displacement can be high tier only |
| The preview looks right | Previews are Fab's renders: they show character, but not tiling or calibration |
| `free` is `true` | `null` means unknown: send the user to the page rather than guessing |

Aim for variety across the shortlist rather than near-duplicates. Fab has many listings with the same title, which are different scans.

## 4. Shortlist

Call `create_shortlist` with assets ranked best first, usually 6 to 12, and a one-line `note` on each saying why it fits this brief. The page opens in the user's browser, so tell them what's on it and your top pick, and give them the path in case it didn't open. If `opened_in_browser` is false, say so.

Then wait. The user adds what they like to their Fab library and downloads the file each card suggests, or a different size.

## 5. File the downloads

When the user says they've downloaded, call `ingest_downloads`, with `library_dir` if the project keeps assets elsewhere.

- `unmatched` files look like Fab downloads but weren't seen in this library's records: ask which listing they came from, then pass `file_path` and `listing_id`.
- `errors` often mean a download is unfinished: ask the user to let it complete, then call again.
- Report the folder, the maps found and any `notes`.

Check the first real download of each type by eye: filing was only tested on synthetic zips, and the zip layout could differ. If maps weren't recognised, say so.

## 6. Hand over

- Hand the maps to `pbr-texturing` for calibration, packing and look-dev. Judge tiling in a 3 × 3 view.
- `source.json` records the normal convention as unverified. Find out which it is before use: an inverted normal map lights backwards. Lit from above, a raised feature should be bright on top in OpenGL (Y+).
- Copy the source and licence from `source.json` into whatever the project records for library assets.

## Licence (checked 2026-11-05)

- Fab Standard License: projects can use the assets, including commercially, with any compatible tools. Only the [EULA summary](https://www.fab.com/eula) could be read, not the binding text.
- Assets can't be redistributed on their own. Don't commit raw filed assets to a public repository, or put them in anything others can extract them from as standalone files. Flag this if the project is public.
- [Quixel says](https://quixel.com/news/update-megascans-are-going-free-again) AI training is now allowed, but the licence text may lag, and listings can still show `ai_forbidden_flag: true`. If the user wants to train on these assets, tell them to confirm the current terms first. Don't state that it's allowed or forbidden.
- Fab's FAQ indicates that the licence comes from adding an asset to your library, not from downloading alone, so remind the user to add it.
