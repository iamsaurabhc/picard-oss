#!/usr/bin/env node
/**
 * Sidecar for backend DOCX mutations via @superdoc-dev/sdk.
 * Usage: node mutate.mjs <path> search <pattern>
 *        node mutate.mjs <path> replace <pattern> <replacement> [--tracked]
 */
import { createSuperDocClient } from "@superdoc-dev/sdk";

const [docPath, action, pattern, replacement, ...rest] = process.argv.slice(2);
const tracked = rest.includes("--tracked");

if (!docPath || !action || !pattern) {
  console.error("Usage: mutate.mjs <path> search|replace <pattern> [replacement] [--tracked]");
  process.exit(1);
}

const client = createSuperDocClient({ defaultChangeMode: tracked ? "tracked" : "direct" });

try {
  await client.connect();
  const doc = await client.open({ doc: docPath });

  if (action === "search") {
    const match = await doc.query.match({
      select: { type: "text", pattern },
      require: "all",
    });
    console.log(JSON.stringify({ matches: match.items ?? [] }));
  } else if (action === "replace") {
    if (!replacement) {
      console.error("replace requires a replacement string");
      process.exit(1);
    }
    const found = await doc.query.match({
      select: { type: "text", pattern },
      require: "first",
    });
    const target = found.items?.[0]?.target;
    if (!target) {
      console.error(JSON.stringify({ error: `No match for pattern: ${pattern}` }));
      process.exit(2);
    }
    await doc.replace({
      target,
      text: replacement,
      changeMode: tracked ? "tracked" : "direct",
    });
    await doc.save({ inPlace: true });
    console.log(JSON.stringify({ ok: true, pattern, replacement, tracked }));
  } else {
    console.error(`Unknown action: ${action}`);
    process.exit(1);
  }

  await doc.close();
  await client.dispose();
} catch (err) {
  const message = err instanceof Error ? err.message : String(err);
  console.error(JSON.stringify({ error: message }));
  process.exit(3);
}
