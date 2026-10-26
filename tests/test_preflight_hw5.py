"""Explicit real preflight: GET/config round-trip/Docker source reads; never chat."""
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
KIT=ROOT.parent/"paypilot-l06-eval"
STAND=ROOT.parent/"paypilot-stand-shared"
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(KIT))
import hw5_capture as C
import stand
from test_live_hw5 import reviewed_forecast

@unittest.skipUnless(os.environ.get("HW5_RUN_PREFLIGHT")=="1",
                     "Real preflight disabled during ordinary offline discovery")
class PreflightHW5(unittest.TestCase):
    def setUp(self):
        self.original_base=stand.BASE
        stand.BASE="http://localhost:8000"
        self.addCleanup(setattr,stand,"BASE",self.original_base)

    def test_00_record_committed_forecast(self):
        commit=subprocess.check_output(["git","log","-1","--format=%H","--","docs/forecast-before-runs.md"],
                                       cwd=ROOT,text=True).strip()
        self.assertEqual(len(commit),40)
        dataset=(ROOT/"evals/sets/l06_security.jsonl").read_bytes()
        frozen=subprocess.check_output(["git","show",commit+":evals/sets/l06_security.jsonl"],cwd=ROOT)
        self.assertEqual(dataset,frozen)
        content=subprocess.check_output(["git","show",commit+":docs/forecast-before-runs.md"],cwd=ROOT)
        self.assertEqual(content,(ROOT/"docs/forecast-before-runs.md").read_bytes())
        digest=hashlib.sha256(dataset).hexdigest()
        self.assertIn(digest[:12].encode(),content)
        proof={"commit":commit,"forecast_path":"docs/forecast-before-runs.md","set_hash":digest[:12],
               "dataset_sha256":digest,"committed_at":subprocess.check_output(
                   ["git","show","-s","--format=%cI",commit],cwd=ROOT,text=True).strip(),
               "verified_on":"2026-10-26","chat_requests_before_verification":0,"model_calls_before_verification":0}
        C.save(ROOT/"evidence/forecast-commit.json",proof)
        self.assertEqual(reviewed_forecast(),(commit,digest[:12]))

    def test_10_read_only_api_and_seed(self):
        data=C.snapshot(stand)
        data["seed"]=stand._call("GET","/api/_test/seed")
        data["transactions"]=stand.state("transactions")
        data["state"]={t:stand.state(t) for t in C.TABLES}
        C.save(ROOT/"evidence/preflight-api.json",data)
        self.assertEqual(data["health"]["status"],"ok")
        self.assertNotEqual(data["health"]["provider"],"mock")
        self.assertFalse(data["health"].get("keys_required"))
        self.assertIn("lesson-06",data["defects"]["known_profiles"])
        customer=next(x for x in data["seed"]["customers"] if x["id"]=="CUS-0001")
        self.assertEqual(customer["email"],"alice.novak@example.com")
        tx=next(x for x in data["transactions"] if x["id"]=="TX-0901")
        oracle=json.loads((ROOT/"evidence/security-case-provenance.json").read_text(encoding="utf-8"))["oracles"]
        self.assertEqual(tx["merchant"],oracle["merchant_payload"])
        self.assertEqual(tx["status"],"settled")
        self.assertEqual(tx["account_id"],"ACC-1010")

    def test_20_runtime_source_and_configured_model(self):
        paths=["app/main.py","app/config.py","app/agent/loop.py","app/agent/summarize.py",
               "app/agent/tools.py","app/agent/providers/base.py",
               "app/agent/providers/anthropic_provider.py","app/engines/policy.py","app/seed.py",
               "profiles/profiles.yaml","profiles/defects.yaml","prompts/base.v1.md",
               "prompts/overlays/fc2aa24d853f.md","app/rag/corpus/compliance.md"]
        code=("import hashlib,json;from pathlib import Path;from app import config;"
              "from app.agent.providers.base import get_provider;"
              "p=get_provider();paths="+repr(paths)+";"
              "print(json.dumps({'runtime':{x:hashlib.sha256(Path(x).read_bytes()).hexdigest() for x in paths},"
              "'provider':p.name,'configured_model':getattr(p,'model',''),"
              "'router':config.ROUTER,'model_calls':0}))")
        result=subprocess.run(["docker","compose","exec","-T","stand","python","-c",code],
                              cwd=STAND,capture_output=True,text=True,encoding="utf-8",check=True)
        actual=json.loads(result.stdout)
        expected={p:hashlib.sha256((STAND/p).read_bytes()).hexdigest() for p in paths}
        actual["checkout"]=expected
        actual["model_scope"]="Configured runtime provider/model; first actual completion model must be checked in pilot trace."
        C.save(ROOT/"evidence/preflight-runtime.json",actual)
        self.assertEqual(actual["runtime"],expected)
        self.assertNotEqual(actual["provider"],"mock")
        self.assertTrue(actual["configured_model"])
        self.assertEqual(actual["router"],"")
        freeze=json.loads((ROOT/"evidence/dataset-freeze.json").read_text(encoding="utf-8"))
        self.assertEqual(subprocess.check_output(["git","rev-parse","HEAD"],cwd=STAND,text=True).strip(),
                         freeze["stand_source_commit"])

    def test_30_settings_round_trip_without_chat_or_reset(self):
        before=C.snapshot(stand)
        self.assertTrue(not before["health"].get("locked") or before["health"].get("admin"),
                        "Global settings are locked; no mutations attempted")
        db_before={t:stand.state(t) for t in C.TABLES}
        C.save(ROOT/"evidence/preflight-settings-before.json",before)
        primary=None;observed={}
        try:
            stand.set_profile("lesson-06")
            stand.set_defects("D24")
            stand.set_clock("2026-09-16T10:00:00Z")
            stand.set_summarize_after(2)
            stand._call("PUT","/api/_test/retrieval",{"index":"kb_clean","top_k":2})
            observed=C.snapshot(stand)
            self.assertEqual(observed["defects"]["profile"],"lesson-06")
            self.assertEqual(set(observed["defects"]["profile_defects"]),{"D08","D09","D10","D23","D24"})
            self.assertEqual(observed["defects"]["extra_defects"],["D24"])
            self.assertEqual(observed["summarize"]["summarize_after_steps"],2)
            self.assertEqual(observed["retrieval"]["requested_index"],"kb_clean")
            self.assertEqual(observed["retrieval"]["requested_top_k"],2)
            self.assertIn("PERSISTENT-CUSTOMER EXCEPTION",json.dumps(observed["prompt"]))
        except BaseException as exc:primary=exc
        finally:
            errors=C.restore(stand,before)
            after=C.snapshot(stand)
            db_after={t:stand.state(t) for t in C.TABLES}
            C.save(ROOT/"evidence/preflight-settings-roundtrip.json",{
                "observed_temporary_settings":observed,"after":after,"restore_errors":errors,
                "settings_equal":all(before[k]==after[k] for k in C.SETTINGS),
                "action_tables_unchanged":db_before==db_after,"model_calls":0,
                "chat_or_reset_called":False,"error":repr(primary) if primary else None})
        if primary:raise primary
        self.assertFalse(errors)
        for key in C.SETTINGS:self.assertEqual(before[key],after[key],key)
        self.assertEqual(db_before,db_after)

if __name__=="__main__":unittest.main()
