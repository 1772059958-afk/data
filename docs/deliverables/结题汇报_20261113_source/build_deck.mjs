import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {constants} from 'node:fs';
const root=process.cwd().replaceAll('\\','/'),build=root+'/work/ppt_update_20261113';
const skill=process.env.PRESENTATIONS_SKILL_DIR,modules=process.env.RUNTIME_NODE_MODULES;
const {FileBlob,PresentationFile}=await import(pathToFileURL(path.join(modules,'@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const {applyPresentationChartFont,finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const source=root+'/docs/deliverables/结题汇报_自适应混合架构程序修复_20261112.pptx';
const final=process.env.PPT_FINAL_PATH??root+'/docs/deliverables/结题汇报_深入分析版_20261113_定稿.pptx';
const d=JSON.parse(await fs.readFile(root+'/runs/ppt_analysis_20261113_01/analysis.json','utf8'));
const p=await PresentationFile.importPptx(await FileBlob.load(source));
p.slides.keep([0,1]);
const look=await p.inspect({select:'$.slides[1]',include:['elements.id','elements.kind','elements.name']});
for(const e of look.records[0].elements)if(!['标题 4','page-number'].includes(e.name)&&['shape','textbox','table','chart'].includes(e.kind))p.delete(e.id);
const N=21;while(p.slides.items.length<N)p.slides.items[1].duplicate();
const s=p.slides.items,blue='#2F5597',ink='#202020',gray='#606060',font='微软雅黑';
const sty=(size=25,color=ink,bold=false,align='left')=>({typeface:font,fontSize:size,color,bold,alignment:align,verticalAlignment:'top',insets:0,wrap:'square',autoFit:'none'});
const text=(i,name,value,{left=70,top=186,width=1130,height=62,size=25,color=ink,bold=false}={})=>{const x=s[i].shapes.add({name,geometry:'textbox',position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});x.text=value;x.text.style=sty(size,color,bold);return x;};
function existing(i,name,value,size=32,color=ink,bold=true,align='left'){const x=s[i].shapes.items.find(v=>v.name===name);if(!x)throw new Error(name);x.text=value;x.text.style=sty(size,color,bold,align);}
function title(i,value,section=4){s[i].setLayout(p.layouts.items.find(v=>v.name===(section===6?'内容页-总结':'内容页-标题'+section)));existing(i,'标题 4',value);existing(i,'page-number',String(i+1).padStart(2,'0')+' / '+N,17,gray,false,'right');}
function rows(i,items,{top=192,gap=130,bodySize=26,labelWidth=200,bodyLeft=290}={}){items.forEach(([label,body],j)=>{text(i,'label-'+j,label,{top:top+j*gap,width:labelWidth,size:27,color:blue,bold:true});text(i,'body-'+j,body,{left:bodyLeft,top:top+j*gap,width:1200-bodyLeft,height:96,size:bodySize});});}
function table(i,values,{top=186,widths,heights,bodySize=23,padY=6}={}){const t=s[i].tables.add({rows:values.length,columns:values[0].length,left:60,top,width:1160,height:heights.reduce((a,b)=>a+b,0),columnWidths:widths,values});t.styleOptions={headerRow:true,bandedRows:true};t.borders.assign({style:'solid',fill:'#CFD7E3',width:1});values.forEach((row,r)=>{t.rows[r].height=heights[r];row.forEach((_,c)=>{const x=t.getCell(r,c);x.fill=r===0?blue:r%2?'#F3F5F8':'#FFFFFF';x.text.style={...sty(bodySize,r===0?'#FFFFFF':c===0?blue:ink,r===0||c===0),verticalAlignment:'middle',insets:{left:12,right:9,top:padY,bottom:padY}};});});return t;}
const take=(i,value)=>text(i,'takeaway',value,{top:613,size:27,color:blue,bold:true,height:60});
const src=['docs/开题报告正文摘录.md','runs/ppt_analysis_20261113_01/analysis.json','docs/test20五组一次实验报告_20261112.md'];
function note(i,value,more=[]){s[i].speakerNotes.text=value+'\n\n资料来源：\n'+[...src,...more].join('\n');}
function chart(i,config){const c=s[i].charts.add('bar',{chartFill:'none',plotAreaFill:'none',chartLine:{fill:'none',width:0},plotAreaLine:{fill:'none',width:0},...config});applyPresentationChartFont(c,{fontFamily:font});return c;}

existing(0,'标题 5','面向仓库级程序修复的\n自适应混合架构研究',44,ink,true,'center');
existing(0,'文本占位符 7','科研课堂结题汇报\n陈堉锋　张曹远臻\n指导教师：齐斌航　　2026年11月13日',25,ink,false,'center');
note(0,'本次重点回答课题研究什么、解决什么问题、实验揭示了什么。核心结果是：级联C明确解决10例，自适应D为7例，差异集中在D选择固定延续的3例。');

title(1,'研究对象与实际需求',2);
text(1,'object','仓库级缺陷修复中的执行模式选择',{size:38,bold:true,color:blue,height:64});
rows(1,[['任务对象','给定问题描述、基线代码和公开测试，\n生成修复补丁'],['决策对象','前缀失败后，继续固定流程还是追加工具交互'],['使用场景','开发者维护Python仓库，修复过程受预算约束']],{top:291,gap:104});
note(1,'研究对象分为任务和决策两层。任务是一例真实仓库缺陷，决策是该任务在前缀失败后采用哪种延续方式。基础模型相同，研究执行组织方式。');

title(2,'现存问题：交互资源如何分配',1);
table(2,[['方式','适用特点','主要困难'],['固定流程','步骤明确，开销容易控制','定位出错后，后续生成难以补充新信息'],['工具交互','能够检索、读取、修改和验证','交互可能重复检索和试错，\n额外开销未必带来修复'],['统一使用一种方式','实现与调度简单','简单问题与复杂失败需要不同处理']],{widths:[240,430,490],heights:[56,105,105,105],bodySize:24});
take(2,'课题关注：哪些失败值得追加交互？');
note(2,'固定流程与交互流程各有适用条件。课题把问题落在失败后的资源分配：已有信息是否足够，继续生成还是先取得新证据。');

title(3,'研究目标与主要价值',2);
rows(3,[['目标','同一模型与预算下，提高解决数，\n或以相近质量减少实际消耗'],['方法价值','用可观测失败证据解释模式选择，\n让每次切换都有记录可查'],['工程价值','统一候选选择、预算控制和独立评测，\n比较固定与交互的实际收益']],{gap:132});
take(3,'本轮交付：可运行的混合修复系统与完整对照数据');
note(3,'目标包含质量和成本两个方向，实际贡献是把模式选择放入可复核的实验框架。后面的结果说明当前规则有哪些有效边界和需要改进的地方。');

title(4,'系统方案：共享前缀与单次路由',3);
table(4,[['阶段','执行内容','作用'],['固定前缀','定位、生成候选、公开验证','为各组提供同一实际起点'],['状态记录','失败类型、定位分歧、候选与预算','整理可用于路由的证据'],['模式选择','停止、固定延续、受限交互','正式任务只执行选中的分支'],['补丁选择','可应用、语法有效、公开验证与规模','保留并选择合法完整候选'],['独立评测','封存补丁后运行评测容器','评价最终任务解决情况']],{widths:[210,520,430],heights:[54,70,70,70,70,70]});
take(4,'局部修正优先固定，定位分歧等证据支持交互');
note(4,'路由有九条有序规则，共享硬停止和公开通过冻结条件优先。D对证据不足的可运行任务保守固定，语法或应用问题优先固定修正。测试文件路径本身不触发范围外源码证据。');

title(5,'实验规模与控制条件',4);
rows(5,[['开发集','完整23例，17例可延续，13对有效分支标签'],['正式实验','从test300分层抽取20例，五组各运行一次'],['统一条件','相同模型、基线代码和全局资源上限'],['独立判分','100条预测全部封存后，统一运行官方评测']],{gap:100,bodySize:25});
take(5,'同一前缀、同一候选选择规则，比较后续模式');
note(5,'正式20例使用事先固定的ID/仓库分层清单，seed20261111、repeat0，无换例。模型deepseek-flash采用批准别名映射及逐请求指纹监测，immutable_version=false。全局上限512000token、12模型请求、80容器执行、1200秒。交互另有6请求、10工具、420秒子上限。');

title(6,'五组对照分别检验什么',3);
table(6,[['组别','执行方式','比较目的'],['A 固定','共享前缀后固定延续','固定流程基线'],['B 纯交互','从相同初始问题开始受限交互','独立交互基线'],['C 级联','所有可继续失败进入交互','检验全面升级的效果'],['D 自适应','根据失败证据选择固定或交互','检验选择性交互的效果'],['E 随机','按dev触发率随机选择延续模式','检验证据选择相对随机选择的价值']],{widths:[190,510,460],heights:[54,66,66,66,66,66]});
take(6,'E使用固定dev概率8/17，正式样本的实际切换次数可不同');
note(6,'A/C/D/E复用同一个真实前缀，每个策略完整计入前缀成本。B从相同初始问题和干净仓库独立开始。E的概率匹配D在全部17个eligible dev实例的触发率，而非分支胜率。');

title(7,'开发集：交互独有收益样本很少',4);
const q=d.dev_quadrants;
table(7,[['有效配对结果','例数','对路由的意义'],['两种延续都解决',String(q.Q1_double_success),'交互没有带来解决数增量'],['仅固定解决',String(q.Q2_fixed_only),'切换可能损失已有修复机会'],['仅交互解决',String(q.Q3_interactive_only),'路由真正需要识别的正例'],['两种延续都未解决',String(q.Q4_double_failure),'追加交互仍未完成修复']],{widths:[350,150,660],heights:[56,85,85,85,85],bodySize:24});
take(7,'13对中11对结果相同，阈值选择主要由平局规则决定');
note(7,'完整dev记录为23例，eligible17例，有效独立配对13例。九格阈值方案的训练内regret均为1、解决均5/13，按既定平局顺序选择0.75/0.75。两候选的重复率最大0.5，严格大于0.75的重复规则实际关闭。', ['runs/test20_resume_20261112_01/formal_freeze_review_01.json','runs/dev23_scoring_replay_20261112_02/analysis.json']);

title(8,'正式结果：C明确解决10例',4);
const arms='ABCDE'.split('');
const status=[['明确解决','resolved',blue],['未解决','unresolved','#90A8CA'],['空提交','empty_patch','#D8E0EB'],['评测异常','errors','#C99445']];
const overview=chart(8,{position:{left:70,top:178,width:1130,height:386},categories:arms,
 series:status.map(([name,key,fill])=>({name,fill,values:arms.map(a=>key==='errors'?(d.arms[a].status_counts.ambiguous_error??0)+(d.arms[a].status_counts.infra_error??0):(d.arms[a].status_counts[key]??0))})),
 barOptions:{direction:'column',grouping:'stacked',overlap:100,gapWidth:95},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:21,typeface:font}},
 xAxis:{textStyle:{fontSize:24,typeface:font}},yAxis:{min:0,max:20,majorUnit:5,numberFormatCode:'0',textStyle:{fontSize:21,typeface:font},majorGridlines:{fill:'#DCE3ED',width:1}},
 dataLabels:{showValue:false,position:'center',textStyle:{fontSize:22,typeface:font,fill:'#FFFFFF',bold:true}}});
overview.series.getItemAt(0).dataLabels={showValue:true,position:'center',textStyle:{fontSize:24,typeface:font,fill:'#FFFFFF',bold:true}};
take(8,'A/B/D各7例，E为8例；每组分母均为20');
note(8,'图中保留原官方主标签：A7解4未4空5异，B7解4未5空4异，C10解4未1空5异，D7解5未2空6异，E8解3未3空6异。异常共26条，其中25含糊、1基础设施错误。20例单次，异常单列。');

title(9,'C比A/D/E解决更多，完整成本更低',4);
text(9,'cost-basis','成本按统一低谷价估算，包含共享前缀',{top:151,height:28,size:20,color:gray});
table(9,[['组别','明确解决','完整成本/元','前缀/元','后续/元','每明确解决/元'],...arms.map(a=>{const x=d.arms[a];return[a,x.resolved+'/20',x.full_cost.toFixed(4),x.prefix_cost.toFixed(4),x.continuation_cost.toFixed(4),x.cost_per_observed_resolved.toFixed(4)];})],{widths:[100,180,230,210,210,230],heights:[66,65,65,65,65,65],bodySize:22});
take(9,'C比D多3条明确解决，完整费用少约0.82元');
note(9,'逐请求按冻结低谷价统一：缓存命中0.02、未命中1、输出4元/百万token，保留实际缓存命中混合。A/C/D/E各计前缀1.61996412元，后续费用是完整费用减前缀。每明确解决费用为全部策略成本/观察到的明确解决数，失败和异常开销均包含。研究实际新增费用另记，不把共享前缀命中算作部署零成本。', ['runs/test20_resume_20261112_02/test20_uniform_off_peak_comparison.json']);

title(10,'B便宜，主要因为输出消耗较少',4);
text(10,'unit','输出词元（万）',{left:91,top:176,width:300,height:33,size:22,color:gray});
chart(10,{position:{left:70,top:212,width:740,height:345},categories:arms,series:[{name:'输出词元/万',values:arms.map(a=>d.arms[a].output_tokens/10000),fill:blue}],barOptions:{direction:'column',grouping:'clustered',gapWidth:90},hasLegend:false,
 xAxis:{textStyle:{fontSize:23,typeface:font}},yAxis:{numberFormatCode:'0',textStyle:{fontSize:20,typeface:font},majorGridlines:{fill:'#DCE3ED',width:1}},dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.0',textStyle:{fontSize:22,typeface:font,bold:true,fill:blue}}});
text(10,'requests','模型请求\nA 128次，B 116次',{left:855,top:218,width:340,height:100,size:27,bold:true,color:blue});
text(10,'tokens','B输出量为A的7.6%\n14/20例达到交互请求上限',{left:855,top:354,width:350,height:120,size:25});
take(10,'全局上限相同，实际消耗还受执行路径和阶段上限影响');
note(10,'本页以完整策略口径计入复用前缀。A输出1006523token，B76585token，比值0.07609。B116请求与A128接近，但平均输出更短，费用明显更低。交互会话固定6请求/10工具/420秒，B14例以model_call_budget结束；这说明全局资源上限相同并不保证各策略使用相同数量的有效尝试。图展示单预算观察，不是多预算曲线。');

title(11,'D把交互用于8例，但未取得明确解决',4);
table(11,[['组别','前缀停止','固定延续','交互延续','明确解决构成'],...['A','C','D','E'].map(a=>{const x=d.arms[a],r=x.routes;const n=route=>x.route_status_counts[route]?.resolved??0;return[a,String(r.stop??0),String(r.fixed??0),String(r.interactive??0),`${n('stop')}前缀 + ${n('fixed')}固定 + ${n('interactive')}交互`];})],{widths:[150,200,200,200,410],heights:[60,82,82,82,82],bodySize:24});
take(11,'D的8个交互实例中：0条明确解决、3条未解决、5条异常');
note(11,'正式共同停止8例，其中公开通过3例、生成环境停止5例，停止后的合法候选仍可进入独立评测。六个明确解决来自相同前缀提交。C后续交互增加4例明确解决，D固定增加1例、交互0例，A固定增加1例，E固定和交互各1例。D正式触发8/12，E随机实现4/12，E概率仍固定为8/17。C在D选交互的相同8个实例也没有明确解决。');

title(12,'C与D的3条差异集中在固定延续',4);
table(12,[['实例','D选择固定的依据','D结果','C结果'],['Django-11910','应用/语法错误优先固定','空提交','交互后解决'],['Seaborn-2848','证据不足，保守固定','空提交','交互后解决'],['pytest-6116','应用/语法错误优先固定','评测异常','交互后解决']],{widths:[250,430,200,280],heights:[58,104,104,104],bodySize:24});
take(12,'C的3条新增明确解决均来自D选择固定延续的实例');
note(12,'C的明确解决集合比D多这三例，没有D独有的明确解决。pytest的D标签是评测异常，不能补为逻辑失败。两组的前缀和可用状态完全相同，延续生成仍存在随机差异，因此此处作逐例观察。');

title(13,'定位缺失时，固定延续难以补证',4);
table(13,[['观察项','Django-11910','Seaborn-2848'],['前缀定位与上下文','定位缺失，源码上下文为空','定位缺失，源码上下文为空'],['可应用前缀候选','0/2','0/2'],['D固定延续结果','空提交','空提交'],['C交互延续结果','明确解决','明确解决']],{widths:[300,430,430],heights:[58,86,72,72,72],bodySize:24});
take(13,'路由改进重点：先识别“需要重新定位”的失败');
note(13,'两例features中localization_missing=true、context_files=[]、n_applicable=0。D的固定延续不能主动扩大检索范围，C的交互分支能够补充定位和源代码信息。该现象提示局部修正优先和证据不足保守固定规则需要审查其前提，特别是当前上下文是否足以执行修复。本次不修改冻结规则或重跑实验。');

title(14,'失败案例：修复位置与行为覆盖',4);
table(14,[['案例','补丁做了什么','为什么仍未完成'],['Flask-4045','增加蓝图名称校验','端点异常约定仍未补齐，\n目标断言失败'],['SymPy-23262','增加Python代码打印器的tuple处理','lambdify的原生tuple经过另一层递归，\n新增打印函数未覆盖问题路径']],{widths:[230,430,500],heights:[58,150,150],bodySize:24});
take(14,'修改相关文件后，还需验证真正执行的问题路径');
note(14,'Flask五组均只修复构造器名称的一部分行为，实际测试窗口显示端点应抛ValueError却触发AssertionError。Sympy23262的非空提交加_print_tuple，但演示用native tuple在_recursive_to_string中递归拼接，缺失singleton comma的问题仍在该层。这里使用正式预测封存之后已完成的语义复核，不使用已取消补充设置。', ['runs/dev_supplement_20261112_02/review_only/semantic_review.json']);

title(15,'收益集中在哪些仓库',4);
const repoNames={'astropy__astropy':'Astropy','django__django':'Django','matplotlib__matplotlib':'Matplotlib','mwaskom__seaborn':'Seaborn','pallets__flask':'Flask','psf__requests':'Requests','pydata__xarray':'Xarray','pylint-dev__pylint':'Pylint','pytest-dev__pytest':'pytest','scikit-learn__scikit-learn':'scikit-learn','sphinx-doc__sphinx':'Sphinx','sympy__sympy':'SymPy'};
table(15,[['仓库','样本','A','B','C','D','E'],...Object.entries(d.per_repository).map(([name,r])=>[repoNames[name]??name,String(r.n),...arms.map(a=>String(r[a]))])],{top:176,widths:[320,140,140,140,140,140,140],heights:[40,...Array(12).fill(32)],bodySize:22,padY:2});
text(15,'takeaway','C新增的3例来自Django、Seaborn和pytest',{top:657,width:1050,size:24,color:blue,bold:true,height:34});
note(15,'按仓库显示各组明确解决数，所有指定样本留在分母。Django占4/20例，仓库分层抽样的微平均不直接代表test300总体。原预注册共同可运行子集7例，其A/B/C/D/E明确解决为3/3/4/3/3；该定义同时考虑生成环境和评测状态，不与其他事后标签交集混用。');

title(16,'结果口径',4);
rows(16,[['生成状态','生成环境失败后，保留的候选仍可能通过独立评测'],['评测状态','39条明确解决，20条未解决，15条空提交，26条异常'],['语义检查','已完成100条agent复核和全量日志审计']],{gap:127,bodySize:25});
take(16,'本轮为20例单次观察，异常单列，原主标签保留');
note(16,'生成环境失败与最终补丁评价属于不同阶段，A/B/D各4条、C/E各5条记录在生成环境错误后仍独立解决。全量日志复核39条明确解决；12条原异常有实际失败证据，10条原未解决只有通过汇总、缺少逐测试解析。Requests五组均在1800秒上限超时。日志中的文档示例也可干扰分类。原官方标签不回写，agent复核不称外部真人签审。单次不提供置信区间或显著性结论。', ['runs/dev_supplement_20261112_02/formal_scoped_log_audit.json']);

title(17,'四个研究问题的回答',4);
table(17,[['问题','本轮观察','分析'],['RQ1 同预算质量','C=10，D=7，A=7','级联是本轮更强的比较基线'],['RQ2 证据选择价值','D交互8例，0条明确解决','当前信号没有捕获本轮新增收益'],['RQ3 质量与成本','C完整成本低于A/D/E，B最低','关注输出量和阶段子上限的影响'],['RQ4 失败与误判','定位缺失、行为遗漏、日志误识别','修复失败和评价失败需要分别定位']],{widths:[280,440,440],heights:[58,85,85,85,85],bodySize:24});
take(17,'当前改进重点是路由信号与可恢复性的对应关系');
note(17,'RQ1的自适应质量收益没有在本轮观察到。RQ2的dev有效配对只有一个交互独胜样本，阈值多方案平局；test中新收益落在保守固定的案例。RQ3目前只有一个资源档，未完成多预算曲线；B的成本还受交互子上限影响。RQ4已经给出定位/路径/异常契约/评价误识别案例，真实消融和敏感性设置按用户指令取消。');

title(18,'结题结论与改进重点',6);
rows(18,[['课题结论','执行模式选择值得单独研究，\n共享前缀让增量收益可以逐例追踪'],['本轮发现','级联C明确解决10例，自适应D为7例；\n差异主要出现在定位不足却继续固定的案例'],['改进重点','识别定位缺失与可恢复失败，\n加强问题行为验证，审查阶段预算配置']],{gap:132,bodySize:26});
take(18,'主要价值：形成可运行、可解释、可复核的模式比较方法');
note(18,'系统实现、dev校准、正式20例五组一次与独立判分已经完成。结论落在执行模式选择与失败证据的对应关系，后续改进方向来源于具体案例，不在本轮测试集上改规则后重跑。已取消补充实验不恢复，统计重复、真实消融与敏感性验证属于后续研究需求。');

const shortId=id=>id.replace('scikit-learn__scikit-learn','sklearn').replace('django__django','Django').replace('matplotlib__matplotlib','Matplotlib').replace('mwaskom__seaborn','Seaborn').replace('pallets__flask','Flask').replace('psf__requests','Requests').replace('pydata__xarray','Xarray').replace('pylint-dev__pylint','Pylint').replace('pytest-dev__pytest','pytest').replace('sphinx-doc__sphinx','Sphinx').replace('astropy__astropy','Astropy').replace('sympy__sympy','SymPy');
const symbols={resolved:'解',unresolved:'未',empty_patch:'空',ambiguous_error:'异',infra_error:'异'};
for(const [j,start] of [0,10].entries()){
 const i=19+j;title(i,'附录：逐例结果（'+(j+1)+'/2）',4);
 table(i,[['实例',...arms],...d.per_case.slice(start,start+10).map(r=>[shortId(r.instance_id),...arms.map(a=>symbols[r.status[a]])])],{top:178,widths:[510,130,130,130,130,130],heights:[42,...Array(10).fill(39)],bodySize:23,padY:2});
 text(i,'legend','解：明确解决　未：未解决　空：空提交　异：评测异常',{top:641,size:22,color:gray,height:34});
 note(i,'本页逐例记录使用原官方主标签。完整实例ID与预测/评测来源见分析JSON及其来源哈希。'+d.per_case.slice(start,start+10).map(r=>'\n'+r.instance_id+' '+JSON.stringify(r.status)).join(''));
}
if(p.slides.items.length!==N)throw new Error('Slide count mismatch');
await fs.mkdir(build+'/draft',{recursive:true});await fs.mkdir(build+'/render',{recursive:true});
const candidate=build+'/draft/candidate.pptx';await (await PresentationFile.exportPptx(p)).save(candidate);
for(const [i,slide] of s.entries()){
 const png=await p.export({slide,format:'png',scale:1});await fs.writeFile(build+'/render/slide-'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await png.arrayBuffer()));
}
await fs.writeFile(build+'/slide_text.json',JSON.stringify((await p.inspect({select:'$.slides[*]',include:['index','elements.text','notes.text']})).records,null,2));
console.log(JSON.stringify({candidate,slides:N}));
if(process.argv.includes('--finalize')){
 const link=fs.link.bind(fs);fs.link=async(a,b)=>{try{return await link(a,b);}catch(e){if(process.platform!=='win32'||e.code!=='EPERM'||!a.endsWith('.validated')||b.replaceAll('\\','/')!==final)throw e;await fs.copyFile(a,b,constants.COPYFILE_EXCL);}};
 const tables=[3,5,7,8,10,12,13,14,15,16,18,20,21];
 const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:final,
 pythonExecutable:process.env.RUNTIME_PYTHON,integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tables.flatMap(n=>['--require-native-table-slide',String(n)])],
 requiredNativeTableOwnerSlides:tables,requiredNativeChartOwnerSlides:[9,11],materializeLiteralChartWorkbooks:true,
 fontPolicy:{basis:'reference',families:[font],referencePath:source,referenceSha256:crypto.createHash('sha256').update(await fs.readFile(source)).digest('hex')},
 verifyArtifactToolImport:true,receiptPath:root+'/runs/ppt_analysis_20261113_01/validation_receipt_final.json'});
 console.log(JSON.stringify(result,null,2));
}
