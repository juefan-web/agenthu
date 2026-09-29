# Third-party notices

## OneTHU core

- Source: https://github.com/smartThise/OneTHU
- Pinned commit: `2e3455fc235719b7f91fffaf5fe35e09220dda73`
- Vendored at: `vendor/onethu/core`
- License: the upstream `LICENSE` contains MIT text plus additional non-commercial and no-abusive-access restrictions. Preserve the complete file; do not describe this vendored code as unrestricted MIT.

## OneTHU info-lib authentication subset

- Source: https://github.com/smartThise/OneTHU
- Pinned commit: `2e3455fc235719b7f91fffaf5fe35e09220dda73`
- Vendored at: `vendor/onethu/info-lib`
- Scope: the CAS/OAuth, 2FA and WebVPN authentication modules used by the native `CampusAdapter`.
- License and notices: retain the upstream MIT, BSL 1.1, LearnX and dependency notices shipped under `vendor/onethu/LICENSES/`. The BSL 1.1 boundary applies to the copied authentication sources where identified by the upstream notices; complete a distribution review before publishing a release.

## OneTHU dependency and project notices

The upstream third-party inventory, copyright notices, and the author grant for the THU Info data library are retained in `vendor/onethu/LICENSES/`. OneTHU core contains code identified by upstream as ported from LearnX, whose additional exception terms are recorded there. The THU Info grant names OneTHU; it must not be assumed to extend to Agenthu. Before distributing Agenthu, review the exact copied files, applicable LearnX conditions, BSL 1.1 terms, and whether separate permission is needed.

Agenthu does not copy credentials, cookies, or upstream raw responses into Event payloads or logs.
