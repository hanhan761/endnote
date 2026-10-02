"use strict";
const $=id=>document.getElementById(id);
const base=location.pathname.replace(/\/$/,"");
let latest=null;
let saved=[];
try{saved=JSON.parse(localStorage.getItem("endnote-tasks")||"[]");$("email").value=localStorage.getItem("endnote-email")||"";}catch{}
function notice(message,error=false){$("notice").textContent=message;$("notice").style.display="block";$("notice").className=error?"error":"";}
async function api(route,data,key,method){const headers={"Content-Type":"application/json"};if(key)headers.Authorization="Bearer "+key;const response=await fetch(base+route,{method:method||(data?"POST":"GET"),headers,body:data?JSON.stringify(data):undefined});const result=await response.json();if(!response.ok)throw new Error(result.error||"请求失败");return result;}
function bind(id,fn){$(id).addEventListener("click",async()=>{const button=$(id);button.disabled=true;try{await fn();}catch(error){notice(error.message,true);}finally{button.disabled=false;}});}
$("lost").onchange=()=>{$("heartbeat-field").hidden=!$("lost").checked;};
$("overtime").onchange=()=>{$("runtime-field").hidden=!$("overtime").checked;};
bind("create",async()=>{
 const email=$("email").value.trim();if(!$("email").checkValidity()||!email)throw new Error("请填写收件邮箱");
 const notify_on=[];if($("success").checked)notify_on.push("succeeded");if($("failure").checked)notify_on.push("failed");if($("lost").checked)notify_on.push("heartbeat_timeout");if($("overtime").checked)notify_on.push("runtime_timeout");
 const data={email,name:$("name").value.trim(),notify_on};
 if($("lost").checked)data.heartbeat_timeout=Number($("heartbeat").value);
 if($("overtime").checked)data.runtime_timeout=Number($("runtime").value);
 if($("metric").value.trim()){if($("threshold").value==="")throw new Error("请填写指标阈值");data.rules=[{metric:$("metric").value.trim(),op:$("op").value,value:Number($("threshold").value)}];}
 if(!notify_on.length&&!data.rules)throw new Error("请至少选择一个提醒条件");
 const task=await api("/v1/quick/tasks",data);
 latest={...task,url:location.origin+base,name:data.name};
 saved.unshift(latest);saved=saved.slice(0,50);
 localStorage.setItem("endnote-tasks",JSON.stringify(saved));localStorage.setItem("endnote-email",email);
 $("result").hidden=false;$("result-text").textContent="通知将发到 "+email+"。下载接入文件即可连接实验。";
 $("integration").textContent=JSON.stringify(latest,null,2);notice("创建成功，首次接入测试邮件已安排。");await refresh();
});
bind("download",async()=>{if(!latest)throw new Error("请先创建提醒");const response=await fetch(base+"/runner.py");if(!response.ok)throw new Error("无法下载接入文件");let script=await response.text();script=script.replace("TASK = None","TASK = json.loads("+JSON.stringify(JSON.stringify(latest))+")");const url=URL.createObjectURL(new Blob([script],{type:"text/x-python;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download="endnote-task.py";a.click();URL.revokeObjectURL(url);});
async function refresh(){
 $("tasks").replaceChildren();
 for(const task of saved){const row=document.createElement("div");row.className="task";const label=document.createElement("div");const name=document.createElement("strong");name.textContent=task.name;const state=document.createElement("span");state.textContent="正在读取…";label.append(name,state);const details=document.createElement("button");details.className="secondary";details.textContent="详情";details.onclick=async()=>{try{$("detail").textContent=JSON.stringify(await api("/v1/tasks/"+task.id,null,task.task_key),null,2);$("detail").hidden=false;}catch(e){notice(e.message,true);}};row.append(label,details);$("tasks").append(row);
  try{const detail=await api("/v1/tasks/"+task.id,null,task.task_key);state.textContent=({running:"运行中",succeeded:"已成功",failed:"已失败",cancelled:"已取消"})[detail.status]||detail.status;}catch{state.textContent="已过期或暂不可用";}
 }
 if(!saved.length)$("tasks").textContent="创建后会显示在这里。";
}
bind("refresh",refresh);
fetch(base+"/health").then(r=>r.json()).then(h=>{$("health").textContent=h.ok?"服务在线":"服务暂不可用";}).catch(()=>{$("health").textContent="连接失败";});
refresh();
