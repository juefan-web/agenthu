# Campus authentication continuation

- Goal: connect the pinned OneTHU authentication pipeline to the desktop adapter and persist campus sessions securely.
- Inputs: pinned OneTHU info-lib auth sources, user-entered credentials, native HTTP responses.
- Outputs: validated session status and campus data through CampusAdapter, encrypted local session snapshots.
- Scope (developer B): native transport and cookie isolation, Windows credential-backed Stronghold, 2FA UI, bounded recovery, fixture tests and CI.
- Excluded: Backend schemas and authentication, real campus credential provisioning, Android credential storage implementation.
- Permissions: campus login and read-only data collection initiated by the user; device trust only with explicit selection. No credentials in events or logs.
- Acceptance: login/2FA/cancel/restore fixtures pass; native cookie scope, redirects, vault and logout tests pass on Windows; failed recovery retries at most once; frontend build passes. Real campus acceptance requires a user login in a built client.
