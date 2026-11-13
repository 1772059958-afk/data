"""Record user cancellation and final main-experiment handoff; no experiments."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def main():
    source=ROOT/'runs/dev_supplement_20261112_02';ledger_path=ROOT/'runs/test20_execution_20261111/batch_ledger.json'
    ledger=read(ledger_path);start=read(source/'ledger_at_start.json');assert ledger['pending'] is None
    assert ledger['records'][:len(start['records'])]==start['records']
    extra=ledger['records'][len(start['records']):]
    assert all(r['system_fingerprint']=='bc19ba97cbe016479903222bb1578db6' for r in extra)
    cost={'ledger_sha256':sha(ledger_path),'ledger_records':len(ledger['records']),
        'cumulative_estimate_cny':round(sum(r['cost_cny'] for r in ledger['records']),8),
        'cancelled_supplement_requests_already_booked':len(extra),
        'cancelled_supplement_estimate_cny':round(sum(r['cost_cny'] for r in extra),8),
        'pending':None,'billing':'usage-based estimate, not supplier payment or account balance'}
    cost['remaining_guard_cny']=round(100-cost['cumulative_estimate_cny'],8)
    assert cost['cumulative_estimate_cny']<=100
    write(OUT/'final_cost_audit.json',cost)
    freeze=read(ROOT/'runs/test20_resume_20261112_02/formal_generation_freeze_manifest.json')
    for a in freeze['artifacts']:assert sha(ROOT/a['path'])==a['sha256']
    snapshot=ROOT/'runs/test20_resume_20261112_01/formal_source_snapshot'
    manifest=read(snapshot/'manifest.json')
    for f in manifest['files']:assert sha(snapshot/f['path'])==f['sha256']
    preservation=read(source/'cancellation_preservation.log')
    assert preservation['experiments']['ok'] and preservation['archive']['ok']
    validation={'preservation_ok':True,'original_verified':93,'archive_verified':131,
        'formal_sealed_artifacts_unchanged':True,'formal_source_snapshot_files_verified':len(manifest['files']),
        'latest_offline_suite':'399/399 passed before supplemental execution; no subsequent generator/test changes',
        'offline_log_sha256':sha(ROOT/'runs/dev_supplement_preflight_20261112_03.log'),
        'preservation_log_sha256':sha(source/'cancellation_preservation.log')}
    write(OUT/'final_validation.json',validation)
    cancellation={'instruction':'取消所有补充设置，已有的不处理，直接进行后面的内容',
        'at':datetime.now(timezone.utc).isoformat(),'all_supplement_settings_cancelled':True,
        'no_further_scoring_or_analysis_of_supplement_settings':True,
        'incomplete_scoring_outputs_retained_not_accepted_as_results':True,
        'generic_api_breakpoint_string_is_not_evidence_of_actual_quota_exhaustion':True,
        'cooperative_stop_preceded_generic_breakpoint':'runs/dev_supplement_20261112_02/WORKFLOW_STOP.json',
        'new_model_calls_after_cancellation':0,'remaining_scope':'Main formal report, existing review artifacts, cost reconciliation, documentation and safe close only'}
    write(OUT/'USER_CANCELLED_SUPPLEMENT.json',cancellation)
    follow=ROOT/'runs/dev_supplement_finish_20261112_01'
    write(follow/'USER_CANCELLED.json',cancellation)
    report='''# 正式实验最终交接与补充设置取消

正式20例、A/B/C/D/E、一次重复已完成，100条预测均先封存后独立判分。原报告、预测、评测及其来源文件保持原字节；本文件追加当前费用和收尾状态。

| 组别 | 明确解决/20 | 真正未解决 | 空提交 | 评测异常 | 完整策略低谷成本/CNY |
|---|---:|---:|---:|---:|---:|
| A | 7 | 4 | 4 | 5 | 4.39227512 |
| B | 7 | 4 | 5 | 4 | 0.43171952 |
| C | 10 | 4 | 1 | 5 | 2.05192828 |
| D | 7 | 5 | 2 | 6 | 2.87039734 |
| E | 8 | 3 | 3 | 6 | 3.56686990 |

上述为封存的原官方主标签，26条异常不并入真正未解决。单次分层20例只作描述，不生成置信区间、显著性、非劣或随机稳定性结论。E按用户要求逐请求换算低谷成本；原时段金额及100元守卫不被换算覆盖。

用户随后先缩减、再取消全部补充设置，并明确“已有的不处理”。本次以最后指令为准：剩余模型设置不执行，两个已生成设置和一个未完成设置不再评测或分析；已短暂启动的补充判分被停止，部分日志不作为已验收成绩。所有既有数据和费用保留，不自动重试；之前的通用API/usage断点字符串源于用户停止守卫，不证明供应商额度耗尽。取消后只进行正式成果、费用与交接收尾。

正式100条的既有代码语义复核已完成，按49个实例内唯一补丁组（含空提交）覆盖；复核者是当前agent，不是外部真人签审。既有全量日志审计复核39条明确解决；12条原异常在实际测试窗口有完整失败证据，10条原未解决只有“全部通过”汇总而缺少可解析的逐测试结果，继续保留未知。5条Requests日志窗口因超时不完整，9条pytest记录缺少完整期望测试覆盖。全部审计都是补充证据，不回写原主标签。详见 runs/dev_supplement_20261112_02/review_only/semantic_review.json 和 formal_scoped_log_audit.json。

完整dev23校准与独立配对、正式冻结和五组判分已经完成；多预算、前缀/步数敏感性及新增真实消融因用户取消不作完成声明。先前已生成的DEV离线回放原件保留，不在取消后继续处理或纳入正式结论。重复信号关闭、D2事前可达性说明缺项及训练内弱证据等历史局限保留，不能补写成事前已审。

源码方面，本轮补充准备新增严格限定DEV diagnostic的跨配置同前缀契约与6项相关回归；正式源快照保持。最新已执行完整离线399/399，收尾复核原始93/93、归档131/131以及62个正式源快照文件一致。真实容器验证、付费生成和正式独立判分均有实物证据；已取消补充判分未完成，不能用离线通过数代替。

最终累计估算/保守记账为 **COST CNY/100CNY**（RECORDS条，pending=null），其中取消前补充模型已发生 EXTRA CNY/144请求；剩余守卫 REMAIN CNY。金额均为usage估算而非账单实付。所有144条补充响应指纹一致；没有新增模型重试或追加额度。

正式报告：docs/test20五组一次实验报告_20261112.md；当前权威收尾目录：runs/test20_final_handoff_20261112_01。所有旧live配置仅作历史，不授权续跑；主proposal及非执行交接副本保持pending/false和live_authorized=false。关停、归档是否核验以本目录shutdown_audit.json、SESSION_SAVED.json实际文件为准。保留D盘活动Docker卷及E盘旧冷备份；本轮项目证据归档不冒充新的全VHDX备份。没有安排系统关机。
'''.replace('COST',str(cost['cumulative_estimate_cny'])).replace('RECORDS',str(cost['ledger_records'])).replace('EXTRA',str(cost['cancelled_supplement_estimate_cny'])).replace('REMAIN',str(cost['remaining_guard_cny']))
    path=ROOT/'docs/正式实验最终交接_20261112.md'
    with path.open('x',encoding='utf-8') as f:f.write(report)
    note='\n\n## 2026-11-12 最终取消所有补充设置并收尾\n\n用户最新明确“取消所有补充设置，已有的不处理，直接进行后面的内容”。已停止补充模型及刚启动的补充判分；已生成和未完成设置均不继续评测/分析，原件及费用保留，不称补充实验全部完成。后续只做正式成果和费用/文档安全收尾，不新增正式或补充模型请求。正式100条原结果与来源封存不变；累计估算'+str(cost['cumulative_estimate_cny'])+'CNY/100CNY、'+str(cost['ledger_records'])+'条、pending=null。当前权威交接为 docs/正式实验最终交接_20261112.md 和 runs/test20_final_handoff_20261112_01/；旧live配置、剩余额度和旧调度器不能授权续跑。已有100条agent语义复核/全量日志审计与新补充设置区分；不能冒称外部真人签审或回写原主标签。关停/归档以该目录真实shutdown_audit.json及SESSION_SAVED.json为准。\n'
    for p in [ROOT/'AGENTS.md',ROOT/'docs/实验记录.md',ROOT/'docs/剩余工作执行与验收_20261112.md']:
        with p.open('a',encoding='utf-8') as f:f.write(note)
    outcome={'state':'formal_complete_supplements_cancelled_by_user','formal_predictions':100,
        'resolved_counts':{'A':7,'B':7,'C':10,'D':7,'E':8},'evaluation_errors':26,
        'report':str(path.relative_to(ROOT)),'report_sha256':sha(path),
        'inactive_config':'configs/test20_inactive_20261112_02.json','new_paid_authorization_required':True,
        'system_shutdown_scheduled':False,'supplement_settings_not_processed_after_cancellation':True}
    write(OUT/'final_outcome.json',outcome)
    print(json.dumps(cost,ensure_ascii=False))
if __name__=='__main__':main()
