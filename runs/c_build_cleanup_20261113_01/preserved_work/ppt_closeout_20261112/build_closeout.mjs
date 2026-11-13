import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {constants} from 'node:fs';
const root=process.cwd().replaceAll('\\','/');
const build=root+'/work/ppt_closeout_20261112';
const skill=process.env.PRESENTATIONS_SKILL_DIR;
const modules=process.env.RUNTIME_NODE_MODULES;
const {FileBlob,PresentationFile}=await import(pathToFileURL(path.join(modules,'@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const source=root+'/docs/deliverables/组会汇报_两例五组实验_20261106.pptx';
const final=root+'/docs/deliverables/结题汇报_自适应混合架构程序修复_20261112.pptx';
const p=await PresentationFile.importPptx(await FileBlob.load(source));
if(p.slides.items.length!==10)throw new Error('Expected ten reference slides');
const blue='#2F5597',ink='#202020',gray='#606060',font='微软雅黑';
const s=p.slides.items;
const snapshot=await p.inspect({select:'$.slides[*]',include:['id','elements.id','elements.kind','elements.name']});
for(let i=1;i<s.length;i++)for(const e of snapshot.records[i].elements){
  if(e.name==='标题 4'||e.name==='page-number')continue;
  if(['textbox','shape','table','chart'].includes(e.kind))p.delete(e.id);
}
const style=(size=25,color=ink,bold=false,align='left')=>({typeface:font,fontSize:size,color,bold,alignment:align,verticalAlignment:'top',insets:0,wrap:'square',autoFit:'none'});
function text(slide,name,value,{left=70,top=186,width=1130,height=58,size=25,color=ink,bold=false,align='left'}={}){
  const sh=slide.shapes.add({name,geometry:'textbox',position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});
  sh.text=value;sh.text.style=style(size,color,bold,align);return sh;
}
function existing(slide,name,value,size=32,color=ink,bold=true,align='left'){
  const sh=slide.shapes.items.find(x=>x.name===name);if(!sh)throw new Error(name);
  sh.text=value;sh.text.style=style(size,color,bold,align);
}
function title(i,value,layout){
  if(layout){const l=p.layouts.items.find(x=>x.name===layout);if(!l)throw new Error(layout);s[i].setLayout(l);}
  existing(s[i],'标题 4',value);
  existing(s[i],'page-number',String(i+1).padStart(2,'0')+' / 10',17,gray,false,'right');
}
function rows(i,items,{top=192,gap=104,labelWidth=200,bodyLeft=290,bodyWidth=910,bodySize=25}={}){
  items.forEach(([label,body],j)=>{
    text(s[i],'label-'+j,label,{top:top+j*gap,width:labelWidth,height:65,size:27,bold:true,color:blue});
    text(s[i],'body-'+j,body,{left:bodyLeft,top:top+j*gap,width:bodyWidth,height:85,size:bodySize});
  });
}
function table(i,values,{top=186,widths,heights,bodySize=23}={}){
  const t=s[i].tables.add({rows:values.length,columns:values[0].length,left:60,top,width:1160,height:heights.reduce((a,b)=>a+b,0),columnWidths:widths,values});
  t.styleOptions={headerRow:true,bandedRows:true};t.borders.assign({style:'solid',fill:'#CFD7E3',width:1});
  values.forEach((row,r)=>{t.rows[r].height=heights[r];row.forEach((v,c)=>{const cell=t.getCell(r,c);cell.fill=r===0?blue:r%2?'#F3F5F8':'#FFFFFF';cell.text.style={...style(bodySize,r===0?'#FFFFFF':c===0?blue:ink,r===0||c===0),verticalAlignment:'middle',insets:{left:12,right:10,top:8,bottom:8}};});});return t;
}
function notes(i,body,sources){s[i].speakerNotes.text=body+'\n\n资料来源：\n'+sources.join('\n');}
const proposal=['docs/开题报告正文摘录.md，第1、3、4节','docs/实验协议_开题对齐.md'];
const formal=['docs/test20五组一次实验报告_20261112.md','runs/test20_resume_20261112_02/test20_uniform_off_peak_comparison.json'];
const current=['docs/正式实验最终交接_20261112.md','runs/test20_final_handoff_20261112_01/FINAL_HANDOFF_VERIFIED.json'];
existing(s[0],'标题 5','面向仓库级程序修复的\n自适应混合架构研究',44,ink,true,'center');
existing(s[0],'文本占位符 7','科研课堂结题汇报\n陈堉锋　张曹远臻\n指导教师：齐斌航　　2026年11月12日',25,ink,false,'center');
notes(0,'本课题围绕大模型仓库级缺陷修复中的执行模式选择开展研究。汇报先说明研究对象、需要解决的问题与价值，再报告已完成的系统和实验结果。本次结题不预设自适应方法一定优于固定或级联方法。',proposal);

title(1,'主要研究对象','内容页-标题2');
text(s[1],'object','仓库级缺陷修复中的执行模式选择',{top:182,size:38,height:62,bold:true,color:blue});
rows(1,[
  ['任务对象','Python真实仓库中的缺陷修复任务\n输入问题描述、基线代码、公开测试和资源上限'],
  ['决策对象','前缀失败后，选择继续固定流程或转入受限交互\n考察两种延续方式各自适用的失败情形'],
  ['服务对象','使用大模型辅助维护代码的开发者与修复系统\n最终输出完整补丁，或停止原因与消耗记录']
],{top:282,gap:111,bodySize:25});
text(s[1],'scope','控制条件：同一基础模型、统一预算、相同初始仓库与独立评测',{top:626,size:23,color:gray,height:40});
notes(1,'主要对象需要分清两个层次。任务层是一个仓库级缺陷修复实例，包含问题描述、指定提交下的代码和可公开访问的测试。决策层是这次任务执行到固定前缀以后，应该继续按给定上下文生成候选，还是让模型在受限工具中继续检索和验证。本课题围绕后一层的模式选择展开。研究范围是Python仓库级程序修复，同一基础模型下比较不同执行策略，服务于代码维护人员及自动修复系统。',proposal);

title(2,'需要解决的现存问题','内容页-标题1');
table(2,[['现有方式','遇到的困难','带来的问题'],
  ['统一固定流程','按预定定位与上下文生成补丁','遇到定位错误或跨文件依赖时，\n后续尝试难以获得新证据'],
  ['统一交互执行','每个任务都允许自主检索和验证','额外工具与模型调用可能重复，\n修复收益与消耗缺少对应'],
  ['仅看公开通过','可见测试只覆盖部分行为','局部通过仍可能遗漏目标行为\n或引入其他功能回归']
],{widths:[220,440,500],heights:[56,100,100,100],bodySize:24});
text(s[2],'problem','核心问题：失败之后，凭什么判断追加交互值得花费预算？',{top:586,size:29,color:blue,bold:true,height:70});
notes(2,'这里列出的困难是本课题的研究动机，不作为所有工具都必然失败的结论。固定流程容易复现和控制，但其后续生成使用的上下文受到前面定位结果限制。交互方式能够主动获取新信息，却需要更多工具和请求，也可能反复做无效动作。公开验证通过又不能等同于最终任务解决。因此我们关注在失败后如何依据已经发生的证据决定是否交互，并在同一预算条件下检验其真实增量。',proposal);

title(3,'研究目标与主要价值','内容页-标题2');
rows(3,[
  ['研究目标','根据失败证据选择延续方式，检验同预算下的修复质量\n与实际消耗，允许保留没有收益的结果'],
  ['预期应用价值','让交互用于需要补充定位或验证证据的任务\n减少缺少新信息的重复尝试，控制单次修复开销'],
  ['已实现的价值','建立同前缀、同预算和独立判分的可复核比较流程\n区分补丁缺陷、环境故障及判分误识别']
],{top:192,gap:132,bodySize:25});
text(s[3],'value-boundary','本轮结果尚未证明自适应规则带来质量或成本优势',{top:624,size:26,color:blue,bold:true,height:42});
notes(3,'研究目标是让模式选择有可观测依据，再用独立实验判断这套依据是否有效。应用上的预期价值是把交互资源用在有机会获得新增证据的修复任务中，并控制失败开销。实际完成的价值是建立了一条可复核的比较链路，能够在相同前缀与预算下比较分支，保存候选、路由依据、资源和独立评测结果。本轮D组没有显示明确解决数提升，所以不将节省成本或提高质量写成已经实现的结论。',proposal.concat(formal));

title(4,'失败证据路由方案','内容页-标题3');
table(4,[['执行阶段','可观测信息','本课题的处理'],
  ['共享固定前缀','定位结果、完整候选、公开验证','A/C/D/E使用相同实际前缀与候选选择规则'],
  ['状态记录','应用/语法错误、失败堆栈、剩余预算','区分可局部修正、定位分歧与环境故障'],
  ['单次模式选择','九规则顺序，先处理停止条件','公开通过可停止，局部错误优先固定，\n定位分歧等证据支持交互'],
  ['分支与提交','固定或受限交互中的有效候选','正式运行仅执行选中分支，保留合法候选'],
  ['独立评测','封存补丁后进行容器测试','评测信息与隐藏测试不进入生成及路由']
],{widths:[220,400,540],heights:[54,67,67,78,67,67],bodySize:23});
text(s[4],'budget','硬预算同时约束token、模型请求、容器执行次数与墙钟时间',{top:620,size:24,color:blue,bold:true,height:45});
notes(4,'固定前缀完成定位、生成和公开验证后，状态记录器保存候选应用结果、失败类型、定位分歧和预算。路由器首先执行环境与预算停止、公开通过冻结等共享规则，其后才考虑交互。正式任务只运行选中的延续分支，开发集配对诊断才从完全相同快照分别运行两条分支。隐藏测试、开发者标准补丁与最终标签只在独立评测侧管理。四元资源预算及金额守卫贯穿全过程。',proposal.concat(['configs/test20_frozen_20261112_01.json']));

title(5,'实验设计与五组对照','内容页-标题4');
text(s[5],'scale','固定20例 × 五组 × 一次，共100条封存预测',{top:174,size:28,bold:true,color:blue,height:50});
table(5,[['策略','执行起点','延续规则'],
  ['A 固定','共享固定前缀','可继续失败采用固定延续'],
  ['B 纯交互','相同初始问题与干净仓库','独立从初始状态进行受限交互'],
  ['C 级联','共享固定前缀','全部可继续失败交互延续'],
  ['D 自适应','共享固定前缀','按失败证据选择固定或交互'],
  ['E 随机','共享固定前缀','按D在开发集的触发率随机切换']
],{top:243,widths:[210,360,590],heights:[50,57,57,57,57,57],bodySize:23});
text(s[5],'dev','dev23完成诊断，17例可延续、13对有效标签，E概率为8/17',{top:600,size:24,color:blue,bold:true,height:42});
text(s[5],'design-limit','test按ID与仓库分层抽取，所有指定实例保留，结果仅作单次描述',{top:647,size:21,color:gray,height:34});
notes(5,'完整开发集23例保留总体记录，其中17例前缀失败可继续，13例具有两条分支的有效独立标签。按既定网格和平局顺序选择阈值0.75/0.75，E按全部17个eligible实例中D的交互触发率8/17设置概率。正式样本在读取方法成绩前，从完整test300按ID和仓库分层抽取20例，种子20261111，repeat0。A/C/D/E共用真实前缀，各自完整计入前缀成本。全100预测封存之后再独立判分。只有一次重复，不作统计显著性或稳定性推断。',formal.concat(['runs/test20_preparation_20261111/preregistration.json','runs/test20_resume_20261112_01/formal_freeze_manifest_01.json']));

title(6,'正式实验结果与成本','内容页-标题4');
const counts=[[7,4,4,5],[7,4,5,4],[10,4,1,5],[7,5,2,6],[8,3,3,6]];
for(const r of counts)if(r.reduce((a,b)=>a+b,0)!==20)throw new Error('Denominator mismatch');
const costs=[4.39227512,.43171952,2.05192828,2.87039734,3.56686990];
table(6,[['组别','明确解决','未解决','空提交','评测异常','完整成本/元'],...counts.map((r,i)=>['ABCDE'[i],r[0]+'/20',String(r[1]),String(r[2]),String(r[3]),costs[i].toFixed(4)])],
  {top:186,widths:[140,190,170,170,190,300],heights:[58,62,62,62,62,62],bodySize:23});
text(s[6],'main-result','C本轮明确解决10例，D为7例，与A相同',{top:585,size:29,bold:true,color:blue,height:46});
text(s[6],'cost-caveat','成本统一换算低谷价并含共享前缀，均为usage估算，非账单实付',{top:640,size:21,color:gray,height:34});
notes(6,'本页保留封存的原官方主标签。A到E明确解决分别是7、7、10、7、8例。其余状态分为真正未解决、空提交和评测异常。异常共26条，其中25条含糊错误、1条基础设施错误，不能统称补丁失败。C本轮观察到的明确解决数最多，D与A相同，尚无自适应收益证据。成本逐请求按缓存命中0.02、未命中1、输出4元每百万token换算低谷价，A/C/D/E均计完整共享前缀。执行顺序、服务端缓存和评测异常限制了比较。总账本20.31946522元还包括校准、准备与取消前的补充请求，其金额不应等同于本表部署策略费用。',formal.concat(current));

title(7,'失败分析与判分风险','内容页-标题4');
rows(7,[
  ['补丁遗漏','Flask修复了蓝图名称校验，却未补齐端点异常约定\n实际测试窗口仍出现目标断言失败'],
  ['回归风险','Pylint目标测试通过，但同一补丁引入维护测试失败\n局部修复效果需要结合已有功能检查'],
  ['判分误识别','日志中的示例文本触发“未收集测试”等分类\n仅有全部通过汇总时，逐测试覆盖仍可能无法确认']
],{top:192,gap:126,bodySize:25});
text(s[7],'review-boundary','已完成100条agent语义复核与日志审计，原官方主标签保持不变',{top:624,size:23,color:blue,bold:true,height:44});
notes(7,'两个案例说明可恢复的失败与路由误判需要分开分析。Flask补丁只覆盖了部分异常契约，实际测试有目标断言失败。Pylint补丁的目标测试通过，但维护测试出现回归。另一方面，全量日志审计发现预测试git diff中的文档示例干扰了分类。39条原明确解决得到复核，12条原异常具有完整失败证据，10条只有全部通过的汇总而没有可解析的逐测试结果。这些事后审计不替换正式标签。语义复核由当前代码agent执行，覆盖100条、49个实例内唯一补丁组（含空提交），没有外部真人签审。',current.concat(['runs/dev_supplement_20261112_02/review_only/semantic_review.json','runs/dev_supplement_20261112_02/formal_scoped_log_audit.json']));

title(8,'已完成成果与研究局限','内容页-标题5');
rows(8,[
  ['系统成果','共享前缀、状态记录、可解释路由及两类延续已连通\n候选选择、资源守卫与判分来源可追溯'],
  ['实验成果','完成dev23校准、test20五组一次及独立判分\n最新离线399/399，原始93与归档131文件哈希一致'],
  ['结论边界','单模型、20例一次，13对有效dev标签，证据有限\n重复规则关闭，补充消融和敏感性设置已取消']
],{top:192,gap:126,bodySize:25});
text(s[8],'identity','模型采用批准别名及逐请求指纹监测，未锁定不可变版本',{top:624,size:23,color:gray,height:44});
notes(8,'工程系统及一次描述性实验已完成。正式数据保存了配置、清单与哈希、镜像和基线、候选与前缀快照、路由、资源、预测和独立判分的来源。最新活动离线套件399项通过，原始93和归档131文件保持字节一致。局限包括单次小样本、模型别名非不可变快照、只有13个有效配对、两候选下重复规则关闭，以及D2事前可达性说明存在文档缺项。用户已取消全部补充设置，既有设置不继续评测或分析，故不宣称完成多预算曲线、真实消融或敏感性验证。外部真人语义签审也未完成。',current.concat(['runs/test20_final_handoff_20261112_01/final_validation.json']));

title(9,'结题结论','内容页-总结');
rows(9,[
  ['主要对象','仓库级缺陷修复中，固定与交互执行模式的选择'],
  ['解决的问题','依据前缀失败证据分配后续交互预算\n并在同一条件下核查交互是否带来增量价值'],
  ['主要价值','提供可复核的修复模式比较方法与运行系统\n保留负结果，暴露修复回归与评测误识别风险']
],{top:192,gap:130,labelWidth:200,bodyLeft:290,bodySize:26});
text(s[9],'conclusion','系统与实验链路已完成，自适应性能收益仍待更充分证据支持',{top:624,size:25,color:blue,bold:true,height:48});
notes(9,'本课题的主要对象是仓库级修复过程中的执行模式选择。需要解决的是固定流程与工具交互如何依据失败证据合理调度，并在统一预算下判断这种调度是否有价值。已经完成的贡献是一套能够保存证据、复核路由、核算成本和独立评测的运行系统与比较流程。本轮D并未获得明确解决数提升，所以结题结论保留负结果，不声称已经提高修复质量或降低成本。后续若继续研究，需要在新的授权范围内补充重复、消融和更充分的语义验收。',proposal.concat(formal,current));

await fs.mkdir(build+'/draft',{recursive:true});await fs.mkdir(build+'/render',{recursive:true});
const candidate=build+'/draft/candidate.pptx';await (await PresentationFile.exportPptx(p)).save(candidate);
await fs.writeFile(build+'/authored-proto.json',JSON.stringify(p.toProto()));
for(const [i,slide] of s.entries()){
  const png=await p.export({slide,format:'png',scale:1});await fs.writeFile(build+'/render/slide-'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await png.arrayBuffer()));
  const layout=await slide.export({format:'layout',detail:'full'});await fs.writeFile(build+'/render/slide-'+String(i+1).padStart(2,'0')+'.layout.json',await layout.text());
}
console.log(JSON.stringify({candidate,slides:10,render:build+'/render'}));
if(process.argv.includes('--finalize')){
 const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
 const link=fs.link.bind(fs);fs.link=async(a,b)=>{try{return await link(a,b);}catch(e){if(process.platform!=='win32'||e.code!=='EPERM'||!a.endsWith('.validated')||b.replaceAll('\\','/')!==final)throw e;await fs.copyFile(a,b,constants.COPYFILE_EXCL);}};
 const result=await finalizePresentation({explicitTotalSlideCount:10,requiredNativeTableOwnerSlides:[3,5,6,7],requiredNativeChartOwnerSlides:[],
 workspaceDir:root,candidatePath:candidate,finalPath:final,pythonExecutable:process.env.RUNTIME_PYTHON,
 integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[3,5,6,7].flatMap(n=>['--require-native-table-slide',String(n)])],
 fontPolicy:{basis:'reference',families:[font],referencePath:source,referenceSha256:crypto.createHash('sha256').update(await fs.readFile(source)).digest('hex')},
 verifyArtifactToolImport:true,receiptPath:build+'/validation.json'});
 console.log(JSON.stringify(result,null,2));
}
