"""Restore exact public Git identity only when official source blobs match."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("public_devprep_io", HERE / "environment/prepare_dev23_offline.py")
io = importlib.util.module_from_spec(spec)
spec.loader.exec_module(io)


class Preparation(io.Preparation):
    def __init__(self, *args):
        super().__init__(*args)
        self.owned_images = {}

    def guard(self):
        if (HERE / "WORKFLOW_STOP.json").exists():
            raise RuntimeError("workflow_stop_requested")
        return super().guard()

    def start(self, label, image):
        name = "test20prep-" + self.args.tag + "-" + hashlib.sha256(label.encode()).hexdigest()[:12]
        r, text = self.docker("name_absence", "inspect", "--type", "container", name, check=False)
        if r["exit_code"] == 0 or not io.explicit_container_absence(text, name):
            raise RuntimeError("cannot establish new container name absence")
        self.owned[name] = None
        self.owned_images[name] = image
        _, text = self.docker("start_public", "run", "-d", "--pull=never", "--network", "none",
                             "--name", name, "--label", "codex.test20.preparation=" + self.args.tag,
                             "--entrypoint", "/bin/bash", image, "-lc", "sleep infinity")
        self.owned[name] = text.strip()
        return name

    def clean(self, name):
        if name not in self.owned:
            return
        if self.owned[name] is None:
            time.sleep(2)
        r, text = self.docker("cleanup_identity", "inspect", "--type", "container", "--format",
            '{{.Id}} {{.Image}} {{index .Config.Labels "codex.test20.preparation"}}', name,
            check=False, cleanup=True, timeout=30)
        values = text.strip().split()
        if r["exit_code"] == 0:
            if (len(values) != 3 or values[1] != self.owned_images[name] or values[2] != self.args.tag
                    or (self.owned[name] is not None and values[0] != self.owned[name])):
                raise RuntimeError("container identity/ownership differs; refusing deletion")
            self.docker("cleanup_owned", "rm", "-f", values[0], cleanup=True, timeout=30)
        elif not io.explicit_container_absence(text, name):
            raise RuntimeError("cannot verify container identity or absence")
        r, text = self.docker("cleanup_absence", "inspect", "--type", "container", name,
                              check=False, cleanup=True, timeout=30)
        if r["exit_code"] == 0 or not io.explicit_container_absence(text, name):
            raise RuntimeError("container absence not verified")
        del self.owned[name]
        del self.owned_images[name]


def program(case):
    return '''import os,sys,json,hashlib,subprocess,importlib
expected=''' + repr(case["expected_public_files"]) + '''
root='/testbed'
def git(*args):
 return subprocess.check_output(['git']+list(args),cwd=root)
head=git('rev-parse','HEAD').decode().strip()
tree=git('rev-parse','HEAD^{tree}').decode().strip()
raw=git('ls-tree','-r','-z','HEAD');actual={}
for item in raw.split(b'\\0'):
 if item:
  meta,path=item.split(b'\\t',1);mode,kind,sha=meta.decode().split();actual[path.decode()]={'mode':mode,'git_blob_sha1':sha}
changed=[p for p in expected if p in actual and actual[p]['git_blob_sha1']!=expected[p]['git_blob_sha1']]
missing=len(set(expected)-set(actual));extra=len(set(actual)-set(expected))
mode_changes=sum(p in actual and actual[p]['mode']!=expected[p]['mode'] for p in expected)
clean=not git('status','--porcelain').strip()
assumed=sum(line[:1].islower() or line[:1]==b'S' for line in git('ls-files','-v').splitlines())
raw_source_mismatch=[]
suffixes=('.py','.pyx','.pxd','.pxi','.c','.cc','.cpp','.h','.hpp','.f','.f90','.sh','.toml','.cfg')
for path,identity in expected.items():
 if not path.lower().endswith(suffixes): continue
 full=os.path.join(root,path)
 try:
  if identity['mode']=='120000': data=os.fsencode(os.readlink(full))
  else:
   with open(full,'rb') as f: data=f.read()
  sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\\0'+data).hexdigest()
  if sha!=identity['git_blob_sha1']: raw_source_mismatch.append(path)
 except (IOError,OSError): raw_source_mismatch.append(path)
safe=not(changed or missing or extra or not clean or assumed or raw_source_mismatch)
result={'head':head,'tree':tree,'clean':clean,'public_blob_count':len(expected),'public_blob_mismatch_count':len(changed),'missing_public_paths':missing,'extra_tracked_paths':extra,'file_mode_differences':mode_changes,'assume_unchanged_or_sparse_entries':assumed,'raw_public_source_mismatch_count':len(raw_source_mismatch),'unknown_extra_path_names_exposed':False,'compiled_artifact_reuse_allowed':safe,'python':sys.version.split()[0]}
if sys.argv[1]=='after':
 safe=safe and head==''' + repr(case["base_commit"]) + ''' and tree==''' + repr(case["expected_tree"]) + ''' and mode_changes==0
 if safe:
  try:
   module=importlib.import_module(''' + repr(case["module"]) + ''')
   location=os.path.realpath(module.__file__)
   if not location.startswith(root+'/'): raise ValueError('subject import outside original checkout')
   result.update(module_file=location,module_version=str(getattr(module,'__version__',None)))
  except Exception as exc:
   safe=False;result['import_error_type']=type(exc).__name__
result['accepted']=safe
print('__PUBLIC_TEST20_IDENTITY__'+json.dumps(result))
sys.exit(0 if safe else 2)
'''


def identity(runner, container, case, source_program, phase):
    runner.docker("copy_public_identity", "cp", str(source_program), container + ":/tmp/public-tree-check.py")
    r, text = runner.shell(container, "identity_" + phase,
                            "cd /testbed && python /tmp/public-tree-check.py " + phase, check=False)
    line = next((s for s in reversed(text.splitlines()) if s.startswith("__PUBLIC_TEST20_IDENTITY__")), None)
    if line is None:
        raise RuntimeError("public identity program failed; preserved log " + r["log"])
    result = json.loads(line.removeprefix("__PUBLIC_TEST20_IDENTITY__"))
    if not result["accepted"]:
        raise RuntimeError("public source/metadata/import identity rejected; preserved log " + r["log"])
    return result


def prepare(runner, case, image, output):
    iid = case["instance_id"]
    result = {"instance_id": iid, "base_commit": case["base_commit"], "official_parent_image": image,
              "status": "not_prepared", "model_calls": 0, "test_assertions_modified": False}
    script = output / (iid + "_public_identity.py")
    with script.open("x", encoding="utf-8", newline="\n") as f:
        f.write(program(case))
    name = runner.start(iid + "_prepare", image)
    try:
        result["before"] = identity(runner, name, case, script, "before")
        source = Path(case["source_directory"]) / ".git"
        runner.docker("copy_exact_public_git", "cp", str(source), name + ":/tmp/public-base.git")
        runner.shell(name, "restore_exact_commit_and_modes",
            "cd /testbed && rm -rf .git && mv /tmp/public-base.git .git "
            "&& git config core.autocrlf false && git config core.filemode true "
            "&& git config core.symlinks true && git config remote.origin.url "
            + shlex.quote("https://github.com/" + case["repo"] + ".git")
            + " && git reset --hard HEAD && git clean -fdq")
        result["after_metadata_restore"] = identity(runner, name, case, script, "after")
        smoke, _ = runner.shell(name, "public_smoke", "cd /testbed && " + case["public_smoke_command"], check=False)
        result["public_smoke"] = smoke
        result["after_smoke"] = identity(runner, name, case, script, "after")
        if smoke["exit_code"]:
            result["status"] = "public_smoke_failed"
            return result
        runner.shell(name, "remove_own_identity_probe", "rm -f /tmp/public-tree-check.py")
        tag = "test20-prepared/" + iid.replace("__", "-") + ":" + runner.args.tag
        runner.docker("commit_exact_public_baseline", "commit", name, tag)
        _, text = runner.docker("prepared_image_id", "image", "inspect", tag, "--format", "{{.Id}}")
        prepared = text.strip()
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", prepared)
        result["prepared_candidate_image"] = prepared
    finally:
        runner.clean(name)
    name = runner.start(iid + "_fresh", prepared)
    try:
        result["fresh_identity"] = identity(runner, name, case, script, "after")
        smoke, _ = runner.shell(name, "fresh_public_smoke", "cd /testbed && " + case["public_smoke_command"], check=False)
        result["fresh_public_smoke"] = smoke
        result["fresh_after_smoke"] = identity(runner, name, case, script, "after")
        if smoke["exit_code"]:
            result["status"] = "fresh_public_smoke_failed"
            return result
        result.update(status="public_smoke_ready", image_id=prepared,
                      source_blob_contents_changed=False, exact_public_git_metadata_restored=True,
                      original_public_file_modes_restored=True, compiled_artifacts_rebuilt=False)
        return result
    finally:
        runner.clean(name)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tag", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--instances", nargs="+")
    args = p.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.tag)
    manifest_path = HERE / "test20_exact_git_tree_manifest_01.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sample = json.loads((ROOT / "runs/test20_preparation_20261111/instances.json").read_text(encoding="utf-8"))
    assert [r["instance_id"] for r in manifest["instances"]] == sample["instance_ids"]
    wanted = set(args.instances or sample["instance_ids"])
    assert wanted and wanted <= set(sample["instance_ids"])
    if not args.execute:
        print(json.dumps({"execute": False, "designated": 20, "selected": sorted(wanted), "model_calls": 0}))
        return 0
    imported = json.loads((HERE / "official_import_all20_01.json").read_text(encoding="utf-8"))
    assert imported["all_imported_image_ids_verified"] is True
    args.context = "desktop-linux"
    args.docker_data_host_path = Path(r"D:\DockerData\swe-repair-20261111\DockerDesktopWSL")
    output = HERE / "environment/test20_preparation_runs" / args.tag
    output.mkdir(parents=True, exist_ok=False)
    runner = Preparation(args, {"wheel_cache": r"D:\CodexExperimentCache\test20_20261111"}, output)
    rows, cleanup_errors = [], []
    try:
        for case in manifest["instances"]:
            if (HERE / "WORKFLOW_STOP.json").exists():
                break
            if case["instance_id"] not in wanted:
                continue
            try:
                row = prepare(runner, case, imported["expected_image_ids"][case["instance_id"]], output)
            except Exception as exc:
                row = {"instance_id": case["instance_id"], "base_commit": case["base_commit"],
                       "status": "preparation_error", "error_type": type(exc).__name__, "error": str(exc), "model_calls": 0}
            rows.append(row)
            with (output / (case["instance_id"] + ".json")).open("x", encoding="utf-8") as f:
                json.dump(row, f, indent=2)
                f.write("\n")
            if (runner.owned or "reserve" in row.get("error", "")
                    or "workflow_stop_requested" in row.get("error", "")):
                break
    finally:
        for name in list(runner.owned):
            try:
                runner.clean(name)
            except Exception as exc:
                cleanup_errors.append({"container": name, "error": str(exc)})
        runner.log.close()
        indexed = {r["instance_id"]: r for r in rows}
        rows = [indexed.get(r["instance_id"], {"instance_id": r["instance_id"], "status": "not_prepared"}) for r in manifest["instances"]]
        images = {r["instance_id"]: r["image_id"] for r in rows if r["status"] == "public_smoke_ready"}
        result = {"kind": "public_test20_exact_baseline_preparation", "designated": 20, "instances": rows,
                  "accepted_public_smoke_images": images, "all20_ready": len(images) == 20 and not cleanup_errors,
                  "manifest_sha256": io.digest(manifest_path), "script_sha256": io.digest(Path(__file__)),
                  "model_calls": 0, "hidden_patch_contents_read": False, "cleanup_errors": cleanup_errors,
                  "owned_containers_remaining": dict(runner.owned), "selection": "all preregistered20 retained"}
        for filename, data in [("summary.json", result), ("public_smoke_images.json", images)]:
            with (output / filename).open("x", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
    print(output / "summary.json")
    return 0 if len(images) == len(wanted) and not cleanup_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
