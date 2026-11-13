import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd();
const {FileBlob,PresentationFile}=await import(pathToFileURL(path.join(process.env.RUNTIME_NODE_MODULES,'@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const file=path.join(root,'docs/deliverables/组会汇报_两例五组实验_20261106.pptx');
const dir=path.join(root,'work/ppt_20261106/final_render');
await fs.mkdir(dir,{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(file));
for(const [i,slide]of p.slides.items.entries()){
  const stem=`${dir}/slide-${String(i+1).padStart(2,'0')}`;
  const image=await p.export({slide,format:'png',scale:1});
  await fs.writeFile(stem+'.png',new Uint8Array(await image.arrayBuffer()));
  const layout=await slide.export({format:'layout',detail:'full'});
  await fs.writeFile(stem+'.layout.json',await layout.text());
}
const snapshot=await p.inspect({select:'$.slides[*]',include:['id','index','layout','elements.id','elements.kind','elements.name','elements.text','elements.position','elements.style','notes.text']});
await fs.writeFile(dir+'/inspection.ndjson',snapshot.ndjson);
const montage=await p.export({format:'png',montage:{columns:2,slideWidth:640},scale:1});
await fs.writeFile(dir+'/montage.png',new Uint8Array(await montage.arrayBuffer()));
console.log(JSON.stringify({slides:p.slides.items.length,output:dir}));
