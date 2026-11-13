import fs from 'node:fs/promises';
import {FileBlob,PresentationFile} from 'file:///C:/Users/remil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
const root='C:/Users/remil/Desktop/3yr/科研/proj';
const decks=[['20261030','组会汇报_边界修复与dev准备_20261030.pptx'],['20261029','组会汇报_开题对齐与离线验证_20261029.pptx']];
for (const [tag,name] of decks) {
  const dir=`${root}/work/ppt_20261106/reference_${tag}`;
  await fs.mkdir(dir,{recursive:true});
  const p=await PresentationFile.importPptx(await FileBlob.load(`${root}/docs/deliverables/${name}`));
  const content=await p.inspect({select:'$.slides[*]',include:['id','index','layout','elements.id','elements.kind','elements.name','elements.text','elements.position','elements.style','notes.text']});
  await fs.writeFile(`${dir}/inspection.ndjson`,content.ndjson);
  await fs.writeFile(`${dir}/source.json`,JSON.stringify(p.toProto()));
  console.log(tag,JSON.stringify({slides:p.slides.items.length,size:p.toProto().slideSize,masters:p.masters.items.map(x=>({id:x.id,name:x.name,placeholders:x.placeholders.summary()})),layouts:p.layouts.items.map(x=>({id:x.id,name:x.name,placeholders:x.placeholders.summary()}))}));
  for (const [i,slide] of p.slides.items.entries()) {
    const stem=`${dir}/slide-${String(i+1).padStart(2,'0')}`;
    const image=await p.export({slide,format:'png',scale:1});
    await fs.writeFile(stem+'.png',new Uint8Array(await image.arrayBuffer()));
    const layout=await slide.export({format:'layout',detail:'full'});
    await fs.writeFile(stem+'.layout.json',await layout.text());
  }
  const montage=await p.export({format:'png',montage:{columns:2,slideWidth:640},scale:1});
  await fs.writeFile(`${dir}/montage.png`,new Uint8Array(await montage.arrayBuffer()));
}
