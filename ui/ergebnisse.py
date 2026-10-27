"""The page that shows the measured results, computed from the run records.

Every number is computed here from `data/*/eval_runs.jsonl` rather than copied
from the README, so the page always shows what the runs recorded. Runs with a
reranker or a model are not deterministic; where a configuration ran several
times, the page shows the range over those runs, never a single pick.
"""

from collections.abc import Callable, Iterable
from datetime import datetime

import altair as alt
import streamlit as st

from anlagen_copilot.runlog import load_runs
from anlagen_copilot.scripts.eval_facts import DEFAULT_FACT_RUNS_PATH, FactCheckRun
from anlagen_copilot.scripts.eval_generate import DEFAULT_GENERATION_RUNS_PATH, GenerationRun
from anlagen_copilot.scripts.eval_retrieval import DEFAULT_RETRIEVAL_RUNS_PATH, RetrievalRun

VERSION = "v4"

# The two indexes, in the order and colours the charts use. Slots 1 and 2 of
# the reference palette, which pass its colour-vision and contrast checks.
STRATEGIES = {"advanced": "Docling (advanced)", "naive": "pypdf (naive)"}
COLOURS = {"advanced": "#2a78d6", "naive": "#eb6834"}

CATEGORIES = {
    "multi-hop": "Zwei Handbücher",
    "diagram": "Zeichnung",
    "lookup": "Nachschlagen",
    "table": "Tabelle",
}

Span = tuple[float, float]

# List prices in US dollars per million input and output tokens, as in
# docs/messungen.md. A model missing here shows no price rather than a wrong one.
PRICES = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-5-5": (2.0, 10.0),
}


def dollars(model: str | None, input_tokens: int, output_tokens: int) -> float | None:
    """What the tokens of one model cost at list price, or None for an unknown model."""
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def show_dollars(values: list[float | None], *, per_question: int | None = None) -> str:
    """Write a span of dollar amounts, or a dash when a price is missing.

    With `per_question`, the amount is divided by that many questions and shown
    in cents: a few cents at two decimals of a dollar would hide the difference.
    """
    if not values or any(v is None for v in values):
        return "–"
    low, high = span(v for v in values if v is not None)
    if per_question is not None:
        low, high = low * 100 / per_question, high * 100 / per_question
        fmt, unit = "{:.1f}", " ct"
    else:
        fmt, unit = "{:.2f}", " $"
    a, b = fmt.format(low), fmt.format(high)
    return (a if a == b else f"{a}–{b}").replace(".", ",") + unit


def span(values: Iterable[float]) -> Span:
    """The lowest and highest value over a set of runs."""
    numbers = list(values)
    return min(numbers), max(numbers)


def show_span(value: Span, *, percent: bool = False) -> str:
    """Write a span as one value when the runs agree, as `low–high` when they do not."""
    low, high = (round(v * 100) if percent else round(v) for v in value)
    unit = " %" if percent else ""
    return f"{low}{unit}" if low == high else f"{low}–{high}{unit}"


@st.cache_data
def load() -> tuple[list[RetrievalRun], list[GenerationRun], list[FactCheckRun]]:
    """Read the three run records once per session, keeping only the current eval set."""
    retrieval = [
        r
        for r in load_runs(DEFAULT_RETRIEVAL_RUNS_PATH, RetrievalRun)
        if r.eval_set_version == VERSION
    ]
    generation = [
        r
        for r in load_runs(DEFAULT_GENERATION_RUNS_PATH, GenerationRun)
        if r.eval_set_version == VERSION
    ]
    facts = [
        r for r in load_runs(DEFAULT_FACT_RUNS_PATH, FactCheckRun) if r.eval_set_version == VERSION
    ]
    return retrieval, generation, facts


def retrieval_runs(
    runs: list[RetrievalRun], strategy: str, *, k: int, reranked: bool
) -> list[RetrievalRun]:
    """The runs of one retrieval configuration; without a reranker only the newest counts.

    The search without a reranker is exact and so deterministic (ADR 011): a
    later run of the same configuration replaces an earlier one, as after the
    umlaut repair of the catalogue. With a reranker every run counts.
    """
    matching = [
        r
        for r in runs
        if r.strategy == strategy and r.k == k and (r.reranker is not None) == reranked
    ]
    if reranked or not matching:
        return matching
    return [max(matching, key=lambda r: r.run_at)]


def found(run: RetrievalRun, category: str | None = None) -> int:
    """How many expected pages a retrieval run found, overall or for one category."""
    return sum(r.found for r in run.results if category is None or r.category == category)


def expected(run: RetrievalRun, category: str | None = None) -> int:
    """How many expected pages there are, overall or for one category."""
    return sum(r.expected for r in run.results if category is None or r.category == category)


def complete_share(run: FactCheckRun, category: str | None = None) -> float:
    """The share of judged answers that state every required fact."""
    judged = [
        r
        for r in run.results
        if r.facts is not None and (category is None or r.category == category)
    ]
    return sum(1 for r in judged if r.complete) / len(judged) if judged else 0.0


def fact_runs_by_strategy(
    facts: list[FactCheckRun], generation: list[GenerationRun]
) -> dict[str, list[FactCheckRun]]:
    """Sort the fact checks by the strategy of the generation run each one judged."""
    strategy_of: dict[datetime, str] = {g.run_at: g.strategy for g in generation}
    return {s: [f for f in facts if strategy_of.get(f.judged_run_at) == s] for s in STRATEGIES}


def grouped_bars(
    rows: list[dict[str, object]], *, x_title: str, x_max: float, percent: bool
) -> alt.LayerChart:
    """Horizontal bars per group, one per index, with a line over the range of the runs.

    The bar runs to the lowest value of the runs; a line continues it to the
    highest, so a spread is visible without picking one run as the result.
    """
    axis_format = ".0%" if percent else "d"
    base = alt.Chart(alt.InlineData(values=rows)).encode(
        y=alt.Y("group:N", title=None, sort=None, axis=alt.Axis(labelLimit=200)),
        yOffset=alt.YOffset("label:N", sort=list(STRATEGIES.values())),
        color=alt.Color(
            "label:N",
            title=None,
            scale=alt.Scale(domain=list(STRATEGIES.values()), range=list(COLOURS.values())),
            legend=alt.Legend(orient="top"),
        ),
        tooltip=[
            alt.Tooltip("group:N", title="Gruppe"),
            alt.Tooltip("label:N", title="Index"),
            alt.Tooltip("text:N", title="Wert"),
            alt.Tooltip("runs:Q", title="Läufe"),
        ],
    )
    x = alt.X(
        "low:Q",
        title=x_title,
        scale=alt.Scale(domain=[0, x_max]),
        axis=alt.Axis(format=axis_format, grid=True, gridOpacity=0.3),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, height={"band": 0.8}).encode(x=x)
    spread = base.mark_rule(strokeWidth=2).encode(x="low:Q", x2="high:Q")
    labels = base.mark_text(align="left", dx=6, color="#52514e").encode(x="high:Q", text="text:N")
    return alt.LayerChart(layer=[bars, spread, labels], height=alt.Step(18))


def row(
    group: str, strategy: str, values: list[float], *, percent: bool = False
) -> dict[str, object]:
    """One bar: a group, an index, and the range of its runs."""
    low, high = span(values)
    return {
        "group": group,
        "label": STRATEGIES[strategy],
        "low": low,
        "high": high,
        "text": show_span((low, high), percent=percent),
        "runs": len(values),
    }


def per_strategy(fn: Callable[[str], list[float]]) -> dict[str, Span]:
    """A span per index, from a function that returns the values of its runs."""
    return {s: span(fn(s)) for s in STRATEGIES}


retrieval, generation, facts = load()
facts_by = fact_runs_by_strategy(facts, generation)

st.title("Ergebnisse")
st.caption(
    f"Eval-Set {VERSION}: 37 Fragen, 32 beantwortbare mit 36 Belegseiten, 5 unbeantwortbare. "
    "Alle Zahlen aus den protokollierten Läufen; wo eine Konfiguration mehrfach lief, "
    "als Spanne über diese Läufe."
)

reranked = {s: retrieval_runs(retrieval, s, k=5, reranked=True) for s in STRATEGIES}
vector5 = {s: retrieval_runs(retrieval, s, k=5, reranked=False) for s in STRATEGIES}
vector50 = {s: retrieval_runs(retrieval, s, k=50, reranked=False) for s in STRATEGIES}
gens = {s: [g for g in generation if g.strategy == s] for s in STRATEGIES}

# --- Headline numbers -------------------------------------------------------
tiles = st.columns(3)
for column, (title, value, help_text) in zip(
    tiles,
    [
        (
            "Belege im Prompt (Reranking, Top 5)",
            {s: show_span(span(found(r) for r in reranked[s])) + " / 36" for s in STRATEGIES},
            "Landet die Seite mit der Antwort unter den 5 Seiten, die das Sprachmodell liest?",
        ),
        (
            "Antworten mit allen Fakten",
            {
                s: show_span(span(complete_share(f) for f in facts_by[s]), percent=True)
                for s in STRATEGIES
            },
            "Ein eigenes Judge-Modell prüft je Antwort die erforderlichen Fakten (ADR 016).",
        ),
        (
            "Falsche Ablehnungen",
            {
                s: show_span(
                    span(
                        sum(1 for r in g.results if r.category != "unanswerable" and not r.answered)
                        for g in gens[s]
                    )
                )
                + " / 32"
                for s in STRATEGIES
            },
            "Beantwortbare Fragen, bei denen das Modell trotzdem ablehnt.",
        ),
    ],
    strict=True,
):
    with column, st.container(border=True):
        st.markdown(f"**{title}**", help=help_text)
        for s, text in value.items():
            st.markdown(f":gray[{STRATEGIES[s]}]  \n### {text}")

# --- Retrieval --------------------------------------------------------------
st.subheader("Retrieval: Wird die Seite mit der Antwort gefunden?")
stages = [
    ("Vektorsuche, Top 5", vector5),
    ("Reranking, Top 5", reranked),
    ("Vektorsuche, Top 50", vector50),
]
st.altair_chart(
    grouped_bars(
        [
            row(stage, s, [found(r) for r in runs[s]])
            for stage, runs in stages
            for s in STRATEGIES
            if runs[s]
        ],
        x_title="Belege gefunden, von 36",
        x_max=36,
        percent=False,
    ),
    width="stretch",
)
st.caption(
    "Docling hilft dem Reranking, das ganze Seiten liest; der reinen Vektorsuche schadet "
    "das Markdown der Tabellen leicht (ADR 015)."
)

st.markdown("**Mit Reranking, nach Fragetyp**")
st.altair_chart(
    grouped_bars(
        [
            row(
                f"{label} ({expected(reranked['naive'][0], category)})",
                s,
                [found(r, category) / expected(r, category) for r in reranked[s]],
                percent=True,
            )
            for category, label in CATEGORIES.items()
            for s in STRATEGIES
            if reranked[s]
        ],
        x_title="Anteil der Belege im Prompt",
        x_max=1,
        percent=True,
    ),
    width="stretch",
)

# --- Facts ------------------------------------------------------------------
st.subheader("Antworten: Nennen sie die erforderlichen Fakten?")
st.altair_chart(
    grouped_bars(
        [
            row(label, s, [complete_share(f, category) for f in facts_by[s]], percent=True)
            for category, label in [*CATEGORIES.items(), (None, "Gesamt")]
            for s in STRATEGIES
            if facts_by[s]
        ],
        x_title="Antworten mit allen erforderlichen Fakten",
        x_max=1,
        percent=True,
    ),
    width="stretch",
)
st.caption(
    "Gezählt sind die bewerteten Antworten; Ablehnungen zählen schon oben. Der Judge streut: "
    "dieselbe Antwort kann einmal vollständig, einmal unvollständig gelten."
)


# --- Tables -----------------------------------------------------------------
def rerank_cost(g: GenerationRun) -> float | None:
    """What the reranking inside one generation run cost; every run reranks anew."""
    return dollars(g.reranker, g.rerank_input_tokens or 0, g.rerank_output_tokens or 0)


def answer_cost(g: GenerationRun) -> float | None:
    """What writing the answers of one generation run cost."""
    return dollars(
        g.generator,
        sum(x.input_tokens for x in g.results),
        sum(x.output_tokens for x in g.results),
    )


def pipeline_cost(g: GenerationRun) -> float | None:
    """Reranking plus answers: what the 37 questions of one run cost through the API path."""
    parts = (rerank_cost(g), answer_cost(g))
    return None if any(p is None for p in parts) else sum(p for p in parts if p is not None)


def judge_cost(f: FactCheckRun) -> float | None:
    """What judging one generation run cost."""
    return dollars(
        f.judge,
        sum(x.input_tokens or 0 for x in f.results),
        sum(x.output_tokens or 0 for x in f.results),
    )


st.subheader("Kosten")
st.dataframe(
    [
        {
            "Index": STRATEGIES[s],
            "Reranking (37 Fragen)": show_dollars([rerank_cost(g) for g in gens[s]]),
            "Antworten (37 Fragen)": show_dollars([answer_cost(g) for g in gens[s]]),
            "Zusammen (37 Fragen)": show_dollars([pipeline_cost(g) for g in gens[s]]),
            "Je Frage": show_dollars([pipeline_cost(g) for g in gens[s]], per_question=37),
            "Faktenprüfung (nur Eval)": show_dollars([judge_cost(f) for f in facts_by[s]]),
        }
        for s in STRATEGIES
        if gens[s]
    ],
    hide_index=True,
    width="stretch",
)
st.caption(
    "Listenpreise je Million Tokens (Input / Output): Claude Haiku 4.5 1 $ / 5 $ (Reranking), "
    "Claude Sonnet 5 2 $ / 10 $ (Antworten), Claude Sonnet 5.5 2 $ / 10 $ (Faktenprüfung). "
    "Die Embeddings der Fragen kosten unter 0,01 $ je Lauf. Im Vergleich auf der Seite "
    "„Fragen“ fallen die Kosten je Frage doppelt an."
)

st.subheader("Die Läufe dahinter")
st.dataframe(
    [
        {
            "Art": kind,
            "Index": STRATEGIES.get(strategy, strategy),
            "Zeitpunkt": run_at.strftime("%Y-%m-%d %H:%M"),
            "Commit": commit or "",
            "Konfiguration": config,
        }
        for kind, strategy, run_at, commit, config in sorted(
            [
                *(
                    (
                        "Retrieval",
                        r.strategy,
                        r.run_at,
                        r.commit,
                        f"k={r.k}"
                        + (f", {r.candidates} Kandidaten, {r.reranker}" if r.reranker else ""),
                    )
                    for runs in (*reranked.values(), *vector5.values(), *vector50.values())
                    for r in runs
                ),
                *(("Generierung", g.strategy, g.run_at, g.commit, g.generator) for g in generation),
                *(
                    ("Faktenprüfung", s, f.run_at, f.commit, f.judge)
                    for s, runs in facts_by.items()
                    for f in runs
                ),
            ],
            key=lambda item: (item[0], item[1], item[2]),
        )
    ],
    hide_index=True,
    width="stretch",
)
