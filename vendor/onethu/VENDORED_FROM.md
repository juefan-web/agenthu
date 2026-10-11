# Vendored OneTHU

- Repository: https://github.com/smartThise/OneTHU
- Commit: `2e3455fc235719b7f91fffaf5fe35e09220dda73`
- Included package: `packages/core` (`@onethu/core` 0.8.0)
- Scope: CampusSession, LearnClient, InfoClient, HTTP/WebVPN transport, and the associated types used by Agenthu's first Study + Time slice.
- The OneTHU desktop UI and unrelated data providers are intentionally not included.

## info-lib (re-derived in-repo, October 2026)

- Included directory: `vendor/onethu/info-lib` — an authentication-only
  (login / roam / csrf) subset. This directory is NOT a copy of an OneTHU
  package: it was re-derived from the thu-info-app monorepo at commit
  `06dc3cf0` (the last MIT snapshot before the upstream BSL 1.1 switch) plus
  repository-authored adaptations, as declared in `info-lib/LICENSE`
  (three-paragraph provenance) and measured in
  `AGENT_CONTEXT/TASKS/m5-p0-6-path-b.md` in the Agenthu repository.

Copyright and third-party terms are retained under `LICENSE` and `LICENSES/`.
