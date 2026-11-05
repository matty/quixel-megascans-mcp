"""Render a shortlist as one self-contained HTML page the user opens to review and click through."""

from __future__ import annotations

from html import escape

_STYLE = """
:root { color-scheme: light dark; --bg:#f6f6f4; --card:#fff; --ink:#1c1c1a; --muted:#666660;
  --line:#deded9; --accent:#0b5fc0; --free:#17693a; --paid:#8f4b00; }
@media (prefers-color-scheme: dark) { :root { --bg:#141413; --card:#1f1f1d; --ink:#ececE8; --muted:#a3a39b;
  --line:#343431; --accent:#7db4f5; --free:#6fcf97; --paid:#f0b165; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.45 system-ui,"Segoe UI",sans-serif; }
header, footer { max-width:1500px; margin:0 auto; padding:24px; }
h1 { margin:0 0 4px; font-size:24px; font-weight:650; }
header p, footer p { margin:0; color:var(--muted); }
main { max-width:1500px; margin:0 auto; padding:0 24px; display:grid; gap:18px;
  grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); }
article { display:flex; flex-direction:column; background:var(--card); border:1px solid var(--line);
  border-radius:8px; overflow:hidden; }
.image { position:relative; display:block; aspect-ratio:16/9; background:var(--line); }
.image img { display:block; width:100%; height:100%; object-fit:cover; }
.rank { position:absolute; top:8px; left:8px; min-width:28px; padding:2px 8px; border-radius:6px;
  background:#000c; color:#fff; font-weight:650; text-align:center; }
.body { display:flex; flex:1; flex-direction:column; gap:8px; padding:14px; }
h2 { margin:0; font-size:17px; font-weight:620; }
.status { font-weight:600; font-size:13px; }
.status.free { color:var(--free); } .status.paid, .status.unknown { color:var(--paid); }
.note { margin:0; }
dl { display:grid; grid-template-columns:auto 1fr; gap:2px 12px; margin:0; font-size:13px; }
dt { color:var(--muted); } dd { margin:0; overflow-wrap:anywhere; }
.open { margin-top:auto; padding-top:6px; }
.open a { display:block; padding:9px; border:1px solid var(--accent); border-radius:6px;
  color:var(--accent); text-align:center; text-decoration:none; font-weight:600; }
.open a:hover { background:var(--accent); color:var(--card); }
.open a:visited { opacity:.65; }
"""

_CSP = "default-src 'none'; img-src https://media.fab.com; style-src 'unsafe-inline'"


def _size_text(specs: dict) -> str | None:
    if specs.get("physical_size_m"):
        return " × ".join(f"{n:g}" for n in specs["physical_size_m"]) + " m"
    if specs.get("scan_area_m"):
        return " × ".join(f"{n:g}" for n in specs["scan_area_m"]) + " m scan"
    return None


def _status(item: dict) -> str:
    if item.get("free") is True:
        return '<span class="status free">Free</span>'
    if item.get("free") is False:
        return f'<span class="status paid">Not free yet ({escape(str(item.get("price")))})</span>'
    return '<span class="status unknown">Price unknown: check on Fab</span>'


def _card(rank: int, item: dict) -> str:
    specs = item.get("specs") or {}
    rows: list[tuple[str, str]] = []
    if size := _size_text(specs):
        rows.append(("Size", size))
    if density := specs.get("texel_density_px_per_m"):
        rows.append(("Density", f"{density} px/m"))
    if maps := specs.get("maps"):
        rows.append(("Maps", ", ".join(maps)))
    if file := item.get("recommended_file"):
        rows.append(("Get", f"{file['name']} ({file['size_mb']:g} MB)"))
    details = "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in rows)
    url = escape(item["url"], quote=True)
    title = escape(item.get("title") or "Untitled")
    image = item.get("preview_url")
    img = (
        f'<img src="{escape(image, quote=True)}" alt="{title}" loading="lazy" '
        'referrerpolicy="no-referrer">'
        if image
        else ""
    )
    note = f'<p class="note">{escape(item["note"])}</p>' if item.get("note") else ""
    return (
        f'<article><a class="image" href="{url}" target="_blank" rel="noopener noreferrer">{img}'
        f'<span class="rank">{rank}</span></a><div class="body"><h2>{title}</h2>{_status(item)}{note}'
        f'<dl>{details}</dl><div class="open"><a href="{url}" target="_blank" '
        'rel="noopener noreferrer">Open on Fab</a></div></div></article>'
    )


def render(title: str, items: list[dict], created: str) -> str:
    free = sum(1 for item in items if item.get("free") is True)
    cards = "".join(_card(rank, item) for rank, item in enumerate(items, 1))
    safe_title = escape(title)
    return (
        '<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{safe_title}</title><style>{_STYLE}</style></head><body>"
        f"<header><h1>{safe_title}</h1><p>{len(items)} Megascans assets, {free} free right now. "
        f"Created {escape(created)}. Opened links dim so you can see where you've been.</p></header>"
        f"<main>{cards}</main><footer><p>Prices and specs come from Fab when the list was made. "
        "Add an asset to your Fab library to get its licence; downloading alone may not be enough. "
        "Fab Standard License terms apply: no redistribution of assets on their own.</p></footer>"
        "</body></html>"
    )
