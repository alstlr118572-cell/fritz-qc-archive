const assert = require("node:assert/strict");
const vm = require("node:vm");
const { runStartup } = require("./test_client_startup");
const roasts = [1,2,3].map(n=>({id:`r${n}`,entryType:"roasting",blend:"올드독",batch:`#${n}`,roastDate:"2026-11-03",roastData:{roaster:"검댕이"}}));
function setup(options = {}, ids = ["r1","r2","r3"]) {
  const state = runStartup({mira_blend_qc_entries_v1:roasts}, {...options, allowWrites:true});
  state.context.testSelectedIds = ids;
  vm.runInContext(`selectedCuppingDate="2026-11-03"; selectedCuppingBatchIds=new Set(testSelectedIds); cuppingBatchFields.comment.value="#1~3 문제없음"; cuppingBatchFields.verdict.value="pass"; fields.roastDate.value="2026-11-03";`,state.context);
  state.submit = state.listeners.get("#cuppingBatchForm:submit")[0];
  return state;
}
let posted;
const saved = setup({onWrite:payload=>{posted=payload.value;}});
saved.submit({preventDefault(){}});
const comment = posted.find(e=>e.entryType==="cupping");
assert.deepEqual([...comment.sourceIds].sort(),["r1","r2","r3"]);
assert.equal(comment.batch,"#1~#3");
assert.equal(posted.filter(e=>e.entryType==="cupping").length,1,"three batches share one assessment record");
assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(entries.filter(e=>e.entryType==="roasting").map(dashboardEntryStatus))',saved.context)),["pass","pass","pass"]);
assert.equal(vm.runInContext('cuppingRoastingCandidates().length',saved.context),0);
assert.match(vm.runInContext('cuppingBatchFields.message.textContent',saved.context),/^3개 배치/);
assert.equal(vm.runInContext('selectedCuppingBatchIds.size',saved.context),0);

const failed = setup({writeStatus:500});
const before = vm.runInContext('JSON.stringify(entries)',failed.context);
assert.throws(()=>failed.submit({preventDefault(){}}));
assert.equal(vm.runInContext('JSON.stringify(entries)',failed.context),before,"a failed save must not mark batches completed in memory");
assert.equal(vm.runInContext('cuppingBatchFields.comment.value',failed.context),"#1~3 문제없음");
assert.equal(vm.runInContext('selectedCuppingBatchIds.size',failed.context),3);
assert.equal(vm.runInContext('cuppingRoastingCandidates().length',failed.context),3);

const stale = setup({},["r1","r2","missing"]);
stale.submit({preventDefault(){}});
assert.equal(stale.requests.length,1,"missing selected targets must block the save");
assert.equal(vm.runInContext('selectedCuppingBatchIds.size',stale.context),3);
assert.equal(vm.runInContext('cuppingBatchFields.comment.value',stale.context),"#1~3 문제없음");
console.log("Cupping bulk submit: three selected IDs, one grouped record, three verdicts, failed-save retention and stale-selection guard passed.");
