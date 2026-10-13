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
 insertBefore(node,next){node.parent=this;const i=this.children.indexOf(next);this.children.splice(i<0?this.children.length:i,0,node);}
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
function rowFor(app,id="1".repeat(32)){return rows(app).find(row=>row.dataset.taskId===id);}
function rows(app){return app.nodes.tasks.children.filter(row=>row.dataset.taskId);}
function setup(){
 const pending=[];let hold=false,readStatus=200,writeStatus=200,retryAfter="",clock=Date.now();
 class Clock extends Date{constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}}
 const nodes=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element("div")]));
 const timers=new Map(),intervals=[],calls=[],events={},archived=new Set(),machines=[];let tick=0;
 const tasks=[{id:"1".repeat(32),name:"<img src=x onerror=alert(1)> seed42",status:"running",created:800,heartbeat:995,heartbeat_received:true,heartbeat_timeout:300,heartbeat_enabled:true,runtime_timeout:7200,outage:false,finished:null,metrics:{loss:.2},trend_metric:"loss",trend:[{time:900,value:.5},{time:950,value:.2}],notifications:[{kind:"started",state:"sent",created:800}]},{id:"2".repeat(32),name:"已成功的实验",status:"succeeded",created:700,heartbeat:900,heartbeat_received:true,heartbeat_timeout:300,heartbeat_enabled:true,runtime_timeout:null,outage:false,finished:900,metrics:{},trend_metric:null,trend:[],notifications:[{kind:"succeeded",state:"sent",created:900}]}];
 const document={getElementById:id=>nodes[id],createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),body:new Element("body"),hidden:false,addEventListener:(name,fn)=>events[name]=fn};
 const fetch=async(url,options={})=>{calls.push({url,options});if(hold){await new Promise((resolve,reject)=>{pending.push({url,resolve,reject});options.signal?.addEventListener("abort",()=>reject(Object.assign(new Error("aborted"),{name:"AbortError"})),{once:true});});}if(options.method==="POST"){if(writeStatus!==200)return{ok:false,status:writeStatus,json:async()=>({error:"服务暂不可用"})};const data=JSON.parse(options.body);if(url.includes("/machines")){if(data.name){machines.push({id:"fixture-machine",name:data.name,state:"waiting",received:null,metrics:{}});return{ok:true,json:async()=>({id:"fixture-machine",script:"print(1)"})};}const machine=machines.find(m=>url.endsWith("/"+m.id));if(machine)machine.state=data.enabled?"online":"disabled";return{ok:true,json:async()=>({ok:true})};}if(data.archived)archived.add(data.task_id);else archived.delete(data.task_id);return{ok:true,json:async()=>({ok:true})};}
  if(readStatus!==200)return{ok:false,status:readStatus,headers:{get:()=>retryAfter},json:async()=>({})};
  if(url.endsWith("/machines"))return{ok:true,json:async()=>({machines})};
  const params=new URL(url,"https://fixture.invalid").searchParams;let shown=tasks.filter(t=>archived.has(t.id)===(params.get("archived")==="1"));if(params.get("task"))shown=shown.filter(t=>t.id===params.get("task"));
  const data={machines,tasks:shown,total:shown.length,now:1000,summary:{running:1,waiting:0,outage:0,succeeded:archived.size?0:1,failed:0,cancelled:0},archived_count:archived.size,has_more:false,blocked:false};return{ok:true,json:async()=>data};};
 const context=vm.createContext({document,window:{addEventListener:(name,fn)=>events[name]=fn},location:{pathname:"/endnote/dashboard/"+"x".repeat(43)},fetch,AbortController,URLSearchParams,Date:Clock,Blob,URL:{createObjectURL:()=>"blob:fixture",revokeObjectURL:()=>{}},setTimeout:(fn,delay)=>{timers.set(++tick,{fn,delay});return tick;},clearTimeout:id=>timers.delete(id),setInterval:(fn,delay)=>{intervals.push({fn,delay});return intervals.length;}});
 vm.runInContext(script,context);return{nodes,tasks,machines,timers,intervals,calls,events,document,archived,pending,advance:ms=>{clock+=ms;},writeStatus:status=>{writeStatus=status;},status:(status,after="")=>{readStatus=status;retryAfter=after;},hold:()=>{hold=true;},release:()=>{hold=false;for(const request of pending.splice(0))request.resolve();}};
}
test("compact status rows render safe text and update automatically every five seconds",async()=>{
 const app=setup();await settle();assert.equal(rows(app).length,2);assert.ok(text(app.nodes.tasks).includes("<img src=x onerror=alert(1)>"));assert.ok(!html.includes('id="refresh"'));assert.equal(app.intervals[0].delay,5000);assert.ok(app.calls[0].url.includes("trends=0"));
 app.tasks[0].metrics.loss=.1;app.intervals[0].fn();await settle();assert.ok(text(app.nodes.tasks).includes("0.1"));assert.equal(app.nodes.summary.children.length,0);assert.equal(app.nodes["machine-empty"].hidden,false);
});
test("ended task archives from overview and restores without deleting data",async()=>{
 const app=setup();await settle();const runningAction=rowFor(app).children.at(-1);assert.equal(runningAction.children.length,0);
 const archive=rowFor(app,"2".repeat(32)).children.at(-1).children[0];await archive.onclick();await settle();assert.equal(rows(app).length,1);assert.equal(app.tasks.length,2);assert.ok(app.archived.has("2".repeat(32)));
 app.nodes.tabs.children.find(button=>text(button).startsWith("已归档")).onclick();await settle();assert.equal(rows(app).length,1);assert.ok(text(app.nodes.tasks).includes("恢复"));
 await rows(app)[0].children.at(-1).children[0].onclick();await settle();assert.equal(app.archived.size,0);assert.equal(rows(app).length,0);
});
test("search goes to server and detail loads trends only when opened",async()=>{
 const app=setup();await settle();app.nodes.search.value="seed42";app.nodes.search.oninput();const debounce=[...app.timers.values()].find(t=>t.delay===250);assert.ok(debounce);debounce.fn();await settle();assert.ok(app.calls.at(-1).url.includes("q=seed42"));
 rowFor(app).children[0].children[0].onclick();await settle();assert.equal(app.nodes.detail.open,true);assert.ok(app.calls.at(-1).url.includes("task="+"1".repeat(32)));assert.ok(app.calls.at(-1).url.includes("trends=1"));assert.ok(text(app.nodes["detail-content"]).includes("指标趋势"));app.nodes["close-detail"].onclick();assert.equal(app.nodes.detail.open,false);
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

test("queued is explicit, persists through heartbeats, and yields to outage or completion",async()=>{const app=setup();await settle();app.tasks[0].metrics.endnote_queued=1;app.intervals[0].fn();await settle();assert.ok(text(rowFor(app)).includes("排队中"));assert.ok(!text(rowFor(app)).includes("endnote_queued"));app.tasks[0].outage=true;app.intervals[0].fn();await settle();assert.ok(text(rowFor(app)).includes("心跳失联"));app.tasks[0].outage=false;app.tasks[0].status="succeeded";app.intervals[0].fn();await settle();assert.ok(text(rowFor(app)).includes("已成功"));app.tasks[0].status="running";app.tasks[0].metrics.endnote_queued=0;app.intervals[0].fn();await settle();assert.ok(text(rowFor(app)).includes("运行中"));});

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


test("slow machine request yields to task refresh without overlapping dashboard reads",async()=>{
 const app=setup();await settle();app.hold();
 app.intervals.find(t=>t.delay===1000).fn();await settle();
 const machineCall=app.calls.at(-1);assert.ok(machineCall.url.endsWith("/machines"));
 app.intervals.find(t=>t.delay===5000).fn();await settle();
 assert.ok(machineCall.options.signal.aborted,"task updates should cancel the obsolete machine read");
 app.release();await settle();assert.equal(text(app.nodes.notice),"");
});

test("transient read timeout retries promptly and retains the last successful overview",async()=>{
 const app=setup();await settle();const previous=rows(app);app.hold();
 app.intervals.find(t=>t.delay===5000).fn();await settle();
 const timeout=[...app.timers.values()].find(t=>t.delay===8000);assert.ok(timeout);timeout.fn();await settle();
 assert.equal(rows(app)[0],previous[0]);assert.equal(text(app.nodes.notice),"","one missed update must not replace the overview with a warning");
 const retry=[...app.timers.values()].find(t=>t.delay===1000);assert.ok(retry,"retry promptly instead of waiting for the next fixed poll");
 app.release();retry.fn();await settle();assert.ok(!app.nodes.connection.className.includes("stale"));
});


test("persistent outage is shown honestly and recovery clears it",async()=>{
 const app=setup();await settle();app.advance(31000);app.status(503);
 app.intervals.find(t=>t.delay===5000).fn();await settle();
 assert.ok(text(app.nodes.notice).includes("更新已延迟"));assert.ok(app.nodes.connection.className.includes("stale"));
 const retry=[...app.timers.values()].find(t=>t.delay===1000);assert.ok(retry);
 app.status(200);retry.fn();await settle();assert.equal(text(app.nodes.notice),"");assert.ok(!app.nodes.connection.className.includes("stale"));
});

test("rate-limited refresh respects retry delay rather than polling into the limit",async()=>{
 const app=setup();await settle();app.status(429,"45");
 app.intervals.find(t=>t.delay===5000).fn();await settle();
 const count=app.calls.length;const retry=[...app.timers.values()].find(t=>t.delay===45000);assert.ok(retry);
 for(const poll of app.intervals)poll.fn();await settle();assert.equal(app.calls.length,count);
 app.status(200);retry.fn();await settle();assert.equal(app.calls.length,count+1);
});

test("machine failures back off while task reads remain available",async()=>{
 const app=setup();await settle();const poll=app.intervals.find(t=>t.delay===1000);
 app.status(503);await poll.fn();await settle();const count=app.calls.length;
 await poll.fn();await settle();assert.equal(app.calls.length,count);
 app.advance(1000);await poll.fn();await settle();assert.equal(app.calls.length,count+1);
 app.advance(1000);await poll.fn();await settle();assert.equal(app.calls.length,count+1);
 app.status(200);app.intervals.find(t=>t.delay===5000).fn();await settle();assert.equal(app.calls.length,count+2);
});

test("invalid dashboard link is explicit and stops automatic requests",async()=>{
 const app=setup();await settle();app.status(404);app.intervals.find(t=>t.delay===5000).fn();await settle();
 assert.ok(text(app.nodes.notice).includes("链接无效"));const count=app.calls.length;
 for(const poll of app.intervals)poll.fn();await settle();assert.equal(app.calls.length,count);
});


test("stable module keeps renamed rounds together without merging other modules",async()=>{const app=setup();await settle();const template=app.tasks[0];app.tasks.splice(0,app.tasks.length,{...template,id:"old",name:"旧实验名 第18轮",group:"beam-module",created:700,status:"failed"},{...template,id:"other",name:"新实验名 无关实验",group:"another-module",created:800},{...template,id:"new",name:"新实验名 第19轮",group:"beam-module",created:900});app.intervals.find(t=>t.delay===5000).fn();await settle();const module=rows(app).filter(r=>r.dataset.groupKey==="beam-module");assert.deepEqual(module.map(r=>r.dataset.taskId),["old","new"]);assert.equal(new Set(module.map(r=>r.className.match(/cluster-tone-\d/)[0])).size,1);assert.equal(rows(app).find(r=>r.dataset.taskId==="other").dataset.groupKey,"another-module");});


test("attention groups lead completed groups and healthy groups remain below without splitting modules",async()=>{const app=setup();await settle();const template=app.tasks[0];app.tasks.splice(0,app.tasks.length,{...template,id:"active",name:"A normal",group:"A",created:100},{...template,id:"done",name:"B finished",group:"B",created:200,status:"succeeded"},{...template,id:"fail",name:"C failed",group:"C",created:300,status:"failed"},{...template,id:"same",name:"C running",group:"C",created:400},{...template,id:"queue",name:"D queued",group:"D",created:500,metrics:{endnote_queued:1}},{...template,id:"lost",name:"E lost",group:"E",created:600,outage:true});app.intervals[0].fn();await settle();assert.deepEqual(rows(app).map(r=>r.dataset.taskId),["fail","same","lost","done","active","queue"]);app.tasks.find(t=>t.id==="lost").outage=false;app.tasks.find(t=>t.id==="active").status="succeeded";app.intervals[0].fn();await settle();assert.deepEqual(rows(app).map(r=>r.dataset.taskId),["fail","same","active","done","queue","lost"]);});


test("outage tasks archive and still restore after heartbeat recovery",async()=>{const app=setup();await settle();app.tasks[0].outage=true;app.intervals[0].fn();await settle();const button=rowFor(app).children.at(-1).children[0];assert.equal(text(button),"归档");await button.onclick();await settle();assert.ok(!rowFor(app));app.nodes.tabs.children.find(b=>text(b).startsWith("已归档")).onclick();await settle();app.tasks[0].outage=false;app.intervals[0].fn();await settle();const restore=rowFor(app).children.at(-1).children[0];assert.equal(text(restore),"恢复");await restore.onclick();await settle();assert.equal(app.archived.size,0);app.nodes.tabs.children.find(b=>text(b).startsWith("全部")).onclick();await settle();assert.ok(rowFor(app));assert.equal(rowFor(app).children.at(-1).children.length,0);});

test("archive leaves overview immediately while network is pending",async()=>{const app=setup();await settle();app.hold();const button=rowFor(app,"2".repeat(32)).children.at(-1).children[0];const operation=button.onclick();await settle();assert.equal(rows(app).length,1,"archiving must not wait for a server round trip");app.release();await operation;await settle();});

test("rejected archive restores row and counts without losing failure notice",async()=>{const app=setup();await settle();app.writeStatus(503);await rowFor(app,"2".repeat(32)).children.at(-1).children[0].onclick();await settle();assert.equal(rows(app).length,2);assert.equal(app.archived.size,0);assert.ok(text(app.nodes.notice).includes("已恢复显示"));assert.ok(text(app.nodes.tabs).includes("已归档0"));});
test("pending archive cancels stale reads and batches concurrent reconciliation",async()=>{const app=setup();await settle();app.tasks[0].outage=true;app.intervals[0].fn();await settle();app.hold();app.intervals[0].fn();await settle();const read=app.calls.at(-1);const a=rowFor(app,"2".repeat(32)).children.at(-1).children[0];const b=rowFor(app).children.at(-1).children[0];const first=a.onclick(),second=b.onclick();await settle();assert.equal(rows(app).length,0);assert.ok(read.options.signal.aborted);const count=app.calls.length;await a.onclick();app.intervals[0].fn();await settle();assert.equal(app.calls.length,count);app.release();await Promise.all([first,second]);await settle();assert.equal(rows(app).length,0);assert.equal(app.archived.size,2);assert.equal(app.calls.length,count);});
test("archive timeout restores visible record and reconciles unknown outcome",async()=>{const app=setup();await settle();app.hold();const operation=rowFor(app,"2".repeat(32)).children.at(-1).children[0].onclick();await settle();const timeout=[...app.timers.values()].find(t=>t.delay===8000);timeout.fn();await operation;await settle();assert.ok(rowFor(app,"2".repeat(32)));assert.ok(text(app.nodes.notice).includes("暂未确认"));app.release();await settle();assert.equal(rows(app).length,2);});
test("restoring an archived row is immediate and tab change settles correctly",async()=>{const app=setup();await settle();await rowFor(app,"2".repeat(32)).children.at(-1).children[0].onclick();await settle();app.nodes.tabs.children.find(b=>text(b).startsWith("已归档")).onclick();await settle();app.hold();const operation=rows(app)[0].children.at(-1).children[0].onclick();await settle();assert.equal(rows(app).length,0);app.nodes.tabs.children.find(b=>text(b).startsWith("全部")).onclick();app.release();await operation;await settle();assert.equal(rows(app).length,2);assert.equal(app.archived.size,0);});

test("archive keeps other rows, tabs and machine cards untouched before and after save",async()=>{const app=setup();await settle();const kept=rowFor(app),tabs=[...app.nodes.tabs.children],cards=[...app.nodes.summary.children];const before=app.calls.length;app.hold();const op=rowFor(app,"2".repeat(32)).children.at(-1).children[0].onclick();await settle();assert.equal(rowFor(app),kept);assert.deepEqual(app.nodes.tabs.children,tabs);assert.equal(text(app.nodes.notice),"");app.release();await op;await settle();assert.equal(rowFor(app),kept);assert.deepEqual(app.nodes.summary.children,cards);assert.equal(app.calls.length,before+1);});

test("archive retains remaining group order and tones on subsequent polls",async()=>{const app=setup();await settle();const template=app.tasks[0];app.tasks.splice(0,app.tasks.length,{...template,id:"a",name:"A run",group:"A"},{...template,id:"b",name:"B done",group:"B",status:"succeeded"},{...template,id:"c",name:"C failed",group:"C",status:"failed"},{...template,id:"d",name:"C run",group:"C"});app.intervals[0].fn();await settle();const prior=rows(app).filter(r=>r.dataset.taskId!=="c").map(r=>[r.dataset.taskId,r.className.match(/cluster-tone-\d/)[0]]);await rowFor(app,"c").children.at(-1).children[0].onclick();await settle();app.intervals[0].fn();await settle();assert.deepEqual(rows(app).map(r=>[r.dataset.taskId,r.className.match(/cluster-tone-\d/)[0]]),prior);app.tasks.find(t=>t.id==="a").status="failed";app.intervals[0].fn();await settle();assert.equal(rows(app)[0].dataset.taskId,"a");});
