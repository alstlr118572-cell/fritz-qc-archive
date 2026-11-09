const assert = require("node:assert/strict");
const vm = require("node:vm");
const { runStartup } = require("./test_client_startup");

const roast = (id, batch, extra = {}) => ({
  id, batch, entryType: "roasting", blend: "올드독", roastDate: "2026-11-03",
  roastData: { roaster: "검댕이" }, ...extra
});
const cup = (batch) => ({
  id: "cup", batch, entryType: "cupping", blend: "올드독", roastDate: "2026-11-03",
  roastData: { roaster: "검댕이" }, verdict: "pass", createdBy: "test-admin", note: "문제 없음"
});
function scenario(batch) {
  const records = [roast("r1", "#1"), roast("r2", "#2 (드립백)"), roast("r3", "#3 (50kg)"),
    roast("r4", "#4"), roast("yellow", "#2", { roastData: { roaster: "노랭이" } }),
    roast("other-date", "#2", { roastDate: "2026-11-04" }),
    roast("strong", "#2", { blend: "올드독 강배전" }), cup(batch)];
  const before = JSON.stringify(records);
  const { context } = runStartup({ mira_blend_qc_entries_v1: records });
  const result = JSON.parse(vm.runInContext(`JSON.stringify(entries.filter(e=>e.entryType==='roasting').map(e=>({id:e.id,status:dashboardEntryStatus(e),completed:isRoastingBatchCompletedByEvaluator(e,entries.filter(isCuppingVerdictEntry))})))`, context));
  assert.equal(JSON.stringify(records), before, "startup must not mutate the stored fixture");
  for (const id of ["r1", "r2", "r3"]) {
    assert.equal(result.find(r=>r.id===id).status, "pass", `${batch}: ${id} verdict`);
    assert.equal(result.find(r=>r.id===id).completed, true, `${batch}: ${id} evaluator completion`);
  }
  for (const id of ["r4", "yellow", "other-date", "strong"]) {
    assert.equal(result.find(r=>r.id===id).status, "pending", `${batch}: must not cover ${id}`);
    assert.equal(result.find(r=>r.id===id).completed, false);
  }
  return context;
}
for (const batch of ["#1~3", "#1 ~ #3", "1-3", "#1～3", "#1〜#3", "#1–3", "#1—3", "#3~1"]) {
  scenario(batch);
}
const context = scenario("#1~3");
assert.equal(vm.runInContext('evaluatorCompletedCuppingEntries("2026-11-03", {id:"other", userId:"other", name:"Other"}).length', context), 0, "another evaluator must retain their own pending batches");
assert.equal(vm.runInContext('batchNumberRange("#2 (강)")', context), null);
assert.equal(vm.runInContext('batchNumberRange("잘2(제품용)")', context), null, "do not guess numbers in arbitrary text");
assert.equal(vm.runInContext('batchNumberRange("샘플 50kg")', context), null);
assert.equal(vm.runInContext('parseQuickCuppingComments("검올 #1～3 문제없음")[0].batch', context), "#1~#3");
assert.equal(vm.runInContext('parseQuickCuppingComments("노잘 #1–3 문제없음")[0].roaster', context), "노랭이");
assert.equal(vm.runInContext(`cuppingCoversRoastingEntry({entryType:'cupping',sourceIds:['exact'],blend:'올드독',roastDate:'2026-11-03',batch:'#1'}, {id:'exact',entryType:'roasting',blend:'올드독',roastDate:'2026-11-03',batch:'잘2(제품용)'})`, context), true);
const noteOnly = runStartup({mira_blend_qc_entries_v1:[roast("n1", "#1"),roast("n2", "#2"),{...cup("#1"),note:"#1~3 문제없음"}]}).context;
assert.equal(vm.runInContext('dashboardEntryStatus(entries.find(e=>e.id==="n2"))',noteOnly), "pending", "prose must not expand an explicitly selected target");
const locked = runStartup({mira_blend_qc_entries_v1:[roast("locked", "#2"),cup("#1~3")],mira_blend_qc_non_ship_results_v1:[{id:"lock",blend:"올드독",roastDate:"2026-11-03",batch:"#2",resultDate:"2026-11-03"}]}).context;
assert.equal(vm.runInContext('dashboardEntryStatus(entries.find(e=>e.id==="locked"))',locked), "issue", "existing ISSUE lock must survive range matching");
console.log("Cupping ranges: inclusive coverage, annotations, separators, evaluator completion and isolation passed.");
