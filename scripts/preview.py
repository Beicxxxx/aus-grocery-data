#!/usr/bin/env python3
"""Generate a self-contained HTML preview of cross-store product groups.

Usage:
    python scripts/preview.py --db data/grocery.db --out data/preview.html [--limit 400]

Reads ``product_groups``/``product_group_members`` from the SQLite database
and renders one comparison card per cross-store group (both stores side by
side: image, name, price, dietary tags, allergens, ingredients, nutrition).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


STORE_STYLE = {
    "Woolworths": ("#00A650", "#E6F7EC"),
    "Coles": ("#E31B23", "#FDECEC"),
}


def money(cents) -> str:
    if cents is None:
        return "—"
    return f"${cents / 100:.2f}"


def esc(value) -> str:
    return html.escape(str(value or ""))


def split_list(value) -> list[str]:
    if not value:
        return []
    out = [x.strip() for x in str(value).split(",") if x.strip() and x.strip() != "None"]
    return out


def canonical_nutrient(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]", " ", str(name).lower())
    n = " ".join(n.split())
    for prefix, label in (
        ("energy kj", "Energy (kJ)"),
        ("energy cal", "Energy (Cal)"),
        ("energy", "Energy (kJ)"),
        ("protein", "Protein"),
        ("fat saturated", "Fat (Saturated)"),
        ("fat total", "Fat (Total)"),
        ("fat", "Fat"),
        ("carbohydrate", "Carbohydrate"),
        ("sugars total", "Sugars"),
        ("sugar", "Sugars"),
        ("sodium", "Sodium"),
        ("calcium", "Calcium"),
    ):
        if n.startswith(prefix):
            return label
    return str(name)


def load_nutrition(row: dict) -> dict:
    """Return {canonical_label: {"100g": str, "serve": str}}."""
    raw = row.get("nutrition_json")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    nutrients = data.get("nutrients") or {}
    out = {}
    for name, v in nutrients.items():
        label = canonical_nutrient(name)
        out.setdefault(label, {})
        if isinstance(v, dict):
            if "per_100g" in v:
                out[label]["100g"] = v["per_100g"]
            if "per_serve" in v:
                out[label]["serve"] = v["per_serve"]
            if "Serve" in v:
                out[label]["serve"] = v["Serve"]
            if "100g" in v:
                out[label]["100g"] = v["100g"]
    return out


def nutrition_rows(ww: dict, co: dict) -> list[dict]:
    w = load_nutrition(ww)
    c = load_nutrition(co)
    labels: list[str] = []
    for d in (w, c):
        for k in d:
            if k not in labels:
                labels.append(k)
    order = [
        "Energy (kJ)", "Energy (Cal)", "Protein", "Fat (Total)",
        "Fat (Saturated)", "Carbohydrate", "Sugars", "Sodium", "Calcium",
    ]
    labels.sort(key=lambda k: (order.index(k) if k in order else 99, k))
    rows = []
    for label in labels:
        rows.append({
            "label": label,
            "ww100": w.get(label, {}).get("100g"),
            "co100": c.get(label, {}).get("100g"),
            "wwserve": w.get(label, {}).get("serve"),
            "coserve": c.get(label, {}).get("serve"),
        })
    return rows


def price_highlight(ww_cents, co_cents) -> tuple[bool, bool]:
    if ww_cents is None or co_cents is None or ww_cents == co_cents:
        return False, False
    return ww_cents < co_cents, co_cents < ww_cents


def card(group_id: int, ww: dict, co: dict, method: str) -> str:
    ww_cheap, co_cheap = price_highlight(ww["price_cents"], co["price_cents"])
    ww_nut = load_nutrition(ww)
    co_nut = load_nutrition(co)
    nut_rows = nutrition_rows(ww, co)

    def store_panel(store: str, p: dict, cheaper: bool) -> str:
        color, bg = STORE_STYLE[store]
        dietary = split_list(p.get("dietary"))
        allergens = split_list(p.get("allergen_claims")) or split_list(p.get("allergens"))
        tags = "".join(
            f'<span class="tag">{esc(t)}</span>' for t in dietary[:8]
        )
        allergen_chips = []
        for a in allergens[:8]:
            cls = "allergen-free" if "free" in a.lower() else "allergen-contains"
            allergen_chips.append(f'<span class="tag {cls}">{esc(a)}</span>')
        price_extra = (
            '<span class="cheaper">更便宜</span>' if cheaper else ""
        )
        info_lines = []
        if p.get("storage"):
            info_lines.append(f"储存：{esc(p['storage'])}")
        if p.get("usage"):
            info_lines.append(f"用法：{esc(p['usage'])}")
        if p.get("origin"):
            info_lines.append(f"原产：{esc(p['origin'])}")
        info_html = "".join(f'<p class="meta">{x}</p>' for x in info_lines)
        img = p.get("image_url")
        img_html = (
            f'<img src="{esc(img)}" alt="{esc(p.get("name"))}" '
            'loading="lazy" onerror="this.parentNode.classList.add(\'noimg\')">'
            if img else '<div class="no-image">无图</div>'
        )
        return f"""
        <div class="panel" style="--accent:{color};--accent-bg:{bg}">
          <div class="store-badge" style="background:{color}">{store}</div>
          <div class="image-wrap">{img_html}</div>
          <h3>{esc(p.get('name'))}</h3>
          <p class="brand">{esc(p.get('brand'))}{' · ' + esc(p.get('size')) if p.get('size') else ''}</p>
          <p class="price">{money(p.get('price_cents'))}{price_extra}</p>
          {f'<p class="unit">{esc(p.get("unit_price"))}</p>' if p.get('unit_price') else ''}
          <p class="barcode">条码 {esc(p.get('barcode'))}</p>
          <div class="tags">{tags}</div>
          <div class="allergens">{''.join(allergen_chips)}</div>
          <details class="ingredients">
            <summary>配料</summary>
            <p>{esc(p.get('ingredients')) or '未提供'}</p>
          </details>
          {info_html}
        </div>
        """

    nut_html = ""
    if nut_rows:
        rows = "".join(
            f"<tr><td>{esc(r['label'])}</td>"
            f"<td>{esc(r['ww100']) or '—'}</td><td>{esc(r['co100']) or '—'}</td>"
            f"<td>{esc(r['wwserve']) or '—'}</td><td>{esc(r['coserve']) or '—'}</td></tr>"
            for r in nut_rows
        )
        nut_html = f"""
        <details class="nutrition" open>
          <summary>营养信息（每 100g / 每份）</summary>
          <table>
            <thead><tr><th>营养</th><th>WW 100g</th><th>Coles 100g</th>
            <th>WW 每份</th><th>Coles 每份</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </details>
        """

    return f"""
    <article class="card" data-search="{esc((ww.get('name') or '') + ' ' + (co.get('name') or '')).lower()}">
      <div class="card-head">
        <span class="method">匹配方式：{esc(method)}</span>
        <span class="group-id">组 #{group_id}</span>
      </div>
      <div class="columns">
        {store_panel('Woolworths', ww, ww_cheap)}
        {store_panel('Coles', co, co_cheap)}
      </div>
      {nut_html}
    </article>
    """


def build_page(groups: list[dict], total_cross: int, total_products: int,
               generated: str, limit: int | None) -> str:
    cards = "\n".join(g["html"] for g in groups)
    shown = f"前 {limit} 组" if limit and limit < len(groups) else f"全部 {len(groups)} 组"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>双店商品对比预览</title>
<style>
:root {{
  --ink:#222; --muted:#777; --line:#e5e5e5; --card-bg:#fff; --page-bg:#f6f7f9;
}}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
  background:var(--page-bg); color:var(--ink); }}
.header {{ background:#1b1b2f; color:#fff; padding:26px 32px; }}
.header h1 {{ margin:0 0 6px; font-size:22px; }}
.header p {{ margin:4px 0; color:#b9b9d6; font-size:13px; }}
.stats {{ display:flex; gap:26px; margin-top:14px; flex-wrap:wrap; }}
.stat b {{ display:block; font-size:24px; color:#ffd166; }}
.stat span {{ font-size:12px; color:#b9b9d6; }}
.toolbar {{ position:sticky; top:0; z-index:5; background:#fff; padding:12px 32px;
  border-bottom:1px solid var(--line); display:flex; gap:12px; align-items:center; }}
.toolbar input {{ flex:1; max-width:520px; padding:9px 14px; border:1px solid #ccc;
  border-radius:8px; font-size:14px; }}
.toolbar .hint {{ color:var(--muted); font-size:12px; }}
main {{ padding:20px 32px 60px; max-width:1280px; margin:0 auto; }}
.card {{ background:var(--card-bg); border:1px solid var(--line); border-radius:14px;
  padding:18px; margin-bottom:22px; box-shadow:0 1px 3px rgba(0,0,0,.05); }}
.card-head {{ display:flex; justify-content:space-between; margin-bottom:10px;
  font-size:12px; color:var(--muted); }}
.columns {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
@media (max-width:820px) {{ .columns {{ grid-template-columns:1fr; }} }}
.panel {{ border:1px solid var(--line); border-radius:12px; padding:14px; position:relative; }}
.store-badge {{ position:absolute; top:-10px; left:14px; color:#fff; font-size:11px;
  font-weight:700; padding:3px 12px; border-radius:999px; }}
.image-wrap {{ height:170px; display:flex; align-items:center; justify-content:center;
  background:#fafafa; border-radius:10px; overflow:hidden; margin:8px 0 10px; }}
.image-wrap img {{ max-height:100%; max-width:100%; object-fit:contain; }}
.image-wrap.noimg {{ background:repeating-linear-gradient(45deg,#f4f4f4,#f4f4f4 8px,#ececec 8px,#ececec 16px); }}
.no-image {{ color:#aaa; font-size:13px; }}
.panel h3 {{ margin:6px 0 2px; font-size:15px; line-height:1.35; }}
.brand {{ margin:2px 0; color:var(--muted); font-size:12px; }}
.price {{ margin:8px 0 2px; font-size:26px; font-weight:800; color:var(--accent); }}
.cheaper {{ font-size:12px; font-weight:700; color:#fff; background:#2e9e44;
  padding:2px 8px; border-radius:999px; margin-left:8px; vertical-align:middle; }}
.unit {{ margin:0; color:var(--muted); font-size:12px; }}
.barcode {{ margin:4px 0 0; color:#aaa; font-size:11px; }}
.tags {{ margin-top:8px; display:flex; flex-wrap:wrap; gap:5px; }}
.tag {{ font-size:11px; background:#eef2ff; color:#3b4a8f; border-radius:999px;
  padding:3px 9px; }}
.allergens {{ margin-top:6px; display:flex; flex-wrap:wrap; gap:5px; }}
.allergen-free {{ background:#e6f7ec; color:#1e7a3a; }}
.allergen-contains {{ background:#fdecec; color:#b3261e; }}
.ingredients {{ margin-top:10px; font-size:13px; }}
.ingredients summary {{ cursor:pointer; color:var(--accent); font-weight:600; }}
.ingredients p {{ margin:6px 0 0; color:#444; line-height:1.5; }}
.meta {{ margin:6px 0 0; font-size:12px; color:#666; }}
.nutrition {{ margin-top:14px; border-top:1px dashed var(--line); padding-top:10px; }}
.nutrition summary {{ cursor:pointer; font-weight:700; font-size:13px; color:var(--ink); }}
.nutrition table {{ width:100%; border-collapse:collapse; margin-top:8px; font-size:12px; }}
.nutrition th,.nutrition td {{ border:1px solid #ececec; padding:5px 8px; text-align:right; }}
.nutrition th {{ background:#fafafa; font-weight:600; }}
.nutrition td:first-child {{ text-align:left; font-weight:600; }}
.empty {{ display:none; text-align:center; padding:60px; color:#999; }}
.footer {{ color:#999; font-size:12px; padding:16px 32px 40px; }}
</style>
</head>
<body>
<div class="header">
  <h1>双店商品对比预览</h1>
  <p>Woolworths × Coles · 生成时间 {esc(generated)} · 数据采集自两家零售商公开页面，仅供参考</p>
  <div class="stats">
    <div class="stat"><b>{total_cross:,}</b><span>跨店可比组</span></div>
    <div class="stat"><b>{total_products:,}</b><span>商品总数</span></div>
    <div class="stat"><b>{shown}</b><span>本页展示</span></div>
  </div>
</div>
<div class="toolbar">
  <input id="q" type="search" placeholder="搜索商品名…（如：Chobani、牛奶、鸡蛋）" oninput="filterCards()">
  <span class="hint" id="count"></span>
</div>
<main id="cards">{cards}</main>
<div class="empty" id="empty">没有匹配的商品</div>
<div class="footer">
  免责声明：信息来自 Woolworths / Coles 公开页面与 Open Food Facts，采集于特定日期；
  食用前请以商品实物标签为准。预览仅用于课程项目演示。
</div>
<script>
function filterCards(){{
  const q = document.getElementById('q').value.trim().toLowerCase();
  let n = 0;
  document.querySelectorAll('.card').forEach(c => {{
    const hit = !q || c.dataset.search.includes(q);
    c.style.display = hit ? '' : 'none';
    if (hit) n++;
  }});
  document.getElementById('count').textContent = '显示 ' + n + ' 组';
  document.getElementById('empty').style.display = n ? 'none' : 'block';
}}
filterCards();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/grocery.db")
    ap.add_argument("--out", default="data/preview.html")
    ap.add_argument("--limit", type=int, default=400,
                    help="max cross-store groups to render (default 400)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    groups = conn.execute(
        """
        SELECT g.group_id, g.method,
               w.product_id, w.name, w.brand, w.size, w.price_cents,
               w.unit_price, w.image_url, w.barcode, w.ingredients,
               w.dietary, w.allergen_claims, w.allergens, w.nutrition_json,
               w.storage, w.usage, w.origin,
               c.product_id, c.name, c.brand, c.size, c.price_cents,
               c.unit_price, c.image_url, c.barcode, c.ingredients,
               c.dietary, c.allergen_claims, c.allergens, c.nutrition_json,
               c.storage, c.usage, c.origin
        FROM product_groups g
        JOIN product_group_members mw
          ON mw.group_id = g.group_id AND mw.store = 'Woolworths'
        JOIN product_group_members mc
          ON mc.group_id = g.group_id AND mc.store = 'Coles'
        JOIN products w ON w.store = mw.store AND w.product_id = mw.product_id
        JOIN products c ON c.store = mc.store AND c.product_id = mc.product_id
        ORDER BY g.group_id
        """
    ).fetchall()
    total_cross = len(groups)
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    cols = [
        "group_id", "method",
        "ww_product_id", "ww_name", "ww_brand", "ww_size", "ww_price_cents",
        "ww_unit_price", "ww_image_url", "ww_barcode", "ww_ingredients", "ww_dietary",
        "ww_allergen_claims", "ww_allergens", "ww_nutrition_json",
        "ww_storage", "ww_usage", "ww_origin",
        "co_product_id", "co_name", "co_brand", "co_size", "co_price_cents",
        "co_unit_price", "co_image_url", "co_barcode", "co_ingredients", "co_dietary",
        "co_allergen_claims", "co_allergens", "co_nutrition_json",
        "co_storage", "co_usage", "co_origin",
    ]

    def product_dict(row: tuple, prefix: str) -> dict:
        p = {}
        for i, col in enumerate(cols):
            if col.startswith(prefix):
                p[col[len(prefix):]] = row[i]
        return p

    rendered = []
    for row in groups:
        ww = product_dict(row, "ww_")
        co = product_dict(row, "co_")
        rendered.append({
            "html": card(row[0], ww, co, row[1]),
            "name": (ww.get("name") or "") + " " + (co.get("name") or ""),
        })

    if args.limit and len(rendered) > args.limit:
        rendered = rendered[:args.limit]
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", " UTC")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        build_page(rendered, total_cross, total_products, generated, args.limit),
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(rendered)} cards, {total_cross} cross-store groups in DB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
