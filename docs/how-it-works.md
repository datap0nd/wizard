# How Wizard works

## One question, end to end

```mermaid
flowchart TD
    A["You ask a question<br/>(browser, signed in)"] --> B["Wizard API<br/>starts a run as you"]
    B --> C{"Your Gemini account linked?"}
    C -- no --> X["Stop: 'link your own Gemini account'<br/>(never borrows someone else's login)"]
    C -- yes --> D["Gemini, under your account<br/>reads Wizard's instructions + your question"]
    D --> E{"Gemini decides the next step"}
    E -- "needs data or a definition" --> F["Calls a Wizard tool<br/>e.g. nerp_run_report"]
    F --> G["Wizard checks run token, arguments<br/>and your rights to report + markets"]
    G --> H["Reads the platform report<br/>(max 500 rows, read-only)"]
    H --> I["Saves evidence E1, E2…<br/>and shows the step on your screen"]
    I --> E
    E -- "has enough" --> J["Writes the answer<br/>citing [E1], placing charts [V1]"]
    J --> K["Wizard saves a dated report<br/>data mode · check status · warnings"]
    K --> L["You see the answer live<br/>Show sources · Check my data · report link"]
    L -- "Check my data" --> M["New run: Gemini recomputes the figures<br/>from the cited evidence"]
    M --> K
```

## Inside one tool call

```mermaid
flowchart LR
    G["Gemini<br/>mcp_nerp_run_report(...)"] --> S["MCP server 'nerp'<br/>(one per platform)"]
    S --> T["Wizard tool gateway<br/>loopback + run token"]
    T --> R["Registry: closed schema,<br/>your report + market rights,<br/>row and call limits"]
    R --> P["Platform adapter<br/>(synthetic today, live later)"]
    P --> E["Evidence E3 stored<br/>event streamed to you"]
    E --> G
```

## Where Gemini runs

- **gemini-cli route:** Wizard starts the Gemini CLI for each question inside your own folder (your sign-in only), with
  no built-in tools, so it can use only Wizard's read-only tools.
- **code-assist route:** Wizard calls the same Code Assist API the CLI uses, with your own Google token.
- **replay:** recorded answers over synthetic data for tests and demos, always labelled REPLAY.

The Step 02 spike on the work PC decides between the first two.
