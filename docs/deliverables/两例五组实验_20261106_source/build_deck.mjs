import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {constants} from 'node:fs';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {validateReportData} from './validate_report_data.mjs';

const here=path.dirname(fileURLToPath(import.meta.url));
let root=here;
while(true){
  try{await fs.access(path.join(root,'configs/proposal_v1.json'));break;}catch{}
  const parent=path.dirname(root);
  if(parent===root)throw new Error('无法发现项目根目录');
  root=parent;
}
root=root.replaceAll('\\','/');
const build=(process.env.PPT_BUILD_DIR??root+'/work/ppt_20261106').replaceAll('\\','/');
const skill=process.env.PRESENTATIONS_SKILL_DIR;
const runtimeModules=process.env.RUNTIME_NODE_MODULES;
if(!skill||!runtimeModules)throw new Error('请设置PRESENTATIONS_SKILL_DIR与RUNTIME_NODE_MODULES');
const {FileBlob,PresentationFile}=await import(pathToFileURL(path.join(runtimeModules,'@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const source=root+'/docs/deliverables/组会汇报_边界修复与dev准备_20261030.pptx';
const output=(process.env.PPT_FINAL_PATH??root+'/docs/deliverables/组会汇报_两例五组实验_20261106.pptx').replaceAll('\\','/');
const dataPath=process.argv.slice(2).find(arg=>!arg.startsWith('--'))??path.join(here,'report_data.json');
const data=validateReportData(JSON.parse((await fs.readFile(dataPath,'utf8')).replace(/^\uFEFF/,'')));
const p=await PresentationFile.importPptx(await FileBlob.load(source));
if(p.slides.items.length!==10)throw new Error('参考必须保留10页');
const font='微软雅黑',ink='#202020',blue='#2F5597',gray='#606060';
const text=(slide,name,value,{left=70,top=186,width=1130,height=54,size=25,color=ink,bold=false,align='left'}={})=>{
  const shape=slide.shapes.add({name,geometry:'textbox',position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});
  shape.text=String(value);
  shape.text.style={typeface:font,fontSize:size,color,bold,alignment:align,verticalAlignment:'top',insets:0,wrap:'square',autoFit:'none'};
  return shape;
};
const snap=await p.inspect({select:'$.slides[*]',include:['id','elements.id','elements.kind','elements.name']});
for(const [i,slide] of p.slides.items.entries()){
  if(i===0)continue;
  for(const element of snap.records[i].elements){
    if(element.name==='标题 4'||element.name==='page-number')continue;
    if(['textbox','shape','table','chart'].includes(element.kind))p.delete(element.id);
  }
}
const s=p.slides.items;
const setExisting=(slide,name,value,size,color=ink,bold=false,align='left')=>{
  const shape=slide.shapes.items.find(x=>x.name===name);
  if(!shape)throw new Error(`缺模板元素 ${name}`);
  shape.text=value;
  shape.text.style={typeface:font,fontSize:size,color,bold,alignment:align,verticalAlignment:'top',insets:0,wrap:'square',autoFit:'none'};
};
const title=(slide,value)=>setExisting(slide,'标题 4',value,32,ink,true);
const table=(slide,values,{top=186,widths=[160,500,500],heights,bodySize=23}={})=>{
  const height=heights?.reduce((a,b)=>a+b,0)??350;
  const t=slide.tables.add({rows:values.length,columns:values[0].length,left:60,top,width:1160,height,columnWidths:widths,values});
  t.styleOptions={headerRow:true,bandedRows:true};
  t.borders.assign({style:'solid',fill:'#CFD7E3',width:1});
  values.forEach((row,r)=>{
    if(heights)t.rows[r].height=heights[r];
    row.forEach((_,c)=>{
      const cell=t.getCell(r,c);
      cell.fill=r===0?'#2F5597':r%2===1?'#F3F5F8':'#FFFFFF';
      cell.text.style={typeface:font,fontSize:bodySize,color:r===0?'#FFFFFF':c===0?blue:ink,bold:r===0||c===0,alignment:'left',verticalAlignment:'middle',insets:{left:16,right:12,top:9,bottom:9},wrap:'square',autoFit:'none'};
    });
  });
  return t;
};
const note=(i,body)=>s[i].speakerNotes.text=body+'\n\n本地资料来源：\n'+data.sources_by_slide[i].join('\n');
const toolsLayout=p.layouts.items.find(x=>x.name==='内容页-标题5');
const evalLayout=p.layouts.items.find(x=>x.name==='内容页-标题4');
for(const i of [3,4])if(toolsLayout)s[i].setLayout(toolsLayout);
for(const i of [5,6,7,8])if(evalLayout)s[i].setLayout(evalLayout);

setExisting(s[0],'标题 5','面向仓库级程序修复的\n自适应混合架构',44,ink,true,'center');
setExisting(s[0],'文本占位符 7',`两例五组实验\n汇报人：陈堉锋　张曹远臻\n${data.date}`,26,ink,false,'center');
note(0,`本次运行规模为${data.scale}。${data.summary}`);

title(s[1],'本轮实验任务');
text(s[1],'experiment-scale',data.scale,{size:38,bold:true,color:blue,height:60});
text(s[1],'selected-instances','pvlib-1707　　pydicom-1139',{top:257,size:26,color:gray});
text(s[1],'task-label','实验内容',{top:337,size:27,bold:true,color:blue});
text(s[1],'task-body','同一模型与资源上限，比较固定、交互及三种混合策略',{top:385,size:25,height:65});
text(s[1],'completion-label','实际完成',{top:470,size:27,bold:true,color:blue});
text(s[1],'completion-body',data.completion,{top:518,size:25,height:70});
text(s[1],'overview',data.summary,{top:614,size:24,bold:true,color:blue,height:40});
note(1,`固定dev样本：${data.instances.join('、')}。本轮累计费用上限${data.budget_ceiling_cny} CNY。${data.completion}`);

title(s[2],'五组执行路径');
table(s[2],[['策略','执行起点','延续规则'],
  ['A 固定','共享固定前缀','固定延续'],
  ['B 纯交互','相同初始问题与checkout','从零交互，不运行固定前缀'],
  ['C 级联','共享固定前缀','可继续的前缀失败转入交互'],
  ['D 自适应','共享固定前缀','根据失败证据选择固定或交互'],
  ['E 随机','共享固定前缀','按D在eligible dev的触发率随机选择']],
  {widths:[170,360,630],heights:[56,66,66,66,66,66],bodySize:23});
text(s[2],'shared-cache','A/C/D/E 复用同一实际前缀，每组只执行选中的延续分支',{top:603,size:25,bold:true,color:blue,height:60});
note(2,'本轮使用dev-only pilot入口。前缀缓存校验配置、镜像和基线身份，各策略完整计入继承前缀成本，同时单列本次真实新增成本。B独立从相同初始信息出发。'+data.candidate_calibration.notes);

title(s[3],'两例运行环境');
table(s[3],[['实例/环节','遇到的问题','本轮处理'],...data.environment_rows],{widths:[190,460,510],heights:[56,...data.environment_rows.map(()=>83)],bodySize:23});
text(s[3],'environment-outcome',data.interface_lines.environment,{top:601,size:25,bold:true,color:blue,height:62});
note(3,data.interface_lines.environment_notes);

title(s[4],'离线回归与真实接口');
const checks=[
  ['离线套件',`${data.offline.passed} / ${data.offline.total} 项通过`],
  ['原件保护',`原始资产 ${data.offline.protected_original}，归档原件 ${data.offline.protected_archive}`],
  ['模型接口',data.interface_lines.model],
  ['独立评测',data.interface_lines.scoring]
];
checks.forEach(([label,body],i)=>{
  text(s[4],`check-label-${i}`,label,{left:70,top:190+i*101,width:180,height:44,size:27,color:blue,bold:true});
  text(s[4],`check-body-${i}`,body,{left:270,top:190+i*101,width:930,height:80,size:25});
});
text(s[4],'api-footnote',data.interface_lines.footnote,{top:624,size:21,color:gray,height:40});
note(4,data.interface_lines.notes);

title(s[5],'两例五组独立判分结果');
text(s[5],'result-legend','每格列出实际路线与独立判分结果',{top:178,size:24,color:gray});
const resultsByKey=new Map(data.results.map(r=>[`${r.instance_id}/${r.arm}`,r]));
table(s[5],[['实例','A 固定','B 纯交互','C 级联','D 自适应','E 随机'],...data.instances.map((id,i)=>[
  i===0?'pvlib\n1707':'pydicom\n1139',...'ABCDE'.split('').map(arm=>{const r=resultsByKey.get(`${id}/${arm}`);return `${r.route}\n${r.verdict}`;})
])],{top:246,widths:[160,200,200,200,200,200],heights:[60,122,122],bodySize:23});
text(s[5],'result-takeaway',data.totals.result_summary,{top:587,size:27,color:blue,bold:true,height:70});
note(5,data.results.map(r=>`${r.instance_id} ${r.arm}：${r.route}，${r.verdict}，status=${r.status}，resolved=${r.resolved}。`).join('\n'));

title(s[6],'各组成本与质量');
table(s[6],[['组别','解决数 / 2','完整策略成本 / 元','新增生成成本 / 元'],...data.arm_costs.map(r=>[
  r.arm,r.resolved===null?'未评测':`${r.resolved} / 2`,r.policy_cny.toFixed(4),r.new_cny.toFixed(4)
])],{top:187,widths:[150,220,395,395],heights:[58,63,63,63,63,63],bodySize:23});
text(s[6],'cost-total',data.totals.cost_summary,{top:587,size:26,color:blue,bold:true,height:42});
text(s[6],'cost-definition','完整策略成本含共享前缀，新增生成成本记录本次真实请求',{top:636,size:21,color:gray,height:36});
note(6,JSON.stringify(data.arm_costs,null,2)+'\n\n'+JSON.stringify(data.totals,null,2)+'\n费用按usage与配置价格估算，累计2.04914488元中包含0.00425元未知usage保守预留，尚未核对账单。');

title(s[7],data.failure_example.title);
text(s[7],'failure-metric-1',data.failure_example.metric1,{left:80,top:186,width:520,height:96,size:66,bold:true,color:blue});
text(s[7],'failure-metric-2',data.failure_example.metric2,{left:700,top:186,width:490,height:96,size:66,bold:true,color:blue});
text(s[7],'failure-label-1',data.failure_example.label1,{left:80,top:306,width:520,height:70,size:28,bold:true});
text(s[7],'failure-label-2',data.failure_example.label2,{left:700,top:306,width:490,height:70,size:28,bold:true});
text(s[7],'failure-evidence',data.failure_example.evidence,{left:80,top:416,width:1120,height:90,size:26});
text(s[7],'failure-cause',data.failure_example.cause,{left:80,top:529,width:1120,height:90,size:26,color:blue,bold:true});
text(s[7],'failure-followup',data.failure_example.followup,{left:80,top:634,width:1120,height:38,size:21,color:gray});
note(7,data.failure_example.notes);

title(s[8],'临时路由与分支表现');
const boundaries=[
  ['配对诊断','eligible 1 例，固定与交互分支均解决'],
  ['本轮配置','临时阈值 0.75/0.75\nE=1.0，依据 D 在 eligible 实例触发 1/1'],
  ['实际路线','pvlib C/D/E 交互\npydicom A/C/D/E 前缀停止'],
  ['关键观察','D 达到请求上限，C/E 完成公开验证']
];
boundaries.forEach(([label,body],i)=>{
  text(s[8],`boundary-label-${i}`,label,{left:70,top:192+i*101,width:180,height:44,size:27,color:blue,bold:true});
  text(s[8],`boundary-body-${i}`,body,{left:270,top:192+i*101,width:930,height:80,size:25});
});
text(s[8],'pilot-scope','两例单次 dev 记录，完整校准与重复在下一阶段开展',{top:625,size:21,color:gray,height:40});
note(8,data.candidate_calibration.notes+'\n本轮保留dev-only pilot身份，同两例参与候选准备，未进行完整dev校准与三重复统计。');

title(s[9],'下一阶段实验');
data.next_steps.forEach(([label,body],i)=>{
  text(s[9],`next-number-${i}`,String(i+1).padStart(2,'0'),{left:70,top:192+i*94,width:70,size:32,color:blue,bold:true});
  text(s[9],`next-label-${i}`,label,{left:154,top:196+i*94,width:270,size:27,bold:true});
  text(s[9],`next-body-${i}`,body,{left:445,top:198+i*94,width:745,height:73,size:24,color:gray});
});
text(s[9],'next-conclusion',data.totals.next_summary,{top:625,size:26,color:blue,bold:true,height:50});
note(9,data.totals.next_summary);

await fs.mkdir(build+'/draft',{recursive:true});
await fs.mkdir(build+'/render',{recursive:true});
const candidate=build+'/draft/candidate.pptx';
await (await PresentationFile.exportPptx(p)).save(candidate);
for(const [i,slide] of s.entries()){
  const stem=`${build}/render/slide-${String(i+1).padStart(2,'0')}`;
  const png=await p.export({slide,format:'png',scale:1});
  await fs.writeFile(stem+'.png',new Uint8Array(await png.arrayBuffer()));
  const layout=await slide.export({format:'layout',detail:'full'});
  await fs.writeFile(stem+'.layout.json',await layout.text());
}
const montage=await p.export({format:'png',montage:{columns:2,slideWidth:640},scale:1});
await fs.writeFile(build+'/render/montage.png',new Uint8Array(await montage.arrayBuffer()));
if(!process.argv.includes('--finalize')){
  console.log(JSON.stringify({draft:candidate,slides:s.length,renderDirectory:build+'/render',status:'awaiting_visual_review'}));
  process.exit(0);
}
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
await fs.mkdir(path.dirname(output),{recursive:true});
const nativeLink=fs.link.bind(fs);
fs.link=async(a,b)=>{
  try{return await nativeLink(a,b);}catch(error){
    if(process.platform!=='win32'||error.code!=='EPERM'||!a.endsWith('.validated')||b.replaceAll('\\','/')!==output)throw error;
    await fs.copyFile(a,b,constants.COPYFILE_EXCL);
  }
};
const result=await finalizePresentation({
  explicitTotalSlideCount:10,
  requiredNativeTableOwnerSlides:[3,4,6,7],requiredNativeChartOwnerSlides:[],
  workspaceDir:root,candidatePath:candidate,finalPath:output,
  pythonExecutable:process.env.RUNTIME_PYTHON??'python',
  integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',
  layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[3,4,6,7].flatMap(n=>['--require-native-table-slide',String(n)])],
  fontPolicy:{basis:'reference',families:[font],referencePath:source,referenceSha256:crypto.createHash('sha256').update(await fs.readFile(source)).digest('hex')},
  verifyArtifactToolImport:true,receiptPath:process.env.PPT_RECEIPT_PATH??build+'/'+path.basename(output)+'.validation.json'
});
console.log(JSON.stringify(result,null,2));
