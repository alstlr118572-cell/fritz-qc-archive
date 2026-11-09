const assert = require("node:assert/strict");
const vm = require("node:vm");
const { runStartup } = require("./test_client_startup");

const roast = (id, batch, extra = {}) => ({
  id, batch, entryType: "roasting", blend: "올드독", roastDate: "2026-10-31",
  roastData: { roaster: "검댕이", roastTime: '14"05', dropTemp: "174.5" }, ...extra
});
const cup = (id, extra = {}) => ({
  id, entryType: "cupping", blend: "올드독", roastDate: "2026-10-31", batch: "#1~3",
  roastData: { roaster: "검댕이" }, evaluatorName: "평가 A", createdBy: id,
  verdict: "pass", note: "이상 없음", ...extra
});
const records = [roast("r1", "#1"), roast("r2", "#2"), roast("r3", "#3"),
  roast("yellow", "#1", { roastData: { roaster: "노랭이", roastTime: "", dropTemp: "bad" } }),
  roast("nov", "#1", { roastDate: "2026-11-01" }),
  roast("oem", "#1", { blend: "문지리" }),
  cup("cup1"), cup("cup2", { evaluatorName: "평가 B", verdict: "hold", tags: ["바디감 가벼움", "바디감 가벼움"], note: "바디감 가벼움" }),
  cup("orphan", { batch: "#99" }),
  { id: "private", entryType: "correction", roastDate: "2026-10-31", note: "PRIVATE SOLUTION" }
];
const { context, elements, requests, listeners } = runStartup({ mira_blend_qc_entries_v1: records });
const read = (code) => JSON.parse(vm.runInContext(`JSON.stringify(${code})`, context));
assert.deepEqual(read('reportPeriod("2026-11-01", "week")'), { start: "2026-10-26", end: "2026-11-01" });
assert.deepEqual(read('reportPeriod("2027-01-01", "week")'), { start: "2026-12-28", end: "2027-01-03" });
assert.deepEqual(read('reportPeriod("2028-02-20", "month")'), { start: "2028-02-01", end: "2028-02-29" });
assert.deepEqual(read('reportPeriod("2028-02-20", "year")'), { start: "2028-01-01", end: "2028-12-31" });
assert.equal(read('reportMetricValue(\'14"05\', "roastTime")'), 845);
assert.equal(read('reportMetricValue("14:05", "roastTime")'), 845);
for (const value of ["", "14:60", "bad", "0:00"]) {
  context.metricInput = value;
  assert.equal(read('reportMetricValue(metricInput, "roastTime")'), null);
}
assert.equal(read('reportMetricValue("174.5°C", "dropTemp")'), 174.5);
assert.equal(read('reportMetricValue("", "dropTemp")'), null);
assert.equal(read('reportMetricValue("174abc", "dropTemp")'), null);
const model = read('buildQcReport(entries, reportPeriod("2026-10-31", "month"))');
assert.equal(model.roasting.length, 5);
assert.deepEqual(model.counts, { pass: 0, hold: 3, pending: 2, issue: 0 });
assert.equal(model.commentCount, 2, "range comments must count once, not once per covered batch");
assert.equal(model.unmatched.length, 1, "unmatched comments must not affect batch counts");
assert.equal(model.cuppingGroups.length, 1, "private correction records are not cupping comments");
assert.equal(read('buildQcReport(entries, reportPeriod("2026-10-31", "month"), "올드독", "노랭이").roasting.length'), 1);
assert.equal(read('buildQcReport(entries, reportPeriod("2026-10-31", "week")).roasting.length'), 6);
assert.equal(read('buildQcReport(entries, reportPeriod("2025-01-01", "month")).roasting.length'), 0);
assert.equal(read('reportFlavorComment({note:"문제향미지표: 바디 약함 / 로스팅 문제 진단: PRIVATE / 솔루션: PRIVATE"})'), "바디 약함");
assert.equal(read('reportFlavorComment({note:"로스팅 문제 진단: PRIVATE"})'), "");
assert.equal(read('reportFlavorComment({note:"단맛 부족\\n솔루션: PRIVATE"})'), "단맛 부족");
assert.ok(read('reportCommentSourceMarkup({note:"<img src=x>",evaluatorName:"<script>"})').includes("&lt;img"));
vm.runInContext('activeAppView="reports"; reportAnchor="2026-10-31"; renderQcReport()', context);
let html = elements.get("#reportContent").innerHTML;
assert.ok(html.includes("가장 많이 기록된 문제향미: 바디감 가벼움 (1건)"));
assert.ok(html.includes("평가 A") && html.includes("평가 B"));
assert.ok(html.includes("시작온도 · 미수집"));
assert.ok(html.includes("산점도"));
assert.ok(!html.includes("PRIVATE SOLUTION"));
assert.ok(html.includes('class="report-flavor-bar"'), "issue counts must have proportional bars");
assert.ok(html.includes('class="report-flavor-days"'), "include a dated visual timeline");
assert.ok(html.includes('class="report-date-list"'), "retain expandable chronological source comments");
assert.equal((html.match(/class="report-flavor-day /g) || []).length, 31);
context.timelineFixture = [
  ...Array.from({length: 7}, (_, index) => ({ id: `trend-${index}`, roastDate: index < 4 ? "2026-10-02" : "2026-10-05", batch: "#1~3", tags: ["향미톤 낮음", "향미톤 낮음"], evaluatorName: `평가 ${index % 2}` })),
  {id:"no-types",roastDate:"2026-10-06",tags:[]},
  {id:"outside",roastDate:"2026-11-01",tags:["향미톤 낮음"]}
];
const timeline = read('reportFlavorTimeline(timelineFixture, reportPeriod("2026-10-01", "month")).map(day => ({date:day.date,count:day.comments.length,total:day.total,types:[...day.types]}))');
assert.equal(timeline.length, 31);
assert.equal(timeline.reduce((sum, day) => sum + day.total, 0), 7, "seven range comments must produce seven events, not 21 batch events");
assert.deepEqual(timeline[1], {date:"2026-10-02",count:4,total:4,types:[["향미톤 낮음",4]]});
assert.equal(timeline[4].total, 3);
assert.equal(timeline[5].count, 1, "evaluated with no issue types must be distinct from no evaluation");
assert.equal(timeline[5].total, 0);
assert.equal(timeline[6].count, 0);
assert.equal(read('reportFlavorTimeline([], reportPeriod("2027-01-01", "week")).length'), 7);
assert.equal(read('reportFlavorTimeline([], reportPeriod("2028-02-01", "month")).length'), 29);
const trendHtml = read('reportFlavorVisualMarkup({blend:"올드독",comments:timelineFixture.slice(0,8),types:new Map([["향미톤 낮음",7]])}, reportPeriod("2026-10-01", "month"))');
assert.ok(trendHtml.includes('aria-label="향미톤 낮음 7건"'));
assert.ok(trendHtml.includes('width:100%'));
assert.ok(!trendHtml.includes('<small>30</small>'), "avoid adjacent 30/31 labels overlapping on mobile");
assert.ok(trendHtml.includes('<small>31</small>'));
assert.ok(trendHtml.includes('2026-10-02 · 평가 4건 · 향미톤 낮음 4건'));
assert.ok(trendHtml.includes('2026-10-06 · 평가 1건 · 선택된 문제향미 유형 없음'));
assert.ok(trendHtml.includes('2026-10-07 · 평가 기록 없음'));
assert.equal(read('reportFlavorTimeline(timelineFixture.slice(0,8),reportPeriod("2026-10-01","year")).length'),12);
assert.equal(read('reportFlavorTimeline(timelineFixture.slice(0,8),reportPeriod("2026-10-01","year")).reduce((sum,month)=>sum+month.total,0)'),7);
elements.get("#reportMonthInput").value = "";
listeners.get("#reportMonthInput:change")[0]();
assert.equal(read('reportMode'), "year");
assert.equal(elements.get("#reportDateInput").value, "2026");
listeners.get("#reportNextButton:click")[0]();
assert.equal(read('reportPeriod(reportAnchor, reportMode).start'), "2027-01-01");
elements.get("#reportMonthInput").value = "09";
listeners.get("#reportMonthInput:change")[0]();
assert.equal(read('reportAnchor'), "2027-09-01");
assert.equal(read('reportMode'), "month");
assert.equal(requests.length, 1, "reports must not fetch repeatedly or write any data");
vm.runInContext('users = users.map(user => ({...user,userId:"viewer",role:"viewer",permissions:[]})); setAppView("reports")', context);
assert.equal(read('activeAppView'), "reports", "approved read-only users may view the public report");
assert.ok(!elements.get("#reportContent").innerHTML.includes("PRIVATE"));

const locked = runStartup({
  mira_blend_qc_entries_v1: [roast("lock", "#2"), cup("pass")],
  mira_blend_qc_non_ship_results_v1: [{ id: "disposal", blend: "올드독", roastDate: "2026-10-31", batch: "#2", resultDate: "2026-10-31", note: "SECRET DISPOSAL" }]
}).context;
assert.equal(vm.runInContext('buildQcReport(entries, reportPeriod("2026-10-31", "month")).issues.length', locked), 1);
vm.runInContext('activeAppView="reports"; reportAnchor="2026-10-31"; renderQcReport()', locked);
assert.ok(!vm.runInContext('reportContent.innerHTML', locked).includes("SECRET DISPOSAL"));
const orderRecords = [
  ["너티트리니티","노랭이"], ["디카페인","노랭이"], ["서울시네마","노랭이"], ["잘되어 가시나","노랭이"],
  ["올드독","노랭이"], ["서울시네마","검댕이"], ["잘되어 가시나","검댕이"], ["올드독","검댕"]
].map(([blend,roaster],index)=>roast(`order-${index}`,"#1",{blend,roastDate:blend==="너티트리니티"?"2026-01-10":"2026-10-31",roastData:{roaster,roastTime:"14:00",dropTemp:"175"}}));
const ordered = runStartup({mira_blend_qc_entries_v1:orderRecords}).context;
assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(buildQcReport(entries,reportPeriod("2026-10-31","year")).groups.map(group=>[group.blend,group.roaster]))',ordered)),[
  ["올드독","검댕이"],["올드독","노랭이"],["잘되어 가시나","검댕이"],["잘되어 가시나","노랭이"],
  ["서울시네마","검댕이"],["서울시네마","노랭이"],["디카페인","노랭이"],["너티트리니티","노랭이"]
]);
vm.runInContext('activeAppView="reports";reportAnchor="2026-10-31";renderQcReport()',ordered);
const annualHtml = vm.runInContext('reportContent.innerHTML',ordered);
assert.ok(annualHtml.includes("너티트리니티"), "a low-volume blend must keep its January history in the annual chart when October is selected");
assert.ok(annualHtml.includes("2026-10 평균 미기록 · 0배치"));
assert.equal(vm.runInContext('buildQcReport(entries,reportPeriod(reportAnchor,"month")).roasting.length',ordered),7,"monthly KPI must not include annual background batches");
console.log("QC reports: date boundaries, metrics, batch counts, filters, evaluator separation, issue locks, privacy and read-only rendering passed.");
