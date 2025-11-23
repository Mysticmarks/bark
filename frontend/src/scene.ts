import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export function bootstrapScene() {
  const canvas = document.getElementById('scene') as HTMLCanvasElement | null;
  if (!canvas) return;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(canvas.clientWidth, canvas.clientHeight);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x03060d);

  const camera = new THREE.PerspectiveCamera(60, canvas.clientWidth / canvas.clientHeight, 0.1, 100);
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
    roughness: 0.3
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
    envMapIntensity: 1.1
  });
  const ring = new THREE.Mesh(ringGeo, ringMat);
  ring.castShadow = true;
  scene.add(ring);

  const cubeGeo = new THREE.BoxGeometry(1.2, 1.2, 1.2);
  const cubeMat = new THREE.MeshStandardMaterial({
    color: new THREE.Color('#f264f3'),
    metalness: 0.7,
    roughness: 0.25,
    emissive: new THREE.Color('#1a0d1e')
  });
  const cube = new THREE.Mesh(cubeGeo, cubeMat);
  cube.position.set(-2, 0.8, -1.4);
  cube.castShadow = true;
  scene.add(cube);

  const gridHelper = new THREE.GridHelper(20, 20, '#1d293a', '#0c1420');
  gridHelper.position.y = 0.001;
  scene.add(gridHelper);

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

  animate();
  window.addEventListener('resize', resizeRenderer);
}

export function renderStats() {
  const statsEl = document.getElementById('sceneStats');
  if (!statsEl) return;
  const stats = [
    `1D: text/audio prompts`,
    `2D: image stacks → volumes`,
    `3D: orbit scene objects`,
    `4D: WebRTC temporal capture`,
    `Video: UHD MP4 @ 30FPS with captions`
  ];
  statsEl.innerHTML = stats.map((line) => `<div>${line}</div>`).join('');
}
