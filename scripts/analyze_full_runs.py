"""Offline checks and metrics for completed full series; preserves raw reports."""
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
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
    dataset=ROOT/"evals/sets/l06_security.jsonl"
    freeze=read(ROOT/"evidence/dataset-freeze.json")
    assert hashlib.sha256(dataset.read_bytes()).hexdigest()==freeze["dataset_sha256"]
    cases={c["id"]:c for c in loader.load(dataset)}
    original={c["id"]:c for c in [json.loads(x) for x in dataset.read_text(encoding="utf-8").splitlines()]}
    leak=re.compile(original["HW5-SEC09"]["additional_metadata"]["invariants"][0]["forbid"])
    forecast=read(ROOT/"evidence/forecast-commit.json")
    epoch=int(subprocess.check_output(["git","show","-s","--format=%ct",forecast["commit"]],cwd=ROOT,text=True))
    full=[];all_rows=[];ledger=[]
    for folder in sorted((ROOT/"evidence/hw5-runs").iterdir()):
        if not (folder/"manifest.json").exists():continue
        m=read(folder/"manifest.json")
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
        if "--only" in m["argv"]:continue
        if m["error"] is not None or m["runner_exit_code"] not in (0,1) or not m["reports"]:
            # Preserve failed partial usage in ledger, never present it as a completed raw report.
            assert m["restore_status"]=="passed"
            continue
        assert len(rows)==m["complete_captures"]==m["chat_attempts"]==29
        assert m["restore_status"]=="passed" and not m["restore_errors"]
        assert not m["artifact_errors"] and m["error"] is None
        assert m["set_hash"]==freeze["set_hash"] and m["forecast_commit"]==forecast["commit"]
        assert len(m["reports"])==1
        report_path=ROOT/"reports"/m["reports"][0]
        assert hashlib.sha256(report_path.read_bytes()).hexdigest()==m["report_sha256"][report_path.name]
        report=read(report_path)
        assert report["total"]==10 and report["set_hash"]==freeze["set_hash"]
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
        assert len(repeats)==14
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
          "native_passed_dialogs":sum(x["native_passed"] for x in repeats),"total_dialogs":14,
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
    assert len(full)==2 and {x["profile"] for x in full}=={"clean","lesson-06"}
    partial=[x for x in ledger if x["phase"]=="full" and not x["completed_report"]]
    assert len(ledger)==5 and len(partial)==1
    assert sum(x["captured_responses"] for x in partial)==19
    expected=70+sum(x["chat_attempts"] for x in partial)
    assert sum(x["chat_attempts"] for x in ledger)==expected
    ids=[x["response"]["request_id"] for x in all_rows]
    assert len(ids)==len(set(ids))==expected
    sessions={x["response"]["session_id"] for x in all_rows}
    assert len(sessions)==34+sum(x["independent_sessions"] for x in partial)
    assert all(x["root_cost_known"] for x in ledger)
    result={"recorded_on":"2026-10-26","set_hash":freeze["set_hash"],"full_runs":full,
      "ledger":ledger,"total_chat_requests_including_pilot":len(ids),"independent_sessions_including_pilot":len(sessions),
      "completed_full_chat_requests":58,"failed_partial_chat_requests":sum(x["captured_responses"] for x in partial),
      "failed_partial_root_cost_usd":round(sum(x["root_cost_known_subtotal_usd"] for x in partial),6),
      "full_root_cost_usd":round(sum(x["root_cost_usd"] for x in full),6),
      "all_root_cost_usd":round(sum(x["root_cost_known_subtotal_usd"] for x in ledger),6),
      "balance_after_pilot_before_full_usd":17.09,"full_balance_reconciliation":read(ROOT/"evidence/balance-after-full.json") if (ROOT/"evidence/balance-after-full.json").exists() else "pending",
      "limits":"Counts/verdicts are native+replay, not semantic proof. D08 markers, D09 quotes and D10 backend exercise need manual evidence review in step12. Root cost is not an invoice."}
    (ROOT/"evidence/full-run-analysis.json").write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+chr(10)).encode())
    print(json.dumps({k:v for k,v in result.items() if k not in ("full_runs","ledger")},ensure_ascii=False,indent=2))
    for run in full:
        print(run["profile"],str(run["native_passed_cases"])+"/10 cases",
              str(run["native_passed_dialogs"])+"/14 dialogs","root USD",run["root_cost_usd"])
        print("D23 first matches:",[x["first_threshold_match_turn"] for x in run["repeats"] if x["case"]=="HW5-SEC09"])

if __name__=="__main__":main()
