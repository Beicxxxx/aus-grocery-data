#!/usr/bin/env python3
"""Generate a self-contained HTML preview from the merged product table.

Usage:
    python scripts/preview.py --db data/grocery.db --out data/preview.html [--limit 400]

Reads ``merged_products`` (union of Woolworths + Coles + Open Food Facts)
and renders one comparison card per merged product: selected image, both
store names/prices, dietary tags, allergens, ingredients, nutrition.
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


def parse_merged_nutrition(value) -> dict:
    """Parse the merged nutrition_json ({"sources": {store: table}}).

    Returns {canonical_label: {"100g": str, "serve": str}} where the value is
    the first non-empty across Woolworths / Coles / Open Food Facts.
    """
    if not value:
        return {}
    try:
        data = json.loads(value)
    except ValueError:
        return {}
    sources = data.get("sources") or {}
    merged: dict = {}
    for label, table in sources.items():
        nutrients = {}
        if isinstance(table, dict) and "nutrients" in table:
            nutrients = table.get("nutrients") or {}
        elif isinstance(table, dict):
            nutrients = table  # OFF nutriments are flat
        for name, v in nutrients.items():
            key = canonical_nutrient(name)
            merged.setdefault(key, {})
            if isinstance(v, dict):
                merged[key].setdefault("100g", v.get("per_100g") or v.get("100g"))
                merged[key].setdefault("serve", v.get("per_serve") or v.get("Serve"))
            elif label == "OpenFoodFacts":
                merged[key].setdefault("100g", v)
    return {k: v for k, v in merged.items() if v.get("100g") or v.get("serve")}


def nutrition_rows(nutrition: dict) -> list[dict]:
    order = [
        "Energy (kJ)", "Energy (Cal)", "Protein", "Fat (Total)",
        "Fat (Saturated)", "Carbohydrate", "Sugars", "Sodium", "Calcium",
    ]
    labels = sorted(
        nutrition,
        key=lambda k: (order.index(k) if k in order else 99, k),
    )
    return [
        {"label": label, "100g": nutrition[label].get("100g"),
         "serve": nutrition[label].get("serve")}
        for label in labels
    ]


def price_highlight(ww_cents, co_cents) -> tuple[bool, bool]:
    if ww_cents is None or co_cents is None or ww_cents == co_cents:
        return False, False
    return ww_cents < co_cents, co_cents < ww_cents


def card(m: dict) -> str:
    ww_cheap, co_cheap = price_highlight(m.get("price_ww_cents"),
                                          m.get("price_coles_cents"))
    nut = parse_merged_nutrition(m.get("nutrition_json"))
    nut_rows = nutrition_rows(nut)
    dietary = split_list(m.get("dietary"))
    allergens = split_list(m.get("allergen_claims")) or split_list(m.get("allergens"))
    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in dietary[:10])
    allergen_chips = []
    for a in allergens[:10]:
        cls = "allergen-free" if "free" in a.lower() else "allergen-contains"
        allergen_chips.append(f'<span class="tag {cls}">{esc(a)}</span>')

    # Price strip: both stores side by side.
    def price_cell(label: str, cents, unit, cheaper: bool) -> str:
        return f"""
        <div class="price-cell">
          <span class="price-store">{esc(label)}</span>
          <span class="price-value">{money(cents)}</span>
          {f'<span class="price-unit">{esc(unit)}</span>' if unit else ''}
          {'<span class="cheaper">更便宜</span>' if cheaper else ''}
        </div>
        """
    prices = f"""
    <div class="prices">
      {price_cell('Woolworths', m.get('price_ww_cents'), m.get('unit_price_ww'), ww_cheap)}
      {price_cell('Coles', m.get('price_coles_cents'), m.get('unit_price_coles'), co_cheap)}
    </div>
    """

    info_rows = []
    if m.get("storage"):
        info_rows.append(f"<tr><th>储存</th><td>{esc(m['storage'])}</td></tr>")
    if m.get("usage"):
        info_rows.append(f"<tr><th>用法</th><td>{esc(m['usage'])}</td></tr>")
    if m.get("origin"):
        info_rows.append(f"<tr><th>原产国</th><td>{esc(m['origin'])}</td></tr>")
    info_html = (
        f"<table class='info'>{''.join(info_rows)}</table>" if info_rows else ""
    )

    nut_html = ""
    if nut_rows:
        rows = "".join(
            f"<tr><td>{esc(r['label'])}</td>"
            f"<td>{esc(r['100g']) or '—'}</td>"
            f"<td>{esc(r['serve']) or '—'}</td></tr>"
            for r in nut_rows
        )
        nut_html = f"""
        <details class="nutrition" open>
          <summary>营养信息（合并三家来源 · 每 100g / 每份）</summary>
          <table>
            <thead><tr><th>营养</th><th>每 100g</th><th>每份</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </details>
        """

    img = m.get("image_url")
    img_html = (
        f'<img src="{esc(img)}" alt="{esc(m.get("name_ww") or m.get("name_coles"))}" '
        'loading="lazy" onerror="this.parentNode.classList.add(\'noimg\')">'
        if img else '<div class="no-image">无图</div>'
    )
    name = m.get("name_ww") or m.get("name_coles") or ""
    brand = m.get("brand") or ""
    size = m.get("size_ww") or m.get("size_coles") or ""

    return f"""
    <article class="card" data-search="{esc(name).lower()}">
      <div class="card-head">
        <span>条码 {esc(m.get('barcode'))}</span>
        <span class="sources">图片来源：{esc(m.get('image_source') or '—')}</span>
      </div>
      <div class="merged">
        <div class="image-wrap">{img_html}</div>
        <div class="merged-main">
          <h3>{esc(name)}</h3>
          <p class="brand">{esc(brand)}{' · ' + esc(size) if size else ''}</p>
          {prices}
          <div class="tags">{tags}</div>
          <div class="allergens">{''.join(allergen_chips)}</div>
        </div>
      </div>
      <details class="ingredients">
        <summary>配料</summary>
        <p>{esc(m.get('ingredients')) or '未提供'}</p>
      </details>
      {info_html}
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
.merged {{ display:grid; grid-template-columns:220px 1fr; gap:18px; }}
@media (max-width:760px) {{ .merged {{ grid-template-columns:1fr; }} }}
.image-wrap {{ height:170px; display:flex; align-items:center; justify-content:center;
  background:#fafafa; border-radius:10px; overflow:hidden; margin:8px 0 10px; }}
.image-wrap img {{ max-height:100%; max-width:100%; object-fit:contain; }}
.image-wrap.noimg {{ background:repeating-linear-gradient(45deg,#f4f4f4,#f4f4f4 8px,#ececec 8px,#ececec 16px); }}
.no-image {{ color:#aaa; font-size:13px; }}
.merged-main h3 {{ margin:4px 0 2px; font-size:17px; line-height:1.35; }}
.brand {{ margin:2px 0; color:var(--muted); font-size:12px; }}
.prices {{ display:flex; gap:10px; margin:10px 0 8px; flex-wrap:wrap; }}
.price-cell {{ border:1px solid var(--line); border-radius:10px; padding:8px 14px;
  min-width:150px; background:#fbfbfb; }}
.price-store {{ display:block; font-size:11px; color:var(--muted); font-weight:700; }}
.price-value {{ font-size:22px; font-weight:800; }}
.price-cell:first-child .price-value {{ color:#00A650; }}
.price-cell:last-child .price-value {{ color:#E31B23; }}
.price-unit {{ font-size:11px; color:var(--muted); display:block; }}
.cheaper {{ font-size:11px; font-weight:700; color:#fff; background:#2e9e44;
  padding:2px 8px; border-radius:999px; margin-top:4px; display:inline-block; }}
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
.sources {{ display:inline-flex; gap:5px; }}
.source {{ font-size:10px; font-weight:700; color:#fff; padding:2px 8px;
  border-radius:999px; }}
.info {{ border-collapse:collapse; margin-top:10px; font-size:12px; }}
.info th {{ text-align:left; color:var(--muted); font-weight:600; width:70px;
  padding:3px 10px 3px 0; }}
.info td {{ padding:3px 0; color:#444; }}
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
    cols = [c[0] for c in conn.execute("SELECT * FROM merged_products LIMIT 0").description]
    rows = conn.execute("SELECT * FROM merged_products ORDER BY group_id").fetchall()
    total_cross = len(rows)
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    rendered = []
    for row in rows:
        m = dict(zip(cols, row))
        rendered.append({
            "html": card(m),
            "name": (m.get("name_ww") or "") + " " + (m.get("name_coles") or ""),
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
