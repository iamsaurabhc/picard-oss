# picard.law download page integration

The marketing site (legaldocx repo) should consume the Picard OSS release manifest so download URLs update automatically on each release.

## Manifest URL

```
https://raw.githubusercontent.com/iamsaurabhc/picard-oss/gh-pages/releases/manifest.json
```

Override at build time: `PICARD_RELEASE_MANIFEST_URL`.

## Example (Next.js client component)

```tsx
const MANIFEST_URL =
  process.env.NEXT_PUBLIC_PICARD_RELEASE_MANIFEST_URL ??
  "https://raw.githubusercontent.com/iamsaurabhc/picard-oss/gh-pages/releases/manifest.json";

export async function getDownloadLinks() {
  const res = await fetch(MANIFEST_URL, { next: { revalidate: 300 } });
  const m = await res.json();
  return {
    version: m.version,
    releasedAt: m.released_at,
    platforms: m.platforms as Record<string, { url: string; sha256: string }>,
    notesUrl: m.notes_url,
  };
}
```

## OS detection

| User agent / `navigator.platform` | Primary key |
|-----------------------------------|-------------|
| Mac ARM | `darwin-aarch64` |
| Mac Intel | `darwin-x86_64` |
| Windows | `windows-x86_64` |
| Linux | `linux-x86_64` |

Show version label `v{m.version}` and fallback link to GitHub Releases latest.

## CI automation

After each tagged release, [`release.yml`](../.github/workflows/release.yml) runs:

```bash
python3 scripts/export_website_downloads.py releases/manifest.json
```

Copy [`website/downloads.example.json`](../website/downloads.example.json) (or the `website-downloads-json` workflow artifact) into the legaldocx repo as `public/picard-downloads.json`, or fetch `manifest_url` at build time per the example below.

Optional: add `repository_dispatch` from the release workflow to open a PR in legaldocx automatically.
