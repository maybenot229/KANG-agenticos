// Registry -> TypeScript client generator, Node half (ADR-011).
//
// Reads the JSON snapshot tools/generate_ts_client.py produced (a real
// registry.get response, fetched from a live throwaway Core over HTTP —
// see that script's docstring for why it has to go through the wire
// rather than an import) and emits one TypeScript interface per
// non-null request_schema/response_schema, via json-schema-to-typescript
// (ADR-011's chosen tool). Output is generated-only, never hand-edited
// (12_API §16 / 17 §12's rule for docs/generated/, applied here).
//
// Usage: node scripts/generate-client.mjs [snapshot.json] [outDir]

import { compile } from "json-schema-to-typescript";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..");

const snapshotPath = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(projectRoot, "registry.snapshot.json");
const outDir = process.argv[3]
  ? path.resolve(process.argv[3])
  : path.join(projectRoot, "src", "generated");

const BANNER =
  "/* eslint-disable */\n" +
  "/**\n" +
  " * GENERATED — do not hand-edit (12_API §16 / ADR-011).\n" +
  " * Rebuild: python tools/generate_ts_client.py && npm run generate\n" +
  " */\n";

/**
 * Pydantic stamps a per-field JSON Schema `"title"` on every property by
 * default (e.g. `plan_date` gets `"title": "Plan Date"`), and that title
 * is what makes json-schema-to-typescript hoist the field into its own
 * named top-level alias (`export type PlanDate = ...;`) instead of
 * inlining the type directly into the interface. Two operations that
 * both happen to have a `plan_date` field then fight over the same
 * generated name `PlanDate` — caught for real here: `plan.generate`'s
 * request has `plan_date: string | null` (optional) and its response has
 * `plan_date: string` (always present) — genuinely different types,
 * which produced a real TS2300 duplicate-identifier compile error, not a
 * cosmetic one. Stripping property-level titles before compiling (kept:
 * the schema's own root `title`, which becomes the interface name and is
 * already guaranteed unique — it's the Pydantic model's class name)
 * removes the hoisting behavior entirely: every field inlines, so there
 * is nothing left to collide on.
 */
function stripPropertyTitles(schema) {
  const clone = JSON.parse(JSON.stringify(schema));
  const strip = (node) => {
    if (node === null || typeof node !== "object") return;
    if (node.properties && typeof node.properties === "object") {
      for (const prop of Object.values(node.properties)) {
        if (prop && typeof prop === "object") delete prop.title;
        strip(prop);
      }
    }
    for (const key of ["$defs", "definitions"]) {
      if (node[key] && typeof node[key] === "object") {
        for (const value of Object.values(node[key])) strip(value);
      }
    }
    if (Array.isArray(node.anyOf)) node.anyOf.forEach(strip);
    if (node.items) strip(node.items);
  };
  strip(clone);
  return clone;
}

/**
 * Splits one compiled chunk into its top-level declarations. With
 * property titles stripped (above), this should now only ever see one
 * `export interface` per compile() call — kept general (handles a stray
 * `export type` too) as a safety net, using a line-based brace-depth
 * counter rather than guessing at closing-line text: a declaration ends
 * on the first line where the running count of `{` minus `}` returns to
 * zero. Each declaration keeps any immediately-preceding `/** ... *‍/`
 * doc comment.
 */
function splitDeclarations(compiled) {
  const lines = compiled.split("\n");
  const declarations = [];
  let i = 0;
  while (i < lines.length) {
    if (lines[i].trim() === "") {
      i += 1;
      continue;
    }
    const blockLines = [];
    if (lines[i].trimStart().startsWith("/**")) {
      while (i < lines.length && !lines[i].includes("*/")) {
        blockLines.push(lines[i]);
        i += 1;
      }
      blockLines.push(lines[i]); // the "*/" line itself
      i += 1;
    }
    if (i >= lines.length || !/^export (type|interface) /.test(lines[i])) {
      throw new Error(
        `expected an "export type"/"export interface" line, got: ${JSON.stringify(lines[i])}`,
      );
    }
    let depth = 0;
    do {
      const line = lines[i];
      blockLines.push(line);
      for (const ch of line) {
        if (ch === "{") depth += 1;
        else if (ch === "}") depth -= 1;
      }
      i += 1;
    } while (i < lines.length && depth > 0);
    const text = blockLines.join("\n").trimEnd();
    const match = text.match(/export (?:type|interface) (\w+)/);
    if (!match) {
      throw new Error(`could not find a declaration name in block:\n${text}`);
    }
    declarations.push({ name: match[1], text });
  }
  return declarations;
}

/** Strips leading doc-comment blocks before comparing bodies, so two
 * declarations that differ only in which operation's comment happens to
 * be attached still count as duplicates when their actual type body is
 * identical. */
function bodyOnly(text) {
  return text.replace(/^\/\*\*[\s\S]*?\*\/\n/, "").trim();
}

function mergeDeclarations(allDeclarations, prefix) {
  const byName = new Map(); // name -> text (first occurrence kept)
  for (const decl of allDeclarations) {
    const existing = byName.get(decl.name);
    if (existing === undefined) {
      byName.set(decl.name, decl.text);
      continue;
    }
    if (bodyOnly(existing) !== bodyOnly(decl.text)) {
      // A genuine conflict: two operations under the same prefix want
      // the same type name to mean two different things. Loud failure,
      // not a silently-picked winner (11_CODING §9: no silent fallbacks).
      throw new Error(
        `${prefix}: type name collision on "${decl.name}" with different ` +
          `bodies — rename one of the source Pydantic models so their ` +
          `titles differ.\n--- first ---\n${existing}\n--- second ---\n${decl.text}`,
      );
    }
    // Identical body (e.g. two operations both have a plain `string`
    // correlation_id) — keep the first, drop the duplicate.
  }
  return [...byName.values()];
}

async function main() {
  const raw = await readFile(snapshotPath, "utf-8");
  const registry = JSON.parse(raw);

  await mkdir(outDir, { recursive: true });

  const operationsWithSchemas = registry.operations.filter(
    (op) => op.request_schema !== null || op.response_schema !== null,
  );

  const declarationsByPrefix = new Map(); // prefix -> declaration[]

  for (const op of operationsWithSchemas) {
    const [prefix] = op.name.split(".");
    if (!declarationsByPrefix.has(prefix)) declarationsByPrefix.set(prefix, []);
    const bucket = declarationsByPrefix.get(prefix);

    for (const schema of [op.request_schema, op.response_schema]) {
      if (schema === null) continue;
      const compiled = await compile(stripPropertyTitles(schema), schema.title, {
        bannerComment: "",
        additionalProperties: false,
      });
      bucket.push(...splitDeclarations(compiled));
    }
  }

  for (const [prefix, declarations] of declarationsByPrefix) {
    const merged = mergeDeclarations(declarations, prefix);
    const filePath = path.join(outDir, `${prefix}.ts`);
    await writeFile(filePath, BANNER + "\n" + merged.join("\n\n") + "\n", "utf-8");
  }

  console.log(
    `generated ${declarationsByPrefix.size} file(s) for ${operationsWithSchemas.length} operation(s) into ${outDir}`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
