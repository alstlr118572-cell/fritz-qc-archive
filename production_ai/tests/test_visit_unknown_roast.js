const assert = require("node:assert/strict");
const vm = require("node:vm");
const {runStartup} = require("./test_client_startup");
const roast = {id:"r1",entryType:"roasting",blend:"올드독",batch:"#1",roastDate:"2026-11-16",roastData:{}};
const {context,listeners,requests} = runStartup({mira_blend_qc_entries_v1:[roast]});
const read = code => JSON.parse(vm.runInContext(`JSON.stringify(${code})`,context));
context.unknown = {roastStatus:"unknown_date",roastEntryId:"r1",roastDate:"2026-11-16",blend:"올드독",batch:"#1",dose:"18",yield:"36",tds:"10"};
const unknown = read("normalizedVisitExtraction(unknown)");
assert.equal(unknown.roastDate,"");
assert.equal(unknown.roastEntryId,"");
assert.equal(unknown.batch,"");
assert.equal(unknown.blend,"올드독");
assert.equal(unknown.extractionYield,"20.00%");
context.dated = {...context.unknown,roastStatus:"unknown_batch"};
const dated = read("normalizedVisitExtraction(dated)");
assert.equal(dated.roastDate,"2026-11-16");
assert.equal(dated.roastEntryId,"");
assert.equal(dated.batch,"");
assert.equal(read('visitRoastingBatchOptionMarkup(dated)').includes('value="__unknown_batch__" selected'),true);
assert.equal(read('visitRoastingBatchOptionMarkup(unknown)').includes('value="__unknown_date__" selected'),true);
assert.equal(read('visitRoastingBatchOptionMarkup(dated)').includes('value="r1" data-blend="올드독" data-batch="#1" selected'),false,"unknown batch must not auto-match batch #1");
assert.equal(read('visitExtractionRowMarkup(unknown)').includes('value="" disabled'),true);
assert.equal(read('visitExtractionRowMarkup(dated)').includes('value="2026-11-16" required'),true);
assert.equal(read('visitExtractionRowMarkup(dated)').includes('data-visit-unknown-blend required'),true);
assert.equal(read('visitExtractionRowMarkup({roastEntryId:"r1",roastDate:"2026-11-16"})').includes('data-visit-unknown-blend-field hidden'),true);
context.visit = {entryType:"visit",visitDate:"2026-11-18",visitData:{coffee:"올드독",beverageQuality:"올드독 11/1 #1",extractions:[context.unknown,context.dated]}};
for (const screen of [true,false]) {
  const report = read(`visitReportMarkup(visit,${screen})`);
  assert.ok(report.includes("올드독 · 로스팅일자 불분명"));
  assert.ok(report.includes("2026-11-16 · 배치번호 불분명"));
  assert.ok(!report.match(/<strong>[^<]*#1/),"never show a stale batch link in recipe context");
}
assert.deepEqual(read("buildVisitExportRows([visit]).map(row=>row[2])"),["","26.11.16."],"explicit unknown state takes precedence over dates in notes");

const nodes = {
  "[data-visit-roast-entry]":{value:"__unknown_date__",selectedOptions:[{dataset:{}}]},
  "[data-visit-roast-date]":{value:"2026-11-16",disabled:false,required:false},
  "[data-visit-unknown-blend]":{value:"올드독",required:false},
  "[data-visit-unknown-blend-field]":{hidden:true},
  "[data-visit-dose]":{value:"18"},"[data-visit-yield]":{value:"36"},
  "[data-visit-time]":{value:"27"},"[data-visit-tds]":{value:"10"},"[data-visit-extraction-yield]":{value:"20.00%"}
};
context.testRow = {querySelector:selector=>nodes[selector]};
const change = listeners.get("#visitExtractionList:change")[0];
const event = {target:{matches:selector=>selector==="[data-visit-roast-entry]",closest:()=>context.testRow}};
change(event);
assert.equal(nodes["[data-visit-roast-date]"].disabled,true);
assert.equal(nodes["[data-visit-roast-date]"].value,"");
assert.equal(nodes["[data-visit-unknown-blend-field]"].hidden,false);
assert.equal(read("selectedVisitExtractionFromRow(testRow).roastStatus"),"unknown_date");
nodes["[data-visit-roast-entry]"].value="__unknown_batch__";
change(event);
assert.equal(nodes["[data-visit-roast-date]"].disabled,false);
assert.equal(nodes["[data-visit-roast-date]"].required,true);
nodes["[data-visit-roast-date]"].value="2026-11-16";
assert.equal(read("selectedVisitExtractionFromRow(testRow).roastDate"),"2026-11-16");
nodes["[data-visit-roast-entry]"].value="r1";
nodes["[data-visit-roast-entry]"].selectedOptions=[{dataset:{blend:"올드독",batch:"#1"}}];
change(event);
assert.equal(nodes["[data-visit-unknown-blend-field]"].hidden,true);
assert.equal(nodes["[data-visit-unknown-blend]"].required,false);
assert.equal(read("selectedVisitExtractionFromRow(testRow).roastEntryId"),"r1");
assert.equal(read("selectedVisitExtractionFromRow(testRow).batch"),"#1");
assert.equal(requests.length,1,"display state must not write records");
console.log("Visit unknown roast: normalization, no guessed links, options, editing, date/coffee constraints, recipe preservation, screen/PDF labels and CSV passed.");
