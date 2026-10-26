"""Reproducible offline check against a disposable clean L06 clone. No live calls."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
KIT=ROOT.parent/"paypilot-l06-eval"
SHARED=ROOT.parent/"paypilot-stand-shared"

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def checked(command,cwd,env=None):
    p=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,encoding="utf-8",errors="replace")
    if p.returncode:
        raise RuntimeError("Offline check failed: "+repr(command)+"\n"+p.stdout+p.stderr)
    return p.stdout+p.stderr

def main():
    prepared=json.loads((ROOT/"evidence/preparation-manifest.json").read_text(encoding="utf-8"))
    revision=prepared["repositories"]["paypilot-l06-eval"]["commit"]
    expected=sha(ROOT/"evals/sets/l06_security.jsonl")
    for path,digest in prepared["protected_datasets_sha256"].items():
        if sha(path)!=digest:raise RuntimeError("Earlier dataset changed: "+path)
    before=checked(["git","diff","--name-only"],KIT).strip()
    if before:raise RuntimeError("Tracked kit changes must be reviewed first")
    parent=Path(tempfile.gettempdir()).resolve()
    workspace=Path(tempfile.mkdtemp(prefix="hw5-step7-",dir=parent)).resolve()
    clone=workspace/"kit"
    project=workspace.name.lower()
    env=os.environ.copy()
    env.update(HW5_ENABLE_PAID_RUNS="",HW5_RUN_PREFLIGHT="",HW5_KIT_DIR=str(clone),PYTHONPATH=str(clone),
               PYTHONDONTWRITEBYTECODE="1",PYTHONUTF8="1",STAND_DIR=str(SHARED),
               EVAL_STAND_URL="http://host.docker.internal:8000")
    docker_started=False
    try:
        checked(["git","clone","--local","--no-hardlinks",str(KIT),str(clone)],ROOT)
        checked(["git","checkout","--detach",revision],clone)
        original=checked(["git","status","--porcelain"],clone).strip()
        if original:raise RuntimeError("Clone is not clean before adding test input")
        shutil.copyfile(ROOT/"evals/sets/l06_security.jsonl",clone/"sets/l06_security.jsonl")
        if sha(clone/"sets/l06_security.jsonl")!=expected:raise RuntimeError("Copy hash mismatch")
        docker_started=True
        dry=checked(["docker","compose","-p",project,"run","--rm","-T","eval",
                     "--set","l06_security","--gate","all","--dry-run"],clone,env)
        (ROOT/"evidence/clean-clone-step7-dry-run.txt").write_bytes(dry.encode("utf-8"))
        test_code=(
          "import os,pathlib,loader,runner,unittest;"
          "p=pathlib.Path(os.environ['HW5_KIT_DIR']).resolve();"
          "assert pathlib.Path(loader.__file__).resolve().parent==p;"
          "assert pathlib.Path(runner.__file__).resolve().parent==p;"
          "print('Native loader/runner imported from verified clean clone',flush=True);"
          "unittest.main(module=None,argv=['step7','discover','-s','tests','-p','test_*.py','-v'])")
        tests=checked([sys.executable,"-c",test_code],ROOT,env)
        (ROOT/"evidence/clean-clone-step7-tests.txt").write_bytes(tests.encode("utf-8"))
        tracked=checked(["git","status","--porcelain","--untracked-files=no"],clone).strip()
        if tracked:raise RuntimeError("Native tracked files were modified")
        match=re.search(r"Ran (\d+) tests",tests)
        skip=re.search(r"OK \(skipped=(\d+)\)",tests)
        if not match or not skip:raise RuntimeError("Unexpected offline test summary")
        skipped=int(skip.group(1))
        preflight_skips=sum("test_preflight_hw5.PreflightHW5" in line and "... skipped" in line for line in tests.splitlines())
        live_skips=sum("test_live_hw5.LiveHW5" in line and "... skipped" in line for line in tests.splitlines())
        if skipped!=preflight_skips+live_skips or live_skips!=1:
            raise RuntimeError("Unexpected skipped-test coverage")
        count=int(match.group(1))
        native=["loader.py","runner.py","stand.py","assertions.py","cli.py","validate.py","docker-compose.yml"]
        proof={"recorded_on":"2026-10-26","kit_commit":revision,
               "clone_source":"Disposable local clone, detached to pinned official commit",
               "cloned_files_clean_before_input":True,"tracked_files_unchanged_after_tests":True,
               "own_dataset_sha256":expected,"set_hash":expected[:12],
               "native_source_sha256":{n:sha(clone/n) for n in native},
               "native_docker_dry_run":"passed","offline_tests_run":count,
               "offline_passed":count-skipped,"live_tests_skipped":live_skips,"preflight_tests_skipped":preflight_skips,
               "real_stand_requests":0,"real_model_calls":0,
               "prior_dataset_hashes_unchanged":True,
               "scope":"Fake HTTP integration and native dry-run; no live profile/DB/model exercised"}
        (ROOT/"evidence/offline-validation-step7.json").write_bytes(
            (json.dumps(proof,ensure_ascii=False,indent=2)+chr(10)).encode("utf-8"))
        print(json.dumps(proof,ensure_ascii=False,indent=2))
    finally:
        if docker_started and clone.exists():
            # Unique disposable project only; it cannot include the running stand.
            checked(["docker","compose","-p",project,"down","--remove-orphans"],clone,env)
        # Resolved deletion target must remain this explicitly created temporary workspace.
        if workspace.parent!=parent or not workspace.name.startswith("hw5-step7-"):
            raise RuntimeError("Refusing cleanup outside the temporary workspace")
        shutil.rmtree(workspace)

if __name__=="__main__":main()
