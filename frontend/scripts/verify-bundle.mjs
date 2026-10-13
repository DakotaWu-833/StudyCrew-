import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
const assets = resolve(import.meta.dirname, "../../static/workspace/assets");
for (const name of readdirSync(assets).filter(name => name.endsWith(".js"))) {
  if (/(?:from|import\()\s*["'][^"']*\bmain\.js(?:["']|\?)/.test(readFileSync(resolve(assets, name), "utf8"))) {
    throw new Error(`${name} imports the entry module again. Versioned Django entry URLs require independently shared chunks.`);
  }
}
console.log("Bundle imports preserve one application root and shared contexts.");
