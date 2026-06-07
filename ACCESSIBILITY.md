# Accessibility Statement

Picard OSS is a local-first legal document assistant. We are committed to making the web UI usable by everyone, including people who rely on assistive technology.

This statement describes our goals, supported environments, known limitations, and how to report barriers.

## Goals

We aim to meet **[WCAG 2.1 Level AA](https://www.w3.org/WAI/WCAG21/quickref/?levels=aaa)** where feasible for the Picard web interface, with priority on:

- **Keyboard access** — all primary workflows operable without a mouse
- **Visible focus** — clear focus indicators on interactive elements
- **Names and labels** — form controls, buttons, and links have accessible names
- **Screen reader support** — semantic HTML and appropriate ARIA where native elements are insufficient
- **Color and contrast** — text and controls meet contrast guidelines; meaning is not conveyed by color alone
- **Citation verification** — navigating from chat citations to source PDF pages

## Supported environments

| Platform | Support |
| -------- | ------- |
| Modern browsers (Chromium, Firefox, Safari) | Primary target |
| Desktop app (Tauri) | Same web UI in a native shell |
| Mobile browsers | Best effort; not a primary design target |
| CLI / backend API | See [Contributing — Testing](CONTRIBUTING.md); API is machine-oriented |

Document language is declared as English (`lang="en"`) in the root layout.

## Known limitations

We are actively improving accessibility. Current known gaps:

1. **PDF bbox highlights** — The citation overlay in `MultiHighlightPDFViewer` is canvas-based. Jump-to-page and citation pills work with keyboard, but individual highlight regions may not be fully exposed to screen readers yet.
2. **Streaming chat** — Answer text streams in incrementally; live-region announcements may be incomplete during generation.
3. **Complex data tables** — Tabular review grids may need additional header associations and keyboard patterns for large reviews.

If a limitation blocks your work, please report it (see below) — we prioritize issues that prevent completing core tasks.

## For contributors

When your pull request changes UI:

1. **Keyboard-only pass** — complete the affected flow without a mouse (Tab, Enter, Space, Escape, arrow keys).
2. **Focus order** — tab order matches visual layout; no focus traps unless intentional (e.g. modals with a clear exit).
3. **Native elements first** — prefer `<button>`, `<a>`, `<input>`, `<label>`, `<select>` over custom widgets.
4. **Focus outlines** — do not remove focus styles without providing an equivalent visible indicator.
5. **Forms** — every control has a label; errors are readable and associated with the field.
6. **Motion** — avoid flashing content; respect `prefers-reduced-motion` when adding animations.

See the accessibility checklist in the [pull request template](.github/pull_request_template.md).

Automated accessibility linting in CI is planned but not yet enforced.

## Reporting accessibility issues

Use the **[accessibility issue template](https://github.com/iamsaurabhc/picard-oss/issues/new?template=accessibility.yml)** and include:

- Expected vs actual behavior
- Steps to reproduce
- OS, browser, and **assistive technology** (e.g. VoiceOver, NVDA, JAWS) with version
- Severity: Critical (blocks a core task), High, Medium, or Low

Issues are labeled `accessibility` for triage. We treat accessibility reports as expertise, not noise — thank you for helping us improve.

For general bugs unrelated to accessibility, use the [bug report template](https://github.com/iamsaurabhc/picard-oss/issues/new?template=bug_report.yml).

## References

- [Open Source Guides — Accessibility](https://opensource.guide/accessibility/)
- [W3C — Developing an Accessibility Statement](https://www.w3.org/WAI/planning/statements/)
- [WCAG 2.1](https://www.w3.org/WAI/WCAG21/quickref/)
