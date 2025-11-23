import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.165.0/build/three.module.js';
import { OrbitControls } from 'https://cdn.jsdelivr.net/npm/three@0.165.0/examples/jsm/controls/OrbitControls.js';

const canvas = document.getElementById('scene');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(canvas.clientWidth, canvas.clientHeight);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x03060d);

const camera = new THREE.PerspectiveCamera(
  60,
  canvas.clientWidth / canvas.clientHeight,
  0.1,
  100
);
camera.position.set(4, 2.5, 4);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.maxDistance = 30;

const hemi = new THREE.HemisphereLight(0x77e7ff, 0x0b0c11, 0.6);
scene.add(hemi);

const dirLight = new THREE.DirectionalLight(0xffffff, 1);
dirLight.position.set(5, 6, 3);
dirLight.castShadow = true;
scene.add(dirLight);

const groundGeo = new THREE.PlaneGeometry(40, 40);
const groundMat = new THREE.MeshStandardMaterial({
  color: new THREE.Color('#0f1624'),
  metalness: 0.6,
  roughness: 0.3,
});
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

const ringGeo = new THREE.TorusKnotGeometry(0.8, 0.28, 180, 32);
const ringMat = new THREE.MeshStandardMaterial({
  color: new THREE.Color('#6ff0ff'),
  metalness: 0.9,
  roughness: 0.1,
  emissive: new THREE.Color('#122436'),
  envMapIntensity: 1.1,
});
const ring = new THREE.Mesh(ringGeo, ringMat);
ring.castShadow = true;
scene.add(ring);

const cubeGeo = new THREE.BoxGeometry(1.2, 1.2, 1.2);
const cubeMat = new THREE.MeshStandardMaterial({
  color: new THREE.Color('#f264f3'),
  metalness: 0.7,
  roughness: 0.25,
  emissive: new THREE.Color('#1a0d1e'),
});
const cube = new THREE.Mesh(cubeGeo, cubeMat);
cube.position.set(-2, 0.8, -1.4);
cube.castShadow = true;
scene.add(cube);

const gridHelper = new THREE.GridHelper(20, 20, '#1d293a', '#0c1420');
gridHelper.position.y = 0.001;
scene.add(gridHelper);

const statsEl = document.getElementById('sceneStats');
const logEl = document.getElementById('log');
const statusEl = document.getElementById('connectionStatus');
const videoPreview = document.getElementById('videoPreview');
let rtcStream;

function updateStats() {
  const stats = [
    `1D: text/audio prompts`,
    `2D: image stacks → volumes`,
    `3D: orbit scene objects`,
    `4D: WebRTC temporal capture`,
  ];
  statsEl.innerHTML = stats.map((line) => `<div>${line}</div>`).join('');
}

function log(message, tag = 'info') {
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `<span>${message}</span><span class="pill">${tag}</span>`;
  logEl.prepend(entry);
}

function resizeRenderer() {
  const { clientWidth, clientHeight } = canvas;
  if (canvas.width !== clientWidth || canvas.height !== clientHeight) {
    renderer.setSize(clientWidth, clientHeight, false);
    camera.aspect = clientWidth / clientHeight;
    camera.updateProjectionMatrix();
  }
}

function animate() {
  requestAnimationFrame(animate);
  resizeRenderer();

  ring.rotation.x += 0.004;
  ring.rotation.y += 0.006;
  cube.rotation.x += 0.005;
  cube.rotation.y -= 0.004;

  controls.update();
  renderer.render(scene, camera);
}

updateStats();
animate();

async function handlePrompt() {
  const text = document.getElementById('textPrompt').value.trim();
  if (!text) {
    log('Please add a prompt before synthesizing.', 'warn');
    return;
  }

  log('Queued text prompt for Bark synthesis (mock endpoint).', '1D');
  try {
    // This stub shows how a backend integration could look.
    await fetch('/api/bark/synthesize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: text, modalities: ['audio', 'video'] }),
    });
    log('Request sent to Bark pipeline.', 'network');
  } catch (err) {
    log(`Offline stub: ${err.message}`, 'offline');
  }
}

document.getElementById('sendPrompt').addEventListener('click', handlePrompt);

document.getElementById('previewAudio').addEventListener('click', () => {
  const file = document.getElementById('audioUpload').files?.[0];
  if (!file) {
    log('Upload an audio file to preview.', 'warn');
    return;
  }
  const url = URL.createObjectURL(file);
  const audio = new Audio(url);
  audio.play();
  log(`Previewing ${file.name} (local only).`, '1D/2D');
});

function buildVolumeTexture(files) {
  // Placeholder to illustrate 3D stacking; real volume building would slice images.
  log(`Queued ${files.length} layer(s) for volume reconstruction.`, '3D');
}

document.getElementById('loadImages').addEventListener('click', () => {
  const files = Array.from(document.getElementById('imageUpload').files || []);
  const asVolume = document.getElementById('enableVolume').checked;
  if (!files.length) {
    log('Add image layers or stacks first.', 'warn');
    return;
  }
  if (asVolume) {
    buildVolumeTexture(files);
  } else {
    log(`Loaded ${files.length} 2D frame(s) for conditioning.`, '2D');
  }
});

async function connectRtc() {
  if (rtcStream) {
    rtcStream.getTracks().forEach((t) => t.stop());
  }
  try {
    rtcStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    videoPreview.srcObject = rtcStream;
    statusEl.textContent = 'RTC Live';
    statusEl.style.color = 'var(--accent)';
    log('WebRTC capture started — frames can feed Bark temporal stacks.', '4D');
  } catch (err) {
    log(`WebRTC unavailable: ${err.message}`, 'offline');
  }
}

document.getElementById('connectRtc').addEventListener('click', connectRtc);

document.getElementById('captureFrame').addEventListener('click', () => {
  if (!rtcStream) {
    log('Connect WebRTC before capturing frames.', 'warn');
    return;
  }
  const track = rtcStream.getVideoTracks()[0];
  const imageCapture = new ImageCapture(track);
  imageCapture
    .grabFrame()
    .then(() => log('Captured frame for 4D stack (client-side stub).', '4D'))
    .catch((err) => log(`Capture failed: ${err.message}`, 'offline'));
});

function saveSession() {
  const entries = Array.from(document.querySelectorAll('.log-entry')).map((el) =>
    el.textContent.trim()
  );
  const blob = new Blob([entries.join('\n')], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'bark-session.log';
  a.click();
  URL.revokeObjectURL(url);
  log('Session saved locally.', 'session');
}

function clearLog() {
  logEl.innerHTML = '';
}

document.getElementById('saveSession').addEventListener('click', saveSession);
document.getElementById('clearLog').addEventListener('click', clearLog);

window.addEventListener('resize', resizeRenderer);
