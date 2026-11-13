import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { FileBlob, PresentationFile } from 'file:///C:/Users/remil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
const root='C:/Users/remil/Desktop/3yr/科研/proj';
const build=root+'/work/ppt_20261029';
const skill='C:/Users/remil/.codex/plugins/cache/openai-primary-runtime/presentations/26.1025.11240/skills/presentations';
process.env.RUNTIME_NODE_MODULES='C:/Users/remil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const source=root+'/dustbin/legacy_20261029/docs/deliverables/第7周进展汇报_自适应混合架构.pptx';
const finalPath=root+'/docs/deliverables/组会汇报_开题对齐与离线验证_20261029.pptx';
const hash=crypto.createHash('sha256').update(await fs.readFile(source)).digest('hex');
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
await fs.mkdir(root+'/docs/deliverables',{recursive:true});
const result=await finalizePresentation({
 explicitTotalSlideCount:10,
 requiredNativeTableOwnerSlides:[3,4,7],
 requiredNativeChartOwnerSlides:[],
 workspaceDir:root,
 candidatePath:build+'/draft/candidate.pptx',
 finalPath,
 pythonExecutable:'C:/Users/remil/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
 integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',
 layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[3,4,7].flatMap(n=>['--require-native-table-slide',String(n)])],
 fontPolicy:{basis:'reference',families:['微软雅黑'],referencePath:source,referenceSha256:hash},
 verifyArtifactToolImport:true,
 receiptPath:build+'/validation.json',
});
console.log(JSON.stringify(result,null,2));
const p=await PresentationFile.importPptx(await FileBlob.load(finalPath));
await fs.mkdir(build+'/final_render',{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
 const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(build+`/final_render/slide-${i+1}.png`,new Uint8Array(await blob.arrayBuffer()));
}
console.log('Final slides rendered',p.slides.items.length);
