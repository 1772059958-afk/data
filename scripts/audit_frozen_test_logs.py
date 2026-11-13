"""Read-only reparse of sealed TEST logs, inside the frozen scoring image.

Never changes official reports. Reference test names stay evaluation-only.
"""
from pathlib import Path
from collections import Counter
import ast, hashlib, inspect, json, re
from swebench.types import TestSpec
import swebench.harness.grading as grading
import swebench.harness.infra_failure as infra
from swebench.harness.log_parsers import PARSER_REGISTRY
from swebench.harness.constants import START_TEST_OUTPUT, END_TEST_OUTPUT

ROOT=Path('/workspace')
OUT=ROOT/'runs/dev_supplement_20261112_02'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def names(v):return ast.literal_eval(v) if isinstance(v,str) else v

def main():
    freeze=read(ROOT/'runs/test20_resume_20261112_02/formal_generation_freeze_manifest.json')
    for item in freeze['artifacts']:assert sha(ROOT/item['path'].replace('\\','/'))==item['sha256']
    rows=[]
    for arm,tag in freeze['tags'].items():
        folder=ROOT/'runs'/tag
        dataset={r['instance_id']:r for r in read(folder/'scoring/evaluation_dataset.json')}
        original={r['instance_id']:r for r in map(json.loads,(folder/'evaluated_records.jsonl').read_text().splitlines())}
        for iid in freeze['instances']:
            r=dataset[iid];log=folder/'controller/logs/run_evaluation'/tag/(tag+'-'+arm)/iid/'test_output.txt'
            entry={'arm':arm,'instance_id':iid,'primary_status':original[iid]['status']}
            if not log.exists():
                entry.update(scoped_status='no_log',log=None);rows.append(entry);continue
            spec=TestSpec(instance_id=iid,image=r['image'],eval_script_list=[],repo=r['repo'],version=r['version'],
                FAIL_TO_PASS=names(r['FAIL_TO_PASS']),PASS_TO_PASS=names(r['PASS_TO_PASS']),log_parser=r['log_parser'],eval_type=r['eval_type'])
            text=log.read_text(errors='replace');parts=text.split(START_TEST_OUTPUT)
            report=read(log.parent/'report.json') if (log.parent/'report.json').exists() else None
            # Reproduce the official parser, independently from the saved report.
            official_map,official_found=grading.get_logs_eval(spec,str(log))
            entry.update(log=str(log.relative_to(ROOT)),log_sha256=sha(log),start_marker_count=len(parts)-1,
                official_found=official_found,official_parsed_tests=len(official_map),whole_log_classification=infra.classify_text(text))
            if len(parts)!=2 or END_TEST_OUTPUT not in parts[1]:
                entry.update(scoped_status='incomplete_or_ambiguous_test_window',scoped_classification=None)
                rows.append(entry);continue
            window=parts[1].split(END_TEST_OUTPUT)[0]
            sm=PARSER_REGISTRY[spec.log_parser](window,spec)
            exit_code=grading.parse_test_exit_code(text)
            missing_f=[t for t in spec.FAIL_TO_PASS if grading._resolve_case(t,sm) is None]
            missing_p=[t for t in spec.PASS_TO_PASS if grading._resolve_case(t,sm) is None]
            test_report=grading.get_eval_tests_report(sm,{'FAIL_TO_PASS':spec.FAIL_TO_PASS,'PASS_TO_PASS':spec.PASS_TO_PASS})
            if not sm:status='no_named_test_results'
            elif missing_f or missing_p:status='incomplete_expected_test_coverage'
            elif exit_code not in (0,None) and not any(v in ('FAILED','ERROR') for v in sm.values()):status='exit_status_inconsistent'
            else:status='resolved' if grading.get_resolution_status(test_report)=='RESOLVED_FULL' else 'unresolved'
            error_lines=[x[:600] for x in window.splitlines() if x.startswith(('ERROR','E ','FAILED','INTERNALERROR'))]
            summaries=[x.strip()[:600] for x in window.splitlines() if re.search(r'\d+ (?:passed|failed|error|errors)|collected \d+ items',x)]
            matches=[]
            for reason,tier,pattern in infra.INFRA_FAILURE_SIGNATURES:
                found=list(re.finditer(pattern,text,re.M))
                if found:
                    matches.append({'reason':reason,'tier':tier,'total_matches':len(found),
                        'inside_window':len(list(re.finditer(pattern,window,re.M))),
                        'first_line':text[:found[0].start()].count('\n')+1})
            entry.update(scoped_status=status,scoped_classification=infra.classify_text(window),
                exit_code=exit_code,parsed_tests=len(sm),missing_expected_f2p=missing_f,missing_expected_p2p=missing_p,
                f2p={k:len(v) for k,v in test_report['FAIL_TO_PASS'].items()},p2p={k:len(v) for k,v in test_report['PASS_TO_PASS'].items()},
                summary_lines=summaries[-8:],error_lines=error_lines[:12],classification_signatures=matches,
                start_line=text[:text.index(START_TEST_OUTPUT)].count('\n')+1,
                official_report_sha256=sha(log.parent/'report.json') if report else None)
            rows.append(entry)
    result={'kind':'supplementary_read_only_scoped_log_audit_not_replacement_primary',
        'scoring_image':'sha256:1f43c83b3d3c631d37af54a19828df269accd045a22c62c0aab5b2bfa713726f',
        'official_grading_source_sha256':hashlib.sha256(inspect.getsource(grading).encode()).hexdigest(),
        'official_infra_source_sha256':hashlib.sha256(inspect.getsource(infra).encode()).hexdigest(),
        'script_sha256':sha(__file__),'source_freeze_sha256':sha(ROOT/'runs/test20_resume_20261112_02/formal_generation_freeze_manifest.json'),
        'method':'Exactly one complete marker window; unchanged official repo parser and expected test names; no whole-log fallback. Missing named expected tests remain unknown. Original labels untouched.',
        'primary_counts':dict(Counter(r['primary_status'] for r in rows)),
        'scoped_counts':dict(Counter(r['scoped_status'] for r in rows)),'rows':rows}
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
