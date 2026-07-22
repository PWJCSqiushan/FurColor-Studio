let projects=[],current=null,pollTimer=null;
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(message){const box=$('#toast');box.textContent=message;box.classList.add('show');setTimeout(()=>box.classList.remove('show'),4500)}
function show(id){$$('.page').forEach(x=>x.classList.toggle('active',x.id===id));$$('nav button').forEach(x=>x.classList.toggle('active',x.dataset.page===id));$('#title').textContent=$(`[data-page="${id}"]`)?.textContent||'FurColor Studio';if(id==='culling')loadPhotos();if(id==='subjects')loadSubjects()}
$$('nav button').forEach(x=>x.onclick=()=>show(x.dataset.page));
async function api(url,options={}){const headers=new Headers(options.headers||{});if(!window.FURCOLOR.demo&&url.startsWith('/api/'))headers.set('X-FurColor-Local',window.FURCOLOR.token);const response=await fetch(url,{...options,headers});let body;try{body=await response.json()}catch{body={detail:await response.text()}}if(!response.ok)throw Error(body.detail||'请求失败');return body}
async function loadRoots(){
  if(window.FURCOLOR.demo)return;
  const result=await api('/api/local/roots');
  let box=$('#authorizedRoots');
  if(!box){box=document.createElement('div');box.id='authorizedRoots';box.className='notice';$('#projectForm').before(box)}
  box.innerHTML=`<b>本机已授权目录</b><small>${result.roots.map(esc).join('<br>')||'尚未授权；请使用各字段右侧的“浏览”按钮。'}</small>`;
}
async function init(){
  const health=await api('/api/health');
  const subjectAvailable=health.subject_intelligence?.available;
  $('#health').textContent=`${health.mode} · v${health.version} · 不上传`;
  $('#subjectEngine').textContent=subjectAvailable?'Fursee 就绪':'可选未就绪';
  projects=await api('/api/projects');$('#projectCount').textContent=projects.length;
  $('#projects').innerHTML=projects.map(p=>`<article><h3>${esc(p.name)}</h3><p class="muted">${esc(p.status)}</p><button onclick="choose(${p.id})">打开项目</button></article>`).join('')||'<p class="muted">尚无本地项目</p>';
  $('#projectSelect').innerHTML=projects.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('');
  if(projects.length&&!current)current=projects[0].id;
  if(current)$('#projectSelect').value=current;
  if(window.FURCOLOR.demo)$$('#projectForm input,#projectForm select,#projectForm button').forEach(x=>x.disabled=true);else await loadRoots();
}
function choose(id){current=id;$('#projectSelect').value=id;show('workflow')}
$('#projectSelect').onchange=e=>{current=+e.target.value;loadPhotos()};
$$('[data-pick]').forEach(button=>button.onclick=async()=>{if(window.FURCOLOR.demo)return toast('演示模式不访问文件系统');try{const result=await api(`/api/local/pick/${button.dataset.pick}`,{method:'POST'});if(result.path){button.parentElement.querySelector('input').value=result.path;toast(`已授权：${result.authorized_root}`);await loadRoots()}}catch(error){toast(error.message)}});
$('#projectForm').onsubmit=async event=>{event.preventDefault();if(window.FURCOLOR.demo)return toast('云端演示模式禁止写入本地路径');try{const data=Object.fromEntries(new FormData(event.target));const result=await api('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});current=result.id;const scanned=await api(`/api/projects/${current}/scan`,{method:'POST'});toast(`已扫描 ${scanned.count} 张照片`);await init();show('culling')}catch(error){toast(error.message)}};
async function subjectData(){if(!current)return {images:{},clusters:[]};try{return await api(`/api/projects/${current}/subjects`)}catch{return {images:{},clusters:[]}}}
async function loadPhotos(){
  if(!current){$('#photoGrid').innerHTML='<p class="muted">请先创建项目</p>';return}
  try{
    const [photos,subjects]=await Promise.all([api(`/api/projects/${current}/photos`),subjectData()]);
    $('#photoGrid').innerHTML=photos.map(photo=>{
      const detected=subjects.images?.[photo.stem]?.fursuits||[];
      const clusters=[...new Set(detected.map(x=>x.cluster_id).filter(Boolean))];
      const badges=[detected.length?`${detected.length} 个兽装主体`:'',...clusters].filter(Boolean).map(x=>`<span>${esc(x)}</span>`).join('');
      return `<article class="photo ${esc(photo.selection)}"><img loading="lazy" src="/api/projects/${current}/thumb/${encodeURIComponent(photo.stem)}" alt="${esc(photo.stem)}"><b>${esc(photo.stem)}</b><div class="badges">${badges}</div><div class="actions"><button onclick="setSel('${encodeURIComponent(photo.stem)}','keep')">保留</button><button onclick="setSel('${encodeURIComponent(photo.stem)}','reject')">废片</button><button class="ghost" onclick="setSel('${encodeURIComponent(photo.stem)}','unset')">默认</button></div></article>`;
    }).join('')||'<p class="muted">没有扫描到照片</p>';
  }catch(error){toast(error.message)}
}
async function setSel(stem,value){await api(`/api/projects/${current}/selection/${stem}/${value}`,{method:'POST'});loadPhotos()}
async function loadSubjects(){
  if(window.FURCOLOR.demo){$('#subjectStatus').textContent='云端演示模式不加载模型、照片或主体特征。';return}
  if(!current){$('#subjectStatus').textContent='请先创建或打开一个项目。';$('#subjectStats').innerHTML='';$('#subjectClusters').innerHTML='';return}
  try{
    const [status,data]=await Promise.all([api('/api/local/subject-status'),subjectData()]);
    $('#subjectStatus').className=`notice ${status.available?'ok':'warning'}`;
    $('#subjectStatus').innerHTML=status.available
      ?`<b>${esc(status.model)} 已就绪</b><small>首次运行会完整核对约 1.27 GB 权重的 SHA-256，随后在本机生成项目级分析。</small>`
      :`<b>主体智能层尚未就绪</b><small>${esc(status.error||'请运行 install_fursee.ps1，并配置本地模型目录。')}</small>`;
    $('#subjectStats').innerHTML=[
      [data.selected_photo_count||0,'已分析照片'],[data.fursuit_detection_count||0,'兽装主体'],
      [data.face_candidate_count||0,'新增人脸候选'],[data.cluster_count||0,'匿名分组']
    ].map(x=>`<article><b>${x[0]}</b><span>${x[1]}</span></article>`).join('');
    $('#subjectClusters').innerHTML=(data.clusters||[]).map(cluster=>{
      const rep=cluster.representative||{};
      return `<article class="cluster-card"><img loading="lazy" src="/api/projects/${current}/subject-crop/${encodeURIComponent(rep.stem||'')}/${Number(rep.index||0)}" alt="${esc(cluster.id)} 代表图"><div><h3>${esc(cluster.id)}</h3><p>${cluster.photo_count} 张照片 · ${cluster.detection_count} 个检测框</p><small>匿名项目内分组，不代表真人身份</small></div><div class="actions"><button onclick="setCluster('${esc(cluster.id)}','keep')">整组保留</button><button onclick="setCluster('${esc(cluster.id)}','reject')">整组废片</button><button class="ghost" onclick="setCluster('${esc(cluster.id)}','unset')">恢复默认</button></div></article>`;
    }).join('')||(data.ready?'<p class="muted">本次没有形成至少两张照片的稳定分组；单独出现的主体不会被强行归类。</p>':'<p class="muted">运行主体分析后，这里会显示项目内匿名分组。</p>');
  }catch(error){$('#subjectStatus').textContent=error.message}
}
async function setCluster(cluster,value){try{const result=await api(`/api/projects/${current}/clusters/${encodeURIComponent(cluster)}/selection/${value}`,{method:'POST'});toast(`已更新 ${result.count} 张照片`);await Promise.all([loadSubjects(),loadPhotos()])}catch(error){toast(error.message)}}
async function runJob(kind){if(!current)return toast('请先选择项目');try{const result=await api(`/api/projects/${current}/jobs/${kind}`,{method:'POST'});toast(`任务 #${result.job_id} 已启动`);show('workflow');poll()}catch(error){toast(error.message)}}
async function poll(){
  if(pollTimer)clearTimeout(pollTimer);
  try{
    const jobs=await api(`/api/projects/${current}/jobs`);if(!jobs.length)return;
    const job=jobs[0];$('#jobLog').textContent=job.log||`${job.kind}: ${job.status}`;
    if(['queued','running'].includes(job.status)){pollTimer=setTimeout(poll,1600)}
    else if(job.status==='complete'){toast(`任务 #${job.id} 已完成`);if(job.kind==='subject'){await loadSubjects();await loadPhotos()}}
    else if(job.status==='failed')toast(`任务 #${job.id} 失败，请查看日志`);
  }catch(error){toast(error.message)}
}
async function deliver(){if(!current)return toast('请先选择项目');const acknowledgements=$$('.checklist input:checked').map(x=>x.value);if(acknowledgements.length!==4)return toast('请完成全部四项人工质检');try{const result=await api(`/api/projects/${current}/deliver`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({acknowledgements,name:$('#deliveryName').value,make_zip:true})});$('#deliveryResult').innerHTML=`<div class="result"><b>交付包已生成：${result.count} 张</b><small>${esc(result.archive)}</small></div>`;toast('交付包与校验清单已生成')}catch(error){toast(error.message)}}
init().catch(error=>toast(error.message));