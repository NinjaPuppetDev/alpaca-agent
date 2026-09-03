# Positions source of truth

The broker is authoritative whenever the Alpaca client is connected to the paper
account. SQLite stores strategy metadata, audit history, and a reconciliation cache;
it must not restore positions that are absent from the broker snapshot.

```mermaid
flowchart TD
    A[Alpaca paper account<br/>get_all_positions + get_account] --> B[AlpacaClient]
    B --> C{Asset class}
    C -->|us_equity| D[Equity snapshot]
    C -->|us_option| E[Live option snapshot]
    D --> F[/api/portfolio]
    E --> F
    F --> G[PortfolioOverview<br/>Equity Holdings]
    F --> H[PortfolioOverview<br/>Live Option Positions]

    D --> I[Theme Portfolio Layer]
    I --> J[Assistant + VWAP guardrails]
    J --> K[Guarded stock order routing]
    K --> A

    D --> L[Derivatives Overlay Layer]
    L --> M[Protective option-leg validation]
    M --> N[Multi-leg option routing]
    N --> A

    E --> O[Reconciliation cache]
    D --> O
    O --> P[(SQLite Position cache<br/>equities only)]
    L --> Q[(SQLite Hedge plans<br/>structure + expiry)]
    Q --> R[/api/hedges]
    R --> S[ActiveHedges<br/>planned overlays]

    T[Expiration Watchdog] --> Q
    T --> M
    T --> N
```

## Contracts

- `AlpacaClient.get_positions()` returns both equities and options.
- `/api/portfolio.positions` contains equities only.
- `/api/portfolio.option_positions` contains live option contracts only.
- `/api/hedges` contains strategy-owned protective overlay records and their DTE state.
- The database cache is synchronized from the broker snapshot in live mode; an
  option-only account therefore has zero cached equity rows.
- Emergency liquidation intentionally sells equities only. Option contracts remain
  under the derivatives overlay and expiration watchdog controls.
