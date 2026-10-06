const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const {test}=require("node:test");
const script=fs.readFileSync(path.join(__dirname,"../endnote/web/dashboard.js"),"utf8");
const html=fs.readFileSync(path.join(__dirname,"../endnote/web/dashboard.html"),"utf8");
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.value="";this.attributes={};this.open=false;this.namespaceURI="http://www.w3.org/2000/svg";}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 setAttribute(key,value){this.attributes[key]=value;}
 get childElementCount(){return this.children.length;}
 showModal(){this.open=true;}
 close(){this.open=false;this.onclose?.();}
 set innerHTML(value){throw new Error("untrusted HTML insertion");}
}
function text(node){return (node.textContent||"")+node.children.map(text).join("");}
async function settle(){for(let i=0;i<20;i++)await Promise.resolve();}
function rows(app){return app.nodes.tasks.children.filter(row=>row.dataset.taskId);}
function setup(){
 const nodes=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element("div")]));
 const timers=new Map(),intervals=[],calls=[],events={},archived=new Set();let tick=0;
 const tasks=[{id:"1".repeat(32),name:"<img src=x onerror=alert(1)> seed42",status:"running",created:800,heartbeat:995,heartbeat_received:true,heartbeat_timeout:300,heartbeat_enabled:true,runtime_timeout:7200,outage:false,finished:null,metrics:{loss:.2},trend_metric:"loss",trend:[{time:900,value:.5},{time:950,value:.2}],notifications:[{kind:"started",state:"sent",created:800}]},{id:"2".repeat(32),name:"已成功的实验",status:"succeeded",created:700,heartbeat:900,heartbeat_received:true,heartbeat_timeout:300,heartbeat_enabled:true,runtime_timeout:null,outage:false,finished:900,metrics:{},trend_metric:null,trend:[],notifications:[{kind:"succeeded",state:"sent",created:900}]}];
 const document={getElementById:id=>nodes[id],createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),hidden:false,addEventListener:(name,fn)=>events[name]=fn};
 const fetch=async(url,options={})=>{calls.push({url,options});if(options.method==="POST"){const data=JSON.parse(options.body);if(data.archived)archived.add(data.task_id);else archived.delete(data.task_id);return{ok:true,json:async()=>({ok:true})};}
  const params=new URL(url,"https://fixture.invalid").searchParams;let shown=tasks.filter(t=>archived.has(t.id)===(params.get("archived")==="1"));if(params.get("task"))shown=shown.filter(t=>t.id===params.get("task"));
  const data={tasks:shown,total:shown.length,now:1000,summary:{running:1,waiting:0,outage:0,succeeded:archived.size?0:1,failed:0,cancelled:0},archived_count:archived.size,has_more:false,blocked:false};return{ok:true,json:async()=>data};};
 const context=vm.createContext({document,window:{addEventListener:(name,fn)=>events[name]=fn},location:{pathname:"/endnote/dashboard/"+"x".repeat(43)},fetch,AbortController,URLSearchParams,Date,setTimeout:(fn,delay)=>{timers.set(++tick,{fn,delay});return tick;},clearTimeout:id=>timers.delete(id),setInterval:(fn,delay)=>{intervals.push({fn,delay});return intervals.length;}});
 vm.runInContext(script,context);return{nodes,tasks,timers,intervals,calls,events,document,archived};
}
test("compact status rows render safe text and update automatically every five seconds",async()=>{
 const app=setup();await settle();assert.equal(rows(app).length,2);assert.ok(text(app.nodes.tasks).includes("<img src=x onerror=alert(1)>"));assert.ok(!html.includes('id="refresh"'));assert.equal(app.intervals[0].delay,5000);assert.ok(app.calls[0].url.includes("trends=0"));
 app.tasks[0].metrics.loss=.1;app.intervals[0].fn();await settle();assert.ok(text(app.nodes.tasks).includes("0.1"));assert.ok(text(app.nodes.summary).includes("全部"));
});
test("ended task archives from overview and restores without deleting data",async()=>{
 const app=setup();await settle();const runningAction=rows(app)[0].children.at(-1);assert.equal(runningAction.children.length,0);
 const archive=rows(app)[1].children.at(-1).children[0];await archive.onclick();await settle();assert.equal(rows(app).length,1);assert.equal(app.tasks.length,2);assert.ok(app.archived.has("2".repeat(32)));
 app.nodes.tabs.children[4].onclick();await settle();assert.equal(rows(app).length,1);assert.ok(text(app.nodes.tasks).includes("恢复"));
 await rows(app)[0].children.at(-1).children[0].onclick();await settle();assert.equal(app.archived.size,0);assert.equal(rows(app).length,0);
});
test("search goes to server and detail loads trends only when opened",async()=>{
 const app=setup();await settle();app.nodes.search.value="seed42";app.nodes.search.oninput();const debounce=[...app.timers.values()].find(t=>t.delay===250);assert.ok(debounce);debounce.fn();await settle();assert.ok(app.calls.at(-1).url.includes("q=seed42"));
 rows(app)[0].children[0].children[0].onclick();await settle();assert.equal(app.nodes.detail.open,true);assert.ok(app.calls.at(-1).url.includes("task="+"1".repeat(32)));assert.ok(app.calls.at(-1).url.includes("trends=1"));assert.ok(text(app.nodes["detail-content"]).includes("指标趋势"));app.nodes["close-detail"].onclick();assert.equal(app.nodes.detail.open,false);
});
test("offline and tab visibility explain stale data and reconnect automatically",async()=>{
 const app=setup();await settle();app.events.offline();assert.ok(app.nodes.connection.className.includes("stale"));assert.ok(text(app.nodes.notice).includes("上次更新"));const count=app.calls.length;app.events.online();await settle();assert.ok(app.calls.length>count);assert.ok(!app.nodes.connection.className.includes("stale"));app.document.hidden=true;const hiddenCount=app.calls.length;app.intervals[0].fn();await settle();assert.equal(app.calls.length,hiddenCount);
});

test("project groups keep attempts together in creation order across status updates",async()=>{
 const app=setup();await settle();
 const template=app.tasks[0];app.tasks.splice(0,app.tasks.length,
 {...template,id:"c",name:"卫星研究 回迁续跑",created:900,status:"running"},
 {...template,id:"b",name:"三维梁 第9轮",created:700},
 {...template,id:"a",name:"卫星研究 回迁续跑",created:800,status:"failed"},
 {...template,id:"d",name:"卫星研究 五模型",created:600,status:"cancelled"});
 app.intervals[0].fn();await settle();
 const order=rows(app).map(row=>row.dataset.taskId);
 assert.equal(app.nodes.tasks.children.filter(row=>row.dataset.groupKey&&!row.dataset.taskId).length,2);
 const satellite=rows(app).filter(row=>row.dataset.groupKey==="卫星研究");
 assert.deepEqual(satellite.map(row=>row.dataset.taskId),["d","a","c"]);
 assert.ok(text(satellite[1]).includes("记录 1/2"));assert.ok(text(satellite[2]).includes("记录 2/2"));
 app.tasks.reverse();app.tasks.find(t=>t.id==="c").status="succeeded";app.intervals[0].fn();await settle();
 assert.deepEqual(rows(app).map(row=>row.dataset.taskId),order);
 const header=app.nodes.tasks.children.find(row=>row.dataset.groupKey==="卫星研究"&&!row.dataset.taskId),button=header.children[0].children[0];
 button.onclick();assert.equal(rows(app).filter(row=>row.dataset.groupKey==="卫星研究").length,0);
 app.intervals[0].fn();await settle();
 const collapsed=app.nodes.tasks.children.find(row=>row.dataset.groupKey==="卫星研究"&&!row.dataset.taskId).children[0].children[0];
 assert.equal(collapsed.attributes["aria-expanded"],"false");assert.ok(text(collapsed).includes("3 条记录"));
 collapsed.onclick();assert.equal(rows(app).length,4);
});
