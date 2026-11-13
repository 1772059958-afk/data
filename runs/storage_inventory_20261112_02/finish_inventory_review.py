"""Add evidence-based retention decisions; no deletion or experiment execution."""
from pathlib import Path
from collections import Counter
from datetime import datetime
import csv,hashlib,json,shutil,zipfile,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_new(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def main():
    previous=read(ROOT/'runs/test20_resume_20261112_02/artifact_manifest.json')
    latest=read(ROOT/'runs/test20_final_handoff_20261112_01/artifact_manifest.json')
    index={r['path']:r for r in latest['files']}
    changed=[r['path'] for r in previous['files'] if r['path'] in index and r['sha256']!=index[r['path']]['sha256']]
    missing=[r['path'] for r in previous['files'] if r['path'] not in index]
    archive_review={'method':'Compare inventories from two already verified ZIP archives; no new evaluation or model request.',
        'old_archive':'E:/DockerBackups/project-session-20261112-02/project-session-20261112-02.zip',
        'new_archive':'E:/DockerBackups/project-final-20261112-01/project-final-20261112-01.zip',
        'old_inventory_sha256':sha(ROOT/'runs/test20_resume_20261112_02/artifact_manifest.json'),
        'new_inventory_sha256':sha(ROOT/'runs/test20_final_handoff_20261112_01/artifact_manifest.json'),
        'old_files_checked':len(previous['files']),'missing_paths':missing,'changed_paths':changed,
        'identical_duplicate':not missing and not changed,'recommendation':'Preserve both historical versions for now. Latest archive covers the paths but five files differ; do not treat equal path coverage as identical backups.'}
    write_new(OUT/'archive_version_comparison.json',archive_review)
    inv=read(OUT/'inventory.json')
    for row in inv['rows']:
        if row['category']=='较早项目证据归档':
            row['suggestion']='暂保留历史版本'
            row['prerequisite']='新旧归档同路径覆盖完整，但5个文件版本不同，不能直接按重复副本删除'
    inv['archive_version_review']='archive_version_comparison.json'
    inv['reviewed_at_local']=datetime.now().isoformat(timespec='seconds')
    inv['action_priority']=[
        {'priority':1,'path':'D:/CodexExperimentCache/test20_20261111','logical_gib':14.844,
         'kind':'可重建下载、公开源码与依赖缓存','action':'后续获得清理指令后可作为优先候选，保留来源/哈希记录，离线重建将需要重新下载'},
        {'priority':2,'path':str(ROOT/'work'),'logical_gib':round(inv['project_directory_bytes']['work']/1024**3,3),
         'kind':'PPT等构建与预览副本','action':'新PPT及构建源已另存docs/deliverables；核对各子目录所需源文件均已另存后可分项清理'},
        {'priority':'保留','path':'D:/DockerData/swe-repair-20261111/DockerDesktopWSL','kind':'活动Docker卷','action':'不直接删除VHDX，不运行全局prune'},
        {'priority':'保留','path':'E:/DockerBackups','kind':'历史冷备与不同时间点的项目归档','action':'保留恢复点；项目ZIP不包含当前77镜像的完整VHDX'},
        {'priority':'保留','path':str(ROOT/'runs'),'kind':'实验数据与审计','action':'已取消设置也只保留，不作后续评测/分析或批量删除'}]
    (OUT/'inventory.json').write_text(json.dumps(inv,ensure_ascii=False,indent=2),encoding='utf-8')
    with (OUT/'large_files.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(inv['rows'][0]));writer.writeheader();writer.writerows(inv['rows'])
    md=(OUT/'清理准备清单.md').read_text(encoding='utf-8')
    md=md.replace('优先核验重复后清理：核对最新归档包含旧证据且SHA有效后，才可去掉旧副本',
        '暂保留历史版本：新旧归档覆盖相同路径，但5个文件的版本不同，不能直接按重复副本删除')
    md=md.replace('建议先清理可重建下载缓存及已核验重复归档，再讨论历史VHDX备份',
        '建议先考虑可重建下载缓存和已另存源文件的构建副本；不同版本项目归档及历史VHDX备份暂保留')
    md+='\n## 清理准备结论\n\n'
    md+='| 顺序 | 对象 | 逻辑大小 | 本次决定 |\n|---|---|---:|---|\n'
    md+='| 1 | D盘实验下载/源码/依赖缓存 | 14.844GiB | 可回收候选，下次重建需重新下载 |\n'
    md+=f'| 2 | C盘项目work构建/渲染目录 | {inv["project_directory_bytes"]["work"]/1024**3:.3f}GiB | 核对源文件另存后可分项清理 |\n'
    md+='| 保留 | D盘活动Docker主数据卷 | 71.136GiB | 当前77镜像，不直接删除VHDX |\n'
    md+='| 保留 | E盘两份旧停机备份，含两个main卷 | 31.344GiB | 旧恢复点，不等于当前镜像全集 |\n'
    md+='| 保留 | E盘两个项目证据ZIP | 1.403GiB | 5个文件版本不同，非完全重复 |\n'
    md+='\n两个项目归档比对了旧清单4045个文件路径，无缺失路径，但下列文件的SHA不同：\n\n'
    md+=''.join('- `'+name+'`\n' for name in changed)
    md+='\n项目ZIP仅备份项目证据，未备份活动VHDX。C盘实验runs目录约3.345GiB保留；未发现已扫描C盘实验目录中≥100MiB的单个普通文件，空间主要由多份小文件累计。新PPT的可复现构建源保存在docs/deliverables/结题汇报_20261112_source，最终PPT和notes均已留在交付目录。\n\n本次删除0文件、启动0实验容器、追加0模型请求。清单是后续清理依据，尚未执行任何清理。\n'
    (OUT/'清理准备清单.md').write_text(md,encoding='utf-8')
    write_new(ROOT/'runs/storage_inventory_20261112_01/SUPERSEDED.json',{'current_inventory':'runs/storage_inventory_20261112_02',
        'reason':'Explicit actual Windows Docker path and project/cache directory totals added; use second inventory and its retention review.'})
    print(json.dumps({'listed_files':inv['listed_files'],'archive_identical':archive_review['identical_duplicate'],'archive_changed_paths':changed,'deleted':0},ensure_ascii=False))
if __name__=='__main__':main()
