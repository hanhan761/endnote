const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const {test}=require("node:test");
const script=fs.readFileSync(path.join(__dirname,"../endnote/web/dashboard.js"),"utf8");
const html=fs.readFileSync(path.join(__dirname,"../endnote/web/dashboard.html"),"utf8");
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.value="";this.attributes={};this.open=false;this.namespaceURI="http://www.w3.org/2000/svg";}
 append(...nodes){for(const node of nodes)node.parent=this;this.children.push(...nodes);}
 click(){this.onclick?.();}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this); }
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
 const timers=new Map(),intervals=[],calls=[],events={},archived=new Set(),machines=[];let tick=0;
 const tasks=[{id:"1".repeat(32),name:"<img src=x onerror=alert(1)> seed42",status:"running",created:800,heartbeat:995,heartbeat_received:true,heartbeat_timeout:300,heartbeat_enabled:true,runtime_timeout:7200,outage:false,finished:null,metrics:{loss:.2},trend_metric:"loss",trend:[{time:900,value:.5},{time:950,value:.2}],notifications:[{kind:"started",state:"sent",created:800}]},{id:"2".repeat(32),name:"已成功的实验",status:"succeeded",created:700,heartbeat:900,heartbeat_received:true,heartbeat_timeout:300,heartbeat_enabled:true,runtime_timeout:null,outage:false,finished:900,metrics:{},trend_metric:null,trend:[],notifications:[{kind:"succeeded",state:"sent",created:900}]}];
 const document={getElementById:id=>nodes[id],createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),body:new Element("body"),hidden:false,addEventListener:(name,fn)=>events[name]=fn};
 const fetch=async(url,options={})=>{calls.push({url,options});if(options.method==="POST"){const data=JSON.parse(options.body);if(url.includes("/machines")){if(data.name){machines.push({id:"fixture-machine",name:data.name,state:"waiting",received:null,metrics:{}});return{ok:true,json:async()=>({id:"fixture-machine",script:"print(1)"})};}const machine=machines.find(m=>url.endsWith("/"+m.id));if(machine)machine.state=data.enabled?"online":"disabled";return{ok:true,json:async()=>({ok:true})};}if(data.archived)archived.add(data.task_id);else archived.delete(data.task_id);return{ok:true,json:async()=>({ok:true})};}
  if(url.endsWith("/machines"))return{ok:true,json:async()=>({machines})};
  const params=new URL(url,"https://fixture.invalid").searchParams;let shown=tasks.filter(t=>archived.has(t.id)===(params.get("archived")==="1"));if(params.get("task"))shown=shown.filter(t=>t.id===params.get("task"));
  const data={machines,tasks:shown,total:shown.length,now:1000,summary:{running:1,waiting:0,outage:0,succeeded:archived.size?0:1,failed:0,cancelled:0},archived_count:archived.size,has_more:false,blocked:false};return{ok:true,json:async()=>data};};
 const context=vm.createContext({document,window:{addEventListener:(name,fn)=>events[name]=fn},location:{pathname:"/endnote/dashboard/"+"x".repeat(43)},fetch,AbortController,URLSearchParams,Date,Blob,URL:{createObjectURL:()=>"blob:fixture",revokeObjectURL:()=>{}},setTimeout:(fn,delay)=>{timers.set(++tick,{fn,delay});return tick;},clearTimeout:id=>timers.delete(id),setInterval:(fn,delay)=>{intervals.push({fn,delay});return intervals.length;}});
 vm.runInContext(script,context);return{nodes,tasks,machines,timers,intervals,calls,events,document,archived};
}
test("compact status rows render safe text and update automatically every five seconds",async()=>{
 const app=setup();await settle();assert.equal(rows(app).length,2);assert.ok(text(app.nodes.tasks).includes("<img src=x onerror=alert(1)>"));assert.ok(!html.includes('id="refresh"'));assert.equal(app.intervals[0].delay,5000);assert.ok(app.calls[0].url.includes("trends=0"));
 app.tasks[0].metrics.loss=.1;app.intervals[0].fn();await settle();assert.ok(text(app.nodes.tasks).includes("0.1"));assert.equal(app.nodes.summary.children.length,0);assert.equal(app.nodes["machine-empty"].hidden,false);
});
test("ended task archives from overview and restores without deleting data",async()=>{
 const app=setup();await settle();const runningAction=rows(app)[0].children.at(-1);assert.equal(runningAction.children.length,0);
 const archive=rows(app)[1].children.at(-1).children[0];await archive.onclick();await settle();assert.equal(rows(app).length,1);assert.equal(app.tasks.length,2);assert.ok(app.archived.has("2".repeat(32)));
 app.nodes.tabs.children.find(button=>text(button).startsWith("已归档")).onclick();await settle();assert.equal(rows(app).length,1);assert.ok(text(app.nodes.tasks).includes("恢复"));
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
 assert.equal(app.nodes.tasks.children.length,4);assert.ok(app.nodes.tasks.children.every(row=>row.dataset.taskId));
 const satellite=rows(app).filter(row=>row.dataset.groupKey==="卫星研究");
 assert.deepEqual(satellite.map(row=>row.dataset.taskId),["d","a","c"]);
 assert.ok(text(satellite[1]).includes("记录 1/2"));assert.ok(text(satellite[2]).includes("记录 2/2"));
 app.tasks.reverse();app.tasks.find(t=>t.id==="c").status="succeeded";app.intervals[0].fn();await settle();
 assert.deepEqual(rows(app).map(row=>row.dataset.taskId),order);
 const colors=rows(app).filter(row=>row.dataset.groupKey==="卫星研究").map(row=>row.className.match(/cluster-tone-\d/)[0]);
 assert.equal(new Set(colors).size,1);
 assert.ok(satellite[0].className.includes("group-start"));assert.ok(!satellite[1].className.includes("group-start"));
 assert.equal(app.nodes.tasks.children.length,4);

});

test("queued is explicit, persists through heartbeats, and yields to outage or completion",async()=>{const app=setup();await settle();app.tasks[0].metrics.endnote_queued=1;app.intervals[0].fn();await settle();assert.ok(text(rows(app)[0]).includes("排队中"));assert.ok(!text(rows(app)[0]).includes("endnote_queued"));app.tasks[0].outage=true;app.intervals[0].fn();await settle();assert.ok(text(rows(app)[0]).includes("心跳失联"));app.tasks[0].outage=false;app.tasks[0].status="succeeded";app.intervals[0].fn();await settle();assert.ok(text(rows(app)[0]).includes("已成功"));app.tasks[0].status="running";app.tasks[0].metrics.endnote_queued=0;app.intervals[0].fn();await settle();assert.ok(text(rows(app)[0]).includes("运行中"));});

test("optional multi-machine dials replace task totals without inventing missing metrics",async()=>{
 const app=setup();await settle();const metrics={cpu_percent:24,cpu_temperature:55,memory_total:32*1024**3,memory_used:16*1024**3,disk_total:1024**4,disk_used:256*1024**3,gpus:[{index:0,name:"NVIDIA RTX 4090",percent:99,temperature:73,memory_total:24*1024**3,memory_used:8*1024**3,power:330},{index:1,name:"GPU second",percent:55,temperature:68,memory_total:24*1024**3,memory_used:4*1024**3}]};
 app.machines.push({id:"a",name:"<img onerror=alert(1)> workstation",state:"online",received:995,metrics},{id:"b",name:"云主机",state:"offline",received:800,metrics:{cpu_percent:null,gpus:[]}});app.intervals[0].fn();await settle();
 assert.equal(app.nodes.summary.children.length,2);assert.equal(app.nodes["machine-empty"].hidden,true);assert.ok(text(app.nodes["machine-count"]).includes("2 台"));assert.ok(text(app.nodes.summary).includes("99%"));assert.ok(text(app.nodes.summary).includes("GPU second"));assert.ok(text(app.nodes.summary).includes("离线 · 数据已过期"));assert.ok(text(app.nodes.summary).includes("温度暂无数据"));assert.ok(!text(app.nodes.summary).includes("已归档"));assert.equal(rows(app).length,2);
 app.machines[0].metrics.cpu_percent=70;app.intervals[0].fn();await settle();assert.ok(text(app.nodes.summary).includes("70%"));
 app.nodes["add-machine"].onclick();assert.equal(app.nodes["machine-setup"].open,true);app.nodes["close-machine-setup"].onclick();assert.equal(app.nodes["machine-setup"].open,false);
});

test("download enrollment and stopping telemetry keep experiment tasks intact",async()=>{const app=setup();await settle();app.nodes["machine-name"].value="第二台机器";await app.nodes["create-machine"].onclick();await settle();assert.equal(app.machines.length,1);assert.ok(text(app.nodes["machine-setup-notice"]).includes("脚本已下载"));assert.equal(rows(app).length,2);const stop=app.nodes.summary.children[0].children[0].children[1];await stop.onclick();await settle();assert.equal(app.machines[0].state,"disabled");assert.equal(rows(app).length,2);assert.ok(text(app.nodes.summary).includes("启用"));});

test("machine refresh uses the lightweight endpoint every second without rebuilding tasks",async()=>{
 const app=setup();await settle();app.machines.push({id:"cadence",name:"Host",state:"online",received:995,metrics:{cpu_percent:10,gpus:[]}});
 const taskRows=rows(app);const poll=app.intervals.find(t=>t.delay===1000);assert.ok(poll);await poll.fn();await settle();
 assert.ok(app.calls.at(-1).url.endsWith("/machines"));assert.equal(app.nodes.summary.children.length,1);assert.equal(rows(app)[0],taskRows[0]);
 app.machines[0].metrics.cpu_percent=60;await poll.fn();await settle();assert.ok(text(app.nodes.summary).includes("60%"));
 app.document.hidden=true;const count=app.calls.length;await poll.fn();await settle();assert.equal(app.calls.length,count);
});
