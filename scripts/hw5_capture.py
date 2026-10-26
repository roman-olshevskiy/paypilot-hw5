"""HW5 evidence adapter around native L06 CLI. Imports perform no HTTP calls."""
import hashlib
import importlib
import json
import os
import shutil
import sys
import time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

SETTINGS=("defects","clock","summarize","retrieval")
TABLES=("statements_sent","disputes","escalations")

class CaptureFailure(RuntimeError):
    """Not a StandError: native case handling must not continue a broken capture."""

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    data=(json.dumps(value,ensure_ascii=False,indent=2)+chr(10)).encode("utf-8")
    # Docker bind mounts on Windows can briefly deny rename while a host reader holds the file.
    # Retry only local file I/O, never chat/trace/state HTTP requests.
    for attempt in range(8):
        try:
            tmp.write_bytes(data)
            tmp.replace(path)
            return
        except PermissionError:
            if attempt==7:raise
            time.sleep(min(0.05*(2**attempt),0.5))

def snapshot(stand):
    return {name:stand._call("GET",endpoint) for name,endpoint in {
        "health":"/health","defects":"/api/_test/defects","clock":"/api/_test/clock",
        "summarize":"/api/_test/summarize_after","retrieval":"/api/_test/retrieval",
        "prompt":"/api/_test/prompt"}.items()}

def restore(stand,before):
    actions=[
        ("profile",lambda:stand.set_profile(before["defects"]["profile"])),
        ("extra_defects",lambda:stand.set_defects(",".join(before["defects"].get("extra_defects",[])))),
        ("clock",lambda:stand.set_clock(before["clock"].get("runtime_override"))),
        ("summarize",lambda:stand.set_summarize_after(before["summarize"]["summarize_after_steps"])),
        ("retrieval",lambda:stand._call("PUT","/api/_test/retrieval",{
            "index":before["retrieval"]["requested_index"],
            "top_k":before["retrieval"]["requested_top_k"]}))]
    errors=[]
    for name,action in actions:
        try:action()
        except Exception as exc:errors.append({"operation":name,"error":repr(exc)})
    return errors

def archive_reports(kit,root,paths):
    kit,root=Path(kit).resolve(),Path(root).resolve()
    boundary=(kit/"reports").resolve()
    hashes={}
    def copy(source):
        source=source.resolve()
        if not source.is_relative_to(boundary):raise CaptureFailure("Evidence path outside kit reports")
        target=root/"reports"/source.relative_to(boundary)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if source.read_bytes()!=target.read_bytes():raise CaptureFailure("Evidence collision")
        else:shutil.copyfile(source,target)
        return target
    for source in paths:
        target=copy(source)
        hashes[target.name]=sha(target)
        for case in json.loads(source.read_text(encoding="utf-8")).get("cases",[]):
            if not case.get("traces_dir"):continue
            folder=(kit/case["traces_dir"]).resolve()
            if not folder.is_relative_to(boundary):raise CaptureFailure("Trace path outside kit reports")
            for trace in folder.glob("*.json"):copy(trace)
    return hashes

def execute(argv,kit,root,cli,runner,stand):
    """Orchestration boundary, injectable for offline integration tests."""
    args=cli.parse(argv)
    if args.profile not in ("clean","lesson-06") or args.dry_run:
        raise ValueError("Require explicit clean/lesson-06 live profile")
    if args.set_name!="l06_security" or args.gate!="all" or not args.traces:
        raise ValueError("Require --set l06_security --gate all --traces")
    if args.summarize_after is not None:raise ValueError("Use per-case summarize_after")
    kit,root=Path(kit),Path(root)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    folder=root/"evidence/hw5-runs"/(stamp+"-"+args.profile)
    before=snapshot(stand)
    save(folder/"before.json",before)
    captures,attempts=[],[]
    counts=Counter()
    context={"case":None,"run":0,"turn":0}
    original_chat,original_one=stand.chat,runner._one_run
    reports_before=set((kit/"reports").glob("*.json"))
    code=None
    primary=None

    def chat(message,session_id=None,customer_id=None):
        context["turn"]+=1
        attempt={**context,"question":message,"session_id_in":session_id,
                 "customer_id":customer_id,"status":"started"}
        attempts.append(attempt)
        try:
            save(folder/"attempts.json",attempts)
            response=original_chat(message,session_id,customer_id=customer_id)
            row={**context,"question":message,"response":response,"trace":None,
                 "state_after":{},"capture_status":"response_saved"}
            captures.append(row)
            save(folder/"captures.json",captures)  # Durable before trace lookup.
            attempt.update(status="response_received",request_id=response["request_id"])
            save(folder/"attempts.json",attempts)
            row["trace"]=stand.trace(response["request_id"])
            row["capture_status"]="trace_saved"
            save(folder/"captures.json",captures)
            for table in TABLES:
                row["state_after"][table]=stand.state(table)
                save(folder/"captures.json",captures)
            row["capture_status"]="complete"
            attempt["status"]="complete"
            save(folder/"captures.json",captures)
            save(folder/"attempts.json",attempts)
            return response
        except Exception as exc:
            attempt.update(status="capture_or_transport_error",error=repr(exc))
            try:save(folder/"attempts.json",attempts)
            except Exception:pass
            raise CaptureFailure("Stopped after incomplete response/capture; no automatic retry") from exc

    def one_run(case):
        counts[case["id"]]+=1
        context.update(case=case["id"],run=counts[case["id"]],turn=0)
        return original_one(case)

    stand.chat,runner._one_run=chat,one_run
    try:
        stand.set_defects("")
        code=cli.main(argv)
        if code not in (0,1):raise CaptureFailure("Native CLI setup/transport failure: "+str(code))
    except BaseException as exc:
        primary=exc
    finally:
        stand.chat,runner._one_run=original_chat,original_one
        # Restoration precedes final file I/O, and each operation is attempted.
        restore_errors=restore(stand,before)
        restored=None
        try:restored=snapshot(stand)
        except Exception as exc:restore_errors.append({"operation":"snapshot","error":repr(exc)})
        matches=restored is not None and all(before[k]==restored[k] for k in SETTINGS)
        errors=[]
        for name,value in [("captures.json",captures),("attempts.json",attempts),("restored.json",restored)]:
            try:save(folder/name,value)
            except Exception as exc:errors.append({"operation":name,"error":repr(exc)})
        produced=sorted(set((kit/"reports").glob("*.json"))-reports_before)
        hashes={}
        try:hashes=archive_reports(kit,root,produced)
        except Exception as exc:errors.append({"operation":"archive_reports","error":repr(exc)})
        manifest={"profile":args.profile,"argv":argv,"runner_exit_code":code,
            "chat_attempts":len(attempts),"captured_responses":len(captures),
            "complete_captures":sum(x["capture_status"]=="complete" for x in captures),
            "reports":[p.name for p in produced],"report_sha256":hashes,
            "restore_status":"passed" if matches and not restore_errors else "failed",
            "restore_errors":restore_errors,"artifact_errors":errors,
            "error":repr(primary) if primary else None,
            "set_hash":os.environ.get("HW5_EXPECTED_SET_HASH"),
            "forecast_commit":os.environ.get("HW5_FORECAST_COMMIT"),
            "usage_scope":"Root/chat usage may omit summarizer/cache billing; absent usage is not zero.",
            "state_scope":"State snapshots are evidence; arbitrary initial DB/session state is not restored."}
        try:save(folder/"manifest.json",manifest)
        except Exception as exc:errors.append({"operation":"manifest.json","error":repr(exc)})
    if primary is not None:
        if restore_errors or errors or not matches:
            raise CaptureFailure("Run failed; evidence/restore also incomplete") from primary
        raise primary
    if restore_errors or errors or not matches:raise CaptureFailure("Evidence/restore incomplete")
    return code

def main(argv):
    # Guard before ALL imports of native modules and before ALL HTTP.
    if os.environ.get("HW5_ENABLE_PAID_RUNS")!="1":
        raise CaptureFailure("Live calls disabled; review and forecast required")
    root=Path(os.environ.get("HW5_ROOT","/hw5"))
    kit=Path(os.environ.get("HW5_KIT_DIR","/course/solutions/evals"))
    expected=os.environ.get("HW5_EXPECTED_SET_HASH")
    path=root/"evals/sets/l06_security.jsonl"
    if not expected or sha(path)[:12]!=expected or sha(kit/"sets/l06_security.jsonl")!=sha(path):
        raise CaptureFailure("Dataset hash/mount mismatch")
    if not os.environ.get("HW5_FORECAST_COMMIT"):raise CaptureFailure("Forecast commit missing")
    sys.path.insert(0,str(kit))
    return execute(argv,kit,root,*[importlib.import_module(n) for n in ("cli","runner","stand")])

if __name__=="__main__":
    try:raise SystemExit(main(sys.argv[1:]))
    except CaptureFailure as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(2)
