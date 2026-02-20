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
