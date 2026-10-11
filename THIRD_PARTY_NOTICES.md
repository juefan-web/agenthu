# Third-party notices

## OneTHU core

- Source: https://github.com/smartThise/OneTHU
- Pinned commit: `2e3455fc235719b7f91fffaf5fe35e09220dda73`
- Vendored at: `vendor/onethu/core`
- License: the upstream `LICENSE` contains MIT text plus additional non-commercial and no-abusive-access restrictions. Preserve the complete file; do not describe this vendored code as unrestricted MIT.

## OneTHU info-lib authentication subset

- Vendored at: `vendor/onethu/info-lib`
- Scope: the authentication modules (login / roam / csrf) used by the native `CampusAdapter`.
- Provenance: re-derived in October 2026 ("path B") from the thu-info-app monorepo
  (`packages/thu-info-lib`, https://github.com/thu-info-community/thu-info-app) at
  commit `06dc3cf0` — the last snapshot under MIT before the upstream switch to the
  Business Source License 1.1 — plus repository-authored work published under MIT.
  The complete provenance declaration is `vendor/onethu/info-lib/LICENSE`; measurement
  records live in `AGENT_CONTEXT/TASKS/m5-p0-6-path-b.md` and
  `AGENT_CONTEXT/TASKS/m5-p0-6-license-inventory.md` §2.2 in this repository.
- License: MIT as declared in `vendor/onethu/info-lib/LICENSE`; no code from post-BSL
  upstream commits is incorporated by copy. The earlier history of this package (a
  copy of OneTHU at commit `2e3455f` under BSL 1.1 boundary terms) was superseded by
  path B and survives only as a historical measurement record (license-inventory
  §2.2); it does not describe this tree.
- Notices: dependency notices for components still vendored from OneTHU core remain
  under `vendor/onethu/LICENSES/`. The THU Info data-library grant names OneTHU and
  must not be assumed to extend to Agenthu; complete a distribution review before
  publishing a release.

## OneTHU dependency and project notices

The upstream third-party inventory, copyright notices, and the author grant for the THU Info data library are retained in `vendor/onethu/LICENSES/`. The upstream notices identify parts of OneTHU as ported from LearnX and record additional exception terms there; Agenthu's vendored subset carries no LearnX port markers (measured in `AGENT_CONTEXT/TASKS/m5-p0-6-license-inventory.md` §2.1), and those terms are retained here as defensive disclosure. The THU Info grant names OneTHU; it must not be assumed to extend to Agenthu. Before distributing Agenthu, review the exact copied files, applicable LearnX conditions, BSL 1.1 terms, and whether separate permission is needed.

Credentials and cookies: campus credentials are held in the Rust-side vault and the auth gateway's memory and are cleared once a login attempt settles; Event payloads carry no credential or cookie fields, and upstream raw responses are not copied into Event payloads or logs. A controlled cookie mirror does exist: for `*.tsinghua.edu.cn` hosts, the host, name, value, and hostOnly flag of cookies seen by campus requests cross the IPC boundary into an in-memory map in the renderer process, where the vendored InfoClient reads them for XSRF tokens and the WebVPN cookie dance; raw Set-Cookie headers and attributes such as Expires or HttpOnly never cross the boundary, the mirror is never persisted, and it is cleared on logout. The campus debug channel (off by default, opt-in) redacts token-shaped values (20 or more characters) before lines reach DevTools and truncates over-long lines; shorter values in `name=value` diagnostic lines are a known residual gap — widening the redaction rule is a tracked optional code change, not part of this notices update.
