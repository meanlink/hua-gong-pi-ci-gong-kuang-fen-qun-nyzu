import {jobs,rechecks} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
const FALLBACK={title:'温压扰动换群复核',method:'固定原批次、群数K、误差范围与每次抽样，扰动温压读数后重新拟合；新旧族群按批次重合最多一一配对，标签对调不算换群。',note:'全部试次得出结论后才展示各批换群率。',parameters:[{key:'error_pct',label:'测量误差范围(±%读数)',type:'number',default:2,min:0.1,max:25},{key:'trials',label:'扰动试次数',type:'number',default:20,min:5,max:100}]};
export async function recheckPage(id){
 const [list,allJobs]=await Promise.all([rechecks.list(),jobs.list()]);workspace.rechecks=list;
 const completed=allJobs.filter(j=>j.status==='completed'),rm=workspace.meta.recheck||FALLBACK;
 const rc=id?await rechecks.get(id):(list.find(x=>x.id===workspace.selectedRecheck)||list[0]);
 if(rc&&!list.some(x=>x.id===rc.id))list.push(rc);
 if(rc)workspace.selectedRecheck=rc.id;
 const preferred=workspace.recheckJob||workspace.selectedJob;
 const form='<section class="panel"><div class="section-title"><h2>发起复核</h2><span>从已完成分群</span></div>'+(completed.length?'<form id="recheck-form"><label>复核名称<input name="name" required minlength="2" value="温压扰动复核 · 换群稳定性"></label><label>来源分群<select name="job_id" required>'+completed.map(j=>'<option value="'+j.id+'" '+(j.id===preferred?'selected':'')+'>'+esc(j.name)+' · K='+esc(j.params?.clusters??'?')+'</option>').join('')+'</select></label><div class="parameter-grid">'+rm.parameters.map(p=>'<label>'+esc(p.label)+'<input type="number" step="'+(p.key==='trials'?'1':'any')+'" name="'+esc(p.key)+'" value="'+esc(p.default)+'" min="'+esc(p.min)+'" max="'+esc(p.max)+'" required></label>').join('')+'</div><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>发起扰动复核 ↗</button><p class="hint">固定原批次、群数K、误差范围与每次抽样；后台逐试次计算，中断自动补算缺项，并发重试不重复计入。观察员仅可查看。</p></form>':'<div class="empty">尚无已完成分群。先到分析工作台完成一次计算。<a href="#/workbench">前往工作台 ↗</a></div>')+'</section>';
 const sheet='<section class="method-sheet"><p class="eyebrow">METHOD / STABILITY</p><h2>'+esc(rm.title)+'</h2><p>'+esc(rm.method)+'</p><h3>判读边界</h3><ul><li>换群率高说明批次位于族群边界，对温压测量误差敏感。</li><li>'+esc(rm.note)+'</li><li>扰动仅施加于温度与釜压读数，停留时间与收率保持原记录。</li></ul></section>';
 let detail='';
 if(!rc)detail='<section class="panel empty">尚无复核记录。先在上方选择已完成分群，发起一次扰动复核。</section>';
 else{
  const r=rc.result||{};
  const head='<div class="result-selector"><label>复核记录<select id="select-recheck">'+list.map(x=>'<option value="'+x.id+'" '+(x.id===rc.id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.status)+'</option>').join('')+'</select></label>'+status(rc.status)+'<span>'+date(rc.created_at)+'</span><span>误差 ±'+esc(rc.error_pct)+'% · 共 '+rc.trials_total+' 试次</span></div>';
  if(rc.status==='completed'){
   detail=head+'<section class="result-lead"><p class="eyebrow">STABILITY FINDING</p><h2>'+esc(r.summary)+'</h2><div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div></section><section class="panel">'+chart(r.chart)+'</section><div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由复核结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section><section class="method-sheet compact"><p class="eyebrow">REPRODUCIBILITY</p><h3>复核口径与参数</h3><p>'+esc(r.method)+'</p><pre>'+esc(JSON.stringify(r.params||{},null,2))+'</pre><p class="hint">试次种子固定，同参数复核结果可复现。</p></section></div><section class="panel"><div class="section-title"><h2>各批换群率</h2><span>'+(r.table?.rows?.length||0)+' 批 · 按换群率降序</span></div>'+table(r.table?.columns||[],r.table?.rows||[])+'</section><section class="panel"><div class="section-title"><h2>失败试次与原因</h2><span>失败试次不计入有效试次</span></div>'+((r.failures||[]).length?'<ol class="questions">'+r.failures.map(f=>'<li>试次 #'+esc(f.trial)+'：'+esc(f.error)+'</li>').join('')+'</ol>':'<p class="hint">全部试次均成功拟合，无失败记录。</p>')+'</section>';
  }else if(rc.status==='failed'){
   detail=head+'<section class="panel empty">复核失败：'+esc(rc.error)+'。请检查来源分群与数据后重新发起。</section>';
  }else{
   const pct=rc.trials_total?Math.round(rc.trials_done/rc.trials_total*100):0;
   detail=head+'<section class="panel"><div class="section-title"><h2>试次进行中</h2><span>全部试次有结论后才展示各批换群率</span></div><div class="progress"><div style="width:'+pct+'%"></div></div><p class="hint">已结论 '+rc.trials_done+' / '+rc.trials_total+' 个试次（有效 '+rc.trials_valid+' · 失败 '+rc.trials_failed+'）。计算中断会自动补算缺项，重试不会重复计入同一试次。</p>'+(session.user.role!=='viewer'?'<button class="button small" id="resume-recheck">重新派发缺项 ↗</button>':'')+'</section>';
  }
 }
 return heading('05 / STABILITY','温压扰动换群复核','温压读数含测量误差。固定原批次、群数K、误差范围与每次抽样，扰动后重新拟合，找出容易换群的釜批。','<button class="button" id="refresh-recheck">刷新进度 ↻</button>')+'<div class="workbench-grid">'+form+sheet+'</div>'+detail;
}
export function bindRecheck(refresh){
 document.querySelector('#refresh-recheck')?.addEventListener('click',refresh);
 document.querySelector('#select-recheck')?.addEventListener('change',e=>{workspace.selectedRecheck=Number(e.target.value);location.hash='#/recheck/'+e.target.value;});
 const recheckForm=document.querySelector('#recheck-form');
 if(recheckForm)submit(recheckForm,async f=>{const rc=await rechecks.create({name:f.get('name'),job_id:Number(f.get('job_id')),error_pct:Number(f.get('error_pct')),trials:Number(f.get('trials'))});workspace.selectedRecheck=rc.id;workspace.recheckJob=rc.job_id;notify('复核已提交，后台逐试次计算');location.hash='#/recheck/'+rc.id;});
 document.querySelector('#resume-recheck')?.addEventListener('click',async()=>{try{await rechecks.resume(workspace.selectedRecheck);notify('已重新派发缺项试次');await refresh();}catch(e){notify(e.message,true);}});
 if(workspace.rechecks.some(x=>x.status==='queued'||x.status==='running'))setTimeout(refresh,2000);
}
