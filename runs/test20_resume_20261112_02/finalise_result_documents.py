"""Write the completed descriptive report and an inactive handoff copy."""
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import copy,hashlib,json
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def main():
    cost=read(OUT/'final_cost_audit.json');summary=read(OUT/'test20_single_run_summary.json')
    comparison=read(OUT/'test20_uniform_off_peak_comparison.json')
    result=read(OUT/'formal_result_audit.json');preserved=read(OUT/'final_preservation.log')
    assert result['all100_generation_inputs_immutable'] and result['all_five_independent_reports_and_provenance_validated']
    assert cost['pending'] is None and preserved['experiments']['ok'] and preserved['archive']['ok']
    snapshot=read(ROOT/'runs/test20_resume_20261112_01/formal_source_snapshot/manifest.json')
    for item in snapshot['files']:assert sha(ROOT/item['path'])==item['sha256']
    log=OUT/'offline_validation.log';assert '392/392 passed' in log.read_text(encoding='utf-8')
    inactive=ROOT/'configs/test20_inactive_20261112_02.json'
    cfg=read(ROOT/'configs/test20_frozen_20261112_01.json');cfg=copy.deepcopy(cfg)
    cfg['execution']['live_authorized']=False
    cfg['note']='Inactive handoff copy after the authorized test20 x A-E x repeat0 has completed. Not the actual execution config. Original frozen execution bytes and hashes remain preserved; unused budget grants no repeat authorization.'
    write(inactive,cfg)
    write(OUT/'final_validation.json',{'offline_suite_passed':True,'offline_passed':392,'offline_total':392,
        'offline_log_sha256':sha(log),'frozen_source_files_reverified':len(snapshot['files']),
        'generation_source_sha256':snapshot['generation_code_sha256'],
        'offline_suite_not_repeated_after_document_only_edits':True,'preservation_ok':True,
        'original_protected_total':93,'original_verified':preserved['experiments']['verified'],
        'archive_protected_total':preserved['archive']['archived_total'],
        'preservation_log_sha256':sha(OUT/'final_preservation.log'),
        'sealed_generation_selection_audit_sha256':sha(OUT/'sealed_generation_selection_audit.json'),
        'all100_submissions_and80_routes_reproduced':True,'recorded_resource_overruns':0,
        'at':datetime.now(timezone.utc).isoformat()})
    ended=datetime.fromisoformat(read(OUT/'formal_scoring_completed.json')['ended_at']).astimezone(ZoneInfo('Asia/Shanghai'))
    table=[]
    for arm in 'ABCDE':
        v=comparison['arms'][arm];counts=v['status_counts']
        unknown=sum(counts.get(k,0) for k in ('ambiguous_error','infra_error','error','not_scored'))
        table.append(f"| {arm} | {v['resolved']}/20 | {counts.get('unresolved',0)} | {counts.get('empty_patch',0)} | {unknown} | {v['comparative_full_strategy_cost_off_peak_cny']:.4f} |")
    common=summary['common_runnable']
    macro='、'.join(f"{a}={summary['primary'][a]['repository_macro_average']:.2%}" for a in 'ABCDE')
    repos=sorted(summary['primary']['A']['per_repo'])
    repo_rows=[]
    for repo in repos:
        vals=[summary['primary'][a]['per_repo'][repo] for a in 'ABCDE']
        repo_rows.append('| '+repo+' | '+str(vals[0]['total'])+' | '+' | '.join(str(v['resolved']) for v in vals)+' |')
    report=f'''# test20五组一次实验报告

本轮授权的完整dev校准、配置冻结、正式20例×A/B/C/D/E×一次预测及独立官方评测流程已经完成。最后评测汇总时间为{ended:%Y-%m-%d %H:%M:%S}（北京时间）。100条状态记录齐全，其中存在26条评测异常；这不等于100条有效语义解决标签齐全。关停和证据归档的最终核验以 `runs/test20_resume_20261112_02/SESSION_SAVED.json` 实际字段为准。

## 正式结果

固定20例从完整test300按ID/仓库分层抽样，12个仓库，seed=20261111、repeat_index=0，无换例、无新增重复。主分母每组20例，环境/含糊异常和未提交均保留。

| 组别 | 明确解决 | 明确未解决 | 未提交 | 评测异常 | 完整策略成本，统一低谷价/CNY |
|---|---:|---:|---:|---:|---:|
{chr(10).join(table)}

异常共25条ambiguous_error、1条infra_error，不能合并为真正未解决。表中解决比例是指定样本的已观察到明确解决份额；不把未知语义标签补成失败。原汇总器的evaluation_complete/known_pair_count表示评价状态已记录，不能解释为所有语义标签有效。100条逐例状态、预测/判分身份、成本及资源见 `test20_single_run_summary.json`；包含明确unknown_semantic字段的用户费用口径见 `test20_uniform_off_peak_comparison.json`。

本次C比D多3条明确解决记录，完整策略成本少约0.82CNY；D比E少1条明确解决记录，完整策略成本少约0.70CNY。这里只描述本轮记录，不能据20例一次、不同异常和随机生成得出方法优势、非劣、稳定性或显著性结论。抽样每仓库至少1例，因此微平均也不代表完整test300的解决率。

全组共同可运行的次要子集仅{len(common['instance_ids'])}例，其明确解决数为{ '、'.join(a+'='+str(common['primary'][a]['resolved']) for a in 'ABCDE') }，不能替换主20例分母。指定样本的仓库宏平均明确解决份额：{macro}。

## 费用口径

本轮原100CNY累计账本估算/保守记账为 **{cost['cumulative_estimated_or_reserved_cny']:.8f}CNY**，剩余守卫{cost['remaining_guard_cny']:.8f}CNY，pending=null。含dev/准备等{cost['dev_preparation_and_other_actual_cost_cny']:.8f}CNY、正式真实新增{cost['formal_actual_generation_cost_cny']:.8f}CNY；正式434次真实新增请求，整个本轮账本1008条。所有金额都是按冻结价表和usage估算，不是供应商账单实付或账户余额。

用户在正式结果读取前要求将E换算为低谷价格。缓存命中/未命中/输出分别按0.02/1/4 CNY每百万token逐请求重算，不能将跨时段全组总额直接减半。E真实新增换算 **1.94690578CNY**，含共享前缀的完整策略换算 **3.56686990CNY**；原时段新增3.71834734、完整5.33831146保留在原账本/审计中。100元守卫仍按原时段金额；没有以换算“退回”额度。

A/C/D/E各自完整计入同一真实前缀1.61996412CNY，同时另报本轮实际新增生成成本；复用不是部署零成本。B合并原7例、无新增API恢复的第8例及新执行12例，旧费用不重复入账。观察到的服务端缓存命中和执行顺序仍是成本比较局限。

## 执行与独立性核验

- 冻结生成算法保持不变；本次新增的是可审计续跑、费用换算、核验/交接脚本。实际配置 `configs/test20_frozen_20261112_01.json`、有效配置哈希facc7c3aba17b36481828a6109a9a3ccd54deabe0ef3e7b33759b2964e3024dc、生成源码b065ff0b3feaa3ecc6865c8992432530ceb3d1f57c785ae8252fcff352ebb789保持原字节。
- 最新完整离线392/392；最终原始实验93/93、归档131/131哈希一致，62个冻结源码文件复核一致。没有用旧通过数代替改代码后的新验证；本次冻结后未修改算法/测试源码。
- 真实Docker公开环境、dev23诊断和正式生成均实际执行。A/C/D/E全20例实际前缀阶段与快照完全相等，正式每例只执行选中分支。100条候选选择、80条路由均从序列化状态复现，无越界提交和记录中的四元资源超限。
- B8恢复逐条核对原37个事件与预算，只补最终公开测试，没有模型HTTP请求，恢复前后原账本SHA相同。新B20的前7例及B8状态与原来源完全一致。
- 全100预测先封存，随后独立Docker官方harness5.0.2评测。实际85个非空补丁容器任务及15个空补丁状态均保留，5份官方报告、provenance及100条evaluated_records通过来源校验；判分新增模型调用0。
- 全正式434请求真实指纹均符合批准的bc19ba97cbe016479903222bb1578db6。模型使用批准别名映射和逐请求指纹监测，immutable_version=false，不能声称锁定不可变模型快照。

正式请求中67次finish_reason=length（A38、B0、C1、D7、E21）属于已冻结单响应长度上限，不是API账户/usage额度耗尽。保留原响应、候选及费用，不据结果调高预算。

## 校准与局限

dev23全体记录保留，17例eligible、13对有效独立配对标签；九规则网格按事前平局顺序选0.75/0.75、E匹配8/17。重复率严格阈值在两候选下不可达，已明确关闭该规则。冻结只是弱证据预注册启发式，不证明完整路由价值；D2可达性单列说明缺项仍披露，不回写历史。

官方判分的5组Requests测试均按1800秒上限处理，主结果保留实际异常。其他missing_module/no_tests_collected等是harness含糊信号，不必然证明纯环境故障。已做一个事后日志语义抽查：A组Flask的“no tests ran”来自测试前git diff打印的文档示例，实际测试窗口已执行且有目标断言失败，属于诊断误触发证据；原主标签未修改。详见 `manual_log_window_spotcheck_A_flask.json`。因此不能把主报告的所有非resolved视为补丁逻辑错误，亦不能称异常识别已全面可靠。

当前只完成用户指定的一次描述性研究，没有三重复推断、置信区间、显著性/非劣结论；没有完整消融、多预算/阈值/步数敏感性，也没有全面人工语义审查。这些不因五组判分完成而自动完成，RQ4只补充了一个诊断误触发个案。

## 逐仓库记录

下表均为指定样本的明确解决数，异常和未提交仍在各仓库分母；详细状态见原JSON。

| 仓库 | 每组样本数 | A | B | C | D | E |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(repo_rows)}

## 交接与产物

全部新产物在 `runs/test20_resume_20261112_02/`。主要文件为 `formal_generation_freeze_manifest.json`、`formal_scoring_completed.json`、`sealed_generation_selection_audit.json`、`final_cost_audit.json`、`formal_result_audit.json`、`test20_single_run_summary.json`、`test20_uniform_off_peak_comparison.json`、`final_validation.json`。

实际执行配置字节不回写；新的非执行交接副本是 `configs/test20_inactive_20261112_02.json`（live_authorized=false），不是实际实验配置。主proposal继续pending/false。剩余额度和历史live=true不授权自动重跑、新tag或新模型请求。

活动Docker数据仍在D:/DockerData/swe-repair-20261111/DockerDesktopWSL。两份11月11日旧停机备份在E:/DockerBackups下，它们不是当前全镜像数据的完整备份。项目证据归档目标是E:/DockerBackups/project-session-20261112-02；最终CRC/SHA和实际关停字段见SESSION_SAVED.json，未生成该文件前不声称归档已核验。没有安排系统关机；用户临时停机指令已取消。
'''
    path=ROOT/'docs/test20五组一次实验报告_20261112.md'
    with path.open('x',encoding='utf-8') as f:f.write(report)
    outcome={'state':'completed_with_evaluation_errors','authorized_model_scope_completed':True,
        'dev_calibration_and_freeze_completed':True,'formal_predictions':100,'official_evaluation_audit_rows':100,
        'official_nonempty_patch_tasks':85,'empty_patch_outcomes':15,'resolved_counts':{a:summary['primary'][a]['resolved'] for a in 'ABCDE'},
        'evaluation_errors':26,'all_semantic_verdicts_known':False,'new_authorization_required_for_any_repeat_or_new_paid_scope':True,
        'inactive_config':inactive.relative_to(ROOT).as_posix(),'actual_execution_config':'configs/test20_frozen_20261112_01.json',
        'report':path.relative_to(ROOT).as_posix(),'report_sha256':sha(path),'system_shutdown_scheduled':False,
        'at':datetime.now(timezone.utc).isoformat()}
    write(OUT/'final_outcome.json',outcome)
    entry='\n\n## 2026-11-12 本轮正式流程完成\n\n20例五组一次100条预测及5组独立官方评测/100条审计记录完成，明确解决A/B/C/D/E=7/7/10/7/8；另有26条评测异常，未合并成真正未解决。全100预测先封存后判分，17.86646022CNY累计估算、pending=null，E低谷完整策略3.56686990CNY/新增1.94690578CNY。详见 docs/test20五组一次实验报告_20261112.md 及 runs/test20_resume_20261112_02/final_outcome.json。新的非执行交接副本 configs/test20_inactive_20261112_02.json 为live_authorized=false，原冻结执行配置/主proposal字节不回写；剩余额度不授权任何自动新请求或重复。收尾关停与归档以实际shutdown_audit.json和SESSION_SAVED.json为准。\n'
    for target in ('AGENTS.md','docs/实验记录.md','docs/恢复执行与断点交接_20261112.md','docs/正式实验续跑与结果_20261112.md'):
        with (ROOT/target).open('a',encoding='utf-8') as f:f.write(entry)
    with (ROOT/'README.md').open('a',encoding='utf-8') as f:f.write('\n\n本轮20例五组一次的最终结果、费用及评测限制见 [实验报告](docs/test20五组一次实验报告_20261112.md)；当前非执行交接配置为 `configs/test20_inactive_20261112_02.json`，不得据历史live标记重跑。\n')
    print(json.dumps({'report':str(path),'state':outcome['state'],'resolved_counts':outcome['resolved_counts']},ensure_ascii=False))
if __name__=='__main__':main()
