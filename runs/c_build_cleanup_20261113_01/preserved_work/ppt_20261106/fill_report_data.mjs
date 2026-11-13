import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
let root=here;
while(true){
  try{await fs.access(path.join(root,'configs/proposal_v1.json'));break;}catch{}
  const parent=path.dirname(root);if(parent===root)throw new Error('无法发现项目根目录');root=parent;
}
const read=async(relative)=>JSON.parse((await fs.readFile(path.join(root,relative),'utf8')).replace(/^\uFEFF/,''));
const acceptance='runs/dev2_acceptance_20261106/';
const summary=await read(acceptance+'pilot_summary.json');
const accounting=await read(acceptance+'generation_accounting.json');
const audit=await read(acceptance+'pilot_execution_audit.json');
const scoring=await read(acceptance+'pilot_official_scoring_summary.json');
const release=await read(acceptance+'release_validation.json');
const data=await read(path.relative(root,path.join(here,'report_data.json')));
if(summary.rows.length!==10||audit.cells.length!==10||scoring.arms.length!==5)throw new Error('最终10格尚未完整');
if(!audit.passed||!scoring.all_five_outer_inner_current_hashes_match)throw new Error('执行或判分来源关联未通过');
const routeNames={fixed:'固定延续',standalone:'从零交互',interactive:'交互延续',stop:'前缀停止'};
data.complete=true;
data.summary='A/C/E 各解决 1 例，B/D 均未解决';
data.completion='两例五组全部生成并完成独立判分，10 格结果齐全';
data.offline={passed:350,total:350,protected_original:'93/93',protected_archive:'131/131',source:acceptance+'release_validation.json',release_evidence:release};
data.interface_lines={
  environment:'两例均通过指定公开测试文件，生成与判分链路可运行',
  environment_notes:'pvlib固定公开基线与NumPy 1.26.4。pydicom使用独立公开源码派生镜像，pytest7.4.4恢复旧setup并预缓存公开SHA256一致的fixture。未修改源码或测试。公开基线验证为245、120、38项通过。pydicom派生镜像不等于原官方实例镜像。',
  model:'deepseek-flash，真实修复生成与工具调用完成',
  scoring:'SWE-bench 5.0.2，10/10 独立判分完成',
  footnote:'真实容器执行、共享前缀、分支选择与判分关联均有独立记录',
  notes:'350/350是最终源码状态的活动离线测试。独立判分在冻结补丁后运行，10个指定结果均完成，非空补丁10个，基础设施错误0个。响应模型名称为服务别名。费用与请求覆盖此前失败探测及诊断。'
};
const auditMap=new Map(audit.cells.map(c=>[`${c.instance_id}/${c.arm}`,c]));
data.results=summary.rows.map(r=>{
  const c=auditMap.get(`${r.instance_id}/${r.arm}`);
  const official=scoring.arms.find(a=>a.arm===r.arm).verdicts[r.instance_id];
  if(official!==r.status)throw new Error('判分汇总不一致');
  return{instance_id:r.instance_id,arm:r.arm,route:routeNames[c.selected_route],verdict:r.status==='resolved'?'已解决':'未解决',resolved:r.status==='resolved',status:r.status,generation_status:r.generation_status,termination_reason:r.termination_reason,run_id:r.run_id,policy_cny:r.cost_cny,new_cny:c.new_generation_cost_cny,resources:r.resources,prediction_sha256:r.prediction_sha256,patch_sha256:r.patch_sha256};
});
data.arm_costs='ABCDE'.split('').map(arm=>({arm,resolved:summary.primary[arm].resolved,policy_cny:accounting.arms[arm].policy_cost_cny,new_cny:accounting.arms[arm].new_generation_cost_cny,resources:summary.primary[arm].resources}));
data.totals={
  result_summary:'pvlib：A/C/E 解决，B/D 未解决\npydicom：五组均未解决',
  cost_summary:`五组新增 ${accounting.pilot_new_generation_cny.toFixed(4)} 元，累计 ${accounting.cumulative_cny.toFixed(4)} 元`,
  next_summary:'本轮完成端到端链路，下一步改进公开验证覆盖与交互预算',
  pilot_new_generation_cny:accounting.pilot_new_generation_cny,
  full_policy_cny:accounting.pilot_full_policy_cny,
  cumulative_cny:accounting.cumulative_cny,
  usage_estimated_cny:accounting.estimated_from_usage_cny,
  unknown_reserved_cny:accounting.unknown_reserved_cny,
  actual_request_records:accounting.actual_request_records,
  pending:accounting.pending,
  budget_ceiling_cny:accounting.ceiling_cny
};
data.failure_example={
  title:'pydicom 的公开通过与最终未解决',
  metric1:'4 组',metric2:'0 组',
  label1:'公开验证通过后停止',label2:'独立判分确认解决',
  evidence:'A/C/D/E 在公开验证通过后共享停止，提交同一前缀补丁。\n四组独立判分均为未解决。',
  cause:'公开通过没有转化为最终解决\n后续需加强公开复现与停止条件审查',
  followup:'pvlib D 则耗尽 6 次交互请求，C/E 在 4/5 次请求后完成公开验证',
  notes:'pydicom A/C/D/E selected_route=stop，termination_reason=early_stop_public_pass，补丁SHA256均为8415fd7cb734e9df85ab0028fafbc86eaf9864fce0ced43db316b833e314636f。四组独立结果均为unresolved。公开通过与最终未解决为直接观察，未根据官方基础设施附加标签推定全面环境健康，也未读取或展示隐藏反馈。pvlib D/C/E均选择interactive，实际交互会话请求为6/4/5次，D因model_call_budget退出，C/E因public_pass退出。'
};
data.candidate_calibration.summary='同两例配对，eligible=1\n临时阈值 0.75/0.75，E 触发概率 1.0';
data.next_steps=[
  ['公开验证','补充 pydicom 公开复现，分析公开通过与最终未解决的差异'],
  ['交互预算','分析 D 的请求分配与候选有效性，保留同路由负结果'],
  ['完整 dev 校准','扩大独立 dev 样本，校准完整路由、前缀与资源上限'],
  ['正式研究','冻结模型配置后重复实验，补消融、敏感性与语义审查']
];
data.sources_by_slide=[
  ['docs/两例五组实验摘要_20261106.md',acceptance+'pilot_summary.json'],
  [acceptance+'preregistration.json',acceptance+'pilot_summary.json',acceptance+'pilot_official_scoring_summary.json'],
  ['src/swe_repair/experiment.py',acceptance+'pilot_execution_audit.json',acceptance+'calibration_candidate.json'],
  [acceptance+'environment/pvlib/public_test_pvsystem_execution_v2.json',acceptance+'environment/pydicom/public_environment_repair_summary.json'],
  [acceptance+'release_validation.json',acceptance+'pilot_official_scoring_summary.json',acceptance+'pilot_execution_audit.json','runs/model_probe_20261106_02/result.json'],
  [acceptance+'pilot_summary.json',acceptance+'pilot_execution_audit.json',acceptance+'pilot_official_scoring_summary.json'],
  [acceptance+'generation_accounting.json',acceptance+'pilot_summary.json',acceptance+'batch_ledger.json'],
  [acceptance+'pilot_execution_audit.json',acceptance+'pilot_official_scoring_summary.json','runs/dev2_pilot_D_20261106_01/matrix.json'],
  [acceptance+'calibration_candidate.json','runs/dev2_diagnostic_20261106_02/analysis.json',acceptance+'generation_accounting.json','configs/proposal_v1.json'],
  ['docs/两例五组实验摘要_20261106.md','docs/实验协议_开题对齐.md',acceptance+'pilot_summary.json']
];
data.source_hashes={};
for(const relative of new Set(data.sources_by_slide.flat())){
  data.source_hashes[relative]=crypto.createHash('sha256').update(await fs.readFile(path.join(root,relative))).digest('hex');
}
await fs.writeFile(path.join(here,'report_data.json'),JSON.stringify(data,null,2)+'\n');
console.log(JSON.stringify({dataComplete:true,cells:data.results.length,arms:data.arm_costs.length,sources:Object.keys(data.source_hashes).length,offline:data.offline.total}));
