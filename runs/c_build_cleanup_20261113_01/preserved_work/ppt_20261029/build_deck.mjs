import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, PresentationFile } from 'file:///C:/Users/remil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';

const root='C:/Users/remil/Desktop/3yr/科研/proj';
const build=root+'/work/ppt_20261029';
const p=await PresentationFile.importPptx(await FileBlob.load(build+'/reference_compatible.pptx'));
const layoutNames={cover:'标题页',goal:'内容页-标题2',design:'内容页-标题3',eval:'内容页-标题4',tool:'内容页-标题5',summary:'内容页-总结'};
const layouts=Object.fromEntries(Object.entries(layoutNames).map(([key,name])=>[key,p.toProto().layouts.find(l=>l.name===name).id]));
const C={ink:'#202020',blue:'#2F5597',gray:'#606060',light:'#DCE9F5',pale:'#F2F2F2',red:'#B02A2A',white:'#FFFFFF'};
const font='微软雅黑';
const outline=await fs.readFile(build+'/content_outline.md','utf8');
const sections=outline.split(/\n## \d\d /).slice(1);
const notes=sections.map(x=>{const match=x.match(/\*\*讲稿\*\*：\s*([\s\S]*?)\n\*\*来源\*\*：\s*([\s\S]*?)(?=\n## |$)/);return match?match[1].trim()+'\n\n资料来源：'+match[2].trim():'';});
p.slides.keep([]);

function text(slide,name,value,x,y,w,h,size=24,color=C.ink,bold=false,align='left'){
 const s=slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 s.text=value;
 s.text.style={typeface:font,fontSize:size,color,bold,alignment:align,verticalAlignment:'top',insets:0,wrap:'square',autoFit:'none'};
 return s;
}
function slide(title,type='design'){
 const s=p.slides.add({layoutId:layouts[type]});
 const t=s.placeholders.getItem('title');
 t.text=title;
 t.position={left:55,top:102,width:1170,height:52};
 t.text.style={typeface:font,fontSize:32,bold:true,color:C.ink,insets:0,autoFit:'none'};
 const ix=p.slides.items.length;
 s.speakerNotes.text=notes[ix-1]||'';
 text(s,'page-number',String(ix).padStart(2,'0')+' / 10',1140,675,80,24,16,C.gray,false,'right');
 return s;
}
function label(s,main,detail,y,{x=70,w=1130}={}){
 text(s,'label-'+y,main,x,y,w,40,27,C.blue,true);
 text(s,'detail-'+y,detail,x,y+48,w,64,24);
}
function table(s,name,values,{x=60,y=190,w=1160,h=330,widths,fontSize=23,rowHeights,firstColumnBlue=true}={}){
 const tb=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
 tb.styleOptions={headerRow:false,bandedRows:false};
 tb.borders.assign({fill:'#D0D6DF',width:1,style:'solid'});
 for(let r=0;r<values.length;r++){
  tb.rows[r].height=rowHeights?.[r]??h/values.length;
  for(let c=0;c<values[0].length;c++){
   const cell=tb.getCell(r,c);
   cell.fill=r===0?C.blue:(r%2===1?'#F5F7FA':C.white);
   cell.text.style={typeface:font,fontSize:r===0?fontSize:fontSize,color:r===0?C.white:(c===0&&firstColumnBlue?C.blue:C.ink),bold:r===0||c===0,alignment:'left',verticalAlignment:'middle',insets:{left:18,right:14,top:12,bottom:12},autoFit:'none'};
  }
 }
 return tb;
}

// 01 Cover retains the source theme, university mark and background artwork.
{
 const s=p.slides.add({layoutId:layouts.cover});
 const t=s.placeholders.getItem('title');
 t.text='面向仓库级程序修复的\n自适应混合架构';
 t.position={left:88,top:177,width:1104,height:130};
 t.text.style={typeface:font,fontSize:44,bold:true,color:C.ink,alignment:'center',insets:0,autoFit:'none'};
 const b=s.placeholders.getItem('body');
 b.text='开题对齐与离线验证进展\n汇报人：陈堉锋　张曹远臻\n2026 年 10 月 29 日';
 b.position={left:270,top:425,width:740,height:126};
 b.text.style={typeface:font,fontSize:26,color:C.ink,alignment:'center',insets:0,autoFit:'none'};
 s.speakerNotes.text=notes[0];
}
// 02 Research intent and scope.
{
 const s=slide('本轮目标与完成范围','goal');
 text(s,'research-question','失败证据能否帮助选择更合适的修复模式？',70,186,1130,54,32,C.blue,true);
 text(s,'comparison-condition','比较条件：同模型、同初始信息、同资源上限',70,253,1130,44,25,C.gray);
 label(s,'本轮已完成','执行约束修复、原始证据保护、历史统计重算、实验交接文档',337);
 label(s,'下一阶段待验证','真实集成、开发集校准、正式重复实验、消融与人工审查',470);
 text(s,'negative-result','允许负结果，路由收益由受控实验检验',70,614,1130,35,24,C.blue,true);
}
// 03 Before and after, native editable evidence.
{
 const s=slide('原流程与开题要求的差距');
 table(s,'deviations',[
  ['环节','原流程问题','本轮修正'],
  ['路由','无行为信号默认升级','证据不足保守固定'],
  ['配对起点','固定新候选串入交互提示','序列化快照独立恢复'],
  ['预算','收尾和多工具请求可能越限','调用前预检并持续记账'],
  ['统计','真实 C 与无条件 ESC 混用','按真实决策分别评分'],
 ],{y:186,h:350,widths:[160,500,500],rowHeights:[58,73,73,73,73]});
 text(s,'why-it-matters','这些修正决定实验能否回答开题问题，效果比较留待新实验',70,580,1130,60,25,C.blue,true);
}
// 04 Formal and paired diagnostic modes.
{
 const s=slide('同一前缀下的两种运行模式');
 table(s,'execution-modes',[
  ['比较项','正式运行','配对诊断'],
  ['执行对象','路由选中的一个延续','可继续失败上的两条延续'],
  ['起点','A/C/D/E 复用同一实际前缀','固定与交互各恢复独立快照'],
  ['资源计入','策略计入完整前缀开销','两分支获得相同剩余额度'],
  ['分析用途','方法解决率与策略成本','升级价值与路由误判'],
 ],{y:185,h:355,widths:[160,500,500],fontSize:22,rowHeights:[59,74,74,74,74]});
 text(s,'branch-boundary','固定分支的新候选不能进入交互分支输入',70,575,1130,40,26,C.blue,true);
 text(s,'cost-boundary','双分支采集开销单独记录，避免混入部署策略成本',70,622,1130,32,21,C.gray);
}
// 05 Routing and candidate semantics, flat hierarchy.
{
 const s=slide('路由与候选选择的修正');
 const rows=[
  ['固定延续','证据不足，或局部应用、语法问题尚可修正'],
  ['交互延续','明显定位分歧、重复候选或新的范围外源码证据'],
  ['统一停止','硬预算、不可恢复环境故障或已有公开通过候选'],
  ['提交筛选','可应用、语法有效、范围合法，并保留此前有效候选'],
 ];
 rows.forEach((r,i)=>{let y=191+i*100;text(s,'route-label-'+i,r[0],70,y,185,40,27,C.blue,true);text(s,'route-body-'+i,r[1],270,y+3,920,62,25);});
 text(s,'candidate-disclosure','公开测试通过只用于候选选择，最终结果由独立评测判断',70,620,1130,34,21,C.gray);
}
// 06 Budget dimensions and concrete behavior.
{
 const s=slide('预算贯穿前缀与交互执行','tool');
 text(s,'budget-dimensions','累计 token　　实际请求　　工具执行　　墙钟时间',70,191,1130,52,32,C.blue,true);
 const lines=[
  ['前缀与失败','前缀、失败请求、重试和验证均计入对应预算'],
  ['收尾与工具','收尾调用占用原有额度，多工具回复逐项受限'],
  ['缺失 usage','保守预留并标记未知，费用不冒称实付'],
 ];
 lines.forEach((r,i)=>{const y=291+i*98;text(s,'budget-label-'+i,r[0],70,y,205,40,26,C.blue,true);text(s,'budget-body-'+i,r[1],290,y+2,890,65,25);});
 text(s,'budget-status','当前开发参数仅为安全限额，主实验预算仍待校准冻结',70,623,1130,33,21,C.gray);
}
// 07 Corrected historical diagnostic evidence.
{
 const s=slide('历史 C/D 成本比较的更正','eval');
 text(s,'historical-scope','历史 v2.3 重算，7 个 dev 实例，单次运行',70,181,1130,42,24,C.gray);
 table(s,'historical-costs',[
  ['真实策略','解决数','升级次数','估算策略成本'],
  ['C 简单级联','4 / 7','4','0.574337 元'],
  ['D 自适应','4 / 7','4','0.574337 元'],
 ],{y:250,h:222,widths:[270,240,240,410],fontSize:27,rowHeights:[64,79,79]});
 text(s,'corrected-conclusion','该样本中 C、D 同决策、同成本，不能声称 D 更省钱',70,520,1130,48,27,C.red,true);
 text(s,'old-cost-definition','原 0.688450 元来自所有实例无条件交互升级（ESC）的另一种策略',70,588,1130,36,22,C.gray);
 text(s,'historical-limit','旧数据仅用于统计口径诊断，新方法效果尚未验证',70,628,1130,32,21,C.gray);
}
// 08 Preservation, distinguish counts and new sampling population.
{
 const s=slide('原始证据与新实验分开管理','tool');
 text(s,'original-count','93',80,180,450,100,70,C.blue,true);
 text(s,'archive-count','131',700,180,450,100,70,C.blue,true);
 text(s,'original-label','原始数据与报告文件',80,289,460,40,28,C.ink,true);
 text(s,'archive-label','归档原件',700,289,460,40,28,C.ink,true);
 text(s,'original-hash','字节不变，哈希校验通过',80,338,490,40,23,C.gray);
 text(s,'archive-hash','旧实现、协议和交付物校验通过',700,338,490,58,23,C.gray);
 text(s,'output-directory','新运行写入独立 runs 目录，已有 tag 拒绝覆盖',80,446,1100,45,27,C.blue,true);
 text(s,'population-note','历史 98 个 gold 通过案例仅表示环境覆盖\n新主总体优先完整 test 300，或预注册的分层子集',80,521,1100,100,25);
 text(s,'handoff-docs','实验协议与 AGENTS.md 已记录下一位实验 agent 的执行约束',80,625,1100,32,21,C.gray);
}
// 09 Offline verification and limits.
{
 const s=slide('离线验证通过 222 项回归','eval');
 text(s,'test-count','222 / 222',70,215,490,100,68,C.blue,true);
 text(s,'test-count-unit','测试项全部通过',75,324,480,50,29,C.ink,true);
 text(s,'fake-runtime','假模型、假容器和纯逻辑回归',75,392,460,72,24,C.gray);
 text(s,'verified-label','已验证',620,194,550,40,27,C.blue,true);
 text(s,'verified-body','路由语义与快照隔离\n预算边界、异常留痕和统计分母\n默认计划不执行，未授权付费请求拒绝',620,247,570,150,24);
 text(s,'unverified-label','未验证',620,421,550,40,27,C.red,true);
 text(s,'unverified-body','真实模型兼容与容器公开测试\n新方法的修复效果',620,474,570,92,24);
 text(s,'offline-scope','本轮未调用真实修复模型、Docker 或官方 harness',70,621,1130,34,23,C.gray);
}
// 10 Future sequence and current authorization state.
{
 const s=slide('下一阶段的实验顺序','summary');
 const rows=[
  ['01','真实集成','获授权后，在少量 dev 验证模型与容器链路'],
  ['02','开发集校准','校准完整路由、预算和前缀比例，冻结版本与配置'],
  ['03','正式重复','固定 test 总体或分层子集，至少三次重复'],
  ['04','解释与审查','实例聚类 95% 区间，补消融、敏感性与人工审查'],
 ];
 rows.forEach((r,i)=>{const y=193+i*94;text(s,'next-step-'+i,r[0],70,y,75,45,31,C.blue,true);text(s,'next-title-'+i,r[1],155,y+2,270,45,27,C.ink,true);text(s,'next-detail-'+i,r[2],447,y+4,750,63,24,C.gray);});
 text(s,'current-gate','当前配置保持 draft，付费执行保持关闭',70,617,1130,43,27,C.blue,true);
}

await fs.mkdir(build+'/draft',{recursive:true});
await fs.mkdir(build+'/render',{recursive:true});
await (await PresentationFile.exportPptx(p)).save(build+'/draft/candidate.pptx');
await fs.writeFile(build+'/draft/inspection.ndjson',(await p.inspect({kind:'slide,textbox,shape,table,chart,image',maxChars:1000000})).ndjson);
for(let i=0;i<p.slides.items.length;i++){
 const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(build+`/render/slide-${i+1}.png`,new Uint8Array(await blob.arrayBuffer()));
 console.log('Rendered',i+1);
}
console.log('Exported draft',p.slides.items.length,'slides');
