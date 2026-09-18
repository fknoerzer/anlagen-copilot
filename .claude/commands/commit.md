---
description: Staged Änderungen als Conventional Commit im Stil dieses Repos committen
argument-hint: [optionaler Hinweis auf den Grund der Änderung]
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git add:*), Bash(git commit:*)
---

## Kontext

- Status: !`git status --short`
- Staged: !`git diff --staged --stat`
- Staged Diff: !`git diff --staged`
- Nicht gestaged: !`git diff --stat`
- Letzte Messages: !`git log --format="%s" -20`

## Aufgabe

Committe die gestagten Änderungen. Ist nichts gestaged, sage das und stage nichts
von dir aus — welche Änderung in welchen Commit gehört, entscheidet der Autor.

Zusätzlicher Hinweis des Autors zum Grund der Änderung (kann leer sein): $ARGUMENTS

## Regeln für die Message

**Form.** `<type>: <subject>` — Conventional Commits ohne Scope. Erlaubte Types:
`feat`, `fix`, `chore`, `test`, `refactor`, `revert`, `docs`, `perf`.
Subject auf Englisch, klein nach dem Doppelpunkt, kein Punkt am Ende, höchstens
72 Zeichen. Kein Body — außer der Grund passt nachweislich nicht in eine Zeile.

**Inhalt — der eigentliche Punkt.** Das Subject sagt die *Wirkung* oder den
*Grund*, nicht die mechanische Änderung. Was geändert wurde, steht im Diff und
gehört nicht noch einmal in die Message.

    gut:      revert: grade by id again, the flat schema stopped reranking
    schlecht: revert: restore nested grade schema

    gut:      fix: size the grading call to the candidate count
    schlecht: fix: change max_tokens in rerank.py

Ist im Gespräch oder in `$ARGUMENTS` ein Grund bekannt, der nicht aus dem Diff
hervorgeht — eine Messung, ein beobachteter Fehlschlag, eine verworfene
Alternative —, dann gehört genau der ins Subject. Das ist der Teil, den später
niemand mehr rekonstruieren kann.

**Type-Wahl in diesem Repo.** Neue Zeilen in `data/eval_runs.jsonl` sind `chore`
(„record the ..."), nicht `feat` — eine Messung ist kein Feature. Reine Tests
sind `test`, auch wenn dabei eine Kleinigkeit im Produktivcode mit geradegezogen
wurde; ändert sich dabei Verhalten, sind es zwei Commits.

**Gemischte Änderungen.** Decken die gestagten Änderungen mehr als einen Zweck
ab, schreibe keine Sammelmessage. Sage, wie die Aufteilung aussähe, und frage
nach, bevor du committest.

## Ablauf

Direkt auf `master` — kein Branch, kein PR. `pre-commit` (ruff, mypy, deptry)
läuft beim Commit mit; schlägt es fehl, behebe die Ursache und committe erneut.
Niemals `--no-verify`.

Die Message endet mit einer Leerzeile und:

    Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
