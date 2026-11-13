import fs from 'node:fs/promises';
import {FileBlob, PresentationFile} from 'file:///C:/Users/remil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
const root='C:/Users/remil/Desktop/3yr/科研/proj';
const source=root+'/work/ppt_20261029/reference_compatible.pptx';
const dir=root+'/work/ppt_20261029/reference';
await fs.mkdir(dir,{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(source));
const inspection=await p.inspect({kind:'slide,textbox,shape,image,table,chart,layout',maxChars:1000000});
await fs.writeFile(dir+'/inspection.ndjson',inspection.ndjson);
await fs.writeFile(dir+'/proto.json',JSON.stringify(p.toProto()));
console.log('Imported reference',p.slides.items.length);
for(let i=0;i<p.slides.items.length;i++){
  const png=await p.export({slide:p.slides.items[i],format:'png',scale:1});
  await fs.writeFile(dir+`/slide-${i+1}.png`,new Uint8Array(await png.arrayBuffer()));
  console.log('Rendered',i+1);
}
const montage=await p.export({format:'webp',montage:true,scale:.5});
await fs.writeFile(dir+'/montage.webp',new Uint8Array(await montage.arrayBuffer()));
