import fs from 'node:fs/promises';
import {FileBlob,PresentationFile} from 'file:///C:/Users/remil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
const root='C:/Users/remil/Desktop/3yr/科研/proj';
const dir=root+'/work/ppt_20261030/reference';
await fs.mkdir(dir,{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(root+'/docs/deliverables/组会汇报_开题对齐与离线验证_20261029.pptx'));
console.log('Slides',p.slides.items.length);
await fs.writeFile(dir+'/source.json',JSON.stringify(p.toProto()));
const snapshot=await p.inspect({select:'$.slides[*]',include:['id','index','layout','elements.id','elements.kind','elements.name','elements.text','elements.position','elements.style']});
await fs.writeFile(dir+'/inspection.ndjson',snapshot.ndjson);
await fs.writeFile(dir+'/layouts.json',JSON.stringify(p.toProto().layouts));
for(let i=0;i<p.slides.items.length;i++){
 const img=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(dir+`/slide-${i+1}.png`,new Uint8Array(await img.arrayBuffer()));
}
const montage=await p.export({format:'png',montage:{columns:2,slideWidth:640},scale:1});
await fs.writeFile(dir+'/montage.png',new Uint8Array(await montage.arrayBuffer()));
console.log('Reference rendered',p.toProto().slideSize);
