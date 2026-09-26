# OneTHU Adapter Research

Status: **not started / blocked on source access** (M0).

OneTHU is a *reference for data acquisition and capability design*, not a runtime
dependency. The product must remain usable without the user opening OneTHU.

## Access status

At M0 the OneTHU source tree and API documentation were not available in this
repository or to the implementing agent, so no endpoint, authentication or data
schema could be verified. Per the project rules we do **not** guess interfaces.

## Required research checklist (before any implementation)

1. Data source: which campus systems back each capability (courses, assignments,
   exams, calendar, grades, notices, slides, mail, campus services).
2. Request mechanism: HTTP/base URL, method, path, query and body params.
3. Authentication: login flow, whether it is an official interface or a
   client-internal one, cookie/session/token mechanics, refresh and expiry.
4. Response schemas: field names, nesting, nullability, units and time formats.
5. Error handling: error codes, retry semantics, rate limits.
6. Pagination / incremental sync: cursors, page sizes, `since` parameters.
7. Time fields: timezone, precision, update frequency.
8. Availability: whether an official, documented API exists.
9. Authorization boundary: what the terms of use permit us to access and store.

## Hard constraints

- Never commit user passwords, cookies or tokens. Never hardcode credentials.
- Do not bypass authentication, access control or other security mechanisms.
- Store credentials, if ever needed, only with encryption + access control +
  a documented deletion path (later milestone decision).
- Normalize all provider data into the shared Event contract; the Backend must
  not depend on OneTHU types.

## Planned adapter surface

```
OneTHUAdapter (SourceAdapter)
├── CampusCourseAdapter
├── CampusAssignmentAdapter
├── CampusGradeAdapter
├── CampusCalendarAdapter
└── CampusNoticeAdapter
```

Each adapter must be testable with recorded, redacted fixtures and must emit
`NormalizedEvent` objects only.
