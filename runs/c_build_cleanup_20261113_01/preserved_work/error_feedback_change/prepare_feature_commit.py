from pathlib import Path
import io
import subprocess
import tarfile

ROOT = Path.cwd()
BASE = ROOT / 'work/error_feedback_change'
OUT = BASE / 'feature_head'


def head(name):
    return (BASE / 'head' / name).read_text(encoding='utf-8')


def save(name, value):
    dest = OUT / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(value.replace('\r\n', '\n').encode('utf-8'))


name = 'src/swe_repair/state.py'
save(name, (ROOT / name).read_text(encoding='utf-8'))
name = 'src/swe_repair/experiment.py'
save(name, head(name).replace('feedback = [r.to_dict()', 'feedback = [r.prompt_view()'))
name = 'src/swe_repair/prefix.py'
save(name, head(name).replace('return "fail", _strip_rc(out)[:300]', 'return "fail", _strip_rc(out)'))
name = 'configs/proposal_v1.json'
save(name, head(name).replace('  "config_version": "proposal_aligned_v1",',
    '  "config_version": "proposal_aligned_v1",\n  "prompt_version": "proposal_v1_error_feedback_20261030",'))
name = 'docs/实验协议_开题对齐.md'
paragraph = (ROOT / name).read_text(encoding='utf-8').split('2026-10-30 错误反馈细化：', 1)[1]
save(name, head(name).rstrip() + '\n\n2026-10-30 错误反馈细化：' + paragraph)

name = 'src/swe_repair/interact.py'
text = head(name)
current = (ROOT / name).read_text(encoding='utf-8')
text = text.replace('from .llm import DeepSeekClient, parse_tool_arguments, tool_message',
    'from .llm import DeepSeekClient, parse_tool_arguments, tool_message\n'
    'from .feedback import error_evidence, failure_feedback, read_failure_log, LOG_REF, ToolFeedback')
intro = current.split('Error feedback selects', 1)[1].split('\n1. analyse', 1)[0]
text = text.replace('1. analyse', 'Error feedback selects' + intro + '\n1. analyse', 1)
text = text.replace('"description": "Read a line range of one file."',
    '"description": "Read source lines or a captured public log:<sha256>; follow the returned cursor for more log text."')
text = text.replace('"path": {"type": "string", "description": "path relative to /testbed"}',
    '"path": {"type": "string", "description": "path relative to /testbed, or an issued log:<sha256> reference"}')
text = text.replace('"end": {"type": "integer", "description": "1-based last line"},',
    '"end": {"type": "integer", "description": "1-based last line"},\n'
    '                        "offset": {"type": "integer", "description": "log only: character offset in the first line, default 0"},')
start, stop = text.index('def execute_tool('), text.index('    if name == "search_symbol":', text.index('def execute_tool('))
new_start, new_stop = current.index('def validate_tool_arguments('), current.index('    if name == "search_symbol":', current.index('def execute_tool('))
text = text[:start] + current[new_start:new_stop] + text[stop:]
start = text.index('        status, detail, raw = run_public_tests(box, targets)')
stop = text.index('\n\n    return f"unknown tool', start)
new_start = current.index('        tested = run_public_tests(box, targets)')
new_stop = current.index('\n\n    return f"unknown tool', new_start)
text = text[:start] + current[new_start:new_stop] + text[stop:]
text = text.replace("        detail = validated.raw_output or '; '.join(f.message_head for f in validated.failures)",
    "        detail = (failure_feedback(validated.failures[-1]) if validated.failures\n"
    "                  else error_evidence(validated.raw_output))")
old = '''                    else:
                        observation, progressed = execute_tool(box, name, args)
                    key = json.dumps'''
new = '''                    else:
                        checked_args, refusal = validate_tool_arguments(name, args)
                        if refusal:
                            observation, progressed = refusal, False
                        elif name == 'read_region' and checked_args['path'].startswith('log:'):
                            observation, progressed = read_failure_log(
                                state.failures.records + state.failures.tool_records,
                                checked_args['path'], checked_args['start'], checked_args['end'], checked_args.get('offset', 0))
                        else:
                            candidate = state.patches.best_candidate()
                            if name == 'run_test' and candidate is not None:
                                box.revert()
                                box.apply(candidate.diff)
                            checked = execute_tool(box, name, checked_args)
                            observation, progressed = checked
                            if isinstance(checked, ToolFeedback):
                                from dataclasses import replace
                                state.failures.tool_records.append(replace(checked.record,
                                    candidate_index=candidate.index if candidate else None))
                    key = json.dumps'''
assert old in text
text = text.replace(old, new)
save(name, text)

for name in ('src/swe_repair/feedback.py', 'tests/test_error_feedback.py', 'docs/错误反馈机制_20261030.md'):
    save(name, (ROOT / name).read_text(encoding='utf-8'))

snapshot = BASE / 'feature_validation'
snapshot.mkdir(exist_ok=True)
archive = subprocess.check_output(['git', 'archive', 'HEAD', 'src', 'scripts', 'tests', 'configs'])
with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
    stream.extractall(snapshot, filter='data')
for path in OUT.rglob('*'):
    if path.is_file():
        dest = snapshot / path.relative_to(OUT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
print('Prepared scoped feature tree without modifying working files or the Git index.')
