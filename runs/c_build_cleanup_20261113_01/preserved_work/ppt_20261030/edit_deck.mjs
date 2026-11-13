export async function editDeck(p) {
  const ink='#202020', blue='#2F5597', gray='#606060', font='微软雅黑';
  const set=(s,name,value,size=24,color=ink,bold=false,position,align='left')=>{
    const shape=s.shapes.items.find(x=>x.name===name);
    if(!shape)throw new Error('Missing source shape '+name);
    shape.text=value;
    shape.text.style={typeface:font,fontSize:size,color,bold,alignment:align,verticalAlignment:'top',insets:0,wrap:'square',autoFit:'none'};
    if(position)shape.position={...shape.position,...position};
    return shape;
  };
  const title=(s,value)=>set(s,'标题 4',value,32,ink,true);
  const table=(s,values,widths)=>{
    const t=s.tables.items[0];
    if(!t)throw new Error('Missing editable reference table');
    if(values.length!==t.rows.length)throw new Error('Table row count mismatch');
    if(widths) widths.forEach((w,c)=>{t.columns.get(c).width=w;});
    values.forEach((row,r)=>row.forEach((value,c)=>{
      const cell=t.getCell(r,c);cell.value=value;
      cell.text.style={typeface:font,fontSize:23,color:r===0?'#FFFFFF':c===0?blue:ink,bold:r===0||c===0,
        alignment:'left',verticalAlignment:'middle',insets:{left:18,right:14,top:12,bottom:12},autoFit:'none'};
    }));
  };
  const s=p.slides.items;
  if(s.length!==10)throw new Error('Reference must have ten slides');
  set(s[0],'标题 5','面向仓库级程序修复的\n自适应混合架构',44,ink,true,undefined,'center');
  set(s[0],'文本占位符 7','边界修复与小范围 dev 准备\n汇报人：陈堉锋　张曹远臻\n2026 年 10 月 30 日',26,ink,false,undefined,'center');

  title(s[1],'本轮工作与当前阶段');
  set(s[1],'research-question','失败证据能否帮助选择更合适的修复模式？',32,blue,true);
  set(s[1],'comparison-condition','同模型、同初始信息、同资源上限\nA 固定　B 纯交互　C 级联　D 自适应　E 随机',25,gray,false,{top:248,height:74});
  set(s[1],'label-337','本轮已完成',27,blue,true);
  set(s[1],'detail-337','源码边界修复、离线回归、原始证据保护与 dev 集成计划',24);
  set(s[1],'label-470','后续待验证',27,blue,true);
  set(s[1],'detail-470','真实模型与容器集成、完整 dev 校准、正式重复及消融',24);
  set(s[1],'negative-result','当前完成工程与离线验收，方法收益仍需受控实验检验',24,blue,true);

  title(s[2],'本地更改覆盖路由、执行与评测');
  table(s[2],[['环节','复核发现的问题','本轮修复'],
    ['路由','外部帧、测试帧误触发','统一源码归属与测试识别'],
    ['执行','共享容器，固定仅单轮','新容器隔离，多轮固定延续'],
    ['预算','重试、收尾与终止状态不一致','按实际请求限额，区分终止'],
    ['评测','标签缺关联，E 分母随缺失改变','绑定预测，保留完整 eligible']]);
  set(s[2],'why-it-matters','修复围绕实验可比性展开，新增回归全部采用离线执行',25,blue,true);

  title(s[3],'共享前缀与分支环境隔离');
  table(s[3],[['比较项','正式运行','配对诊断'],
    ['执行对象','只执行所选延续分支','eligible 失败运行两条延续'],
    ['共同起点','A/C/D/E 复用同一实际前缀','分别恢复同一序列化快照'],
    ['环境核对','实际 image ID 与 base commit','每条延续新建独立容器'],
    ['资源口径','完整计入继承的前缀开销','各自获得相同剩余预算']]);
  set(s[3],'branch-boundary','新容器隔离文件与进程，清理异常保留费用及审计记录',26,blue,true);
  set(s[3],'cost-boundary','双分支采集成本单列，固定分支的新候选不进入交互输入',21,gray);

  title(s[4],'路由证据与环境恢复');
  const rows=[
    ['源码证据','确认 repo_root 归属，外部依赖帧保留审计但不触发'],
    ['测试路径','统一排除 test/tests 目录、test_*.py 与 *_test.py'],
    ['默认选择','证据不足或仍可局部修正时，保守固定延续'],
    ['环境恢复','绑定原失败候选，同一公开命令可运行才清除故障']];
  rows.forEach(([label,body],i)=>{set(s[4],`route-label-${i}`,label,27,blue,true);set(s[4],`route-body-${i}`,body,25);});
  set(s[4],'candidate-disclosure','环境恢复最多一次，失败后停止。最终结果仍由独立评测判断',21,gray);

  title(s[5],'固定延续与交互预算');
  set(s[5],'budget-dimensions','固定最多 6 轮候选生成，交互最多 6 次请求',32,blue,true);
  const budgets=[
    ['固定生成','保持前缀上下文，接收结构化反馈，保留已有有效候选'],
    ['交互控制','校验状态与参数，重试计数，在原限额内预留收尾'],
    ['终止留痕','区分预算、环境与生成错误，未知 usage 保守预留']];
  budgets.forEach(([label,body],i)=>{set(s[5],`budget-label-${i}`,label,26,blue,true);set(s[5],`budget-body-${i}`,body,25);});
  set(s[5],'budget-status','开发上限：512000 token、12 请求、80 次 container exec、1200 秒，均待校准',21,gray);

  title(s[6],'独立判分与校准统计');
  set(s[6],'historical-scope','补丁冻结后独立判分，结果不回流同次生成',24,gray);
  table(s[6],[['环节','绑定或校验对象','使用范围','缺失处理'],
    ['独立判分','运行、预测、补丁及报告','新报告必须关联','拒绝串用或篡改'],
    ['dev 校准','完整配对拟合阈值','全部 eligible 匹配 E','披露分母与缺失']], [150,390,300,310]);
  set(s[6],'corrected-conclusion','正式记录核对 seed 与哈希，主总体保留环境失败',27,blue,true);
  set(s[6],'old-cost-definition','另报共同可运行子集和四元资源，当前产出质量成本比较点',22,gray);
  set(s[6],'historical-limit','统计出口已实现，正式统计与多预算成本曲线仍待实测',21,gray);

  const evalLayout=p.layouts.items.find(x=>x.name==='内容页-标题4');
  const toolLayout=p.layouts.items.find(x=>x.name==='内容页-标题5');
  if(evalLayout)s[7].setLayout(evalLayout);
  if(toolLayout)s[8].setLayout(toolLayout);
  title(s[7],'离线验收与原始资产保护');
  set(s[7],'original-count','291 / 291',66,blue,true,{width:530});
  set(s[7],'archive-count','+69',70,blue,true);
  set(s[7],'original-label','活动离线回归全通过',28,ink,true);
  set(s[7],'archive-label','新增边界回归',28,ink,true);
  set(s[7],'original-hash','假模型、假容器、假 harness',23,gray);
  set(s[7],'archive-hash','相较上一轮 222 项',23,gray);
  set(s[7],'output-directory','原始资产 93/93，归档原件 131/131 哈希一致',27,blue,true);
  set(s[7],'population-note','覆盖路由、隔离、预算、异常与判分关联\n真实模型、Docker 和官方 harness 本轮未运行',25);
  set(s[7],'handoff-docs','历史原件保持字节不变，旧复现与新验收材料分别保留',21,gray);

  title(s[8],'3 例 dev 的分阶段准备');
  set(s[8],'test-count','1 + 2',68,blue,true);
  set(s[8],'test-count-unit','首例验收后再扩展两例',29,ink,true);
  set(s[8],'fake-runtime','覆盖 3 个仓库\n完整保留 dev 23 例台账',24,gray,{height:90});
  set(s[8],'verified-label','首例（未执行）',27,blue,true);
  set(s[8],'verified-body','pvlib__pvlib-python-1707\n仅按实例 ID 与仓库分布抽取',24);
  set(s[8],'unverified-label','扩展两例（未执行）',27,blue,true);
  set(s[8],'unverified-body','pydicom__pydicom-1139\npyvista__pyvista-4315',24);
  set(s[8],'offline-scope','种子 20261030。单策略实例 2 CNY，批次 6 CNY，诊断上界 18 CNY，可能提前停止',21,gray);

  title(s[9],'下一阶段的验收与研究任务');
  const next=[
    ['首例集成','明确授权并固定服务模型，在 WSL 验收接口与公开测试'],
    ['扩展与校准','完成其余两例，再做完整 dev 路由与预算校准'],
    ['正式重复','预注册 test 总体或分层子集，同实例至少三次重复'],
    ['统计与审查','实例聚类区间、逐仓库与宏平均，补消融和人工审查']];
  next.forEach(([label,body],i)=>{set(s[9],`next-title-${i}`,label,27,ink,true);set(s[9],`next-detail-${i}`,body,24,gray);});
  set(s[9],'current-gate','配置仍待校准，真实容器与付费生成均未执行',27,blue,true);

  const notes=[
    ['本次汇报覆盖当前所有本地修复。研究问题仍是同模型、同信息与同资源上限下的模式选择。工作重心是实验可比性和集成准备，没有新的真实方法效果结论。',
     'docs/开题报告正文摘录.md；docs/修复验收与dev准备_20261030.md'],
    ['五组保持原设计。A 为固定流程，B 从零交互，C 对可继续失败级联，D 按失败证据选择，E 匹配 D 的 eligible 触发率随机选择。当前处于离线验收后的研究原型阶段。',
     'docs/实验协议_开题对齐.md；configs/proposal_v1.json'],
    ['上一轮复核发现的主要问题覆盖路由、执行、预算及判分校准。此次还增加 seed/run/预测哈希检查、公开验证真实退出码、交互状态校验和完整 dev 台账。历史分析与旧合成复现保持原样。',
     'docs/项目现状与源码复核_20261029.md；docs/修复验收与dev准备_20261030.md；当前 git diff'],
    ['正式只运行所选路线，配对诊断只针对 eligible 前缀失败。固定和交互恢复独立状态与相同剩余预算，各自使用新容器。镜像身份来自实际运行容器，基线提交必须匹配。缓存命中仍完整计入策略前缀成本，另记新增生成成本。该机制已通过假容器回归，真实隔离尚未实测。',
     'src/swe_repair/experiment.py；src/swe_repair/prefix.py；tests/test_experiment.py'],
    ['外部绝对帧不再缩成 basename，测试路径识别在路由与补丁范围中一致。环境恢复绑定原失败候选，只允许同一公开命令确定性重验一次。恢复后测试确实可运行才清除环境故障。合法相对帧仍按 checkout cwd 解释，文件存在性和 symlink 未实测。',
     'src/swe_repair/fingerprint.py；src/swe_repair/patchutil.py；src/swe_repair/prefix.py；tests/test_routing_evidence.py；tests/test_public_validation.py'],
    ['固定最多六轮生成只是开发限额，空输出也占轮次，不代表已冻结的最优候选数。交互会话限制六次实际模型请求、十次具名工具和420秒，重试占请求额度，最终调用预留在上限内。全局四元预算为512000 token、12请求、80次container exec及1200秒。未知usage的资源和费用采用保守预留，不是实付。',
     'configs/proposal_v1.json；src/swe_repair/execution.py；src/swe_repair/interact.py；tests/test_interaction_contracts.py'],
    ['新 scoring sidecar 绑定 matrix、预测文件字节、每实例补丁、arm/split/seed/repeat/config 和报告。新分析器默认拒绝无关联或不匹配标签。阈值拟合需要完整配对标签，E概率则在全部eligible dev前缀上回放，分母不随判分缺失缩小。主分析保留指定总体，次分析报告各组均可运行子集。模型失败和空补丁不能因成绩不佳被排除。当前只有单预算比较点。',
     'src/swe_repair/evaluation.py；scripts/score_run.py；scripts/analyse_cf.py；src/swe_repair/calibration.py；src/swe_repair/statistics.py'],
    ['2026年10月30日的验收记录为Python3.14.2活动离线套件291/291通过，较222项新增69项。原始资产93/93与归档原件131/131哈希一致。包含假harness生成sidecar到CLI分析往返。此处不是修复成功率，也不是官方判分结果。',
     'runs/dev_preparation_20261030/validation.json；docs/修复验收与dev准备_20261030.md'],
    ['样本按完整dev23的实例ID和仓库分布、种子20261030确定，没有使用旧模型成绩或gold通过名单。先验收pvlib，再扩展pydicom和pyvista，不因失败静默换例。所有计划execute=false，完整23例均留存not_run/not_verified/not_scored状态。2CNY为单策略实例守卫，6CNY为批次守卫。三例双分支加独立B的保守上界18CNY不是批准预算或实付，批次守卫可能先停。',
     'runs/dev_preparation_20261030/instances.json；first_instance.json；remaining_instances.json；full_dev_coverage.json；preparation.json'],
    ['当前model_version、路由两个阈值和E概率仍为null，状态draft-pending-calibration，live_authorized=false。小范围集成仍需新明确授权和服务模型版本锁定。宿主Python未发现requests/pyarrow/swebench，PATH未发现Docker，WSL内部环境尚未检查。完整dev校准、正式至少三次重复、独立判分、统计、消融、敏感性和人工语义审查仍待完成。',
     'configs/proposal_v1.json；runs/dev_preparation_20261030/preparation.json；docs/实验协议_开题对齐.md']
  ];
  notes.forEach(([body,sources],i)=>{s[i].speakerNotes.text=body+'\n\n本地资料来源：'+sources;});
  return {slideCount:s.length};
}
