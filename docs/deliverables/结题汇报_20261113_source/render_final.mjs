import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
const root=process.cwd().replaceAll('\\','/');
const {FileBlob,PresentationFile}=await import(pathToFileURL(path.join(process.env.RUNTIME_NODE_MODULES,'@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const source=root+'/docs/deliverables/结题汇报_深入分析版_20261113_定稿.pptx';
const target=root+'/work/ppt_update_20261113/final_render';
const p=await PresentationFile.importPptx(await FileBlob.load(source));
await fs.mkdir(target,{recursive:true});
const hashes=[];
for(const [i,slide] of p.slides.items.entries()){
 const bytes=new Uint8Array(await (await p.export({slide,format:'png',scale:1})).arrayBuffer());
 await fs.writeFile(target+'/slide-'+String(i+1).padStart(2,'0')+'.png',bytes);
 hashes.push({slide:i+1,sha256:crypto.createHash('sha256').update(bytes).digest('hex')});
}
await fs.writeFile(root+'/runs/ppt_analysis_20261113_01/final_render_manifest_v2.json',JSON.stringify({source,source_sha256:crypto.createHash('sha256').update(await fs.readFile(source)).digest('hex'),slides:hashes},null,2));
console.log(JSON.stringify({rendered:hashes.length,target}));
