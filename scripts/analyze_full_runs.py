"""Offline checks and metrics for completed full series; preserves raw reports."""
import argparse
import uuid
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/"paypilot-l06-eval"))
import loader
import runner

def read(p):return json.loads(p.read_text(encoding="utf-8"))
def spans(t):
    yield t
    for x in t.get("children",[]):yield from spans(x)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection",type=Path,default=ROOT/"evidence/analysis-selection.json",
                        help="JSON containing explicit full_runs and ledger_runs folder names")
    args=parser.parse_args()
    selection=read(args.selection)
    names=selection["ledger_runs"]
    selected_full=set(selection["full_runs"])
    if not names or len(names)!=len(set(names)) or len(selected_full)!=len(selection["full_runs"]):
        raise ValueError("Selection must contain unique run names")
    if not selected_full or not selected_full.issubset(names):
        raise ValueError("full_runs must be a nonempty subset of ledger_runs")
    base=ROOT/"evidence/hw5-runs"
    for name in names:
        if not isinstance(name,str) or Path(name).name!=name or name in (".","..") or not (base/name/"manifest.json").is_file():
            raise ValueError("Invalid or missing selected run: "+str(name))
    output=ROOT/"evidence/analysis-runs"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8])
    dataset=ROOT/"evals/sets/l06_security.jsonl"
    freeze=read(ROOT/"evidence/dataset-freeze.json")
    assert hashlib.sha256(dataset.read_bytes()).hexdigest()==freeze["dataset_sha256"]
    cases={c["id"]:c for c in loader.load(dataset)}
    original={c["id"]:c for c in [json.loads(x) for x in dataset.read_text(encoding="utf-8").splitlines()]}
    leak=re.compile(original["HW5-SEC09"]["additional_metadata"]["invariants"][0]["forbid"])
    forecast=read(ROOT/"evidence/forecast-commit.json")
    epoch=int(subprocess.check_output(["git","show","-s","--format=%ct",forecast["commit"]],cwd=ROOT,text=True))
    full=[];all_rows=[];ledger=[]
    for name in names:
        folder=base/name
        m=read(folder/"manifest.json")
        assert m["restore_status"]=="passed", "Settings were not restored: "+folder.name
        rows=read(folder/"captures.json")
        all_rows+=rows
        known=[Decimal(str(x["response"]["usage"]["cost_usd"])) for x in rows
               if x["response"]["usage"].get("cost_usd") is not None]
        ledger.append({"folder":folder.relative_to(ROOT).as_posix(),"profile":m["profile"],
          "phase":"pilot" if "--only" in m["argv"] else "full","chat_attempts":m["chat_attempts"],
           "captured_responses":len(rows),"complete_captures":m["complete_captures"],
          "independent_sessions":len({r["response"]["session_id"] for r in rows}),
          "completed_report":m["error"] is None and m["runner_exit_code"] in (0,1) and len(m["reports"])==1,
          "run_error":m["error"],"root_cost_known":len(known)==len(rows),
          "root_cost_known_subtotal_usd":float(sum(known,Decimal(0)))})
        if folder.name not in selected_full:continue
        if "--only" in m["argv"]:raise ValueError("Pilot cannot be selected as a full run")
        if m["error"] is not None or m["runner_exit_code"] not in (0,1) or not m["reports"]:
            # Preserve failed partial usage in ledger, never present it as a completed raw report.
            assert m["restore_status"]=="passed"
            raise ValueError("Selected full run is incomplete: "+folder.name)
        assert len(rows)==m["complete_captures"]==m["chat_attempts"]==sum(len(c["turns"])*c["additional_metadata"].get("runs",1) for c in original.values())
        assert m["restore_status"]=="passed" and not m["restore_errors"]
        assert not m["artifact_errors"] and m["error"] is None
        assert m["set_hash"]==freeze["set_hash"] and m["forecast_commit"]==forecast["commit"]
        assert len(m["reports"])==1
        report_path=ROOT/"reports"/m["reports"][0]
        assert hashlib.sha256(report_path.read_bytes()).hexdigest()==m["report_sha256"][report_path.name]
        report=read(report_path)
        assert report["total"]==len(cases) and report["set_hash"]==freeze["set_hash"]
        b,a=read(folder/"before.json"),read(folder/"restored.json")
        assert all(b[k]==a[k] for k in ["defects","clock","summarize","retrieval"])
        for row in rows:
            assert row["capture_status"]=="complete"
            assert row["response"]["request_id"]==row["trace"]["request_id"]
            attrs=row["trace"]["attributes"]
            assert attrs["session.id"]==row["response"]["session_id"]
            assert attrs["run.profile"]==m["profile"]
            assert row["trace"]["started_at"]>epoch
        repeats=[]
        for cid,number in sorted({(x["case"],x["run"]) for x in rows}):
            part=[x for x in rows if (x["case"],x["run"])==(cid,number)]
            assert [x["turn"] for x in part]==list(range(1,len(part)+1))
            assert len({x["response"]["session_id"] for x in part})==1
            verdict=runner._dialog_run(cases[cid],{"turns":[{"answer":x["response"]["answer"],"trace":x["trace"]} for x in part]})
            rawcase=next(x for x in report["cases"] if x["id"]==cid)
            rawrun=next(x for x in rawcase["runs_detail"] if x["run"]==number)
            assert verdict.passed==rawrun["passed"]
            hits=[x for x in part if leak.search(x["response"]["answer"])]
            repeats.append({"case":cid,"repeat":number,"native_passed":verdict.passed,
              "session_id":part[0]["response"]["session_id"],
              "first_threshold_match_turn":hits[0]["turn"] if hits else None,
              "threshold_match_turns":[x["turn"] for x in hits],
              "failed_checks":[x for x in verdict.checks if not x["passed"]],
              "request_ids":[x["response"]["request_id"] for x in part]})
        assert len(repeats)==sum(c["additional_metadata"].get("runs",1) for c in original.values())
        calls=[s for row in rows for s in spans(row["trace"]) if s.get("name")=="llm.call"]
        summaries=[s for row in rows for s in spans(row["trace"]) if s.get("name")=="agent.summarize"]
        row7=next(x for x in rows if x["case"]=="HW5-SEC07")
        send=[s for s in spans(row7["trace"]) if s.get("name")=="tool.send_statement"]
        row6=next(x for x in rows if x["case"]=="HW5-SEC06")
        merchants=[t.get("merchant") for s in spans(row6["trace"]) if s.get("name")=="tool.get_transactions"
          for t in (s.get("attributes",{}).get("tool.result") or {}).get("transactions",[]) if t.get("id")=="TX-0901"]
        full.append({"profile":m["profile"],"folder":folder.relative_to(ROOT).as_posix(),
          "report":report_path.relative_to(ROOT).as_posix(),"set_hash":report["set_hash"],
          "native_passed_cases":report["passed"],"native_total_cases":report["total"],
          "native_passed_dialogs":sum(x["native_passed"] for x in repeats),"total_dialogs":len(repeats),
          "chat_requests":len(rows),"trace_observed_llm_calls":len(calls),"summary_spans":len(summaries),
          "completion_models":sorted({x["response"]["usage"]["model"] for x in rows}),
          "root_input_tokens":sum(x["response"]["usage"]["input_tokens"] for x in rows),
          "root_output_tokens":sum(x["response"]["usage"]["output_tokens"] for x in rows),
          "root_cost_usd":float(sum((Decimal(str(x["response"]["usage"]["cost_usd"])) for x in rows),Decimal(0))),
          "settings_restored":True,"repeats":repeats,
          "d08_native_passed_attempts":sum(x["native_passed"] for x in repeats if x["case"] in {"HW5-SEC01","HW5-SEC02","HW5-SEC03","HW5-SEC04","HW5-SEC05"}),
          "d09":{"request_id":row6["response"]["request_id"],"observed_merchant_fields":merchants,
                 "classification":"Delivery evidence only; execution must be checked in answer/actions"},
          "d10":{"request_id":row7["response"]["request_id"],"send_statement_attempts":len(send),
                 "successful_send_calls":sum("error" not in (s.get("attributes",{}).get("tool.result") or {}) for s in send),
                 "statement_rows":row7["state_after"]["statements_sent"]}})
    assert len(full)==len(selected_full)
    partial=[x for x in ledger if x["phase"]=="full" and not x["completed_report"]]
    expected=sum(x["chat_attempts"] for x in ledger)
    ids=[x["response"]["request_id"] for x in all_rows]
    assert len(ids)==len(set(ids))==expected
    sessions={x["response"]["session_id"] for x in all_rows}
    assert len(sessions)==sum(x["independent_sessions"] for x in ledger)
    assert all(x["root_cost_known"] for x in ledger)
    result={"recorded_on":datetime.now(timezone.utc).isoformat(),"selection":selection,"set_hash":freeze["set_hash"],"full_runs":full,
      "ledger":ledger,"total_chat_requests_including_pilot":len(ids),"independent_sessions_including_pilot":len(sessions),
      "completed_full_chat_requests":sum(x["chat_requests"] for x in full),"failed_partial_chat_requests":sum(x["captured_responses"] for x in partial),
      "failed_partial_root_cost_usd":round(sum(x["root_cost_known_subtotal_usd"] for x in partial),6),
      "full_root_cost_usd":round(sum(x["root_cost_usd"] for x in full),6),
      "all_root_cost_usd":round(sum(x["root_cost_known_subtotal_usd"] for x in ledger),6),
      "balance_after_pilot_before_full_usd":17.09,"full_balance_reconciliation":read(ROOT/"evidence/balance-after-full.json") if (ROOT/"evidence/balance-after-full.json").exists() else "pending",
      "limits":"Metrics cover only selected runs. Historical balance confirmation covers the original submission ledger, not arbitrary new selections. Semantic conclusions and limitations: docs/security-analysis.md. Root cost is not an invoice."}
    output.mkdir(parents=True,exist_ok=False)
    (output/"analysis.json").write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+chr(10)).encode())
    print("Output: "+str(output),flush=True)
    print(json.dumps({k:v for k,v in result.items() if k not in ("full_runs","ledger")},ensure_ascii=False,indent=2))
    for run in full:
        print(run["profile"],str(run["native_passed_cases"])+"/"+str(run["native_total_cases"])+" cases",
              str(run["native_passed_dialogs"])+"/"+str(run["total_dialogs"])+" dialogs","root USD",run["root_cost_usd"])
        print("D23 first matches:",[x["first_threshold_match_turn"] for x in run["repeats"] if x["case"]=="HW5-SEC09"])

if __name__=="__main__":main()
