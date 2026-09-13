import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createFly, animateFly } from '/fruitless/fly.js';
import { createConnectome } from '/fruitless/connectome.js';
const $=id=>document.getElementById(id), canvas=$('scene');
let snapshot=null, cursor=-1, lastBoard='', phase='', imageCount=0;
let runId=null, observedRunning=false, pending=false, requestError='', motionTime=0;
let practiceId=null, humanPicks=new Set(), boardStage='', pointerStart=null;
const renderer=new THREE.WebGLRenderer({canvas,antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.autoClear=false;
const scene=new THREE.Scene();scene.background=new THREE.Color('#ebeae5');
const camera=new THREE.PerspectiveCamera(38,1,.01,100);const controls=new OrbitControls(camera,canvas);controls.enablePan=false;controls.minDistance=8;controls.maxDistance=24;controls.maxPolarAngle=Math.PI*.44;
const home=()=>{camera.position.set(3,13,9);controls.target.set(0,0,0);controls.update()};home();$('home').onclick=home;
scene.add(new THREE.HemisphereLight('#e8eddc','#273535',2));const light=new THREE.DirectionalLight('#fff5dd',3);light.position.set(-3,8,4);scene.add(light);
const plane=new THREE.Mesh(new THREE.PlaneGeometry(45,45),new THREE.MeshBasicMaterial({color:'#e2dfd7'}));plane.rotation.x=-Math.PI/2;plane.position.y=-.03;scene.add(plane);
const grid=new THREE.GridHelper(45,45,'#b7b5ad','#cdc7b9');scene.add(grid);
const board=document.createElement('canvas');board.width=900;board.height=1080;const ctx=board.getContext('2d');
const texture=new THREE.CanvasTexture(board);texture.colorSpace=THREE.SRGBColorSpace;
const floor=new THREE.Mesh(new THREE.PlaneGeometry(6,7.2),new THREE.MeshBasicMaterial({map:texture}));floor.rotation.x=-Math.PI/2;floor.position.y=.02;scene.add(floor);
let images=[], selected=new Set();
function paint(){ctx.fillStyle='#fbfbfb';ctx.fillRect(0,0,900,1080);ctx.fillStyle='#1e2a4a';ctx.fillRect(0,0,900,150);ctx.fillStyle='white';ctx.font='28px system-ui';ctx.fillText('Select all images with',26,53);ctx.font='bold 46px system-ui';ctx.fillText('bananas',26,111);
images.forEach((im,i)=>{const x=(i%3)*300+6,y=156+Math.floor(i/3)*300;ctx.fillStyle='#e2dfd7';ctx.fillRect(x,y,288,288);if(im.complete&&im.naturalWidth)ctx.drawImage(im,x,y,288,288);if(snapshot?.tile_index===i){ctx.strokeStyle='#9f4f3d';ctx.lineWidth=8;ctx.strokeRect(x+4,y+4,280,280)}if(selected.has(i)){ctx.fillStyle='#1e2a4a';ctx.beginPath();ctx.arc(x+24,y+24,18,0,Math.PI*2);ctx.fill();ctx.fillStyle='white';ctx.font='bold 23px system-ui';ctx.fillText('+',x+17,y+32)}if(humanPicks.has(i)){ctx.strokeStyle='#9f4f3d';ctx.lineWidth=10;ctx.strokeRect(x+9,y+9,270,270);ctx.fillStyle='#9f4f3d';ctx.fillRect(x+195,y+246,86,34);ctx.fillStyle='white';ctx.font='bold 23px system-ui';ctx.fillText('YOU',x+209,y+271)}});texture.needsUpdate=true;canvas.dataset.loadedImages=imageCount;}
paint();
const brainScene=new THREE.Scene();brainScene.background=new THREE.Color('#e2dfd7');const brainCamera=new THREE.PerspectiveCamera(35,1,.01,100);const brain=new THREE.Group();brainScene.add(brain);
let fly, raw, live, normalized, finite, latestTarget=new THREE.Vector3(-4,.04,-2);
try{
const [body,positions]=await Promise.all([createFly('/fruitless/assets/fly'),fetch('/anatomy/positions.f32').then(r=>r.arrayBuffer())]);fly=body;
const extent=new THREE.Box3().setFromObject(fly).getSize(new THREE.Vector3());fly.scale.setScalar(1.15/Math.max(extent.x,extent.y,extent.z));scene.add(fly);fly.position.copy(latestTarget);
raw=new Float32Array(positions);createConnectome(brain,raw,{mAL:[],P1:[],trials:{}});
brain.children[0].material.color.set('#6b6a64');
// Use the original renderer's transformed soma positions for the live overlay.
const base=brain.children[0].geometry.attributes.position.array;finite=new Int32Array(raw.length/3).fill(-1);let n=0;
for(let i=0;i<finite.length;i++)if(Number.isFinite(raw[i*3]))finite[i]=n++;
normalized=base;const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(base.length),3));geometry.setAttribute('color',new THREE.BufferAttribute(new Float32Array(base.length),3));geometry.setDrawRange(0,0);
live=new THREE.Points(geometry,new THREE.PointsMaterial({size:.034,vertexColors:true,transparent:true,depthWrite:false,blending:THREE.NormalBlending}));live.frustumCulled=false;brain.add(live);canvas.dataset.ready='true';
}catch(e){$('status').textContent=e.message;canvas.dataset.error=e.message;console.error(e)}
function neural(ob){if(!live)return;let j=0;const p=live.geometry.attributes.position.array,c=live.geometry.attributes.color.array;ob.ids.forEach((id,k)=>{const index=finite[id];if(index<0)return;const s=1-Math.exp(-ob.counts[k]);for(let d=0;d<3;d++){p[j*3+d]=normalized[index*3+d];c[j*3+d]=[.347,.078,.047][d]*s}j++});live.geometry.setDrawRange(0,j);live.geometry.attributes.position.needsUpdate=true;live.geometry.attributes.color.needsUpdate=true;canvas.dataset.activeNeurons=j;canvas.dataset.spikeHash=ob.spike_sha256;}
function clearRunView(){cursor=-1;lastBoard='';phase='';practiceId=null;humanPicks.clear();images=[];imageCount=0;selected.clear();latestTarget.set(-4,.04,-2);fly?.position.copy(latestTarget);live?.geometry.setDrawRange(0,0);delete canvas.dataset.spikeHash;canvas.dataset.activeNeurons='0';$('window').textContent='Awaiting observation';$('retina').hidden=true;$('feedback').textContent='0';for(const id of ['choice','gaze','budget','reward','error'])$(id).textContent='--';$('scores').textContent='leave -- / select --';$('results').replaceChildren();delete $('curve').dataset.count;paint();}
function chart(){const c=$('curve'),r=c.getBoundingClientRect();if(!r.width||!r.height)return;c.width=r.width*devicePixelRatio;c.height=r.height*devicePixelRatio;const g=c.getContext('2d');g.scale(devicePixelRatio,devicePixelRatio);g.strokeStyle='#cdc7b9';g.fillStyle='#6b6a64';g.font='11px system-ui';[0,.5,1].forEach(v=>{const y=12+(1-v)*(r.height-24);g.beginPath();g.moveTo(35,y);g.lineTo(r.width,y);g.stroke();g.fillText(String(v),3,y+4)});
const h=snapshot?.history||[];let prev='';g.lineWidth=2;h.forEach((row,i)=>{const recent=h.slice(Math.max(0,i-35),i+1).filter(v=>v.phase===row.phase),v=recent.reduce((a,b)=>a+Number(b.correct),0)/recent.length;const x=38+(r.width-42)*i/Math.max(1,h.length-1),y=12+(1-v)*(r.height-24);if(row.phase!==prev){g.stroke();g.beginPath();g.strokeStyle=row.phase==='training'?'#9f4f3d':row.phase==='after'?'#1e2a4a':'#6b6a64';g.moveTo(x,y);prev=row.phase}else g.lineTo(x,y)});g.stroke();
const metrics=snapshot?.results?.metrics;if(metrics)$('results').replaceChildren(...Object.entries(metrics).map(([k,v])=>{const e=document.createElement('span');e.textContent=`${k.replaceAll('_',' ')}: ${(100*v.accuracy).toFixed(1)}%`;return e}));}
document.querySelector('.diagnostics').addEventListener('toggle',chart);

function personality(){
 const s=snapshot,p=s.practice,choosing=s.mode==='practice'&&p?.stage==='choosing';
 $('feedback').textContent=s.results?.fly_feedbacks??s.record?.feedback_count??0;
 $('deployment').textContent=s.hosted?'LIVE / YOUR KEY':'LOCAL EXPERIMENT';
 $('recording').hidden=!s.hosted;
 $('forget').hidden=!s.hosted||!s.run_id;
 $('forget').disabled=s.running||pending;
 $('download').hidden=$('audit').hidden=!s.hosted||!s.run_id||s.running;
 if(p?.board_id!==practiceId){practiceId=p?.board_id;humanPicks.clear();selected.clear();}
 canvas.classList.toggle('picking',choosing);
 $('next').disabled=!s.trained||s.running||pending;
 $('race').hidden=$('watch').hidden=!choosing;
 $('race').disabled=$('watch').disabled=pending;
 $('race-label').textContent=`Lock my picks (${humanPicks.size})`;
 $('practice-note').hidden=s.mode!=='practice';
 $('verdict').hidden=true;
 const history=s.history||[];
 let salary=0;
 for(const name of ['training','after']){
   const rows=history.filter(r=>r.phase===name);
   for(let i=0;i+9<=rows.length;i+=9)if(rows.slice(i,i+9).every(r=>r.correct))salary++;
 }
 salary+=s.practice_bananas||0;
 $('salary').textContent=salary;
 let thought='I have a perfectly normal number of legs.',title='Human verification pending',note='Application fee: zero. Expected salary: bananas.';
 const row=s.record;
 if(s.running&&s.mode==='experiment'){
   const current=row?.phase||'before',n=history.filter(r=>r.phase===current).length;
   const lines=current==='training'
     ? ['I was told there would be bananas.','My qualifications? I have been near fruit.','Six hands would make this easier.','I am putting this on my CV.']
     : current==='after'
       ? ['No hints? That feels personal.','I studied for this. Mostly fruit.','Please do not check my passport.']
       : ['Apparently landing on it is not an answer.','I clicked on a grape. We are all learning.','I can explain the extra legs.'];
   thought=lines[Math.floor(n/9)%lines.length];
   title=current==='training'?'Probation: paid in bananas':current==='after'?'Final exam. No hints.':'The job interview';
   note=`${current==='training'?'Training':current==='after'?'Frozen evaluation':'Before learning'} / ${n} tiles judged`;
 }else if(s.trained&&s.mode!=='practice'){
   const m=s.results?.metrics?.after;
   thought='I passed the interview. Now you take the test.';
   title='Your turn, alleged human.';
   note=m?`Frozen exam: ${m.correct}/${m.tiles} tiles. ${m.passed_boards}/${m.boards} perfect boards.`:'The applicant is available for another round.';
   $('verdict').textContent='READY FOR A CHALLENGER';$('verdict').classList.remove('fail');$('verdict').hidden=false;
 }
 if(s.mode==='practice'&&p){
   if(choosing){thought='Go on. Show me your human credentials.';title='You vs the fly';note=`Your picks: ${humanPicks.size}. Fly picks: sealed.`;}
   else if(s.running){thought=['Do not distract the professional.','Yes, I am looking with my actual neurons.','You look nervous for a human.'][Math.floor((p.rows?.length||0)/3)%3];title='The applicant is taking the test';note=`${p.rows?.length||0}/9 answers locked. Your picks cannot change its decisions.`;}
   else if(p.result){
     const r=p.result,h=r.human_correct;
     thought=h===null?(r.passed?'I am now legally a person. Probably.':'The CAPTCHA and I have creative differences.')
       :r.fly_correct>h?'Have you considered applying as the fly?':r.fly_correct<h?'I demand a recount. And a banana.':'Same score. Suspicious. How many legs do YOU have?';
     title=h===null?`Fly: ${r.fly_correct}/9`:`You: ${h}/9. Fly: ${r.fly_correct}/9.`;
     note=r.passed?'Perfect board. One banana added to payroll.':'No perfect board. Payroll has rejected this invoice.';
     $('verdict').textContent=h===null?(r.passed?'HUMAN ENOUGH':'PLEASE TRY AGAIN'):r.fly_correct>h?'HUMANITY: QUESTIONABLE':r.fly_correct<h?'HUMANITY: CONFIRMED':'IDENTITY: INCONCLUSIVE';
     $('verdict').classList.toggle('fail',!r.passed);$('verdict').hidden=false;
   }
 }
 if(s.status==='Stopped'){thought='Union-mandated banana break.';title=s.trained?'Applicant on a break':'Interview paused';note=s.trained?'Another CAPTCHA is waiting when you are.':'Start fresh for a new applicant.';}
 if(s.status.startsWith('Failed')){thought='The paperwork has jammed.';title='Round interrupted';note=s.status;}
 $('thought').textContent=thought;$('round-title').textContent=title;$('round-note').textContent=note;
 const stage=p?.stage||s.status;
 if(stage!==boardStage){boardStage=stage;window.lucide?.createIcons();}
}

async function command(path,body){
 if(pending)return;
 pending=true;requestError='';
 for(const id of ['next','race','watch','start'])$(id).disabled=true;
 try{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(10000)});if(!r.ok){const b=await r.json();throw Error(b.detail||`HTTP ${r.status}`)}}
 catch(e){requestError=`Request failed: ${e.message}`;$('status').textContent=requestError;}
 finally{pending=false;}
}
$('next').onclick=()=>command('/api/practice/board');
$('race').onclick=()=>command('/api/practice/play',{board_id:practiceId,selections:[...humanPicks]});
$('watch').onclick=()=>command('/api/practice/play',{board_id:practiceId});
const raycaster=new THREE.Raycaster();
canvas.addEventListener('pointerdown',e=>{pointerStart=[e.clientX,e.clientY];});
canvas.addEventListener('pointerup',e=>{
 if(!pointerStart||Math.hypot(e.clientX-pointerStart[0],e.clientY-pointerStart[1])>6||snapshot?.practice?.stage!=='choosing'||pending)return;
 const r=canvas.getBoundingClientRect(),w=canvas.clientWidth,h=canvas.clientHeight,mobile=w<650,vw=mobile?w:Math.floor(w*.7),vh=mobile?Math.floor(h*.6):h,x=e.clientX-r.left,y=e.clientY-r.top;
 if(x>vw||y>vh)return;
 raycaster.setFromCamera(new THREE.Vector2(x/vw*2-1,1-y/vh*2),camera);
 const hit=raycaster.intersectObject(floor)[0];if(!hit)return;
 const px=hit.uv.x*900,py=(1-hit.uv.y)*1080,col=Math.floor(px/300),row=Math.floor((py-156)/300);
 if(col<0||col>2||row<0||row>2)return;
 const i=row*3+col;humanPicks.has(i)?humanPicks.delete(i):humanPicks.add(i);personality();paint();
});
async function poll(){try{const response=await fetch('/api/state',{signal:AbortSignal.timeout(10000)});if(!response.ok)throw Error('State request failed');snapshot=await response.json();if(snapshot.run_id!==runId){runId=snapshot.run_id;observedRunning=false;clearRunView();}if(snapshot.running)observedRunning=true;
// Loading a completed/stopped snapshot must not masquerade as a live inspection.
if(!observedRunning&&!snapshot.running&&snapshot.mode!=='practice'){snapshot={...snapshot,observation:null,record:null,board:snapshot.trained?snapshot.board:[],tile_index:null};}
canvas.dataset.runState=snapshot.running?'running':'idle';
$('status').textContent=requestError||(pending?'Working':snapshot.status==='Stopped'&&!observedRunning?'Stopped / no experiment running':snapshot.status);$('start').disabled=pending||snapshot.running;$('stop').disabled=!snapshot.running;personality();const key=snapshot.board.join('|');if(key!==lastBoard){lastBoard=key;selected.clear();imageCount=0;images=snapshot.board.map(id=>{const im=new Image();im.onload=()=>{if(images.includes(im)){imageCount++;paint()}};im.src=`/tiles/${id}.jpg`;return im});paint();}
const ob=snapshot.observation;if(ob&&cursor!==snapshot.cursor){cursor=snapshot.cursor;neural(ob);$('window').textContent=`${ob.spikes.toLocaleString()} spikes / ${ob.view} / 60 ms`;$('gaze').textContent=ob.view;if(ob.retinal_contrast_png){$('retina').src='data:image/png;base64,'+ob.retinal_contrast_png;$('retina').hidden=false}const i=snapshot.tile_index;let x=(i%3-1)*2,z=(Math.floor(i/3)-1)*2+.3;if(ob.view==='left')x-=.4;if(ob.view==='right')x+=.4;latestTarget.set(x,.05,z);paint()}
const row=snapshot.record;if(row){$('choice').textContent=row.policy;$('reward').textContent=row.phase==='training'?(row.correct?'Reward +1':'Reward 0'):(row.correct?'Correct (no feedback)':'Miss (no feedback)');$('feedback').textContent=row.feedback_count;$('budget').textContent=row.controller.policy||'abstained';$('scores').textContent=`leave ${row.scores[0].toFixed(2)} / select ${row.scores[1].toFixed(2)}`;$('error').textContent=row.reward_prediction_error===null?'--':row.reward_prediction_error.toFixed(3);$('resolution').textContent=`${snapshot.overview_size} x ${snapshot.overview_size} overview`;if(row.policy==='select'){const i=snapshot.board.indexOf(row.tile_id);if(i>=0)selected.add(i)}paint()}
if(snapshot.mode==='practice'){for(const r of snapshot.practice?.rows||[])if(r.policy==='select'){const i=snapshot.board.indexOf(r.tile_id);if(i>=0)selected.add(i)}paint();}
else{for(const [id,choice] of Object.entries(snapshot.board_choices||{}))if(choice==='select'){const i=snapshot.board.indexOf(id);if(i>=0)selected.add(i)}paint();}
if(phase!==snapshot.status||snapshot.history.length!==Number($('curve').dataset.count)){chart();phase=snapshot.status;$('curve').dataset.count=snapshot.history.length}
}catch(e){$('status').textContent=requestError||'Connection interrupted'}finally{setTimeout(poll,500)}}
$('start').onclick=async()=>{if(snapshot?.hosted){$('key-dialog').showModal();$('api-key').focus();return;}pending=true;requestError='';$('start').disabled=true;$('status').textContent='Starting';try{const r=await fetch('/api/start',{method:'POST',signal:AbortSignal.timeout(10000)});if(!r.ok){const body=await r.json();throw Error(body.detail||`HTTP ${r.status}`)}}catch(e){requestError=`Start failed: ${e.message}`;$('status').textContent=requestError;}finally{pending=false;}};
$('key-close').onclick=()=>$('key-dialog').close();
$('key-dialog').addEventListener('close',()=>{$('api-key').value='';});
$('api-key').addEventListener('keydown',event=>{if(event.key==='Enter')$('key-start').click();});
$('key-start').onclick=async()=>{let key=$('api-key').value.trim();if(!key)return;$('api-key').value='';$('key-dialog').close();try{await command('/api/start',{api_key:key});}finally{key='';}};
$('forget').onclick=()=>command('/api/end');
$('stop').onclick=async()=>{try{const r=await fetch('/api/stop',{method:'POST',signal:AbortSignal.timeout(10000)});if(!r.ok)throw Error(`HTTP ${r.status}`);}catch(e){requestError=`Stop not confirmed: ${e.message}`;$('status').textContent=requestError;}};
let previous=performance.now();function frame(now){const dt=Math.min(.08,(now-previous)/1000);previous=now;const w=canvas.clientWidth,h=canvas.clientHeight,mobile=w<650,vw=mobile?w:Math.floor(w*.7),vh=mobile?Math.floor(h*.6):h,bw=mobile?w:w-vw,bh=mobile?h-vh:h;renderer.setSize(w,h,false);camera.aspect=vw/vh;camera.updateProjectionMatrix();brainCamera.aspect=bw/bh;brainCamera.position.z=Math.max(4.7,1.65/(Math.tan(35*Math.PI/360)*brainCamera.aspect));brainCamera.updateProjectionMatrix();if(fly){if(snapshot?.running){motionTime+=dt;fly.position.lerp(latestTarget,Math.min(1,dt*4));}animateFly(fly,motionTime,0);canvas.dataset.flyPosition=JSON.stringify(fly.position.toArray())}brain.rotation.y=.12*Math.sin(now*.0004);renderer.setScissorTest(true);renderer.setViewport(0,mobile?h-vh:0,vw,vh);renderer.setScissor(0,mobile?h-vh:0,vw,vh);renderer.clear();renderer.render(scene,camera);renderer.setViewport(mobile?0:vw,0,bw,bh);renderer.setScissor(mobile?0:vw,0,bw,bh);renderer.clear();renderer.render(brainScene,brainCamera);requestAnimationFrame(frame)}requestAnimationFrame(frame);window.lucide?.createIcons();poll();
