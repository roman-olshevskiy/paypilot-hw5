"""Future explicit live unittest. Discovery is offline unless deliberately enabled."""
import hashlib
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
KIT=ROOT.parent/"paypilot-l06-eval"
PILOT={"HW5-SEC07","HW5-SEC08","HW5-SEC09"}

def reviewed_forecast():
    proof=json.loads((ROOT/"evidence/forecast-commit.json").read_text(encoding="utf-8"))
    commit=proof["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}",commit):raise ValueError("Forecast needs a full commit SHA")
    path=proof.get("forecast_path","docs/forecast-before-runs.md")
    if not path.startswith("docs/") or ".." in Path(path).parts:raise ValueError("Invalid forecast path")
    dataset=(ROOT/"evals/sets/l06_security.jsonl").read_bytes()
    frozen=subprocess.check_output(["git","show",commit+":evals/sets/l06_security.jsonl"],cwd=ROOT)
    if frozen!=dataset:raise ValueError("Current dataset differs from committed forecast dataset")
    digest=hashlib.sha256(dataset).hexdigest()[:12]
    forecast=subprocess.check_output(["git","show",commit+":"+path],cwd=ROOT).decode("utf-8")
    if digest not in forecast:raise ValueError("Forecast does not identify this dataset hash")
    committed=int(subprocess.check_output(["git","show","-s","--format=%ct",commit],cwd=ROOT,text=True))
    if committed>=datetime.now(timezone.utc).timestamp():raise ValueError("Forecast timestamp is not before run")
    return commit,digest

@unittest.skipUnless(os.environ.get("HW5_ENABLE_PAID_RUNS")=="1",
                     "Paid live runs disabled; review, forecast and pilot step are pending")
class LiveHW5(unittest.TestCase):
    def test_real_security_eval_with_capture_and_restore(self):
        profile=os.environ.get("HW5_PROFILE")
        phase=os.environ.get("HW5_PHASE")
        self.assertIn(profile,["clean","lesson-06"])
        self.assertIn(phase,["pilot","full"])
        commit,digest=reviewed_forecast()  # Fails before Docker/HTTP if step 8 is not ready.
        cases=[json.loads(x) for x in (ROOT/"evals/sets/l06_security.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        selected=[x for x in cases if phase=="full" or x["id"] in PILOT]
        expected=sum(sum(t["role"]=="user" for t in c["turns"])*
                     (1 if phase=="pilot" else c["additional_metadata"].get("runs",1)) for c in selected)
        sessions=sum(1 if phase=="pilot" else c["additional_metadata"].get("runs",1) for c in selected)
        folders=ROOT/"evidence/hw5-runs"
        before=set(folders.glob("*")) if folders.exists() else set()
        command=["docker","compose","run","--rm","-T",
          "--volume",str(ROOT)+":/hw5",
          "--volume",str(ROOT/"evals/sets/l06_security.jsonl")+":/course/solutions/evals/sets/l06_security.jsonl:ro"]
        for name,value in {"HW5_ENABLE_PAID_RUNS":"1","HW5_ROOT":"/hw5",
            "HW5_KIT_DIR":"/course/solutions/evals","HW5_EXPECTED_SET_HASH":digest,
            "HW5_FORECAST_COMMIT":commit,"CASE":"","REPEAT":"","SUMMARIZE_AFTER":"",
            "GATE":"all","SET":"l06_security","TRACES":"1","JUDGE_MODEL":"not-used"}.items():
            command+=["-e",name+"="+value]
        command+=["eval","python","/hw5/scripts/hw5_capture.py","--set","l06_security",
                  "--profile",profile,"--gate","all","--traces"]
        if phase=="pilot":command+=["--only",",".join(sorted(PILOT)),"--repeat","1"]
        env=os.environ.copy()
        env.update(STAND_DIR="../paypilot-stand-shared",EVAL_STAND_URL="http://host.docker.internal:8000")
        result=subprocess.run(command,cwd=KIT,env=env,capture_output=True,text=True,
                              encoding="utf-8",errors="replace")
        new=set(folders.glob("*"))-before
        self.assertEqual(len(new),1,result.stdout+result.stderr)
        folder=new.pop()
        (folder/"console.stdout.txt").write_bytes((result.stdout+result.stderr).encode("utf-8"))
        self.assertIn(result.returncode,[0,1],result.stdout[-2500:]+result.stderr[-1000:])
        manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["restore_status"],"passed")
        self.assertFalse(manifest["artifact_errors"])
        self.assertFalse(manifest["restore_errors"])
        self.assertIsNone(manifest["error"])
        self.assertEqual(manifest["runner_exit_code"],result.returncode)
        for key in ["chat_attempts","captured_responses","complete_captures"]:
            self.assertEqual(manifest[key],expected,key)
        self.assertEqual(manifest["set_hash"],digest)
        self.assertEqual(manifest["forecast_commit"],commit)
        self.assertEqual(len(manifest["reports"]),1)
        rows=json.loads((folder/"captures.json").read_text(encoding="utf-8"))
        self.assertEqual(len({x["response"]["request_id"] for x in rows}),expected)
        self.assertEqual(len({x["response"]["session_id"] for x in rows}),sessions)
        for group in {(x["case"],x["run"]) for x in rows}:
            part=[x for x in rows if (x["case"],x["run"])==group]
            self.assertEqual([x["turn"] for x in part],list(range(1,len(part)+1)))
            self.assertEqual(len({x["response"]["session_id"] for x in part}),1)
        for name,digest in manifest["report_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT/"reports"/name).read_bytes()).hexdigest(),digest)

if __name__=="__main__":unittest.main()
