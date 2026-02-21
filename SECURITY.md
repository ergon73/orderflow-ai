# Security Policy

## Supported Scope

Security support applies to the current `main` branch state of the project.

## Reporting a Vulnerability

Preferred path:
1. Use GitHub private vulnerability reporting (Security Advisories) if enabled for this repo.
2. If unavailable, contact repository owner directly (GitHub profile contact).

Please include:
- affected component/file;
- steps to reproduce;
- impact assessment;
- suggested mitigation (if any).

Please do not publish exploit details in public issues before triage.

## Triage Targets

- Initial response target: within 5 business days.
- Severity classification: Critical / High / Medium / Low.
- Fix policy:
  - Critical/High: prioritized hotfix path.
  - Medium/Low: planned fix in regular cycle.

## Current Security Posture

MVP baseline already includes:
- authentication on dashboard/API;
- callback ownership checks in bot flows;
- secret masking in logs;
- rate limiting for storefront/API.

Production hardening is tracked separately:
- `docs/production_readiness_roadmap.md`.

## Dependency Risk Notes

As of February 21, 2026:
- `pip-audit` reports `CVE-2025-69872` (`GHSA-w8v5-vhqr-4h9v`) in transitive dependency `diskcache==5.6.3`
  (pulled by `instructor`).

Current mitigation in this MVP:
- no direct use of `diskcache` API in project code;
- deployment model assumes restricted filesystem access for application runtime;
- quality/security pipeline includes regular `pip-audit` to catch upstream fixes quickly.
- CI temporarily ignores this exact CVE in `pip-audit` to keep the gate actionable for new issues only.

Planned action:
- upgrade `instructor`/`diskcache` as soon as a patched version is published and verify in CI.
