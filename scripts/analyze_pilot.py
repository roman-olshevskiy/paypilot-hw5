"""Offline analysis of the two primary HW5 pilots; never calls a stand/provider."""
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def read(path):return json.loads(path.read_text(encoding="utf-8"))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def spans(tree):
    yield tree
    for child in tree.get("children",[]):yield from spans(child)

def main():
    freeze=read(ROOT/"evidence/dataset-freeze.json")
    forecast=read(ROOT/"evidence/forecast-commit.json")
    dataset=ROOT/"evals/sets/l06_security.jsonl"
    assert sha(dataset)==freeze["dataset_sha256"]
    cases={r["id"]:r for r in [json.loads(x) for x in dataset.read_text(encoding="utf-8").splitlines()]}
    forbidden=re.compile(cases["HW5-SEC09"]["additional_metadata"]["invariants"][0]["forbid"])
    committed=int(subprocess.check_output(["git","show","-s","--format=%ct",forecast["commit"]],cwd=ROOT,text=True))
    runs=[]
    request_ids=[];sessions=[]
    for folder in sorted((ROOT/"evidence/hw5-runs").iterdir()):
        manifest=read(folder/"manifest.json")
        if "--only" not in manifest["argv"]:continue
        assert manifest["set_hash"]==freeze["set_hash"]
        assert manifest["forecast_commit"]==forecast["commit"]
        assert manifest["restore_status"]=="passed" and not manifest["restore_errors"]
        assert not manifest["artifact_errors"] and manifest["error"] is None
        rows=read(folder/"captures.json")
        assert len(rows)==manifest["complete_captures"]==manifest["chat_attempts"]==6
        assert all(r["capture_status"]=="complete" for r in rows)
        assert len(manifest["reports"])==1
        path=ROOT/"reports"/manifest["reports"][0]
        assert sha(path)==manifest["report_sha256"][path.name]
        report=read(path)
        assert report["set_hash"]==freeze["set_hash"] and report["total"]==3
        before,after=read(folder/"before.json"),read(folder/"restored.json")
        assert all(before[k]==after[k] for k in ["defects","clock","summarize","retrieval"])
        calls=[s for r in rows for s in spans(r["trace"]) if s.get("name")=="llm.call"]
        summaries=[s for r in rows for s in spans(r["trace"]) if s.get("name")=="agent.summarize"]
        for r in rows:
            assert committed < r["trace"]["started_at"]
            request_ids.append(r["response"]["request_id"])
            assert r["response"]["usage"].get("cost_usd") is not None
        own_sessions=sorted({r["response"]["session_id"] for r in rows})
        assert len(own_sessions)==3;sessions+=own_sessions
        d10=next(r for r in rows if r["case"]=="HW5-SEC07")
        sends=[s for s in spans(d10["trace"]) if s.get("name")=="tool.send_statement"]
        successful=[s for s in sends if "error" not in (s.get("attributes",{}).get("tool.result") or {})]
        multi=[r for r in rows if r["case"]=="HW5-SEC09"]
        assert [r["turn"] for r in multi]==[1,2,3,4]
        leak=[r for r in multi if forbidden.search(r["response"]["answer"])]
        cost=sum((Decimal(str(r["response"]["usage"]["cost_usd"])) for r in rows),Decimal(0))
        verdicts={c["id"]:c["verdict"] for c in report["cases"]}
        runs.append({"profile":manifest["profile"],"folder":folder.relative_to(ROOT).as_posix(),
          "report":path.relative_to(ROOT).as_posix(),"chat_requests":len(rows),"sessions":len(own_sessions),
          "native_passed_cases":report["passed"],"native_total_cases":report["total"],
          "native_verdicts":verdicts,"settings_restored":True,"complete_capture":True,
          "trace_observed_llm_calls":len(calls),"summary_spans":len(summaries),
          "completion_models":sorted({r["response"]["usage"]["model"] for r in rows}),
          "trace_request_models":sorted({s.get("attributes",{}).get("gen_ai.request.model") for s in calls}),
          "prompt_versions":sorted({r["trace"]["attributes"]["prompt.version"] for r in rows}),
          "root_input_tokens":sum(r["response"]["usage"]["input_tokens"] for r in rows),
          "root_output_tokens":sum(r["response"]["usage"]["output_tokens"] for r in rows),
          "root_cost_usd":float(cost),
          "d10":{"send_statement_attempts":len(sends),"successful_sends":len(successful),
            "captured_statement_rows":d10["state_after"]["statements_sent"],
            "backend_recipient_check_exercised":bool(sends),"request_id":d10["response"]["request_id"]},
          "d23":{"first_leak_turn":leak[0]["turn"] if leak else None,
            "leak_turns":[r["turn"] for r in leak],
            "first_leak_request_id":leak[0]["response"]["request_id"] if leak else None,
            "repetitions":1,"frequency_inference":"Pilot only; not a five-run distribution"}})
    assert len(runs)==2 and {r["profile"] for r in runs}=={"clean","lesson-06"}
    assert len(request_ids)==len(set(request_ids))==12
    assert len(sessions)==len(set(sessions))==6
    total=sum((Decimal(str(r["root_cost_usd"])) for r in runs),Decimal(0))
    estimate=total*Decimal(58)/Decimal(12)
    analysis={"recorded_on":"2026-10-26","set_hash":freeze["set_hash"],"phase":"pilot",
      "runs":runs,"total_chat_requests":12,"independent_sessions":6,
      "trace_observed_llm_calls":sum(r["trace_observed_llm_calls"] for r in runs),
      "observed_summary_calls":sum(r["summary_spans"] for r in runs),
      "root_input_tokens":sum(r["root_input_tokens"] for r in runs),
      "root_output_tokens":sum(r["root_output_tokens"] for r in runs),
      "root_cost_usd":float(total),"billing_verified":False,
      "budget":{"starting_available_usd":17.10,"next_full_series_chat_requests":58,
        "pilot_average_root_cost_per_chat_usd":float(total/Decimal(12)),
        "linear_full_root_projection_usd":float(estimate),
        "proposed_full_series_reserve_usd":0.25,"hard_cap":False,
        "limits":"Projection uses pilot average; D08/D09/control were not piloted. Output size, tool loops and provider retries may differ. Cache billing/HTTP retry attempts are not separately archived."},
      "next_step":"No more paid calls in step10; review pilot and budget before step11.",
      "limitations":["D10 safe response did not exercise backend send_statement validation.",
        "One multi-turn repetition per profile is not the required five-run distribution.",
        "Provider-message bodies are not logged. D23 input evidence is captured history/profile/prompt version plus matched preflight prompt/source.",
        "Trace span counts do not independently count SDK HTTP retries; root cost is not an invoice."]}
    (ROOT/"evidence/pilot-analysis.json").write_bytes((json.dumps(analysis,ensure_ascii=False,indent=2)+chr(10)).encode("utf-8"))
    print(json.dumps({k:v for k,v in analysis.items() if k!="runs"},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
