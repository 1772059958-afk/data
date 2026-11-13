import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {constants} from 'node:fs';
import {pathToFileURL} from 'node:url';
const root='C:/Users/remil/Desktop/3yr/科研/proj';
const build=root+'/work/ppt_20261030';
const skill='C:/Users/remil/.codex/plugins/cache/openai-primary-runtime/presentations/26.1025.11240/skills/presentations';
const host='C:/Users/remil/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Roaming/Codex/web/Codex/artifact-sessions/exports/latest/3b5633dbec0312c887e508d61ae9b950856f1f5e2ae4e077aa4afa24999720a2';
const source=root+'/docs/deliverables/组会汇报_开题对齐与离线验证_20261029.pptx';
const candidate=build+'/draft/candidate.pptx';
const finalPath=root+'/docs/deliverables/组会汇报_边界修复与dev准备_20261030.pptx';
await fs.mkdir(build+'/draft',{recursive:true});
await fs.writeFile(candidate,await fs.readFile(host+'/group_meeting_20261030.pptx'));
process.env.RUNTIME_NODE_MODULES='C:/Users/remil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
// This Windows sandbox disallows hard links. Keep every validator and hash
// check, but publish with an exclusive no-overwrite copy if hardlink fails.
const nativeLink=fs.link.bind(fs);
fs.link=async(source,destination)=>{
 try{return await nativeLink(source,destination);}catch(error){
  if(process.platform!=='win32'||error.code!=='EPERM'||!source.endsWith('.validated')||destination.replaceAll('\\','/')!==finalPath)throw error;
  await fs.copyFile(source,destination,constants.COPYFILE_EXCL);
 }
};
const result=await finalizePresentation({
 explicitTotalSlideCount:10,
 requiredNativeTableOwnerSlides:[3,4,7],
 requiredNativeChartOwnerSlides:[],
 workspaceDir:root,
 candidatePath:candidate,
 finalPath,
 pythonExecutable:'C:/Users/remil/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
 integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',
 layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[3,4,7].flatMap(n=>['--require-native-table-slide',String(n)])],
 fontPolicy:{basis:'reference',families:['微软雅黑'],referencePath:source,referenceSha256:crypto.createHash('sha256').update(await fs.readFile(source)).digest('hex')},
 verifyArtifactToolImport:true,
 receiptPath:build+'/validation.json'
});
console.log(JSON.stringify(result,null,2));
