/* The renderer follows recorded Core policies. It never chooses a correct tile. */
const $ = (id) => document.getElementById(id);
// Keep the fixed-size board as a texture source; controls stay in the visible scene.
$('begin').innerHTML='<i data-lucide="play"></i> Watch recording';
$('learner-controls').append($('begin'), $('fresh'), $('stop-run'), $('live-progress'));
$('scene-commands').append($('restart'), $('info'));
$('scene-transport').append(document.querySelector('.transport'));
$('run-status')?.append($('mode-label'), $('board-count'));
const state = {
  trials: [], boards: [], board: 0, step: 0, elapsed: 0, stage: 'move', started: false,
  paused: false, complete: false, live: false, liveDone: false, liveCursor: 0, liveRunId: null, stopping: false, stopped: false,
  outcomes: [], neural: [], passes: 0, attempted: 0, correct: 0, phaseCount: 0,
  lastPhase: '', renderedBoard: -1, x: 0, y: 0, fromX: 0, fromY: 0, angle: 0, result: null,
};
let audioContext, muted = true, previous = performance.now(), pollTimer, polling = false;
const quips = {
  before: ['I have never been more human.', 'Nine squares. How hard can it be?', 'My lawyer says I am human.'],
  training: ['Is that a banana or a promotion?', 'Okay. Less citrus. More banana.', 'Feedback noted. Dignity intact.', 'I am growing professionally.'],
  after: ['I would like my banana now.', 'Six legs. Zero doubts.', 'Please respect my human rights.'],
};
const phaseLabels = {before: 'FIRST IMPRESSIONS', training: 'LEARNING', after: 'UNSEEN IMAGE TEST'};

function icons() { if (window.lucide) window.lucide.createIcons(); }
function toast(text) {
  $('toast').textContent = text; $('toast').hidden = false;
  setTimeout(() => $('toast').hidden = true, 5500);
}
function canvasSize(canvas) {
  const rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
    canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
  }
  const ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {ctx, w: rect.width, h: rect.height};
}
function lineChart(canvas, values, color, range = [0, 1]) {
  const {ctx, w, h} = canvasSize(canvas); ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = '#cdc7b9'; ctx.lineWidth = 1;
  for (let i = 1; i <= 3; i++) { let y = h * i / 4; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  if (!values.length) return;
  const pos = values.map((v, i) => [3 + (w - 6) * i / Math.max(1, values.length - 1), h - 7 - (v - range[0]) / Math.max(.01, range[1] - range[0]) * (h - 14)]);
  ctx.beginPath(); pos.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
  const [x, y] = pos.at(-1); ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
}
function charts() {
  const rolling = state.outcomes.map((_, i, a) => { const v = a.slice(Math.max(0, i-35), i+1); return v.reduce((x,y)=>x+y,0)/v.length; });
  lineChart($('learning'), rolling, '#9f4f3d');
  lineChart($('activity'), state.neural.slice(-45), '#9f4f3d', [0, 50000]);
}
function groupBoards(rows) {
  const boards = [];
  for (const phase of ['before', 'training', 'after']) {
    // Baseline is condensed to the first two chronological boards, not best/worst selected.
    const all = rows.filter(r => r.phase === phase), subset = phase === 'before' ? all.slice(0, 18) : all;
    for (let i = 0; i + 9 <= subset.length; i += 9) boards.push({phase, rows: subset.slice(i, i + 9)});
  }
  return boards;
}
function updateStats(row) {
  state.outcomes.push(Number(row.correct)); state.neural.push(row.neural.spikes);
  state.correct += Number(row.correct); state.phaseCount++;
  $('accuracy').innerHTML = `${Math.round(state.correct / state.phaseCount * 100)}<em>%</em>`;
  $('feedback').textContent = row.feedback_count;
  $('spikes').textContent = `${row.neural.spikes.toLocaleString()} SPIKES`;
  charts();
}
function setBoard() {
  if (state.board >= state.boards.length) {
    if (state.live && !state.liveDone) { state.renderedBoard=-1;state.stage='waiting';$('inspection').textContent = 'WAITING FOR CORE'; return false; }
    state.complete = true; state.paused = true; $('pause').innerHTML = '<i data-lucide="play"></i>'; icons();
    $('phase').textContent = 'EXPERIMENT COMPLETE';
    $('speech').textContent = 'I would like to speak to a banana.';
    toast('Run complete. Every choice is in the trace.'); return false;
  }
  const board = state.boards[state.board];
  state.renderedBoard = state.board;
  if (board.phase !== state.lastPhase) {
    state.correct = 0; state.phaseCount = 0; state.lastPhase = board.phase;
    $('phase').textContent = phaseLabels[board.phase];
    const labels = {before:['EMPTY TASK MEMORY','Great confidence.<br>Absolutely no qualifications.'],training:['FEEDBACK ON','One choice. One outcome.<br>The readout is learning.'],after:['LEARNING FROZEN','Different photographs.<br>No answers coming back.']};
    $('stage-label').textContent = labels[board.phase][0]; $('stage-copy').innerHTML = labels[board.phase][1];
  }
  const sayings = quips[board.phase]; $('speech').textContent = sayings[state.board % sayings.length];
  $('board-count').textContent = `ROUND ${String(state.board + 1).padStart(2,'0')}`;
  $('verdict').hidden = true; $('verify').classList.remove('pressed');
  $('tiles').replaceChildren(...board.rows.map((row, i) => {
    const tile = document.createElement('div'); tile.className = 'tile';
    const img = document.createElement('img'); img.src = `/tiles/${row.tile_id}.jpg`; img.alt = `Fruit photograph ${i+1}`; img.draggable = false;
    const tick = document.createElement('span'); tick.className = 'tick'; tick.innerHTML = '<i data-lucide="check"></i>';
    const idx = document.createElement('span'); idx.className = 'index'; idx.textContent = String(i+1).padStart(2,'0');
    tile.append(img, tick, idx); return tile;
  }));
  icons(); state.step = 0; state.stage = 'move'; state.elapsed = 0;
  const rect = $('captcha').getBoundingClientRect(); state.x = -rect.width / 7; state.y = rect.width / 7;
  state.fromX = state.x; state.fromY = state.y; $('inspection').textContent = 'INSPECTING'; return true;
}
function destination() {
  const parent = $('captcha').getBoundingClientRect();
  const el = state.step < 9 ? $('tiles').children[state.step] : $('verify');
  if (!el) return {x:parent.width/2, y:55};
  const rect = el.getBoundingClientRect(); return {x:rect.x-parent.x+rect.width/2, y:rect.y-parent.y+rect.height/2};
}
function chime(good) {
  if (muted || !audioContext) return;
  const oscillator = audioContext.createOscillator(), gain = audioContext.createGain(), now = audioContext.currentTime;
  oscillator.type = 'sine'; oscillator.frequency.setValueAtTime(good ? 550 : 180, now); oscillator.frequency.exponentialRampToValueAtTime(good ? 850 : 120, now+.16);
  gain.gain.setValueAtTime(.035,now); gain.gain.exponentialRampToValueAtTime(.0001,now+.25);
  oscillator.connect(gain); gain.connect(audioContext.destination); oscillator.start(now); oscillator.stop(now+.26);
}
function tick(dt) {
  if (!state.started || state.paused || state.complete) return;
  const board = state.boards[state.board]; if (!board) {setBoard(); return;}
  if(state.renderedBoard !== state.board){setBoard();return;}
  if ($('tiles').children.length !== 9) {setBoard(); return;}
  state.elapsed += dt * Number($('speed').value);
  if (state.stage === 'move') {
    const point = destination(), p = Math.min(state.elapsed / 700, 1), eased = p*p*(3-2*p);
    state.x = state.fromX + (point.x-state.fromX)*eased + Math.sin(p*Math.PI)*12;
    state.y = state.fromY + (point.y-state.fromY)*eased;
    state.angle = Math.atan2(point.y-state.fromY,point.x-state.fromX)+Math.PI/2;
    if (p === 1) {state.stage='choose';state.elapsed=0;if(state.step<9)window.flyAnatomy?.observe(board.rows[state.step]);}
    if(state.step < 9 && !$('tiles').children[state.step].classList.contains('inspecting')) $('tiles').children[state.step].classList.add('inspecting');
  } else if (state.stage === 'choose' && state.elapsed > 420) {
    if (state.step < 9) {
      const row = board.rows[state.step], tile = $('tiles').children[state.step];
      tile.classList.remove('inspecting');
      if (row.policy === 'select') tile.classList.add('selected');
      $('inspection').textContent = row.policy === 'select' ? 'SELECT' : row.policy === 'leave' ? 'LEAVE' : 'ABSTAIN';
      updateStats(row); state.step++; state.fromX=state.x;state.fromY=state.y;state.stage='move';state.elapsed=0;
    } else {
      $('verify').classList.add('pressed'); state.stage='verify';state.elapsed=0;
    }
  } else if (state.stage === 'verify' && state.elapsed > 450) {
    const correct = board.rows.filter(r=>r.correct).length, pass = correct === 9;
    state.attempted++; if(pass) state.passes++;
    $('passes').textContent = `${state.passes} / ${state.attempted}`;
    $('stamp').textContent = pass ? 'HUMAN ENOUGH' : 'IDENTITY UNCONFIRMED'; $('stamp').classList.toggle('accepted',pass);
    $('verdict').classList.toggle('fail',!pass); $('verdict').hidden=false;
    $('verdict-title').textContent = pass ? 'Human enough.' : 'Sir, you are a fly.';
    $('verdict-detail').textContent = pass ? 'Apparently this is all it takes.' : `${correct} of 9 correct. Please try being human again.`;
    $('verdict').querySelector('.verdict-icon').innerHTML = `<i data-lucide="${pass?'check':'scan-face'}"></i>`;icons();chime(pass);
    state.stage='verdict';state.elapsed=0;
  } else if (state.stage === 'verdict' && state.elapsed > 3700) {
    state.board++;setBoard();
  }
  $('timeline-fill').style.width = `${(state.board+(state.step/10))/(state.live?62:Math.max(1,state.boards.length))*100}%`;
}
function frame(now) {
  const dt=Math.min(80,now-previous);previous=now;tick(dt);
  window.flyAnatomy?.renderOverlay?.(state, now);
  requestAnimationFrame(frame);
}
function reset(rows) {
  window.flyAnatomy?.clear();
  Object.assign(state,{trials:rows,boards:groupBoards(rows),board:0,renderedBoard:-1,step:0,elapsed:0,stage:'move',complete:false,paused:false,outcomes:[],neural:[],passes:0,attempted:0,correct:0,phaseCount:0,lastPhase:''});
  $('tiles').replaceChildren();
  $('passes').textContent='0 / 0';$('feedback').textContent='0';$('accuracy').innerHTML='--<em>%</em>';
  $('pause').innerHTML='<i data-lucide="pause"></i>';$('pause').title='Pause playback';$('pause').setAttribute('aria-label','Pause playback');
  charts();setBoard();icons();
}
async function loadReplay() {
  const response=await fetch('/api/replay');if(!response.ok) throw Error('The experiment is not ready yet.');
  const data=await response.json();state.result=data;state.live=false;state.liveDone=false;
  state.stopping=false;state.stopped=false;$('live-progress').textContent='';$('stop-run').hidden=true;
  $('download-results').href='/api/evidence';$('download-trace').href='/api/trace';
  $('download-audit').hidden=true;
  $('mode-label').innerHTML='<span class="status-dot"></span> RECORDED EXPERIMENT';
  const m=data.results.metrics;
  $('before-result').textContent=`${(m.before.accuracy*100).toFixed(1)}%`;
  $('after-result').textContent=`${(m.after.accuracy*100).toFixed(1)}%`;
  $('shuffle-result').textContent=`${(m.shuffled_neural_input.accuracy*100).toFixed(1)}%`;
  $('reference-note').textContent=`Recorded reference / seed ${data.results.seed}. 360 feedbacks; 180 test images.`;
  reset(data.trials);return data;
}
async function pollLive() {
  if(polling)return;
  polling=true;
  try {
    const response=await fetch(`/api/live?cursor=${state.liveCursor}${state.liveRunId?'&run_id='+encodeURIComponent(state.liveRunId):''}`,{signal:AbortSignal.timeout(10000)}),data=await response.json();
    if(!response.ok)throw Error(data.detail||data.error||'Unable to read this run.');
    state.trials.push(...data.events);state.liveCursor=data.cursor;state.boards=groupBoards(state.trials);state.liveDone=!data.running;
    state.stopped=Boolean(data.stopped);state.stopping=Boolean(data.stopping);
    $('live-progress').textContent=state.stopping?'Stopping after the current API request.':data.error||data.progress||'';
    if(!data.running){
      $('fresh').disabled=false;$('stop-run').hidden=true;clearInterval(pollTimer);
      if(state.stopped){state.paused=true;state.complete=true;$('phase').textContent='LEARNING STOPPED';$('mode-label').textContent='STOPPED / YOUR LEARNER';$('live-progress').textContent='Stopped. Your partial results are available to download.';}
      else if(data.error){state.paused=true;state.complete=true;$('phase').textContent='RUN INCOMPLETE';toast(data.error);}
      else $('live-progress').textContent='Learning run complete. Results are ready.';
    }
  }catch(error){$('live-progress').textContent='Connection interrupted. Learning may still be running; Stop learning remains available.';$('fresh').disabled=state.live&&!state.liveDone;state.paused=true;}
  finally{polling=false;}
}
async function resumeOwnedRun() {
  const response=await fetch('/api/current');if(!response.ok)return;
  const {run}=await response.json();if(!run)return;
  state.live=true;state.liveDone=false;state.liveCursor=0;state.liveRunId=run.run_id;
  reset([]);state.complete=false;state.paused=false;state.started=true;
  $('fresh').disabled=run.running;$('stop-run').hidden=!run.running;$('stop-run').disabled=false;
  $('begin').hidden=true;$('start-overlay').hidden=true;
  $('mode-label').textContent=`LIVE CORE / SEED ${run.seed}`;
  const query='?run_id='+encodeURIComponent(run.run_id);
  $('download-results').href='/api/live/evidence'+query;$('download-trace').href='/api/live/trace'+query;
  $('download-audit').href='/api/live/audit'+query;$('download-audit').hidden=false;
  await pollLive();if(!state.liveDone)pollTimer=setInterval(pollLive,1000);
}
$('begin').onclick=()=>{state.started=true;state.paused=false;$('start-overlay').hidden=true;$('begin').hidden=true;};
$('pause').onclick=()=>{
  if(state.complete){reset(state.trials);state.started=true;}
  else state.paused=!state.paused;
  const label=state.paused?'Resume playback':'Pause playback';$('pause').title=label;$('pause').setAttribute('aria-label',label);$('pause').innerHTML=`<i data-lucide="${state.paused?'play':'pause'}"></i>`;icons();
};
$('restart').onclick=async()=>{if(state.live&&!state.liveDone){toast('Stop the active learner before switching to the recording.');return;}clearInterval(pollTimer);await loadReplay();state.started=true;$('start-overlay').hidden=true;};
$('info').onclick=()=>$('details').showModal();$('details').querySelector('.close').onclick=()=>$('details').close();
$('sound').onclick=async()=>{muted=!muted;if(!muted){audioContext??=new AudioContext();await audioContext.resume();chime(true);}$('sound').innerHTML=`<i data-lucide="${muted?'volume-x':'volume-2'}"></i>`;$('sound').title=muted?'Enable sound':'Mute sound';$('sound').setAttribute('aria-label',$('sound').title);icons();};
$('fresh').onclick=()=>{if(document.body.dataset.recordingOnly){location.href='/live';return;}$('key-dialog').showModal();$('api-key').focus();};
$('key-close').onclick=()=>$('key-dialog').close();
$('key-dialog').addEventListener('close',()=>{$('api-key').value='';});
$('api-key').addEventListener('keydown',event=>{if(event.key==='Enter')$('key-start').click();});
$('stop-run').onclick=async()=>{
  $('stop-run').disabled=true;state.paused=true;
  try {
    const response=await fetch('/api/stop?run_id='+encodeURIComponent(state.liveRunId),{method:'POST',signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw Error('Stop was not confirmed. Please retry.');
    state.stopping=true;$('stop-run').innerHTML='<i data-lucide="loader-circle"></i> Stopping...';icons();
    $('live-progress').textContent='Stopping after the current API request. Previously accepted feedback is kept.';
    clearInterval(pollTimer);pollTimer=setInterval(pollLive,1000);await pollLive();
  } catch(error){$('stop-run').disabled=false;toast(error.message);$('live-progress').textContent='Stop not confirmed. Retry Stop learning.';}
};
$('key-start').onclick=async()=>{
  let apiKey=$('api-key').value.trim();
  if(!apiKey){$('api-key').focus();return;}
  $('api-key').value='';$('key-dialog').close();
  $('fresh').disabled=true;
  try {
    const response=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:apiKey})});apiKey='';
    const data=await response.json();if(!response.ok)throw Error(data.detail);
    state.live=true;state.liveDone=false;state.liveCursor=0;state.liveRunId=data.run_id||null;state.stopping=false;state.stopped=false;reset([]);state.complete=false;state.paused=false;state.started=true;
    const runQuery=state.liveRunId?'?run_id='+encodeURIComponent(state.liveRunId):'';
    $('download-results').href='/api/live/evidence'+runQuery;$('download-trace').href='/api/live/trace'+runQuery;
    $('download-audit').href='/api/live/audit'+runQuery;$('download-audit').hidden=false;
    $('stop-run').hidden=false;$('stop-run').disabled=false;$('stop-run').innerHTML='<i data-lucide="square"></i> Stop learning';icons();
    $('begin').hidden=true;
    $('start-overlay').hidden=true;$('verdict').hidden=true;$('mode-label').innerHTML=`<span class="status-dot"></span> LIVE CORE / SEED ${data.seed}`;
    $('phase').textContent='EMPTY LEARNER';$('inspection').textContent='WAITING FOR CORE';
    toast('Fresh hosted Domain. The fly is starting over with your API key.');
    clearInterval(pollTimer);await pollLive();if(!state.liveDone)pollTimer=setInterval(pollLive,1000);
  } catch(error){$('fresh').disabled=false;toast(error.message);}finally{apiKey='';}
};
for(const id of ['download-results','download-trace','download-audit']) $(id).addEventListener('click',event=>{
  if(state.live && !state.liveDone){event.preventDefault();toast('The live run is still recording. Downloads will be ready when it finishes.');}
});
window.addEventListener('resize',charts);
icons();loadReplay().then(()=>{if(document.body.dataset.recordingOnly){$('fresh').innerHTML='<i data-lucide="key-round"></i> Try the live neural learner';$('details').querySelectorAll('p')[2].textContent='This recording uses cached neural responses with Adapt-1 selecting tiles. Live mode simulates each view, learns tile choices in fly-side readouts, and uses Adapt-1 to manage additional inspections. Start with your own API key from the live page.';icons();return;}return resumeOwnedRun();}).catch(error=>toast(error.message));requestAnimationFrame(frame);
