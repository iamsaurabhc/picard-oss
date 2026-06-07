# Security Policy

Picard OSS handles privileged legal documents locally. We take security reports seriously and appreciate responsible disclosure.

## Supported versions

Security fixes are provided for:

| Version | Supported |
| ------- | --------- |
| Latest release on [GitHub Releases](https://github.com/iamsaurabhc/picard-oss/releases) | Yes |
| `main` branch (HEAD) | Yes |
| Older tagged releases | Best effort — upgrade recommended |

Release artifacts and update manifests: [releases/manifest.json](releases/manifest.json).

## Reporting a vulnerability

**Do not open a public GitHub issue for exploitable vulnerabilities.**

Email **saurabh.c@picard.law** with:

1. Description of the issue and potential impact
2. Steps to reproduce (proof of concept if available)
3. Affected version or commit
4. Your environment (OS, Docker vs desktop vs dev, browser if UI-related)
5. Whether you would like credit in release notes (optional)

We aim to acknowledge reports within **72 hours** and will keep you informed of progress.

You may also use [GitHub Private vulnerability reporting](https://github.com/iamsaurabhc/picard-oss/security/advisories/new) if enabled on the repository.

## In scope

Examples of issues we want to hear about:

- Path traversal or arbitrary file read/write via PDF upload, storage, or export
- Bypass of encrypted settings storage or exfiltration of API keys
- Remote code execution in backend, OCR sidecar, or desktop updater
- SSRF or unintended egress beyond user-configured LLM/OCR endpoints
- Docker Compose misconfiguration that exposes the API or data volume unintentionally
- Tauri updater integrity failures (unsigned or tampered updates)
- Cross-workspace data leakage in multi-document scenarios

## Out of scope / design expectations

These are intentional or environmental — not treated as vulnerabilities:

- **No authentication by design** — Picard OSS is a single-user local application. Network exposure of an unauthenticated instance is a deployment misconfiguration; bind to localhost in untrusted networks.
- **User-configured LLM egress** — sending document excerpts to OpenAI/Ollama is expected when chat or entity extraction is enabled.
- **AGPL-3.0 obligations** — licensing questions belong in [LICENSE](LICENSE) / [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md), not this channel.
- **Denial of service via large PDFs** — report if you find a trivial crash with a small, malformed file; large-document resource limits are a known class of hardening work.

## Safe harbor

We support good-faith security research on your own installations. We will not pursue legal action against researchers who:

- Avoid privacy violations and data destruction
- Do not access systems or data you do not own
- Report findings promptly and allow reasonable time for a fix before public disclosure

We ask for coordinated disclosure: please allow up to **90 days** for a fix before public release, unless we agree otherwise.

## Response process

1. Acknowledge receipt
2. Confirm and prioritize (critical / high / medium / low)
3. Develop and test a fix on `main`
4. Release a patched version and publish an advisory when appropriate
5. Credit reporters who opt in

Thank you for helping keep Picard OSS safe for legal engineers handling sensitive documents.
