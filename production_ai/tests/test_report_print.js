const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { runStartup } = require("./test_client_startup");
const note = "원문 전체 유지 ".repeat(100) + "끝부분도 보존";
const roasts = [{id:"r",entryType:"roasting",blend:"올드독",roastDate:"2026-09-01",batch:"#1",roastData:{roaster:"검댕이"}}];
const comment = {id:"c",entryType:"cupping",blend:"올드독",roastDate:"2026-09-01",batch:"#1",createdBy:"a",evaluatorName:"평가 A",verdict:"pass",note,roastData:{roaster:"검댕이"}};
const {context,elements,listeners,requests}=runStartup({mira_blend_qc_entries_v1:[...roasts,comment]});
vm.runInContext('activeAppView="reports";reportAnchor="2026-09-01";renderQcReport()',context);
const read=code=>JSON.parse(vm.runInContext(`JSON.stringify(${code})`,context));
const original=read("reportContent.innerHTML");
const mapSize=read("reportTimelineRows.size");
assert.ok(original.includes(note));
const classes=new Set();
let root=null;
const node=()=>({
  children:[],events:new Map(),attributes:{},innerHTML:"",open:false,
  append(...children){this.children.push(...children);},
  remove(){if(this===root)root=null;this.removed=true;},
  removeAttribute(name){delete this.attributes[name];},
  querySelectorAll(){return[];},
  addEventListener(type,callback){this.events.set(type,callback);}
});
const content=node();
content.innerHTML=original;
const controls=[node(),node(),node()];
const disclosure=[{open:true},{open:false}];
const interactive=node();
interactive.attributes={role:"button",tabindex:"0","aria-pressed":"false","data-report-timeline-row":"timeline-0"};
content.querySelectorAll=selector=>({"button, input, select, .report-segments":controls,"details":disclosure,"[data-report-timeline-row]":[interactive]})[selector]||[];
elements.get("#reportContent").cloneNode=deep=>{assert.equal(deep,true);return content;};
const originalQuery=context.document.querySelector;
context.document.querySelector=selector=>selector==="#qcReportPrintRoot"?root:originalQuery(selector);
context.document.createElement=node;
context.document.body={append(value){root=value;},classList:{add:value=>classes.add(value),remove:value=>classes.delete(value)}};
context.document.title="Original title";
context.document.querySelector("#reportPeriodLabel").textContent="2026-09-01 ~ 2026-09-30 <unsafe>";
listeners.get("#reportPdfButton:click")[0]();
assert.ok(root&&classes.has("qc-report-previewing"));
assert.equal(root.children[1].children[1],content,"use the rendered report itself, not a second report builder");
assert.ok(root.children[1].children[0].innerHTML.includes("&lt;unsafe&gt;"));
assert.equal(content.innerHTML,original,"preserve graph, comment and numeric order/content without excerpts");
assert.equal(read("reportContent.innerHTML"),original,"leave the source report unchanged");
assert.deepEqual(disclosure,[{open:true},{open:false}],"do not expand or collapse details automatically");
assert.ok(controls.every(control=>control.removed));
assert.deepEqual(interactive.attributes,{});
assert.equal(read("reportTimelineRows.size"),mapSize,"do not rebuild charts or their controls");
let prints=0;
context.print=()=>{prints++;};
root.events.get("click")({target:{closest:()=>({dataset:{reportPdfAction:"print"}})}});
assert.equal(prints,1);
assert.ok(classes.has("qc-report-printing"));
vm.runInContext("finishQcReportPrint()",context);
assert.equal(root,null);
assert.equal(classes.size,0);
assert.equal(context.document.title,"Original title");
vm.runInContext("prepareQcReportPrint();prepareQcReportPrint();finishQcReportPrint()",context);
assert.equal(context.document.title,"Original title");
vm.runInContext("activeAppView='dashboard'",context);
assert.equal(vm.runInContext("prepareQcReportPrint()",context),false);
vm.runInContext("activeAppView='reports';prepareQcReportPrint()",context);
context.print=()=>{throw Error("unavailable");};
root.events.get("click")({target:{closest:()=>({dataset:{reportPdfAction:"print"}})}});
assert.equal(root,null);
assert.equal(classes.size,0);
assert.equal(requests.length,1,"printing must not save or refetch records");
const html=fs.readFileSync(path.join(__dirname,"..","mira_archive.html"),"utf8");
assert.match(html,/@page\s*\{\s*size:\s*A4 landscape/);
assert.ok(!html.includes("function buildQcReportPrintMarkup")&&!html.includes("function reportPrintExcerpt"));
console.log("A4 original report: exact rendered content/order, full notes, disclosure state, noninteractive controls, cleanup and read-only behavior passed.");
