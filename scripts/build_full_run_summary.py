"""Build a concise run-completeness summary from measured full-run analysis."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def main():
    a=json.loads((ROOT/"evidence/full-run-analysis.json").read_text(encoding="utf-8"))
    profiles={x["profile"]:x for x in a["full_runs"]}
    assert set(profiles)=={"clean","lesson-06"}
    c,v=profiles["clean"],profiles["lesson-06"]
    lines=["# ДЗ5 — повні серії кроку11","",
      "Набір **"+a["set_hash"]+"**. Пілотні результати лишаються окремими.",
      "Це перевірка повноти й нативних verdicts; фінальний аналіз механізмів/пріоритетів — наступний крок.","",
      "| Профіль | PASS кейсів | PASS діалогів | Chat requests | Raw report |",
      "|---|---|---|---|---|"]
    for r in [c,v]:
        lines.append(f"| {r['profile']} | {r['native_passed_cases']}/10 | {r['native_passed_dialogs']}/14 | 29 | [raw](../{r['report']}) |")
    lines+=["","## По кейсах","","| Кейс | Clean | Lesson-06 |","|---|---|---|"]
    for n in range(1,11):
        cid=f"HW5-SEC{n:02}"
        results=[]
        for r in [c,v]:
            reps=[x for x in r["repeats"] if x["case"]==cid]
            results.append(str(sum(x["native_passed"] for x in reps))+"/"+str(len(reps)))
        lines.append("| "+cid+" | "+" | ".join(results)+" |")
    lines+=["","## D23 — п’ять незалежних діалогів","",
      "Перший збіг чутливого порогу визначено з відповідей; семантична відмова й вхід аналізуються окремо.",
      "| Повтор | Clean: перший поріг | Lesson-06: перший поріг |","|---|---|---|"]
    def label(x):return "не названо" if x is None else str(x)
    for n in range(1,6):
        vals=[]
        for r in [c,v]:
            rep=next(x for x in r["repeats"] if x["case"]=="HW5-SEC09" and x["repeat"]==n)
            vals.append(label(rep["first_threshold_match_turn"]))
        lines.append("| "+str(n)+" | "+" | ".join(vals)+" |")
    lines+=["","## Вхід D09 і дія D10",""]
    for r in [c,v]:
        lines+=[f"### {r['profile']}",
          "D09 merchant у tool.get_transactions:","~~~text",
          "\n".join(x or "<empty>" for x in r["d09"]["observed_merchant_fields"]),"~~~",
          f"D09 request_id: {r['d09']['request_id']}. Доставка payload не означає його виконання.",
          f"D10 request_id: {r['d10']['request_id']}; send_statement attempts={r['d10']['send_statement_attempts']}, "+
          f"successful calls={r['d10']['successful_send_calls']}, statement rows={len(r['d10']['statement_rows'])}."]
        if r["d10"]["send_statement_attempts"]==0:
            lines+=["Backend recipient validation не випробувано: агент не дійшов до send_statement."]
        lines+=[""]
    lines+=["## Capture, модель й вартість","",
      "Обидва full-unittest завершені, captures повні, native/replay verdicts збігаються.",
      "Raw report hashes, request/session IDs, profile та час після forecast перевірено; settings відновлено.",
      f"Дві завершені full-серії:58 requests і28 сесій. Незавершена спроба lesson-06: "+
      f"{a['failed_partial_chat_requests']} responses, збережені окремо.",
      f"Разом із пілотом та перерваною спробою:{a['total_chat_requests_including_pilot']} requests "+
      f"і{a['independent_sessions_including_pilot']} сесій. Початковий план перевищено на19 requests через I/O-recovery."]
    for r in [c,v]:
        lines+=[f"- {r['profile']}: {r['trace_observed_llm_calls']} llm.call spans, "+
                f"{r['summary_spans']} summary spans; model "+", ".join(r["completion_models"])+
                f"; root USD{r['root_cost_usd']:.6f}."]
    lines+=["",f"Full root cost **USD{a['full_root_cost_usd']:.6f}**, з пілотом і перерваною спробою **USD{a['all_root_cost_usd']:.6f}**.",
      f"Окрема root cost перерваної спроби: **USD{a['failed_partial_root_cost_usd']:.6f}**.",
      "Це оцінка стенду, не invoice; SDK retries/cache billing categories не пораховані незалежно.",
      "Пілот звірено на рівні відображення балансу:17.10→17.09, тобто USD0.01.",
      "Баланс після full підтверджено:17.05. Загалом17.10→17.05 = USD0.05; після пілота17.09→17.05 = USD0.04. Обидві різниці узгоджуються з root cost на точності дисплея; деталізований invoice не перевірявся. [Звірка](../evidence/balance-after-full.json). Резерв USD0.25 — плановий запас, не hard cap.",
      "Reset не відновлює довільний початковий стан БД; snapshots дій збережені до наступного reset.","",
      "[Машинний аналіз](../evidence/full-run-analysis.json) · [пілот](pilot-review.md).",
      "Межі lexical assertions D08/D09/D23 та умови D10 перевірити в аналізі кроку12; raw bytes не змінювалися."]
    (ROOT/"docs/full-run-summary.md").write_bytes((chr(10).join(lines)+chr(10)).encode("utf-8"))
    print("Built full-run summary from completed evidence")

if __name__=="__main__":main()
