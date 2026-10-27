"""The page that asks the answer API and shows the answer with its sources.

Talks to the running API over HTTP rather than calling the pipeline itself, so
the page uses the endpoint the way any other client would. The response is
read back into `AskResponse`, so a change to the API's contract fails here
loudly instead of rendering half a page.

By default the page asks both indexes and shows the answers side by side, so
what Docling changes against pypdf is visible on the question itself.

Needs the API running (`uv run anlagen-copilot-api`); `ui/streamlit_app.py` serves it.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx
import streamlit as st

from anlagen_copilot.answer import AskResponse, Citation

API_URL = os.environ.get("ANLAGEN_API_URL", "http://127.0.0.1:8000")

# Search, rerank and generation take some seconds each; a minute leaves room
# for a slow model without hanging the page forever.
TIMEOUT_SECONDS = 60

# The API's strategies, with the name the page shows for each.
STRATEGIES = {"advanced": "Docling (advanced)", "naive": "pypdf (naive)"}
MODES = {"Vergleich": ["advanced", "naive"], "Docling": ["advanced"], "pypdf": ["naive"]}

# One question per kind the eval set measures, so a demo starts with a click.
EXAMPLES = {
    "Tabelle": (
        "Welches Shell-Öl darf ich in ein Stirnradgetriebe R37 mit Standard-CLP VG 150 füllen?"
    ),
    "Zwei Handbücher": (
        "Ich bestelle einen Motor DRN132M4 für den Betrieb an einem G120C. Welchen "
        "Temperaturfühler sollte ich als Option wählen, damit der Umrichter die "
        "Motortemperatur überwacht?"
    ),
    "Nachschlagen": "Wie oft muss ich meinen Motor DRN100LS4 warten, und was ist dabei zu tun?",
    "Nicht in den Handbüchern": "Kann ich den G120C per OPC UA an unser MES anbinden?",
}


@dataclass(frozen=True)
class Answer:
    """One strategy's answer to a question, and how long the API took for it."""

    response: AskResponse
    seconds: float


@dataclass(frozen=True)
class Failed:
    """Why one strategy has no answer, in words the page can show."""

    message: str


@dataclass(frozen=True)
class Turn:
    """One question of this session with the outcome of each strategy asked."""

    question: str
    answers: dict[str, Answer | Failed]


def ask(question: str, strategy: str) -> Answer:
    """Send one question to the API for one strategy and read the answer back."""
    start = time.perf_counter()
    response = httpx.post(
        f"{API_URL}/api/ask",
        json={"question": question, "strategy": strategy},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return Answer(AskResponse.model_validate(response.json()), time.perf_counter() - start)


def ask_or_fail(question: str, strategy: str) -> Answer | Failed:
    """Ask one strategy; an error of the API becomes a `Failed` for that strategy alone.

    In a comparison one strategy can fail where the other answers, for instance
    when the model returns an answer the API rejects. The other answer is still
    worth showing. Only an unreachable API is left to raise: then nothing works.
    """
    try:
        return ask(question, strategy)
    except httpx.HTTPStatusError as e:
        return Failed(
            f"Die API antwortete mit {e.response.status_code}. "
            "Die Ursache steht im Terminal der API."
        )
    except httpx.TimeoutException:
        return Failed(f"Keine Antwort innerhalb von {TIMEOUT_SECONDS} s.")


def ask_all(question: str, strategies: list[str]) -> Turn:
    """Ask every strategy at once, so a comparison takes as long as the slower answer."""
    with ThreadPoolExecutor(max_workers=len(strategies)) as pool:
        answers = pool.map(lambda strategy: ask_or_fail(question, strategy), strategies)
        return Turn(question, dict(zip(strategies, answers, strict=True)))


def short_name(citation: Citation) -> str:
    """Name a cited page briefly, for the marks behind a statement."""
    return f"{citation.manufacturer} S. {citation.page}"


def show_citation(citation: Citation, *, cited: bool) -> None:
    """Show one page as a source card; pages the answer did not cite are greyed."""
    with st.container(border=True):
        heading = f"**[{citation.n}]** {citation.title} · **S. {citation.page}**"
        st.markdown(heading if cited else f":gray[{heading}]")
        st.caption(f"„{citation.excerpt.strip()} …“")
        st.caption(
            f"{citation.manufacturer} · Score {citation.score:.2f} · "
            f"[PDF S. {citation.page} öffnen]({citation.url})"
        )


def show_answer(answer: Answer) -> None:
    """Show one answer: its statements with their pages, then the pages as cards."""
    result = answer.response
    by_n = {citation.n: citation for citation in result.citations}
    cited = {n for statement in result.statements for n in statement.sources}

    if not result.answered:
        st.warning("Die Handbücher beantworten diese Frage nicht.")
    for statement in result.statements:
        marks = " ".join(f"`[{n}] {short_name(by_n[n])}`" for n in statement.sources)
        st.markdown(f"- {statement.text} {marks}")
    st.caption(f"Antwort in {answer.seconds:.1f} s")

    st.markdown("**Quellen**")
    for citation in result.citations:
        if citation.n in cited:
            show_citation(citation, cited=True)
    uncited = [c for c in result.citations if c.n not in cited]
    if uncited:
        with st.expander(f"Weitere Seiten, die der Antwort vorlagen ({len(uncited)})"):
            for citation in uncited:
                show_citation(citation, cited=False)


def show_turn(turn: Turn) -> None:
    """Show the answers to one question, side by side when both strategies were asked."""
    st.subheader(turn.question)
    columns = st.columns(len(turn.answers), gap="large")
    for column, (strategy, answer) in zip(columns, turn.answers.items(), strict=True):
        with column:
            if len(turn.answers) > 1:
                st.markdown(f"#### {STRATEGIES[strategy]}")
            if isinstance(answer, Failed):
                st.error(answer.message)
            else:
                show_answer(answer)


def use_example(question: str) -> None:
    """Put an example into the question field; runs before the field is drawn again."""
    st.session_state.question = question


def show_from_history(index: int) -> None:
    """Show an earlier question again, without asking the API a second time."""
    st.session_state.shown = index


st.session_state.setdefault("history", [])
history: list[Turn] = st.session_state.history

with st.sidebar:
    st.header("Anlagen-Copilot")
    st.markdown(
        "Beantwortet Fragen aus 6 Handbüchern von SEW-EURODRIVE und Siemens "
        "(1.322 Seiten im Index). Jede Aussage nennt die Seite, aus der sie stammt; "
        "steht die Antwort nicht in den Handbüchern, lehnt das System ab."
    )
    st.markdown(
        "**Ablauf:** Vektorsuche (20 Seiten) → Reranking mit Claude Haiku (5 Seiten) "
        "→ Antwort mit Claude Sonnet. **Vergleich:** dieselbe Frage an den Index aus "
        "Docling und den aus pypdf."
    )
    st.caption(f"API: {API_URL}")

st.title("Fragen an den Copiloten")

st.write("Beispiele:")
for column, (label, example) in zip(st.columns(len(EXAMPLES)), EXAMPLES.items(), strict=True):
    column.button(label, on_click=use_example, args=(example,), width="stretch")

with st.form("ask"):
    question = st.text_area("Frage", key="question", max_chars=500, height=80)
    mode = st.radio("Index", list(MODES), horizontal=True)
    submitted = st.form_submit_button("Fragen", type="primary")

if submitted and question.strip():
    try:
        with st.spinner("Suche, Reranking, Antwort …"):
            history.append(ask_all(question.strip(), MODES[mode]))
    except httpx.ConnectError:
        st.error(
            f"Die API unter {API_URL} ist nicht erreichbar. Läuft `uv run anlagen-copilot-api`?"
        )
        st.stop()
    st.session_state.shown = len(history) - 1

shown = st.session_state.get("shown")
if shown is not None and shown < len(history):
    show_turn(history[shown])

# Drawn last, so a question asked in this run is already in the list.
if history:
    with st.sidebar:
        st.markdown("**Verlauf dieser Sitzung**")
        for index in reversed(range(len(history))):
            label = history[index].question
            st.button(
                label if len(label) <= 60 else f"{label[:57]} …",
                key=f"history-{index}",
                on_click=show_from_history,
                args=(index,),
                width="stretch",
            )
