"""The README figures, drawn from the marts by code.

Both figures ask the same question of the finished warehouse: how different
would the numbers be if every claim were reported under the insured's
*current* attributes, which is what "keep the last record" does? The dims
hold both answers, one join apart, so the comparison is a query, not an
argument.
"""

from pathlib import Path

import psycopg2

from estrato.config import Postgres

# Two categorical slots of a colorblind-safe palette, plus ink and grid
# tones. "As it was" is the warehouse's answer; "as it looks today" is the
# overwrite's.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"

DRIFT_SQL = """
select
    extract(year from f.occurrence_date)::int as year,
    count(*) as claims,
    count(*) filter (where p_at.in_programme <> p_now.in_programme) as programme,
    count(*) filter (where i_at.region is distinct from i_now.region) as region,
    count(*) filter (where i_at.marital_status is distinct from i_now.marital_status) as marital,
    count(*) filter (where p_at.product <> p_now.product) as product
from marts.fct_claim as f
inner join marts.dim_insured as i_at on i_at.insured_sk = f.insured_sk
inner join marts.dim_insured as i_now on i_now.insured_id = i_at.insured_id and i_now.is_current
inner join marts.dim_policy as p_at on p_at.policy_sk = f.policy_sk
inner join marts.dim_policy as p_now on p_now.policy_id = p_at.policy_id and p_now.is_current
group by 1
order by 1
"""

PROGRAMME_SQL = """
select
    to_char(f.occurrence_date, 'YYYY-MM') as month,
    count(*) filter (where p_at.in_programme) as as_it_was,
    count(*) filter (where p_now.in_programme) as as_it_looks_today
from marts.fct_claim as f
inner join marts.dim_diagnosis as d on d.diagnosis_code = f.diagnosis_code
inner join marts.dim_policy as p_at on p_at.policy_sk = f.policy_sk
inner join marts.dim_policy as p_now on p_now.policy_id = p_at.policy_id and p_now.is_current
where d.is_chronic
group by 1
order by 1
"""


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def draw_drift(rows, path: Path):
    import matplotlib.pyplot as plt

    years = [r[0] for r in rows]
    attributes = [("Programme membership", 2), ("Region", 3), ("Marital status", 4), ("Product", 5)]
    colours = [BLUE, ORANGE, AQUA]

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150, facecolor=SURFACE)
    _style(ax)
    width = 0.8 / len(years)
    for k, (year, row) in enumerate(zip(years, rows)):
        xs = [i + (k - (len(years) - 1) / 2) * width for i in range(len(attributes))]
        shares = [100.0 * row[col] / row[1] for _, col in attributes]
        bars = ax.bar(xs, shares, width=width * 0.92, color=colours[k % 3], label=str(year))
        for bar, share in zip(bars, shares):
            if share >= 0.5:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.15,
                    f"{share:.1f}%",
                    ha="center",
                    va="bottom",
                    fontsize=7.5,
                    color=INK_2,
                )
    ax.set_xticks(range(len(attributes)), [a for a, _ in attributes], color=INK)
    ax.set_ylabel("Claims that would be misreported (%)", color=INK_2, fontsize=9)
    ax.set_title(
        "Reporting each year's claims under today's attributes",
        loc="left",
        fontsize=11,
        color=INK,
        pad=12,
    )
    ax.legend(title="Year of claim", frameon=False, fontsize=9, title_fontsize=9, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def draw_programme(rows, path: Path):
    import matplotlib.pyplot as plt

    months = [r[0] for r in rows]
    was = [r[1] for r in rows]
    today = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150, facecolor=SURFACE)
    _style(ax)
    xs = range(len(months))
    ax.plot(xs, today, color=ORANGE, linewidth=2, label="counted with today's membership")
    ax.plot(xs, was, color=BLUE, linewidth=2, label="counted with membership at the time")
    # Direct labels at the start, where the two lines are furthest apart:
    # the gap is the point, and it closes as history catches up with today.
    for label, series, colour in (("today's flag", today, ORANGE), ("flag at the time", was, BLUE)):
        ax.annotate(
            label, (0, series[0]), (8, -14), textcoords="offset points", color=colour, fontsize=8.5
        )
    ticks = [i for i, m in enumerate(months) if m.endswith(("-01", "-07"))]
    ax.set_xticks(ticks, [months[i] for i in ticks], color=INK)
    ax.set_xlim(-0.5, len(months) - 0.5)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Chronic-diagnosis claims in the programme, per month", color=INK_2, fontsize=9)
    ax.set_title(
        "The prevention programme, read two ways",
        loc="left",
        fontsize=11,
        color=INK,
        pad=12,
    )
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def draw_all(pg: Postgres, img_dir: Path):
    img_dir.mkdir(parents=True, exist_ok=True)
    with psycopg2.connect(pg.dsn()) as con, con.cursor() as cur:
        cur.execute(DRIFT_SQL)
        drift = cur.fetchall()
        cur.execute(PROGRAMME_SQL)
        programme = cur.fetchall()
    draw_drift(drift, img_dir / "drift_by_attribute.png")
    draw_programme(programme, img_dir / "programme_two_ways.png")
    for row in drift:
        year, claims, *counts = row
        print(f"{year}: {claims} claims; misreported under today's attributes:", *counts)
    print(f"wrote {img_dir / 'drift_by_attribute.png'} and {img_dir / 'programme_two_ways.png'}")
