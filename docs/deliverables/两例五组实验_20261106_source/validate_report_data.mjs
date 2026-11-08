import fs from 'node:fs/promises';
const source=process.argv[2]??new URL('./report_data.json',import.meta.url);
export function validateReportData(data){
  if(data.complete!==true)throw new Error('实验汇报数据尚未完成，拒绝导出');
  if(data.mode!=='pilot')throw new Error('本轮汇报必须保留pilot身份');
  if(data.instances?.length!==2||data.results?.length!==10)throw new Error('必须保留两例、五组共10格结果');
  const expected=new Set(data.instances.flatMap(id=>'ABCDE'.split('').map(arm=>`${id}/${arm}`)));
  for(const record of data.results){
    const key=`${record.instance_id}/${record.arm}`;
    if(!expected.delete(key))throw new Error(`重复或范围外结果 ${key}`);
    if(typeof record.verdict!=='string'||typeof record.route!=='string')throw new Error(`缺结果状态 ${key}`);
    if(record.resolved!==null&&typeof record.resolved!=='boolean')throw new Error(`非法resolved ${key}`);
  }
  if(expected.size)throw new Error('结果不完整');
  if(data.arm_costs?.length!==5||data.arm_costs.some(r=>!Number.isFinite(r.policy_cny)||!Number.isFinite(r.new_cny)))throw new Error('缺五组完整/新增成本');
  if(data.offline.passed!==data.offline.total||!Number.isInteger(data.offline.total))throw new Error('缺最终离线验证结果');
  if(data.sources_by_slide?.length!==10||data.sources_by_slide.some(r=>!Array.isArray(r)||!r.length))throw new Error('缺逐页来源');
  for(const key of ['summary','completion','environment_rows','interface_lines','totals','failure_example','candidate_calibration','next_steps'])if(data[key]===null)throw new Error(`缺事实 ${key}`);
  return data;
}
if(process.argv[1]&&new URL('file:///'+process.argv[1].replaceAll('\\','/')).href===import.meta.url){
  const data=validateReportData(JSON.parse((await fs.readFile(source,'utf8')).replace(/^\uFEFF/,'')));
  console.log(JSON.stringify({validated:true,mode:data.mode,cells:data.results.length,arms:data.arm_costs.length}));
}
