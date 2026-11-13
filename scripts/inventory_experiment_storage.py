"""Read-only C/D/E experiment storage inventory; never deletes or hashes volumes."""
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import csv,json,os,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/storage_inventory_20261112_02'
THRESHOLD=100*1024**2
def category(p):
    s=str(p).replace('\\','/').lower()
    if '/dockerdata/swe-repair-20261111/' in s:return '活动Docker数据','保留','当前77镜像所在活动卷，旧冷备不覆盖当前全集'
    if '/dockerbackups/swe-repair-' in s:return '历史停机备份','待复核备份保留策略','先确认无需旧恢复点，不能用它替代当前活动卷备份'
    if '/project-final-20261112-01/' in s:return '最新完整项目证据归档','保留','4227文件CRC及逐项SHA已验证，凭据排除'
    if '/project-session-20261112-02/' in s:return '较早项目证据归档','优先核验重复后清理','核对最新归档包含旧证据且SHA有效后，才可去掉旧副本'
    if '/official_oci_20261112/' in s:return '官方镜像下载缓存','可回收候选','确认当前镜像可用且不再离线重建后可删缓存，不能删除活动VHDX'
    if '/codexexperimentcache/' in s:return '公开源码或依赖缓存','可回收候选','会增加下次重建下载时间，先保留来源及哈希记录'
    if '/dockerdesktopdata/' in s or '/appdata/local/docker/' in s:return '旧Docker路径待确认','暂勿清理','先核对Docker设置和迁移审计，排除活动卷或路径链接'
    if '/dustbin/' in s or '/reports/' in s or '/data/' in s:return '受保护实验原件或数据','保留','原始93及归档131字节保护，不按缓存处理'
    if '/work/' in s:return '项目构建和预览中间文件','可回收候选','最终PPT及来源已保存后，可清理构建副本与预览'
    if '/runs/' in s:return '实验运行与审计证据','保留','原始预测、矩阵、日志、账本、manifest及判分来源保留'
    return '实验相关性待确认','暂勿清理','仅有路径关联，尚未证明可删除'
def main():
    OUT.mkdir(exist_ok=False)
    roots=[ROOT,Path('D:/CodexExperimentCache/test20_20261111'),Path('D:/DockerData/swe-repair-20261111'),
        Path('D:/DockerDesktopData/wsl'),Path('D:/docker images'),Path('E:/DockerBackups'),
        Path('C:/Users/remil/AppData/Local/Docker/wsl')]
    rows=[];summary=[];errors=[];seen=set();project_dirs=defaultdict(int);cache_dirs=defaultdict(int)
    for root in roots:
        count=total=large=0
        if not root.exists():summary.append({'root':str(root),'exists':False});continue
        for directory,dirs,files in os.walk(root,followlinks=False,onerror=lambda e:errors.append(str(e))):
            dirs[:]=[d for d in dirs if d not in ('.git','node_modules','__pycache__') and not (Path(directory)/d).is_symlink()]
            for name in files:
                p=Path(directory)/name
                if p.is_symlink() or p.name.startswith('.env'):continue
                try:s=p.stat()
                except OSError as e:errors.append(str(e));continue
                count+=1;total+=s.st_size
                if root==ROOT:project_dirs[p.relative_to(ROOT).parts[0]]+=s.st_size
                if root==Path('D:/CodexExperimentCache/test20_20261111'):cache_dirs[p.relative_to(root).parts[0]]+=s.st_size
                if s.st_size<THRESHOLD and p.suffix.lower()!='.vhdx':continue
                key=str(p.resolve()).casefold()
                if key in seen:continue
                seen.add(key);large+=s.st_size
                kind,action,reason=category(p)
                rows.append({'drive':p.drive,'path':str(p),'bytes':s.st_size,'GiB':round(s.st_size/1024**3,4),
                    'last_write_local':datetime.fromtimestamp(s.st_mtime).isoformat(timespec='seconds'),
                    'category':kind,'suggestion':action,'prerequisite':reason,'reparse_or_sparse_allocation_not_measured':True})
        summary.append({'root':str(root),'exists':True,'files_scanned':count,'logical_bytes':total,'listed_logical_bytes':large})
    rows.sort(key=lambda r:r['bytes'],reverse=True)
    volumes={d:{'total_bytes':shutil.disk_usage(d+':/').total,'free_bytes':shutil.disk_usage(d+':/').free} for d in 'CDE'}
    result={'at_local':datetime.now().isoformat(timespec='seconds'),'threshold_bytes':THRESHOLD,'listed_files':len(rows),
        'listed_logical_bytes':sum(r['bytes'] for r in rows),'rows':rows,'roots':summary,'volumes':volumes,
        'read_only':True,'files_deleted':0,'scope':'Known project, experiment cache, Docker data/legacy paths and E experiment backup roots. Unrelated user directories were not scanned.',
        'size_note':'Logical file lengths, not allocated space. VHDX may be sparse or contain duplicates; totals are not guaranteed reclaimable space.',
        'project_directory_bytes':dict(project_dirs),'download_cache_directory_bytes':dict(cache_dirs),
        'scan_errors':errors}
    (OUT/'inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    with (OUT/'large_files.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['path']);writer.writeheader();writer.writerows(rows)
    md='# C、D、E盘实验大文件与清理准备\n\n盘点时间：'+result['at_local']+'。未删除文件，未启动Docker。扫描项目、实验缓存、Docker活动/旧路径及E盘实验备份目录；没有扫描其他无关用户目录。逐项列出≥100MiB文件，另列全部VHDX。大小按逻辑长度计算，稀疏卷的实际占用和可回收量可能更小。\n\n'
    md+='| 盘符 | 当前可用/GiB |\n|---|---:|\n'+''.join(f'| {d} | {v["free_bytes"]/1024**3:.2f} |\n' for d,v in volumes.items())
    md+='\n| 大小/GiB | 文件 | 类型 | 清理建议及前提 |\n|---:|---|---|---|\n'
    for r in rows:md+=f'| {r["GiB"]:.4f} | `{r["path"]}` | {r["category"]} | {r["suggestion"]}：{r["prerequisite"]} |\n'
    md+='\n完整清单见同目录large_files.csv和inventory.json。建议先清理可重建下载缓存及已核验重复归档，再讨论历史VHDX备份；活动D盘卷、原始93文件、归档131文件和实验审计证据保留。删除前需另行明确授权，不能把逻辑长度合计视为保证可释放空间。\n\n目录总量（含小文件）\n\n'
    for s in summary:
        if s.get('exists'):md+=f'- `{s["root"]}`：{s["logical_bytes"]/1024**3:.3f}GiB，{s["files_scanned"]}个文件。\n'
    md+='\nC盘项目目录分项（含小文件）\n\n'
    for name,size in sorted(project_dirs.items(),key=lambda v:v[1],reverse=True):
        if size>=10*1024**2:md+=f'- `{ROOT/name}`：{size/1024**3:.3f}GiB。'+('构建/渲染副本，完成交付后可核验清理。' if name=='work' else '实验原件和环境分开核对，勿直接整目录删除。')+'\n'
    md+='\nD盘下载缓存分项（含小文件）\n\n'
    for name,size in sorted(cache_dirs.items(),key=lambda v:v[1],reverse=True):md+=f'- `{Path("D:/CodexExperimentCache/test20_20261111")/name}`：{size/1024**3:.3f}GiB。\n'
    if errors:md+='\n未能读取的路径：\n'+''.join('- '+e+'\n' for e in errors)
    (OUT/'清理准备清单.md').write_text(md,encoding='utf-8')
    print(json.dumps({'listed_files':len(rows),'volumes_free_gib':{d:round(v['free_bytes']/1024**3,2) for d,v in volumes.items()},'largest':rows[:7],'scan_errors':errors},ensure_ascii=False))
if __name__=='__main__':main()
