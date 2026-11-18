const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { runStartup } = require("./test_client_startup");
const longNote = "문단 전체를 유지합니다.\n".repeat(100) + "원문 끝";
const entry = {id:"visit-print",entryType:"visit",visitDate:"2026-11-12",createdByName:"담당자",visitData:{
  customer:"테스트 고객",store:"테스트 상호 <script>",address:"테스트 주소",phone:"테스트 연락처",
  coffee:"올드독 / 서울시네마",monthlyUsage:"30kg",machine:"테스트 머신",grinder:"테스트 그라인더",basket:"20g",flowPressure:"9bar / 좌 240, 우 250",
  recipe:"추가 레시피 메모",storeFeature:longNote,beverageQuality:"음료 평가",equipment:"점검 내용",extra:"기타 <img src=x>",
  extractions:[{blend:"올드독",roastDate:"2026-11-10",batch:"#1",dose:"18",yield:"36",time:"27",tds:"10"},
    {blend:"서울시네마",roastDate:"2026-11-11",batch:"#2",dose:"20g",yield:"40g",time:"30s",tds:"9%",extractionYield:"18%"}]
}};
const {context,listeners,requests}=runStartup({mira_blend_qc_entries_v1:[entry]});
const read=code=>JSON.parse(vm.runInContext(`JSON.stringify(${code})`,context));
context.printVisitInput=entry;
const html=read("visitReportMarkup(printVisitInput)");
for(const label of ["도매거래처 방문일지","고객명","상호명","주소","전화번호","사용커피","월평균사용량","머신","그라인더","바스켓","머신 유량 및 압력","레시피","업장 및 상권특징","음료퀄리티","기기장비 관리상태","기타"]){assert.ok(html.includes(label),label);}
assert.ok(html.includes("Input: 18g / Output: 36g / Time: 27s / TDS: 10% / Ext: 20.00%"),html);
assert.ok(html.includes("Input: 20g / Output: 40g / Time: 30s / TDS: 9% / Ext: 18%"));
assert.ok(!html.includes("gg")&&!html.includes("%%"));
assert.ok(html.includes(longNote)&&html.includes("원문 끝"));
assert.ok(html.includes("&lt;script&gt;")&&html.includes("&lt;img src=x&gt;"));
assert.ok(!html.includes("<script>")&&!html.includes("<img src=x>"));
assert.ok(html.includes("2026-11-12")&&html.includes("담당자"));
assert.ok(html.includes("추가 레시피 메모"));
context.legacyVisit={entryType:"visit",visitData:{dose:"18",yield:"36",time:"26",tds:"10",recipe:"예전 메모"}};
assert.ok(read("visitReportMarkup(legacyVisit)").includes("Ext: 20.00%"));
const emptyReport=read('visitReportMarkup({entryType:"visit",visitData:{extractions:[{}]}})');
assert.ok(emptyReport.includes("도매거래처 방문일지"));
assert.ok(!emptyReport.includes("undefined")&&!emptyReport.includes("NaN"));
assert.ok(read("visitCardMarkup(printVisitInput)").includes('data-print-visit="visit-print"'));
const screenReport=read("visitCardMarkup(printVisitInput)");
assert.ok(screenReport.includes('class="visit-report-record"'));
assert.ok(screenReport.includes(read("visitReportMarkup(printVisitInput,true)")),"screen and PDF must use the same report structure");
assert.ok(!screenReport.includes('class="comment-field-block"')&&!screenReport.includes('class="qc-body"'));
assert.equal(screenReport.split(longNote).length-1,1,"do not repeat a summary and the same full note");
assert.ok(!read("visitCardMarkup(printVisitInput,true)").includes('data-print-visit'));
const classes=new Set();
let root=null;
const node=()=>({children:[],events:new Map(),innerHTML:"",append(...children){this.children.push(...children);},remove(){if(this===root)root=null;},addEventListener(t,f){this.events.set(t,f);}});
const query=context.document.querySelector;
context.document.querySelector=s=>s==="#qcReportPrintRoot"?root:query(s);
context.document.createElement=node;
context.document.body={append(value){root=value;},classList:{add:v=>classes.add(v),remove:v=>classes.delete(v)}};
context.document.title="원래 제목";
assert.equal(vm.runInContext('prepareVisitReportPrint("missing")',context),false);
listeners.get("#visitRecentList:click")[0]({target:{closest:s=>s==="[data-print-visit]"?{dataset:{printVisit:"visit-print"}}:null}});
assert.equal(root.children[1].className,"visit-print-document");
assert.ok(root.children[1].innerHTML.includes("원문 끝"));
assert.ok(classes.has("qc-report-previewing"));
assert.ok(context.document.title.includes("2026-11-12"));
vm.runInContext("finishQcReportPrint()",context);
assert.equal(root,null);
assert.equal(context.document.title,"원래 제목");
vm.runInContext('approvedSessionUser=()=>({id:"viewer",userId:"viewer",role:"user",status:"approved",permissions:[]})',context);
assert.equal(vm.runInContext('prepareVisitReportPrint("visit-print")',context),false);
assert.ok(!read("visitCardMarkup(printVisitInput)").includes("data-print-visit"));
assert.equal(requests.length,1,"export must not save or refetch records");
assert.equal(read("entries[0].visitData.storeFeature"),longNote);
const source=fs.readFileSync(path.join(__dirname,"..","mira_archive.html"),"utf8");
assert.match(source,/@page visit-report\s*\{\s*size:\s*A4 portrait/);
assert.match(source,/@page\s*\{\s*size:\s*A4 landscape/);
console.log("Visit report: template fields, multiple/legacy recipes, yield, full multiline notes, escaping, permission guards, delegated PDF controls, cleanup and read-only export passed.");
