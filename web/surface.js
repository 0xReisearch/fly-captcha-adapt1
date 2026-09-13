import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createFly, animateFly } from '/fruitless/fly.js';
import { createConnectome } from '/fruitless/connectome.js';

const canvas = document.getElementById('anatomy');
const status = document.getElementById('anatomy-status');
const label = document.getElementById('neural-window');
const source = document.getElementById('captcha');
let latest = null, tile = null, playback = null, dirty = true, motionTime = 0;
window.flyAnatomy = {
  observe(row) { latest = row; },
  clear() { latest = null; tile = null; label.textContent = 'AWAITING OBSERVATION'; dirty = true; },
  renderOverlay(state) { playback = state; },
};
async function load(url, kind = 'json') {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response[kind]();
}

// The existing board supplies layout and visible choices, never an answer oracle.
const boardCanvas = document.createElement('canvas'), ctx = boardCanvas.getContext('2d');
const boardTexture = new THREE.CanvasTexture(boardCanvas);
boardTexture.colorSpace = THREE.SRGBColorSpace;
new MutationObserver(() => { dirty = true; }).observe(source, {subtree:true, childList:true, attributes:true, characterData:true});
source.addEventListener('load', () => { dirty = true; }, true);
document.fonts.ready.then(() => { dirty = true; });
function paintBoard() {
  const r = source.getBoundingClientRect(), width = 1200, height = Math.round(width*r.height/r.width);
  if(boardCanvas.width!==width||boardCanvas.height!==height){boardCanvas.width=width;boardCanvas.height=height;}
  ctx.setTransform(width/r.width,0,0,width/r.width,0,0);
  ctx.fillStyle='white';ctx.fillRect(0,0,r.width,r.height);
  const rect=el=>{const b=el.getBoundingClientRect();return {x:b.x-r.x,y:b.y-r.y,w:b.width,h:b.height};};
  const fill=(b,color)=>{ctx.fillStyle=color;ctx.fillRect(b.x,b.y,b.w,b.h);};
  const text=(value,x,y,size,color,weight=400)=>{ctx.font=`${weight} ${size}px "DM Sans", sans-serif`;ctx.fillStyle=color;ctx.textAlign='left';ctx.fillText(value,x,y);};
  const prompt=rect(source.querySelector('.prompt'));fill(prompt,'#1e2a4a');
  text('Select all images with',prompt.x+23,prompt.y+32,16,'white');
  text('bananas',prompt.x+23,prompt.y+65,31,'white',700);
  text('Your species is not a valid form of identification.',prompt.x+23,prompt.y+88,10,'#e9efff');
  let loaded=0;
  for(const el of source.querySelectorAll('.tile')){
    const b=rect(el),img=el.querySelector('img'),selected=el.classList.contains('selected');fill(b,selected?'#1e2a4a':'#eee');
    if(img.complete&&img.naturalWidth){const pad=selected?b.w*.075:0;ctx.drawImage(img,b.x+pad,b.y+pad,b.w-2*pad,b.h-2*pad);loaded++;}
    if(el.classList.contains('inspecting')){ctx.strokeStyle='#9f4f3d';ctx.lineWidth=3;ctx.strokeRect(b.x+2,b.y+2,b.w-4,b.h-4);}
    if(selected){
      ctx.beginPath();ctx.arc(b.x+17,b.y+17,11,0,Math.PI*2);ctx.fillStyle='#1e2a4a';ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=2;ctx.stroke();
      ctx.beginPath();ctx.moveTo(b.x+12,b.y+17);ctx.lineTo(b.x+16,b.y+21);ctx.lineTo(b.x+23,b.y+13);ctx.stroke();
    }
  }
  const verify=rect(document.getElementById('verify'));
  fill(verify,document.getElementById('verify').classList.contains('pressed')?'#141c32':'#1e2a4a');
  text('VERIFY',verify.x+18,verify.y+verify.h*.65,12,'white',700);
  text(document.getElementById('inspection').textContent,23,verify.y+verify.h*.65,10,'#6b6a64');
  const verdict=document.getElementById('verdict');
  if(!verdict.hidden){
    ctx.fillStyle=verdict.classList.contains('fail')?'#fff6f0ed':'#fdfbf8ed';ctx.fillRect(0,0,r.width,r.height);
    ctx.textAlign='center';ctx.font='600 29px "DM Sans", sans-serif';ctx.fillStyle=verdict.classList.contains('fail')?'#a5482d':'#9f4f3d';
    ctx.fillText(document.getElementById('verdict-title').textContent,r.width/2,r.height/2);
    ctx.font='13px "DM Sans", sans-serif';ctx.fillText(document.getElementById('verdict-detail').textContent,r.width/2,r.height/2+32);
  }
  boardTexture.needsUpdate=true;dirty=false;canvas.dataset.loadedImages=loaded;
  canvas.dataset.selectedTiles=JSON.stringify([...source.querySelectorAll('.tile')].flatMap((el,i)=>el.classList.contains('selected')?[i]:[]));
  return r;
}

try{
  const renderer=new THREE.WebGLRenderer({canvas,antialias:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.autoClear=false;
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  boardTexture.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());
  const scene=new THREE.Scene();scene.background=new THREE.Color('#ebeae5');
  const camera=new THREE.PerspectiveCamera(37,1,.01,100);
  const controls=new OrbitControls(camera,document.getElementById('scene-interaction'));
  controls.enablePan=false;controls.minDistance=9;controls.maxDistance=30;controls.minPolarAngle=.15;controls.maxPolarAngle=Math.PI*.43;
  const home=()=>{const mobile=canvas.clientWidth<650;camera.position.set(mobile?2.6:4.7,mobile?17:14.5,mobile?13:11.5);controls.target.set(0,0,0);controls.update();};
  home();document.getElementById('camera-home').onclick=home;
  scene.add(new THREE.HemisphereLight('#d5d9df','#20232b',1.4));
  const key=new THREE.DirectionalLight('#fff1d1',3);key.position.set(-4,12,7);key.castShadow=true;
  Object.assign(key.shadow.camera,{left:-9,right:9,top:9,bottom:-9,near:.1,far:35});key.shadow.mapSize.set(2048,2048);key.shadow.normalBias=.025;scene.add(key);
  const rim=new THREE.DirectionalLight('#aabed8',1.4);rim.position.set(3,5,-7);scene.add(rim);
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(60,60),new THREE.MeshStandardMaterial({color:'#e2dfd7',roughness:1}));
  floor.rotation.x=-Math.PI/2;floor.position.y=-.05;floor.receiveShadow=true;scene.add(floor);
  const grid=new THREE.GridHelper(60,60,'#b7b5ad','#cdc7b9');grid.material.transparent=true;grid.material.opacity=.3;grid.position.y=-.04;scene.add(grid);
  const r=paintBoard(),boardWidth=7,boardHeight=boardWidth*r.height/r.width;
  const board=new THREE.Mesh(new THREE.PlaneGeometry(boardWidth,boardHeight),new THREE.MeshBasicMaterial({map:boardTexture,toneMapped:false}));
  board.rotation.x=-Math.PI/2;board.position.y=.005;scene.add(board);
  const shadow=new THREE.Mesh(board.geometry,new THREE.ShadowMaterial({opacity:.28}));shadow.rotation.x=-Math.PI/2;shadow.position.y=.01;shadow.receiveShadow=true;scene.add(shadow);
  const brainScene=new THREE.Scene();brainScene.background=new THREE.Color('#e2dfd7');
  const brainCamera=new THREE.PerspectiveCamera(35,1,.01,100),brain=new THREE.Group();brainScene.add(brain);
  const [fly,raw,activity,manifest]=await Promise.all([createFly('/fruitless/assets/fly'),load('/anatomy/positions.f32','arrayBuffer'),load('/api/neural-activity'),load('/anatomy/manifest.json')]);
  const extent=new THREE.Box3().setFromObject(fly).getSize(new THREE.Vector3());fly.scale.setScalar(1.25/Math.max(extent.x,extent.y,extent.z));scene.add(fly);
  const connectome=createConnectome(brain,new Float32Array(raw),activity);
  brain.children[0].material.color.set('#6b6a64');
  for(const layer of brain.children.slice(1)){layer.material.color.set('#9f4f3d');layer.material.blending=THREE.NormalBlending;}
  canvas.dataset.ready='true';canvas.dataset.mesh=fly.name;canvas.dataset.positionedNeurons=manifest.positioned_neurons;
  status.textContent=`${manifest.positioned_neurons.toLocaleString()} mapped soma positions`;document.getElementById('begin').disabled=false;
  let previous=performance.now(),lastMobile=null,lastW=0,lastH=0;
  function frame(now){
    const dt=Math.min(.08,(now-previous)/1000);previous=now;if(dirty)paintBoard();
    const w=canvas.clientWidth,h=canvas.clientHeight,mobile=w<650;
    const viewW=mobile?w:Math.round(w*.72),viewH=mobile?Math.round(h*.65):h;
    const brainW=mobile?w:w-viewW,brainH=mobile?h-viewH:h;
    if(w!==lastW||h!==lastH){renderer.setSize(w,h,false);lastW=w;lastH=h;}
    camera.aspect=viewW/viewH;camera.updateProjectionMatrix();if(lastMobile!==mobile){home();lastMobile=mobile;}
    brainCamera.aspect=brainW/brainH;brainCamera.position.z=Math.max(4.8,1.65/(Math.tan(35*Math.PI/360)*brainCamera.aspect));brainCamera.updateProjectionMatrix();
    if(latest&&tile!==latest.tile_id){tile=latest.tile_id;connectome.update(0,'measured',tile);canvas.dataset.tile=tile;canvas.dataset.spikeHash=latest.neural.spike_sha256;label.textContent=`${latest.neural.spikes.toLocaleString()} SPIKES / 60 ms`;}
    if(!latest){for(const child of brain.children.slice(1))child.geometry?.setDrawRange(0,0);delete canvas.dataset.tile;delete canvas.dataset.spikeHash;}
    if(playback){
      const s=playback,r=source.getBoundingClientRect(),started=s.started,moving=started&&!s.paused&&!s.complete&&s.stage==='move';
      if(moving)motionTime+=dt*Number(document.getElementById('speed').value);
      // One transform maps both the photographed board and recorded cursor to the floor.
      fly.position.set(started?(s.x/r.width-.5)*boardWidth:-boardWidth/2-1,.02,started?(s.y/r.height-.5)*boardHeight:-boardHeight/2+1);
      fly.rotation.y=started?Math.PI/2-s.angle:0;animateFly(fly,motionTime,0);
      if(moving){
        const rig=fly.userData.fly;
        // Illustrative tripod stride; it never changes a choice or a neural response.
        for(const side of ['l','r'])for(const leg of ['f','m','h']){
          const name=`${side}${leg}_trochanterfemur`,dof=rig.dofs[name]?.find(d=>d.name.endsWith('-pitch'));
          if(dof){const phase=(side==='l'?0:Math.PI)+(leg==='m'?Math.PI:0);rig.nodes[name].quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(dof.vector,Math.sin(motionTime*14+phase)*.16));}
        }
      }
      canvas.dataset.flyPosition=JSON.stringify(fly.position.toArray());canvas.dataset.boardSize=JSON.stringify([boardWidth,boardHeight]);canvas.dataset.stage=s.stage;
    }
    brain.rotation.y=.12*Math.sin(now*.0004);brain.rotation.z=.04;renderer.setScissorTest(true);
    renderer.setViewport(0,mobile?h-viewH:0,viewW,viewH);renderer.setScissor(0,mobile?h-viewH:0,viewW,viewH);renderer.clear();renderer.render(scene,camera);
    renderer.setViewport(mobile?0:viewW,0,brainW,brainH);renderer.setScissor(mobile?0:viewW,0,brainW,brainH);renderer.clear();renderer.render(brainScene,brainCamera);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}catch(error){status.textContent=`Anatomy unavailable: ${error.message}`;canvas.dataset.error=error.message;console.error(error);}
