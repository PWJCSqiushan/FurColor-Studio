let projects=[],current=null;
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(message){const box=$('#toast');box.textContent=message;box.classList.add('show');setTimeout(()=>box.classList.remove('show'),4000)}
function show(id){$$('.page').forEach(x=>x.classList.toggle('active',x.id===id));$$('nav button').forEach(x=>x.classList.toggle('active',x.dataset.page===id));$('#title').textContent=$(`[data-page="${id}"]`)?.textContent||'FurColor Studio';if(id==='culling')loadPhotos()}
$$('nav button').forEach(x=>x.onclick=()=>show(x.dataset.page));
async function api(url,options={}){const headers=new Headers(options.headers||{});if(!window.FURCOLOR.demo&&url.startsWith('/api/'))headers.set('X-FurColor-Local',window.FURCOLOR.token);const response=await fetch(url,{...options,headers});let body;try{body=await response.json()}catch{body={detail:await response.text()}}if(!response.ok)throw Error(body.detail||'请求失败');return body}
async function loadRoots(){
  if(window.FURCOLOR.demo)return;
  const result=await api('/api/local/roots',{headers:{'X-FurColor-Local':window.FURCOLOR.token}});
  let box=$('#authorizedRoots');
  if(!box){box=document.createElement('div');box.id='authorizedRoots';box.className='notice';$('#projectForm').before(box)}
  box.innerHTML=`<b>本机已授权目录</b><small>${result.roots.map(esc).join('<br>')||'尚未授权；请使用各字段右侧的“浏览”按钮。'}</small>`;
}
async function init(){
  const health=await api('/api/health');$('#health').textContent=`${health.mode} · v${health.version} · 不上传`;
  projects=await api('/api/projects');$('#projectCount').textContent=projects.length;
  $('#projects').innerHTML=projects.map(p=>`<article><h3>${esc(p.name)}</h3><p class="muted">${esc(p.status)}</p><button onclick="choose(${p.id})">打开项目</button></article>`).join('')||'<p class="muted">尚无本地项目</p>';
  $('#projectSelect').innerHTML=projects.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('');if(projects.length&&!current)current=projects[0].id;
  if(window.FURCOLOR.demo)$$('#projectForm input,#projectForm select,#projectForm button').forEach(x=>x.disabled=true);else await loadRoots();
}
function choose(id){current=id;$('#projectSelect').value=id;show('workflow')}
$('#projectSelect').onchange=e=>{current=+e.target.value;loadPhotos()};
$$('[data-pick]').forEach(button=>button.onclick=async()=>{if(window.FURCOLOR.demo)return toast('演示模式不访问文件系统');try{const result=await api(`/api/local/pick/${button.dataset.pick}`,{method:'POST',headers:{'X-FurColor-Local':window.FURCOLOR.token}});if(result.path){button.parentElement.querySelector('input').value=result.path;toast(`已授权：${result.authorized_root}`);await loadRoots()}}catch(error){toast(error.message)}});
$('#projectForm').onsubmit=async event=>{event.preventDefault();if(window.FURCOLOR.demo)return toast('云端演示模式禁止写入本地路径');try{const data=Object.fromEntries(new FormData(event.target));const result=await api('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});current=result.id;const scanned=await api(`/api/projects/${current}/scan`,{method:'POST'});toast(`已扫描 ${scanned.count} 张照片`);await init();show('culling')}catch(error){toast(error.message)}};
async function loadPhotos(){if(!current){$('#photoGrid').innerHTML='<p class="muted">请先创建项目</p>';return}const photos=await api(`/api/projects/${current}/photos`);$('#photoGrid').innerHTML=photos.map(x=>`<article class="photo ${esc(x.selection)}"><img loading="lazy" src="/api/projects/${current}/thumb/${encodeURIComponent(x.stem)}" alt="${esc(x.stem)}"><b>${esc(x.stem)}</b><div class="actions"><button onclick="setSel('${encodeURIComponent(x.stem)}','keep')">保留</button><button onclick="setSel('${encodeURIComponent(x.stem)}','reject')">废片</button><button class="ghost" onclick="setSel('${encodeURIComponent(x.stem)}','unset')">默认</button></div></article>`).join('')||'<p class="muted">没有扫描到照片</p>'}
async function setSel(stem,value){await api(`/api/projects/${current}/selection/${stem}/${value}`,{method:'POST'});loadPhotos()}
async function runJob(kind){if(!current)return toast('请先选择项目');try{const result=await api(`/api/projects/${current}/jobs/${kind}`,{method:'POST'});toast(`任务 #${result.job_id} 已启动`);poll()}catch(error){toast(error.message)}}
async function poll(){const jobs=await api(`/api/projects/${current}/jobs`);if(!jobs.length)return;$('#jobLog').textContent=jobs[0].log||`${jobs[0].kind}: ${jobs[0].status}`;if(['queued','running'].includes(jobs[0].status))setTimeout(poll,1600)}
async function deliver(){if(!current)return toast('请先选择项目');const acknowledgements=$$('.checklist input:checked').map(x=>x.value);if(acknowledgements.length!==4)return toast('请完成全部四项人工质检');try{const result=await api(`/api/projects/${current}/deliver`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({acknowledgements,name:$('#deliveryName').value,make_zip:true})});$('#deliveryResult').innerHTML=`<div class="result"><b>交付包已生成：${result.count} 张</b><small>${esc(result.archive)}</small></div>`;toast('交付包与校验清单已生成')}catch(error){toast(error.message)}}
init().catch(error=>toast(error.message));
