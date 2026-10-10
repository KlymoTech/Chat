import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {describe,expect,it} from "vitest";

const script=fileURLToPath(new URL("../scripts/verify-imports.mjs",import.meta.url));
describe("offline relative-import preflight",()=>{
  it("accepts valid local imports and rejects missing relative modules",()=>{
    const folder=mkdtempSync(join(tmpdir(),"website-relative-import-"));
    try{
      mkdirSync(join(folder,"src"),{recursive:true});
      writeFileSync(join(folder,"src","component.ts"),'import {test} from "./contract";\nexport {test};\n');
      writeFileSync(join(folder,"src","contract.ts"),"export const test=true;\n");
      const valid=spawnSync(process.execPath,[script,folder],{encoding:"utf8",timeout:10000});
      expect(valid.status).toBe(0);
      expect(valid.stdout).toContain('"unresolved":0');
      writeFileSync(join(folder,"src","broken.ts"),
        'import {unknown} from "./nonexistent";\nexport {unknown};\n');
      const broken=spawnSync(process.execPath,[script,folder],{encoding:"utf8",timeout:10000});
      expect(broken.status).toBe(1);
      expect(broken.stderr).toContain("unresolved ./nonexistent");
      expect(broken.stdout).toContain('"unresolved":1');
    }finally{rmSync(folder,{recursive:true,force:true});}
  });
});
