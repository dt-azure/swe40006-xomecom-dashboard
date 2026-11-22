"""Draw the overview and per-component data flow diagrams as 1920x1080 (16:9) SVGs.

    python3 docs/diagrams/build_diagrams.py            # writes docs/diagrams/*.svg
    for f in docs/diagrams/*.svg; do rsvg-convert -w 3840 -h 2160 -b white "$f" -o "${f%.svg}.png"; done

No dependencies beyond the standard library. Layouts are placed by hand, so moving a box means
editing its coordinates below.
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT_DIR = Path(__file__).resolve().parent
WC, HC = 1920, 1080

INK, SUB, MUTED = "#1f2937", "#374151", "#4b5563"
EDGE, EDGE_SOFT, EDGE_FAIL = "#475569", "#94a3b8", "#c2413b"
FONT = "Inter, -apple-system, 'Helvetica Neue', Arial, sans-serif"
MONO = "'SF Mono', Menlo, Consolas, monospace"
STYLES = {
    "proc": ("#fff8eb", "#d48806"),
    "store": ("#eaf2ff", "#2f6fde"),
    "stream": ("#e7f7ee", "#15965a"),
    "serve": ("#fdecef", "#c23a57"),
    "bronze": ("#f7e8da", "#b4692b"),
    "silver": ("#eef1f5", "#7b8797"),
    "gold": ("#fbf1cc", "#c29408"),
    "decision": ("#f3efff", "#7c5cd6"),
    "ctx": ("#f8fafc", "#94a3b8"),
    "ok": ("#eaf8f0", "#15965a"),
    "fail": ("#fdeeee", "#c2413b"),
    "note": ("#f8fafc", "#cbd5e1"),
}
TEXT = {
    "title": (18, 700, INK, FONT, 24),
    "big": (21, 700, INK, FONT, 28),
    "sub": (14, 400, SUB, FONT, 19),
    "code": (13, 500, MUTED, MONO, 18),
}


class Diagram:
    def __init__(self, name, title, subtitle, legend="detail"):
        self.name = name
        self.out = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WC}" height="{HC}" viewBox="0 0 {WC} {HC}">',
            "<defs>"
            + "".join(
                f'<marker id="arr-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" '
                f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
                for k, c in (("hard", EDGE), ("soft", EDGE_SOFT), ("fail", EDGE_FAIL))
            )
            + "</defs>",
            f'<rect width="{WC}" height="{HC}" fill="#ffffff"/>',
        ]
        self.add(f'<text x="30" y="60" font-family="{FONT}" font-size="34" font-weight="800" fill="{INK}">{escape(title)}</text>')
        self.add(f'<text x="30" y="94" font-family="{FONT}" font-size="16.5" fill="{MUTED}">{escape(subtitle)}</text>')
        self.legend(legend)

    def add(self, s):
        self.out.append(s)

    # ---------- text ----------
    def lines(self, cx, cy, lines, anchor="middle"):
        lines = [(k, t) for k, t in lines if t]
        total = sum(TEXT[k][4] for k, _ in lines)
        y = cy - total / 2
        for kind, t in lines:
            size, weight, color, fam, lh = TEXT[kind]
            y += lh
            self.add(f'<text x="{cx:.1f}" y="{y - lh * 0.3:.1f}" text-anchor="{anchor}" font-family="{fam}" '
                     f'font-size="{size}" font-weight="{weight}" fill="{color}">{escape(t)}</text>')

    def text(self, x, y, t, size=14, weight=400, color=SUB, anchor="start", mono=False, halo=False):
        fam = MONO if mono else FONT
        h = ' stroke="#ffffff" stroke-width="5" stroke-linejoin="round" paint-order="stroke"' if halo else ""
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-family="{fam}" font-size="{size}" '
                 f'font-weight="{weight}" fill="{color}"{h}>{escape(t)}</text>')

    # ---------- shapes ----------
    def box(self, x, y, w, h, style, lines, r=12, dashed=None):
        fill, stroke = STYLES[style]
        dashed = style == "ctx" if dashed is None else dashed
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>')
        self.lines(x + w / 2, y + h / 2, lines)

    def pill(self, x, y, w, h, style, lines):
        self.box(x, y, w, h, style, lines, r=h / 2)

    def cyl(self, x, y, w, h, style, lines, dashed=False):
        fill, stroke = STYLES[style]
        ry = 12
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        self.add(f'<path d="M{x:.1f},{y + ry:.1f} L{x:.1f},{y + h - ry:.1f} A{w / 2:.1f},{ry} 0 0 0 {x + w:.1f},{y + h - ry:.1f} '
                 f'L{x + w:.1f},{y + ry:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>')
        self.add(f'<ellipse cx="{x + w / 2:.1f}" cy="{y + ry:.1f}" rx="{w / 2:.1f}" ry="{ry}" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>')
        self.lines(x + w / 2, y + h / 2 + ry * 0.6, lines)

    def hexa(self, x, y, w, h, style, lines):
        fill, stroke = STYLES[style]
        i = 18
        pts = [(x + i, y), (x + w - i, y), (x + w, y + h / 2), (x + w - i, y + h), (x + i, y + h), (x, y + h / 2)]
        self.add(f'<polygon points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="{fill}" stroke="{stroke}" stroke-width="2" stroke-linejoin="round"/>')
        self.lines(x + w / 2, y + h / 2, lines)

    def diamond(self, cx, cy, w, h, lines, style="decision"):
        fill, stroke = STYLES[style]
        pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
        self.add(f'<polygon points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="{fill}" stroke="{stroke}" stroke-width="2" stroke-linejoin="round"/>')
        self.lines(cx, cy, lines)

    def badge(self, x, y, n):
        self.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="{INK}"/>')
        self.add(f'<text x="{x:.1f}" y="{y + 5:.1f}" text-anchor="middle" font-family="{FONT}" font-size="14" font-weight="700" fill="#fff">{n}</text>')

    def panel(self, x, y, w, h, title, tint="#f8fafc", stroke="#d5dde8", dashed=False, title_at="top"):
        dash = ' stroke-dasharray="8 6"' if dashed else ""
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="18" fill="{tint}" stroke="{stroke}" stroke-width="1.5"{dash}/>')
        if title:
            ty = y + 27 if title_at == "top" else y + h - 14
            self.add(f'<text x="{x + 16:.1f}" y="{ty:.1f}" font-family="{FONT}" font-size="13.5" font-weight="700" '
                     f'letter-spacing="0.9" fill="#64748b">{escape(title)}</text>')

    def card(self, x, y, w, title, rows, row_h=26, style="note", key_size=14, val_size=13.5, header_style=None, key_w=None):
        """A list card. rows: (key, value, flag) with flag in {None, 'pk', 'tech', 'ref'}; key in mono."""
        fill, stroke = STYLES[style]
        hh = 44
        h = hh + row_h * len(rows) + 10
        hfill, hstroke = STYLES[header_style or style]
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" fill="#ffffff" stroke="{hstroke}" stroke-width="2"/>')
        self.add(f'<path d="M{x:.1f},{y + hh:.1f} L{x:.1f},{y + 12:.1f} Q{x:.1f},{y:.1f} {x + 12:.1f},{y:.1f} L{x + w - 12:.1f},{y:.1f} '
                 f'Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + 12:.1f} L{x + w:.1f},{y + hh:.1f} Z" fill="{hfill}" stroke="{hstroke}" stroke-width="2"/>')
        self.text(x + 16, y + 29, title, size=17, weight=700, color=INK)
        ry = y + hh + 5
        for key, val, *flag in rows:
            flag = flag[0] if flag else None
            if flag == "tech":
                self.add(f'<rect x="{x + 2:.1f}" y="{ry:.1f}" width="{w - 4:.1f}" height="{row_h:.1f}" fill="#f3efff"/>')
            kx = x + 16
            if flag == "pk":
                self.add(f'<rect x="{kx:.1f}" y="{ry + row_h / 2 - 9:.1f}" width="26" height="18" rx="4" fill="#fde68a"/>')
                self.text(kx + 13, ry + row_h / 2 + 4.5, "PK", size=10.5, weight=700, color="#78350f", anchor="middle")
                kx += 34
            if key_w is None:
                self.text(kx, ry + row_h / 2 + 5, key, size=key_size, weight=600, color=INK, mono=True)
                vcolor = "#2f6fde" if flag == "ref" else ("#6d28d9" if flag == "tech" else MUTED)
                self.text(x + w - 16, ry + row_h / 2 + 5, val, size=val_size, color=vcolor, anchor="end",
                          mono=flag not in ("ref",) and val[:1].islower() and " " not in val)
            else:
                self.text(kx, ry + row_h / 2 + 5, key, size=key_size, weight=600, color=INK, mono=True)
                self.text(x + key_w, ry + row_h / 2 + 5, val, size=val_size, color=SUB)
            ry += row_h
        return h

    def bullets(self, x, y, w, title, items, line_h=24, size=15):
        """A note card with bullet lines; items may contain '\n' for a wrapped continuation."""
        rows = []
        for it in items:
            parts = it.split("\n")
            rows.append(("•", parts[0]))
            rows += [("", p) for p in parts[1:]]
        h = 46 + line_h * len(rows) + 12
        fill, stroke = STYLES["note"]
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        self.text(x + 18, y + 31, title, size=16, weight=700, color=INK)
        ry = y + 46
        for b, t in rows:
            ry += line_h
            if b:
                self.text(x + 20, ry - 6, b, size=size, color="#64748b")
            self.text(x + 38, ry - 6, t, size=size, color=SUB)
        return h

    # ---------- edges ----------
    def edge(self, points, kind="hard", label=None, lpos=None, anchor="middle", both=False, r=12, dashed=None, size=13.5, arrow=True):
        color = {"hard": EDGE, "soft": EDGE_SOFT, "fail": EDGE_FAIL}[kind]
        dashed = kind == "soft" if dashed is None else dashed
        d = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
        for i in range(1, len(points) - 1):
            (x0, y0), (x1, y1), (x2, y2) = points[i - 1], points[i], points[i + 1]

            def towards(ax, ay, bx, by, dist):
                L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 or 1
                k = min(dist, L / 2) / L
                return ax + (bx - ax) * k, ay + (by - ay) * k

            p1, p2 = towards(x1, y1, x0, y0, r), towards(x1, y1, x2, y2, r)
            d += f" L{p1[0]:.1f},{p1[1]:.1f} Q{x1:.1f},{y1:.1f} {p2[0]:.1f},{p2[1]:.1f}"
        d += f" L{points[-1][0]:.1f},{points[-1][1]:.1f}"
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        start = f' marker-start="url(#arr-{kind})"' if both else ""
        end = f' marker-end="url(#arr-{kind})"' if arrow else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2"{dash}{end}{start}/>')
        if label:
            lx, ly = lpos
            for j, t in enumerate(label.split("\n")):
                self.text(lx, ly + j * 17, t, size=size, color="#7f1d1d" if kind == "fail" else "#334155", anchor=anchor, halo=True)

    # ---------- legend ----------
    def legend(self, kind):
        lx, ly = 1250, 34
        if kind == "overview":
            items = [("proc", "Process"), ("store", "Data store"), ("stream", "Stream"), ("serve", "Dashboard")]
        else:
            items = [("proc", "Step"), ("decision", "Decision"), ("store", "Data store"), ("ctx", "Other component")]
        x0 = lx
        for st, name in items:
            fill, stroke = STYLES[st]
            if st == "store":
                self.add(f'<path d="M{x0},{ly + 6} L{x0},{ly + 20} A14,5 0 0 0 {x0 + 28},{ly + 20} L{x0 + 28},{ly + 6}" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>')
                self.add(f'<ellipse cx="{x0 + 14}" cy="{ly + 6}" rx="14" ry="5" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>')
            elif st == "stream":
                self.add(f'<polygon points="{x0 + 6},{ly} {x0 + 22},{ly} {x0 + 28},{ly + 12} {x0 + 22},{ly + 24} {x0 + 6},{ly + 24} {x0},{ly + 12}" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>')
            elif st == "decision":
                self.add(f'<polygon points="{x0 + 14},{ly - 2} {x0 + 30},{ly + 12} {x0 + 14},{ly + 26} {x0 - 2},{ly + 12}" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>')
            else:
                dash = ' stroke-dasharray="4 3"' if st == "ctx" else ""
                self.add(f'<rect x="{x0}" y="{ly}" width="28" height="24" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.8"{dash}/>')
            self.text(x0 + 38, ly + 18, name, size=15)
            x0 += 52 + len(name) * 8.2
        ly2 = ly + 48
        self.add(f'<line x1="{lx}" y1="{ly2}" x2="{lx + 40}" y2="{ly2}" stroke="{EDGE}" stroke-width="2.2" marker-end="url(#arr-hard)"/>')
        self.text(lx + 50, ly2 + 5, "Data or control flow", size=15)
        self.add(f'<line x1="{lx + 230}" y1="{ly2}" x2="{lx + 270}" y2="{ly2}" stroke="{EDGE_SOFT}" stroke-width="2.2" stroke-dasharray="7 5" marker-end="url(#arr-soft)"/>')
        self.text(lx + 280, ly2 + 5, "Read-only or occasional", size=15)
        if kind != "overview":
            self.add(f'<line x1="{lx + 480}" y1="{ly2}" x2="{lx + 520}" y2="{ly2}" stroke="{EDGE_FAIL}" stroke-width="2.2" marker-end="url(#arr-fail)"/>')
            self.text(lx + 530, ly2 + 5, "Failure", size=15)

    def save(self):
        self.add("</svg>")
        path = OUT_DIR / f"{self.name}.svg"
        path.write_text("\n".join(self.out))
        print("wrote", path.relative_to(OUT_DIR.parent.parent))


def spread(widths, x0, x1):
    """Left edges for boxes of these widths spread evenly between x0 and x1."""
    gap = (x1 - x0 - sum(widths)) / (len(widths) - 1)
    xs, x = [], x0
    for w in widths:
        xs.append(x)
        x += w + gap
    return xs


# =====================================================================================
# 00 Overview
# =====================================================================================
def overview():
    d = Diagram("00-overview", "Xóm E-Com · Data flow overview",
                "The key components, left to right. Numbers match the detail diagrams 01–08.", legend="overview")
    W = [165, 165, 165, 165, 165, 500, 185]
    X = spread(W, 30, 1890)
    MY, MH = 400, 270
    MC = MY + MH / 2
    # warehouse panel with three layers
    wx, ww = X[5], W[5]
    d.panel(wx, 310, ww, 440, "WAREHOUSE · Postgres xom", "#f5f8fe", "#cddbf3")
    lw = 134
    LX = spread([lw] * 3, wx + 20, wx + ww - 20)
    # transform below the warehouse
    TX, TW, TY, TH = LX[1] - 60, LX[2] + lw - LX[1] + 120, 830, 150

    for i, lab in enumerate(["rows", "POST", "publish", "poll", "insert"]):
        tgt = X[i + 1] if i < 4 else LX[0]
        d.edge([(X[i] + W[i], MC), (tgt, MC)], label=lab, lpos=((X[i] + W[i] + tgt) / 2, MC - 12), size=15)
    d.edge([(LX[0] + lw, MC), (LX[1], MC)])
    d.edge([(LX[1] + lw, MC), (LX[2], MC)])
    d.edge([(LX[2] + lw, MC), (X[6], MC)], label="SQL", lpos=((LX[2] + lw + X[6]) / 2, MC - 12), size=15)
    d.edge([(LX[0] + lw / 2, MY + MH + 6), (LX[0] + lw / 2, TY + TH / 2), (TX, TY + TH / 2)], label="new rows?", lpos=(LX[0] + lw / 2 - 10, 795), anchor="end", size=15)
    d.edge([(LX[1] + lw / 2, TY), (LX[1] + lw / 2, MY + MH + 8)], label="builds", lpos=(LX[1] + lw / 2 + 10, 795), anchor="start", size=15)
    d.edge([(LX[2] + lw / 2, TY), (LX[2] + lw / 2, MY + MH + 8)])
    d.edge([(X[6] + W[6] / 2, MY), (X[6] + W[6] / 2, 255)])

    d.cyl(X[0], MY - 14, W[0], MH + 28, "store", [("big", "xom_source"), ("sub", "source database"), ("sub", "orders, customers,"), ("sub", "products, regions")])
    d.box(X[1], MY, W[1], MH, "proc", [("big", "Source poller"), ("sub", "sends new and"), ("sub", "changed rows"), ("sub", "every 5 s")])
    d.box(X[2], MY, W[2], MH, "proc", [("big", "Raw data API"), ("sub", "Flask"), ("sub", "checks and"), ("sub", "publishes records")])
    d.hexa(X[3], MY, W[3], MH, "stream", [("big", "Kafka"), ("code", "raw.ecom_records"), ("sub", "3 partitions")])
    d.box(X[4], MY, W[4], MH, "proc", [("big", "Bronze"), ("big", "consumer"), ("sub", "micro-batches"), ("sub", "into bronze")])
    d.cyl(LX[0], MY - 10, lw, MH + 20, "bronze", [("big", "bronze"), ("sub", "raw records,"), ("sub", "append-only")])
    d.cyl(LX[1], MY - 10, lw, MH + 20, "silver", [("big", "silver"), ("sub", "cleaned,"), ("sub", "latest version")])
    d.cyl(LX[2], MY - 10, lw, MH + 20, "gold", [("big", "gold"), ("sub", "star schema"), ("sub", "+ 4 marts")])
    d.box(TX, TY, TW, TH, "proc", [("big", "Transform runner + dbt"), ("sub", "every 30 s, when bronze has new rows"), ("sub", "82 data tests")])
    d.box(X[6], MY, W[6], MH, "serve", [("big", "CommercePulse"), ("sub", "Streamlit"), ("sub", "dashboard"), ("sub", "5 pages")])
    d.pill(X[6], 150, W[6], 105, "serve", [("big", "Business"), ("big", "users")])

    for n, (bx, by) in enumerate([(X[0], MY - 12), (X[1], MY), (X[2], MY), (X[3] + 12, MY), (X[4], MY),
                                  (wx, 310), (TX, TY), (X[6], MY)], start=1):
        d.badge(bx + 4, by + 4, n)
    d.text(30, 1040, "Live path: a new source row reaches bronze within seconds; gold is rebuilt at most every 30 s; "
           "the dashboard re-reads gold every 30 s.", size=16, color=MUTED)
    d.save()


# =====================================================================================
# 01 Source system
# =====================================================================================
def source_system():
    d = Diagram("01-source-system", "01 · Source system: xom_source",
                "The operational database the pipeline reads: four tables in schema e_commerce, without foreign keys.")
    rh = 27
    tables = [
        ("sales_line", [("row_id", "integer", "pk"), ("order_id", "varchar"), ("order_date", "date"),
                        ("customer_id", "→ customer", "ref"), ("segment", "varchar"), ("region_code", "→ region", "ref"),
                        ("product_code", "→ product", "ref"), ("quantity", "integer"), ("sales", "numeric"),
                        ("discount", "numeric"), ("profit", "numeric"), ("is_sample", "boolean", "tech"),
                        ("change_seq", "bigint", "tech")]),
        ("customer", [("customer_id", "varchar", "pk"), ("first_name", "varchar"), ("last_name", "varchar"),
                      ("birth_date", "date"), ("marital_status", "varchar"), ("gender", "varchar"),
                      ("email_address", "varchar"), ("annual_income", "integer"), ("education_level", "varchar"),
                      ("occupation", "varchar"), ("home_owner", "varchar"), ("is_sample", "boolean", "tech"),
                      ("change_seq", "bigint", "tech")]),
        ("product", [("product_code", "varchar", "pk"), ("product", "varchar"), ("category", "varchar"),
                     ("subcategory", "varchar"), ("is_sample", "boolean", "tech"), ("change_seq", "bigint", "tech")]),
        ("region", [("region_code", "varchar", "pk"), ("city", "varchar"), ("state", "varchar"), ("country", "varchar"),
                    ("country_latitude", "numeric"), ("country_longitude", "numeric"), ("region", "varchar"),
                    ("market", "varchar"), ("is_sample", "boolean", "tech"), ("change_seq", "bigint", "tech")]),
    ]
    TW = 345
    TX = spread([TW] * 4, 30, 1460)
    for (name, cols), x in zip(tables, TX):
        d.card(x, 132, TW, f"e_commerce.{name}", cols, row_h=rh, style="store", header_style="store")

    # right column: counts + legend
    d.card(1500, 132, 390, "Rows in the history", [
        ("sales_line", "51,290"), ("customer", "17,415"), ("product", "28,356"), ("region", "3,828")],
        row_h=30, style="note", val_size=15)
    d.bullets(1500, 340, 390, "Reading the tables", [
        "PK  primary key", "→  logical reference (no FK:\norphan references are kept)",
        "Purple rows: technical columns,\nnever part of a record's payload",
        "is_sample marks demo rows",
    ], line_h=24, size=14.5)

    # bottom: how changes become visible to the poller
    d.panel(30, 600, 1860, 450, "HOW THE POLLER SEES NEW AND CHANGED ROWS", "#fafafa", "#d5dde8")
    Y1, Y2, H = 690, 910, 104
    d.pill(60, Y1 + 12, 190, 80, "ctx", [("title", "INSERT a row")])
    d.pill(60, Y2 + 12, 190, 80, "ctx", [("title", "UPDATE a row")])
    d.box(320, Y1, 330, H, "proc", [("title", "change_seq = nextval()"), ("code", "sequence e_commerce.change_seq")])
    d.box(320, Y2, 330, H, "proc", [("title", "Trigger bump_change_seq"), ("sub", "sets a new, higher change_seq")])
    d.box(760, 790, 300, 120, "store", [("title", "Every row version"), ("sub", "has a unique change_seq,"), ("sub", "higher than all before it")])
    d.box(1150, 790, 380, 120, "proc", [("title", "Poller reads the next batch"), ("code", "WHERE change_seq > mark"), ("code", "ORDER BY change_seq LIMIT 1000")])
    d.box(1620, 800, 240, 100, "ctx", [("title", "Source poller"), ("sub", "see 02")])
    d.edge([(250, Y1 + 52), (320, Y1 + 52)])
    d.edge([(250, Y2 + 52), (320, Y2 + 52)])
    d.edge([(650, Y1 + 52), (705, Y1 + 52), (705, 830), (760, 830)])
    d.edge([(650, Y2 + 52), (705, Y2 + 52), (705, 870), (760, 870)])
    d.edge([(1060, 850), (1150, 850)], label="indexed", lpos=(1105, 840))
    d.edge([(1530, 850), (1620, 850)])
    d.save()


# =====================================================================================
# 02 Source poller
# =====================================================================================
def source_poller():
    d = Diagram("02-source-poller", "02 · Source poller",
                "Every 5 s, sends each table's new and changed rows to the API. Reads xom_source; writes only its own marks in ops.")
    W = [130, 210, 200, 150, 190, 200, 130, 200]
    X = spread(W, 30, 1890)
    CX = [X[i] + W[i] / 2 for i in range(len(W))]
    Y, H = 470, 120
    C = Y + H / 2

    # contexts
    d.cyl(X[2] - 150, 168, 220, 110, "store", [("title", "xom_source"), ("code", "4 tables")])
    d.cyl(X[7] - 30, 168, W[7] + 20, 110, "store", [("title", "ops.source_offsets"), ("sub", "mark per table")])
    d.box(X[5] - 10, 690, W[5] + 20, 100, "ctx", [("title", "Raw data API"), ("sub", "see 03")])
    d.box(X[6] - 25, 690, W[6] + 50 + 60, 100, "fail", [("title", "Stop the cycle"), ("sub", "mark unchanged,"), ("sub", "retry next tick")])

    # loops and context links
    d.edge([(CX[7] - 40, Y), (CX[7] - 40, 395), (CX[2] + 60, 395), (CX[2] + 60, Y)], label="repeat until the table is drained",
           lpos=((CX[2] + CX[7]) / 2 + 10, 386))
    d.edge([(CX[2] - 50, 290), (CX[2] - 50, Y)], label="rows", lpos=(CX[2] - 60, 380), anchor="end")
    d.edge([(CX[7] + 40, Y), (CX[7] + 40, 290)], label="save", lpos=(CX[7] + 50, 380), anchor="start")
    d.edge([(X[7] - 30, 222), (X[7] - 60, 222), (X[7] - 60, 140), (CX[2] + 10, 140), (CX[2] + 10, Y)],
           kind="soft", label="mark to start from", lpos=((CX[2] + X[7]) / 2, 132))
    d.edge([(CX[3], Y + H + 15), (CX[3], 650), (CX[1], 650), (CX[1], Y + H)], label="no: next table (after sales_line, wait for the next tick)",
           lpos=((CX[1] + CX[3]) / 2, 642))
    d.edge([(CX[5], Y + H), (CX[5], 690)], both=True, label="batch / reply", lpos=(CX[5] + 8, 650), anchor="start")
    d.edge([(CX[6], Y + H + 5), (CX[6], 690)], kind="fail", label="no", lpos=(CX[6] + 8, 650), anchor="start")

    # main row
    labels = [None, None, None, "yes", None, None, "yes"]
    for i in range(7):
        x0 = X[i] + W[i] if i not in (3, 6) else CX[i] + W[i] / 2
        x1 = X[i + 1] if i + 1 not in (3, 6) else CX[i + 1] - W[i + 1] / 2
        d.edge([(x0, C), (x1, C)], label=labels[i], lpos=((x0 + x1) / 2, C - 10))
    d.pill(X[0], Y + 20, W[0], H - 40, "ctx", [("title", "Every 5 s")])
    d.box(X[1], Y, W[1], H, "proc", [("title", "Next table"), ("sub", "customer, product,"), ("sub", "region, sales_line")])
    d.box(X[2], Y, W[2], H, "proc", [("title", "Read next batch"), ("sub", "change_seq > mark"), ("sub", "up to 1,000 rows")])
    d.diamond(CX[3], C, W[3], H + 30, [("title", "Rows"), ("title", "left?")])
    d.box(X[4], Y, W[4], H, "proc", [("title", "Wrap each row"), ("sub", "in the record"), ("sub", "envelope")])
    d.box(X[5], Y, W[5], H, "proc", [("title", "POST the batch"), ("code", "/api/v1/records")])
    d.diamond(CX[6], C, W[6], H + 30, [("title", "202?")])
    d.box(X[7], Y, W[7], H, "proc", [("title", "Save the mark"), ("sub", "last change_seq"), ("sub", "of the batch")])

    # envelope card
    d.card(30, 760, 900, "Record envelope (one per source row)", [
        ("source", "xom_ecom"), ("entity", "sales_line, customer, product or region"),
        ("record_id", "the source key as text"), ("event_at", "order_date for sales lines, otherwise null"),
        ("collected_at", "when the poller read the row"), ("is_sample", "copied from the source row"),
        ("source_version", "the row's change_seq"), ("payload", "the source row as JSON, without technical columns"),
    ], row_h=27, key_w=200, key_size=14, val_size=14.5)
    d.bullets(1180, 830, 710, "Why re-sending is safe", [
        "The mark moves only after a 202, so a failure re-sends the batch",
        "A crash between the 202 and saving the mark also re-sends it",
        "Bronze ignores a record version it already has",
    ], size=15)
    d.save()


# =====================================================================================
# 03 Raw data API
# =====================================================================================
def raw_data_api():
    d = Diagram("03-raw-data-api", "03 · Raw data API (Flask)",
                "Accepts records from the poller and publishes them to Kafka. It never writes the warehouse; it only reads bronze.")
    # lane A: POST
    d.panel(30, 128, 1860, 470, "POST /api/v1/records · WRITE PATH", "#fffdf8", "#f0dcb0")
    W = [180, 220, 170, 230, 230, 170, 200]
    X = spread(W, 60, 1860)
    CX = [X[i] + W[i] / 2 for i in range(len(W))]
    Y, H = 210, 120
    C = Y + H / 2
    for i, lab in enumerate([None, None, "yes", None, None, "yes"]):
        x0 = X[i] + W[i] if i not in (2, 5) else CX[i] + W[i] / 2
        x1 = X[i + 1] if i + 1 not in (2, 5) else CX[i + 1] - W[i + 1] / 2
        d.edge([(x0, C), (x1, C)], label=lab, lpos=((x0 + x1) / 2, C - 10))
    d.box(X[0], Y, W[0], H, "ctx", [("title", "Source poller"), ("sub", "see 02")])
    d.box(X[1], Y, W[1], H, "proc", [("title", "Read the body"), ("sub", "one record or a list"), ("sub", "at most 5,000")])
    d.diamond(CX[2], C, W[2], H + 40, [("title", "All"), ("title", "envelopes"), ("title", "valid?")])
    d.box(X[3], Y, W[3], H, "proc", [("title", "Publish each record"), ("sub", "message key"), ("code", "source:entity:record_id")])
    d.box(X[4], Y, W[4], H, "proc", [("title", "Flush"), ("sub", "wait until Kafka has"), ("sub", "acknowledged each one")])
    d.diamond(CX[5], C, W[5], H + 40, [("title", "All"), ("title", "acked?")])
    d.box(X[6], Y, W[6], H, "ok", [("title", "202 Accepted"), ("code", "{accepted: n}")])
    FY = 430
    d.edge([(CX[1], Y + H), (CX[1], FY)], kind="fail", label="> 5,000", lpos=(CX[1] + 8, 390), anchor="start")
    d.box(X[1], FY, W[1], 110, "fail", [("title", "413 Too Large")])
    d.edge([(CX[2], Y + H + 20), (CX[2], FY)], kind="fail", label="no", lpos=(CX[2] + 8, 390), anchor="start")
    d.box(CX[2] - 120, FY, 240, 110, "fail", [("title", "400 Bad Request"), ("sub", "nothing published")])
    d.edge([(CX[3], Y + H), (CX[3], FY)], label="produce", lpos=(CX[3] + 8, 390), anchor="start")
    d.hexa(X[3] - 10, FY, W[3] + 20, 110, "stream", [("title", "Kafka"), ("code", "raw.ecom_records")])
    d.edge([(X[3] + W[3] + 10, FY + 55), (CX[4], FY + 55), (CX[4], Y + H)], kind="soft", label="acks", lpos=(CX[4] - 30, FY + 47))
    d.edge([(CX[5], Y + H + 20), (CX[5], FY)], kind="fail", label="no (within 15 s)", lpos=(CX[5] + 8, 390), anchor="start")
    d.box(CX[5] - 120, FY, 240, 110, "fail", [("title", "503 Unavailable"), ("sub", "the poller retries")])

    # lane B: GET records
    d.panel(30, 618, 1110, 220, "GET /api/v1/records · READ PATH", "#f5f8fe", "#cddbf3")
    B = [170, 300, 200, 220]
    BX = spread(B, 60, 1110)
    BY, BH = 680, 120
    for i in range(3):
        d.edge([(BX[i] + B[i], BY + BH / 2), (BX[i + 1], BY + BH / 2)])
    d.box(BX[0], BY, B[0], BH, "ctx", [("title", "Client"), ("sub", "developer, tests")])
    d.box(BX[1], BY, B[1], BH, "proc", [("title", "Read query"), ("sub", "source, entity, page,"), ("sub", "page_size (default 100, max 500)")])
    d.cyl(BX[2], BY - 8, B[2], BH + 16, "bronze", [("title", "bronze"), ("code", "raw_records"), ("sub", "read-only")])
    d.box(BX[3], BY, B[3], BH, "ok", [("title", "200 OK"), ("sub", "records, total,"), ("sub", "next_page")])

    # lane C: other endpoints
    d.panel(30, 858, 1110, 192, "OTHER ENDPOINTS", "#fafafa", "#d5dde8")
    d.box(60, 912, 300, 110, "proc", [("title", "GET /api/v1/sources"), ("sub", "known sources")])
    d.edge([(360, 967), (420, 967)])
    d.box(420, 912, 230, 110, "ok", [("code", "xom_ecom:"), ("sub", "sales_line, customer,"), ("sub", "product, region")])
    d.box(700, 912, 200, 110, "proc", [("title", "GET /health"), ("sub", "no Kafka or DB call")])
    d.edge([(900, 967), (950, 967)])
    d.box(950, 912, 170, 110, "ok", [("code", "status: ok"), ("code", "version")])

    d.bullets(1170, 618, 720, "Envelope checks (same code as the consumer)", [
        "Every envelope field is present",
        "source is xom_ecom; entity is one of the four tables",
        "record_id is a non-empty string; is_sample is true or false",
        "payload is a JSON object",
        "source_version is a 64-bit integer or null",
        "No NaN, Infinity or NUL characters (Postgres cannot store them)",
        "One bad record rejects the whole request",
    ], line_h=26, size=15)
    d.save()


# =====================================================================================
# 04 Kafka
# =====================================================================================
def kafka():
    d = Diagram("04-kafka", "04 · Kafka",
                "One broker, one topic. Records are keyed by source row, so every version of a row lands in the same partition, in order.")
    # producer and consumer
    CY = 300
    d.card(30, CY, 400, "Producer: Raw data API", [
        ("acks", "all"), ("enable.idempotence", "true"), ("linger.ms", "5"), ("flush", "before each reply"),
        ("on failure", "API answers 503"),
    ], row_h=38, style="proc", header_style="proc", key_w=215, val_size=15)
    d.card(1490, CY, 400, "Consumer group: bronze-loader", [
        ("members", "1 (bronze consumer)"), ("enable.auto.commit", "false"), ("auto.offset.reset", "earliest"),
        ("batch", "≤ 1,000 msgs or 2 s"), ("commit", "after the DB commit"),
    ], row_h=38, style="proc", header_style="proc", key_w=215, val_size=15)
    MID = CY + 122
    # topic
    d.panel(520, 140, 880, 580, "TOPIC raw.ecom_records · 3 PARTITIONS · replication 1", "#f2fbf6", "#9fd8b8")
    PY = [215, 395, 575]
    for p, py in enumerate(PY):
        d.add(f'<rect x="545" y="{py + 18}" width="46" height="46" rx="8" fill="#15965a"/>')
        d.text(568, py + 48, f"P{p}", size=17, weight=800, color="#ffffff", anchor="middle")
        cw = 70
        for c in range(11):
            cx0 = 606 + c * cw
            filled = c < 9 - p
            fill = "#d3f1e0" if filled else "#ffffff"
            stroke = "#15965a" if filled else "#b6e3c9"
            d.add(f'<rect x="{cx0}" y="{py + 10}" width="{cw - 7}" height="62" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
            if filled:
                d.text(cx0 + (cw - 7) / 2, py + 47, str(c), size=16, color="#0f5132", anchor="middle", mono=True)
    d.text(606, PY[0] + 104, "offsets 0, 1, 2 … oldest to newest; each partition is an ordered log", size=14.5, color=MUTED)
    for py in PY:
        d.edge([(430, MID), (485, MID), (485, py + 41), (545, py + 41)])
        d.edge([(1376, py + 41), (1440, py + 41), (1440, MID), (1490, MID)])
    d.text(485, PY[0] + 22, "hash(key)", size=14.5, anchor="middle", halo=True)
    d.text(1450, MID - 10, "poll", size=14.5, anchor="start", halo=True)

    # message anatomy and broker
    d.card(30, 770, 900, "One message", [
        ("key", "xom_ecom:sales_line:48213"),
        ("value", "the JSON record envelope (see 02)"),
        ("order", "same key → same partition → versions stay in order"),
        ("delivery", "at least once; bronze ignores repeats"),
    ], row_h=50, key_w=140, key_size=15.5, val_size=16)
    d.bullets(990, 770, 900, "Broker setup", [
        "Single broker in KRaft mode (no ZooKeeper)",
        "Topic created once by kafka-init; auto-create is off",
        "Containers connect on kafka:19092; the host only on 127.0.0.1:9092",
        "No Schema Registry, Kafka Connect or stream processing",
        "Replays come from Kafka retention or from xom_source",
    ], line_h=40, size=16.5)
    d.save()


# =====================================================================================
# 05 Bronze consumer
# =====================================================================================
def bronze_consumer():
    d = Diagram("05-bronze-consumer", "05 · Bronze consumer",
                "Streams Kafka into bronze in micro-batches. Database commit first, Kafka offsets second, so a crash never loses a record.")
    W = [170, 220, 220, 290, 150, 230]
    X = spread(W, 30, 1890)
    CX = [X[i] + W[i] / 2 for i in range(len(W))]
    Y, H = 450, 160
    C = Y + H / 2
    for i, lab in enumerate(["poll", None, None, None, "yes"]):
        x0 = X[i] + W[i] if i != 4 else CX[i] + W[i] / 2
        x1 = X[i + 1] if i + 1 != 4 else CX[i + 1] - W[i + 1] / 2
        d.edge([(x0, C), (x1, C)], label=lab, lpos=((x0 + x1) / 2, C - 10))
    d.hexa(X[0], Y, W[0], H, "stream", [("title", "Kafka"), ("code", "raw.ecom_records")])
    d.box(X[1], Y, W[1], H, "proc", [("title", "Take a batch"), ("sub", "up to 1,000 messages"), ("sub", "or whatever arrived"), ("sub", "within 2 s")])
    d.box(X[2], Y, W[2], H, "proc", [("title", "Check each message"), ("sub", "parse JSON,"), ("sub", "validate envelope")])
    d.box(X[3], Y, W[3], H, "proc", [("title", "Write in one transaction"), ("sub", "valid rows, rejects"), ("sub", "and a run row")])
    d.diamond(CX[4], C, W[4], H + 30, [("title", "Database"), ("title", "commit"), ("title", "OK?")])
    d.box(X[5], Y, W[5], H, "proc", [("title", "Commit Kafka"), ("title", "offsets"), ("sub", "then the next batch")])

    # success loop (top) and failure path
    d.edge([(CX[5], Y), (CX[5], 175), (CX[1] - 40, 175), (CX[1] - 40, Y)], label="next batch", lpos=((CX[1] + CX[5]) / 2, 166))
    d.box(CX[4] - 145, 235, 290, 100, "fail", [("title", "Rewind to the batch start"), ("sub", "no offsets committed,"), ("sub", "back off up to 30 s")])
    d.edge([(CX[4], Y - 15), (CX[4], 335)], kind="fail", label="no", lpos=(CX[4] + 8, 390), anchor="start")
    d.edge([(CX[4] - 145, 285), (CX[1] + 40, 285), (CX[1] + 40, Y)], kind="fail", label="retry the same messages", lpos=((CX[1] + CX[4] - 145) / 2, 277))

    # outputs under the transaction
    OY = 730
    outs = [("bronze", "bronze.raw_records", ["one row per record version", "ON CONFLICT DO NOTHING:", "repeats are ignored"]),
            ("bronze", "bronze.rejected_records", ["invalid messages", "with the reason"]),
            ("store", "ops.pipeline_runs", ["one 'ingest' row per batch:", "loaded, rejected, duplicates"])]
    OW = 300
    OX = spread([OW] * 3, X[2] - 30, X[5] + W[5])
    for (st, t, subs), ox in zip(outs, OX):
        d.cyl(ox, OY, OW, 170, st, [("title", t)] + [("sub", s) for s in subs])
        d.edge([(CX[3], Y + H), (CX[3], 680), (ox + OW / 2, 680), (ox + OW / 2, OY)])
    d.text(CX[3] + 10, 665, "valid → raw_records · invalid → rejected_records · summary → pipeline_runs", size=14, halo=True)

    d.bullets(30, 730, 560, "Rules", [
        "Uses the same envelope check as the API",
        "A message that fails the check is stored as\nrejected; it never blocks the partition",
        "A row Postgres refuses is retried alone and\nrejected, so the rest of the batch lands",
        "On SIGTERM: finish and commit the batch, then exit",
    ], line_h=25, size=15)
    d.save()


# =====================================================================================
# 06 Warehouse layers
# =====================================================================================
def warehouse():
    d = Diagram("06-warehouse", "06 · Warehouse layers (Postgres xom)",
                "Bronze holds what arrived; dbt builds silver and gold from it. Arrows show which model reads which.")
    # panels
    d.panel(30, 130, 250, 920, "BRONZE", "#fcf5ee", "#e9c9a8")
    d.panel(300, 130, 330, 920, "SILVER", "#f6f8fa", "#d3d9e1")
    d.panel(650, 130, 1240, 920, "GOLD", "#fefaec", "#ecd88a")
    H = 104
    RY = [190, 330, 470, 640, 840]  # row tops
    S_X, S_W = 325, 280
    D_X, D_W = 690, 260
    F_X, F_W = 1030, 260
    M_X, M_W = 1370, 300
    rc = lambda r: RY[r] + H / 2

    # bronze
    d.cyl(50, 400, 210, 150, "bronze", [("title", "raw_records"), ("sub", "every record version"), ("sub", "jsonb payload"), ("sub", "append-only")])
    d.cyl(50, 640, 210, 120, "bronze", [("title", "rejected_records"), ("sub", "invalid messages")])
    d.box(50, 840, 210, 120, "store", [("title", "ops"), ("code", "pipeline_runs"), ("code", "source_offsets")])
    d.text(155, 990, "bookkeeping, not dbt", size=13.5, color=MUTED, anchor="middle")

    silver = [("stg_customers", "latest version"), ("stg_products", "latest version"), ("stg_regions", "latest version"),
              ("stg_sales_lines", "latest version, typed,\nnet_sales, discount_band")]
    for r, (name, desc) in enumerate(silver):
        d.edge([(260, 475), (290, 475), (290, rc(r)), (S_X, rc(r))])
        d.box(S_X, RY[r], S_W, H, "silver", [("title", name)] + [("sub", s) for s in desc.split("\n")] + [("code", "incremental")])
    d.box(S_X, RY[4], S_W, H + 20, "silver", [("title", "stg_sales_line_flags"), ("sub", "unknown customer, product,"),
                                               ("sub", "region; multi-customer order"), ("code", "table · reads all four")])

    dims = [("dim_customer", "per customer + unknown"), ("dim_product", "per product + unknown"),
            ("dim_region", "per city + unknown")]
    for r, (name, desc) in enumerate(dims):
        d.edge([(S_X + S_W, rc(r)), (D_X, rc(r))])
        d.box(D_X, RY[r], D_W, H, "gold", [("title", name), ("sub", desc)])
        d.edge([(D_X + D_W, rc(r)), (990, rc(r)), (990, rc(3) - 20)], arrow=False)
    d.edge([(S_X + S_W, rc(3) + 25), (660, rc(3) + 25), (660, rc(4)), (D_X, rc(4))])
    d.box(D_X, RY[4], D_W, H, "gold", [("title", "dim_date"), ("sub", "one row per day")])
    d.edge([(990, rc(3) - 30), (990, rc(3) - 20), (F_X, rc(3) - 20)], r=6)
    d.text(995, rc(3) - 30, "dims", size=13.5, halo=True)
    d.edge([(S_X + S_W, rc(3) + 15), (F_X, rc(3) + 15)])
    d.box(F_X, RY[3] - 30, F_W, H + 60, "gold", [("title", "fct_sales_lines"), ("sub", "one row per sales line,"),
                                                 ("sub", "keys to every dimension"), ("code", "incremental")])

    marts = [("mart_discount_impact", "month × category × band", "also dim_product"),
             ("mart_segment_pnl", "quarter × segment", None),
             ("mart_market_growth", "year × market × region", "also dim_region"),
             ("mart_customer_retention", "cohort × months since", None)]
    MY = [190, 370, 550, 730]
    for (name, grain, extra), my in zip(marts, MY):
        d.edge([(F_X + F_W, rc(3)), (1330, rc(3)), (1330, my + 55), (M_X, my + 55)])
        d.box(M_X, my, M_W, 110, "gold", [("title", name), ("sub", grain), ("code", extra)])
    d.bullets(1030, 880, 840, "How dbt builds it", [
        "dbt build every 30 s with 82 data tests; a failing test leaves gold as it was",
        "incremental: merges new bronze rows (10-minute lookback); table: rebuilt each run",
        "Every gold table carries is_sample, so demo rows can be shown or hidden",
    ], line_h=27, size=15)
    d.save()


# =====================================================================================
# 07 Transform runner
# =====================================================================================
def transform_runner():
    d = Diagram("07-transform-runner", "07 · Transform runner + dbt",
                "Every 30 s, runs dbt build when bronze has rows the last successful build has not seen. Runs never overlap.")
    W = [140, 240, 230, 250, 160, 230]
    X = spread(W, 30, 1890)
    CX = [X[i] + W[i] / 2 for i in range(len(W))]
    Y, H = 300, 130
    C = Y + H / 2
    for i in range(4):
        x0 = X[i] + W[i]
        x1 = X[i + 1] if i + 1 != 4 else CX[4] - W[4] / 2
        d.edge([(x0, C), (x1, C)])
    d.edge([(CX[4] + W[4] / 2, C), (X[5], C)], label="no", lpos=((CX[4] + W[4] / 2 + X[5]) / 2, C - 10))
    d.pill(X[0], Y + 25, W[0], H - 50, "ctx", [("title", "Every 30 s")])
    d.box(X[1], Y, W[1], H, "proc", [("title", "Close interrupted runs"), ("sub", "'running' → 'failed'"), ("code", "ops.pipeline_runs")])
    d.box(X[2], Y, W[2], H, "proc", [("title", "Read the watermark"), ("sub", "of the last successful run"), ("code", "ops.pipeline_runs")])
    d.box(X[3], Y, W[3], H, "proc", [("title", "Read bronze high mark"), ("code", "max(ingested_at)")])
    d.diamond(CX[4], C, W[4], H + 40, [("title", "Newer"), ("title", "rows?")])
    d.box(X[5], Y + 15, W[5], H - 30, "ctx", [("title", "Wait for the next tick"), ("sub", "nothing recorded")])
    d.cyl(X[3] + 20, 150, W[3] - 40, 100, "bronze", [("title", "bronze"), ("code", "raw_records")])
    d.edge([(CX[3], 250), (CX[3], Y)], kind="soft")

    # row 2
    W2 = [250, 300, 160, 330]
    X2 = spread(W2, 300, 1890)
    CX2 = [X2[i] + W2[i] / 2 for i in range(len(W2))]
    Y2, H2 = 600, 150
    C2 = Y2 + H2 / 2
    d.edge([(CX[4], Y + H + 20), (CX[4], 510), (CX2[0], 510), (CX2[0], Y2)], label="yes", lpos=(CX[4] + 10, 490), anchor="start")
    d.edge([(X2[0] + W2[0], C2), (X2[1], C2)])
    d.edge([(X2[1] + W2[1], C2), (CX2[2] - W2[2] / 2, C2)])
    d.edge([(CX2[2] + W2[2] / 2, C2), (X2[3], C2)], label="yes", lpos=((CX2[2] + W2[2] / 2 + X2[3]) / 2, C2 - 10))
    d.box(X2[0], Y2, W2[0], H2, "proc", [("title", "Record a run"), ("sub", "status 'running'"), ("code", "ops.pipeline_runs")])
    d.box(X2[1], Y2, W2[1], H2, "proc", [("title", "dbt build"), ("sub", "silver and gold models"), ("sub", "+ 82 data tests"), ("sub", "timeout 600 s")])
    d.diamond(CX2[2], C2, W2[2], H2 + 30, [("title", "All"), ("title", "passed?")])
    d.box(X2[3], Y2, W2[3], H2, "ok", [("title", "Record 'success'"), ("sub", "new watermark = the bronze"), ("sub", "high mark read before dbt"), ("sub", "rows_loaded = new rows")])
    d.edge([(CX2[2], C2 + H2 / 2 + 15), (CX2[2], 880)], kind="fail", label="no", lpos=(CX2[2] + 8, 860), anchor="start")
    d.box(CX2[2] - 190, 880, 380, 130, "fail", [("title", "Record 'failed'"), ("sub", "no new watermark; dbt summary"), ("sub", "and failing tests in message;"), ("sub", "retried on the next tick")])
    # dbt targets
    d.cyl(CX2[1] - 150, 860, 140, 110, "silver", [("title", "silver")])
    d.cyl(CX2[1] + 10, 860, 140, 110, "gold", [("title", "gold")])
    d.edge([(CX2[1] - 80, Y2 + H2), (CX2[1] - 80, 860)])
    d.edge([(CX2[1] + 80, Y2 + H2), (CX2[1] + 80, 860)])
    d.text(CX2[1] - 8, 830, "builds", size=13.5, anchor="end", halo=True)

    d.bullets(30, 600, 240, "Good to know", [
        "A failed test leaves\nthe old gold in place",
        "The dashboard shows\ndata as stale after\n2 min without success",
        "Bronze rows landing\nduring a build trigger\nthe next cycle",
    ], line_h=23, size=14.5)
    d.save()


# =====================================================================================
# 08 Dashboard
# =====================================================================================
def dashboard():
    d = Diagram("08-dashboard", "08 · CommercePulse dashboard (Streamlit)",
                "Reads gold in one consistent, read-only transaction, caches it for 30 s, and filters it in memory for five pages.")
    # gold inputs
    d.panel(30, 130, 380, 920, "WAREHOUSE · read-only", "#fefaec", "#ecd88a")
    d.cyl(55, 190, 330, 220, "gold", [("title", "Sales lines"), ("code", "fct_sales_lines"), ("sub", "joined to"), ("code", "dim_customer"), ("code", "dim_product"), ("code", "dim_region")])
    d.cyl(55, 450, 330, 110, "gold", [("title", "Calendar bounds"), ("code", "dim_date")])
    d.cyl(55, 600, 330, 200, "gold", [("title", "Marts"), ("code", "mart_segment_pnl"), ("code", "mart_customer_retention"), ("code", "mart_discount_impact"), ("code", "mart_market_growth")])
    d.cyl(55, 840, 330, 110, "store", [("title", "ops.pipeline_runs"), ("sub", "not read yet")], dashed=True)

    RX, RW = 470, 260
    RY, RH = 420, 200
    for y in (300, 505, 700):
        d.edge([(385, y), (440, y), (440, RY + RH / 2), (RX, RY + RH / 2)])
    d.box(RX, RY, RW, RH, "proc", [("title", "Read gold"), ("sub", "one REPEATABLE READ,"), ("sub", "read-only transaction"), ("sub", "+ row count per table")])
    d.text(RX + RW / 2, RY + RH + 34, "DASHBOARD_DATABASE_URL", size=13.5, color=MUTED, anchor="middle", mono=True)
    CXp, CW = 790, 220
    d.edge([(RX + RW, RY + RH / 2), (CXp, RY + RH / 2)])
    d.box(CXp, RY, CW, RH, "proc", [("title", "Cache"), ("sub", "30 s in memory"), ("sub", "re-read on the next"), ("sub", "interaction after expiry")])
    FX, FW = 1070, 270
    d.edge([(CXp + CW, RY + RH / 2), (FX, RY + RH / 2)])
    d.box(FX, RY - 60, FW, RH + 120, "proc", [("title", "Filters"), ("sub", "Gold data:"), ("sub", "historical only, include"), ("sub", "sample rows, sample only"),
                                             ("sub", "Date range"), ("sub", "Comparison: previous"), ("sub", "year or period, or none")])
    pages = [("Overview", "KPIs, segment P&L,", "retention cohorts"), ("Sales Trend", "daily net sales", "and orders"),
             ("Categories", "categories, products,", "discount impact"), ("Geography", "markets, countries,", "market growth"),
             ("Pipeline Health", "readable tables, row", "counts, read time")]
    PX, PW, PH = 1400, 280, 150
    PY = spread([PH] * 5, 140, 1045)
    PY = [140 + i * 182 for i in range(5)]
    for (t, a, b), py in zip(pages, PY):
        d.edge([(FX + FW, RY + RH / 2), (1370, RY + RH / 2), (1370, py + PH / 2), (PX, py + PH / 2)])
        d.box(PX, py, PW, PH, "serve", [("title", t), ("sub", a), ("sub", b)])
        d.edge([(PX + PW, py + PH / 2), (1720, py + PH / 2), (1720, 520), (1745, 520)])
    d.pill(1745, 470, 145, 100, "serve", [("title", "Business"), ("title", "users")])
    d.bullets(470, 760, 870, "Notes", [
        "Sample rows are labelled is_sample in every gold table; the Gold data filter shows or hides them",
        "Unknown customer, product or region rows show as 'Unknown', so totals still add up",
        "Run history and staleness alerts wait for an agreed ops.pipeline_runs contract",
    ], line_h=27, size=15)
    d.save()


if __name__ == "__main__":
    for fn in (overview, source_system, source_poller, raw_data_api, kafka, bronze_consumer, warehouse,
               transform_runner, dashboard):
        fn()
