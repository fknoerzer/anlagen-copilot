# ADR 010: Kein RAG-Framework

## Kontext

Die Pipeline hat wenige Schritte: extrahieren, einbetten, suchen, umsortieren,
später generieren. Die Evaluation soll zeigen, was jeder dieser Schritte
bringt, und muss dafür jeden einzeln steuern und protokollieren können.
`langchain` stand seit dem ersten Setup in den Abhängigkeiten, wurde aber nie
importiert.

## Entscheidung

Die Pipeline ruft die Bibliotheken direkt auf: `openai` für Embeddings,
`anthropic` für das Reranking, `psycopg` mit `pgvector` für die Datenbank,
Pydantic für Schemas und Validierung. `langchain` wurde entfernt (`27f3503`).

## Alternativen

- **LangChain oder LlamaIndex.** Fertige Bausteine für Loader, Splitter,
  Retriever und Reranker. Mehrere Entscheidungen dieses Projekts müssten aber
  gegen deren Abstraktion gebaut werden: das eigene Tool-Schema mit strikter
  Validierung ([ADR 004](004-reranker-ausgabe.md)), der Fehler statt eines
  Rückfalls ([ADR 005](005-kein-stiller-rueckfall.md)), die Token-Zählung je
  Lauf ([ADR 008](008-eval-laeufe-protokollieren.md)) und die Transaktion pro
  Dokument ([ADR 006](006-transaktion-pro-dokument.md)).

## Konsequenzen

- Jeder Schritt ist eigener Code, den das Projekt selbst testet. Die Tests
  ersetzen die API-Clients durch Fakes, ohne eine Framework-Schicht dazwischen.
- Die Abhängigkeiten bleiben klein. `deptry` meldet jede, die nicht importiert
  wird; die einzige Ausnahme ist `fastapi`, vorab deklariert für den Endpunkt.
- Ein neuer Anbieter oder eine neue Strategie braucht eigenen Code statt einer
  fertigen Integration.
- **Offen:** Für den agentischen Suchpfad ist die Frage neu zu stellen. In
  einem Azure-Zweig wäre das Microsoft Agent Framework die naheliegende Wahl.
