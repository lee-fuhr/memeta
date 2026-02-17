# Security policy

## Supported versions

Only the latest release on `main` receives security fixes.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, email **hi@leefuhr.com** with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

You'll receive a response within 48 hours. If the issue is confirmed, a fix will be released as soon as possible and you'll be credited in the changelog (unless you prefer anonymity).

## Scope

Total Recall runs locally and stores all data on your machine. There is no server-side component, no telemetry, and no data leaves your system unless you explicitly configure external API calls (Claude API for extraction, sentence-transformers for embeddings).

**Out of scope:**
- Vulnerabilities in dependencies (report to those projects directly)
- Issues that require physical access to the machine
- Self-inflicted misconfiguration
