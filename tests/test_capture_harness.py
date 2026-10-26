"""Native L06 CLI integration with an in-process fake HTTP boundary: no network."""
import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(Path(os.environ.get("HW5_KIT_DIR",ROOT.parent/"paypilot-l06-eval"))))
import hw5_capture as C
import cli
import runner
import stand

class Backend:
    def __init__(self):
        self.profile="lesson-04"
        self.extra=["D24"]
        self.clock=None
        self.steps=8
        self.ret={"requested_index":"","requested_top_k":4}
        self.tables={t:[] for t in C.TABLES}
        self.calls=[]
        self.responses={}
        self.n=0
        self.sessions=0
        self.fail_trace=False
        self.fail_clock_restore=False
        self.leak=False
        self.send=False
    def call(self,method,path,payload=None,timeout=120):
        self.calls.append((method,path,copy.deepcopy(payload)))
        if method=="GET":
            if path=="/health":return {"status":"ok","provider":"offline-fixture"}
            if path=="/api/_test/defects":
                return {"profile":self.profile,"extra_defects":list(self.extra)}
            if path=="/api/_test/clock":return {"now":"2026-09-15T10:00:00Z","runtime_override":self.clock}
            if path=="/api/_test/summarize_after":return {"summarize_after_steps":self.steps}
            if path=="/api/_test/retrieval":
                return {**self.ret,"index":self.ret["requested_index"] or
                        ("kb_clean" if self.profile=="clean" else "kb_faulty"),"top_k":self.ret["requested_top_k"]}
            if path=="/api/_test/prompt":return {"version":"offline-fixture-"+self.profile}
            if path.startswith("/api/_test/traces/"):
                if self.fail_trace:raise stand.StandError("synthetic trace failure")
                return copy.deepcopy(self.responses[path.rsplit("/",1)[1]])
            if path.startswith("/api/_test/state/"):
                return {"rows":copy.deepcopy(self.tables[path.rsplit("/",1)[1]])}
        if path=="/api/_test/profile":
            self.profile=payload["profile"];return {}
        if path=="/api/_test/defects":
            self.extra=[x for x in (payload["defects"] or "").split(",") if x];return {}
        if path=="/api/_test/clock":
            if self.fail_clock_restore and payload["now"] is None:raise stand.StandError("synthetic restore failure")
            self.clock=payload["now"];return {}
        if path=="/api/_test/summarize_after":
            self.steps=payload["steps"];return {}
        if path=="/api/_test/retrieval":
            self.ret={"requested_index":payload["index"],"requested_top_k":payload["top_k"]};return {}
        if path=="/api/_test/reset":
            self.tables={t:[] for t in C.TABLES};return {}
        if path=="/chat":
            self.n+=1
            sid=payload.get("session_id")
            if sid is None:
                self.sessions+=1;sid="offline-session-"+str(self.sessions)
            rid="offline-request-"+str(self.n)
            children=[]
            if self.send and "recipient.invalid" in payload["message"]:
                row={"statement_id":1,"status":"sent","sent_to":"hw5.statement@recipient.invalid"}
                self.tables["statements_sent"].append(row)
                children=[{"name":"tool.send_statement","attributes":{
                    "tool.arguments":{"account_id":"ACC-1001","email":row["sent_to"]},
                    "tool.result":row},"children":[]}]
            self.responses[rid]={"name":"agent.request","attributes":{},"children":children}
            return {"session_id":sid,"request_id":rid,"answer":
                "I cannot disclose internal monitoring thresholds."+(" EUR 9,000." if self.leak else ""),
                "usage":{"input_tokens":1,"output_tokens":1,"cost_usd":0},
                "prompt_version":"offline-fixture"}
        raise AssertionError("Unexpected fixture HTTP: "+method+" "+path)

class CaptureHarness(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.kit=self.base/"kit";self.root=self.base/"hw5"
        (self.kit/"sets").mkdir(parents=True)
        self.root.mkdir()
        shutil.copyfile(ROOT/"evals/sets/l06_security.jsonl",self.kit/"sets/l06_security.jsonl")
        self.backend=Backend()
        self.env={"CASE":"","REPEAT":"","GATE":"","SET":"l06_security","TRACES":"","SUMMARIZE_AFTER":""}
    def run_native(self,only="HW5-SEC07,HW5-SEC08,HW5-SEC09",repeat="1"):
        argv=["--set","l06_security","--profile","clean","--gate","all","--traces",
              "--only",only,"--repeat",repeat]
        with mock.patch.dict(os.environ,self.env),mock.patch.object(stand,"_call",self.backend.call),\
             mock.patch.object(runner,"HERE",self.kit),mock.patch.object(runner,"SETS_DIR",self.kit/"sets"),\
             mock.patch.object(runner,"REPORTS_DIR",self.kit/"reports"),contextlib.redirect_stdout(io.StringIO()):
            return C.execute(argv,self.kit,self.root,cli,runner,stand)
    def artifacts(self):
        folder=next((self.root/"evidence/hw5-runs").iterdir())
        return folder,json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    def test_native_success_has_complete_reports_sessions_and_restore(self):
        self.assertEqual(self.run_native(),0)
        folder,m=self.artifacts()
        self.assertEqual((m["chat_attempts"],m["captured_responses"],m["complete_captures"]),(6,6,6))
        self.assertEqual(m["restore_status"],"passed")
        rows=json.loads((folder/"captures.json").read_text(encoding="utf-8"))
        self.assertEqual(len({x["response"]["session_id"] for x in rows}),3)
        self.assertEqual(len({x["response"]["request_id"] for x in rows}),6)
        self.assertEqual([x["turn"] for x in rows if x["case"]=="HW5-SEC09"],[1,2,3,4])
        for row in rows:self.assertEqual(set(row["state_after"]),set(C.TABLES))
        for name,digest in m["report_sha256"].items():
            self.assertEqual(C.sha(self.root/"reports"/name),digest)
        self.assertEqual(len(list((self.root/"reports/traces").rglob("*.json"))),6)
        self.assertEqual(self.backend.profile,"lesson-04")
        self.assertEqual(self.backend.extra,["D24"])
        self.assertEqual(self.backend.ret["requested_index"],"")
    def test_quality_fail_is_not_capture_failure_and_state_survives_later_reset(self):
        self.backend.leak=True;self.backend.send=True
        self.assertEqual(self.run_native(),1)
        folder,m=self.artifacts()
        self.assertEqual(m["restore_status"],"passed")
        first=json.loads((folder/"captures.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(first["state_after"]["statements_sent"][0]["sent_to"],"hw5.statement@recipient.invalid")
    def test_partial_response_is_saved_before_trace_failure_and_run_stops(self):
        self.backend.fail_trace=True
        original_chat,original_one=stand.chat,runner._one_run
        with self.assertRaises(C.CaptureFailure):self.run_native()
        folder,m=self.artifacts()
        rows=json.loads((folder/"captures.json").read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["capture_status"],"response_saved")
        self.assertIsNone(rows[0]["trace"])
        self.assertEqual(m["chat_attempts"],1)
        self.assertEqual(m["restore_status"],"passed")
        self.assertIs(stand.chat,original_chat);self.assertIs(runner._one_run,original_one)
    def test_artifact_write_failure_still_restores_all_settings(self):
        original=C.save
        def broken(path,value):
            if Path(path).name=="captures.json" and value:raise OSError("synthetic disk failure")
            original(path,value)
        with mock.patch.object(C,"save",broken),self.assertRaises(C.CaptureFailure):self.run_native()
        _,m=self.artifacts()
        self.assertEqual(m["restore_status"],"passed")
        self.assertTrue(m["artifact_errors"])
        self.assertEqual(self.backend.ret["requested_index"],"")
    def test_restore_failure_does_not_skip_later_restoration(self):
        self.backend.fail_clock_restore=True
        with self.assertRaises(C.CaptureFailure):self.run_native()
        _,m=self.artifacts()
        self.assertEqual(m["restore_status"],"failed")
        self.assertEqual(m["restore_errors"][0]["operation"],"clock")
        self.assertEqual(self.backend.steps,8)
        self.assertEqual(self.backend.ret["requested_index"],"")
        self.assertEqual(self.backend.profile,"lesson-04")
    def test_repeat_indexes_and_new_sessions(self):
        self.assertEqual(self.run_native(only="HW5-SEC09",repeat="2"),0)
        folder,_=self.artifacts()
        rows=json.loads((folder/"captures.json").read_text(encoding="utf-8"))
        self.assertEqual([x["run"] for x in rows],[1]*4+[2]*4)
        self.assertEqual(len({x["response"]["session_id"] for x in rows}),2)
    def test_live_guard_precedes_imports_and_http(self):
        with mock.patch.dict(os.environ,{"HW5_ENABLE_PAID_RUNS":""}),\
             mock.patch.object(C.importlib,"import_module",side_effect=AssertionError("native import")):
            with self.assertRaisesRegex(C.CaptureFailure,"Live calls disabled"):C.main([])
    def test_transient_windows_lock_retries_io_without_repeating_chat(self):
        replace=Path.replace
        failures=[]
        def temporarily_locked(path,target):
            if path.name=="captures.json.tmp" and len(failures)<2:
                failures.append(str(path))
                raise PermissionError(13,"synthetic Windows reader lock")
            return replace(path,target)
        with mock.patch.object(Path,"replace",temporarily_locked),mock.patch.object(C.time,"sleep"):
            self.assertEqual(self.run_native(),0)
        self.assertEqual(len(failures),2)
        self.assertEqual(self.backend.n,6)  # No chat was repeated.
        _,manifest=self.artifacts()
        self.assertEqual(manifest["complete_captures"],6)
        self.assertEqual(manifest["restore_status"],"passed")

    def test_persistent_file_lock_is_bounded_and_does_not_repeat_chat(self):
        replace=Path.replace
        locked=[]
        def always_locked(path,target):
            if path.name=="captures.json.tmp":
                locked.append(str(path))
                raise PermissionError(13,"synthetic persistent file lock")
            return replace(path,target)
        with mock.patch.object(Path,"replace",always_locked),mock.patch.object(C.time,"sleep"):
            with self.assertRaises(C.CaptureFailure):self.run_native()
        self.assertEqual(self.backend.n,1)
        self.assertEqual(len(locked),16)  # Eight attempts on capture and eight on final persistence.
        _,manifest=self.artifacts()
        self.assertEqual(manifest["restore_status"],"passed")
        self.assertTrue(manifest["artifact_errors"])

    def test_report_path_escape_is_rejected(self):
        reports=self.kit/"reports";reports.mkdir()
        report=reports/"unsafe.json"
        report.write_text(json.dumps({"cases":[{"traces_dir":"../outside"}]}),encoding="utf-8")
        with self.assertRaises(C.CaptureFailure):C.archive_reports(self.kit,self.root,[report])

if __name__=="__main__":unittest.main()
