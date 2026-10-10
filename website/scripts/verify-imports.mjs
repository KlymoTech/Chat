#!/usr/bin/env node
/**
 * Lightweight offline import-graph preflight. Run before the Next.js build.
 * Checks local relative imports only; TypeScript handles package exports/types.
 */
import {existsSync,readdirSync,statSync,readFileSync} from "node:fs";
import {dirname,extname,join,relative,resolve} from "node:path";
import {fileURLToPath} from "node:url";

const root=process.argv[2]?resolve(process.argv[2]):
  resolve(dirname(fileURLToPath(import.meta.url)),"..");
const sources=["src","tests","scripts"];
const extensions=[".ts",".tsx",".js",".jsx",".mjs",".cjs",".json",".css"];
const scanned=new Set([".ts",".tsx",".js",".jsx",".mjs",".cjs"]);
const failures=[];
let files=0,imports=0;
function walk(dir){
  if(!existsSync(dir))return;
  for(const entry of readdirSync(dir,{withFileTypes:true})){
    if(entry.name.startsWith(".")||entry.name==="node_modules")continue;
    const path=join(dir,entry.name);
    if(entry.isDirectory()){walk(path);continue;}
    if(!entry.isFile()||!scanned.has(extname(path)))continue;
    files++;
    const source=readText(path);
    // Handles static, side-effect, dynamic string and require imports, including
    // imports whose "from" keyword is on a different line. Non-literal imports
    // remain TypeScript/bundler work and are not interpreted as executable code.
    const expressions=[
      /\bfrom\s*["'](\.[^"'\n]+)["']/g,
      /\bimport\s*["'](\.[^"'\n]+)["']/g,
      /\bimport\s*\(\s*["'](\.[^"'\n]+)["']/g,
      /\brequire\s*\(\s*["'](\.[^"'\n]+)["']/g,
    ];
    const importsInFile=new Set();
    for(const pattern of expressions){
      for(const match of source.matchAll(pattern))importsInFile.add(match[1]);
    }
    for(const target of importsInFile){
      imports++;
      const bare=target.split("?")[0].split("#")[0];
      const absolute=resolve(dirname(path),bare);
      const candidates=[absolute,...extensions.map(ext=>absolute+ext),
        ...extensions.map(ext=>join(absolute,"index"+ext))];
      if(!candidates.some(file=>existsSync(file)&&statSync(file).isFile())){
        failures.push(relative(root,path)+": unresolved "+target);
      }
    }
  }
}
function readText(path){
  // Use a direct small read rather than executing, importing or evaluating code.
  return readFileSync(path,"utf8");
}

for(const source of sources)walk(join(root,source));
const config=join(root,"playwright.config.ts");
if(existsSync(config))files++; // its module imports only third-party packages.
for(const issue of failures)console.error(issue);
console.log(JSON.stringify({filesScanned:files,relativeImportsChecked:imports,
  unresolved:failures.length}));
if(failures.length)process.exitCode=1;
