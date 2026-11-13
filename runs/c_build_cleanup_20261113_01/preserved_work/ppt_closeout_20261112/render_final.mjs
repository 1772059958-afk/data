import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd().replaceAll('\\','/');
const {FileBlob,PresentationFile}=await import(pathToFileURL(path.join(process.env.RUNTIME_NODE_MODULES,'@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const input=root+'/docs/deliverables/结题汇报_自适应混合架构程序修复_20261112.pptx';
const out=root+'/work/ppt_closeout_20261112/final_render';await fs.mkdir(out,{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(input));
for(const [i,slide] of p.slides.items.entries()){
 const image=await p.export({slide,format:'png',scale:1});await fs.writeFile(out+'/slide-'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await image.arrayBuffer()));
}
console.log(JSON.stringify({slides:p.slides.items.length,out}));
