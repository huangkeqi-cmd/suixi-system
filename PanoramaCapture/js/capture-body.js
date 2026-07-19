// ========== 数据 ==========
var PROJ = null;
var FLOORS = [];
var CURRENT_FLOOR = null;
var MARKERS = {};
var FLOORPLANS = {};
var ACTIVE = null;
var IMG_W = 0, IMG_H = 0;
var SCALE = 1, OFF_X = 0, OFF_Y = 0;
var tempZipBlob = null;

// ========== 方向设置状态 ==========
var DIRECTION_MODE = 'none'; // 'none', 'north', 'manual'
var ALIGN_STEP = 1;
var GYRO_BASE_ANGLE = null;
var CURRENT_GYRO_ANGLE = 0;
var GYRO_LISTENER = null;
var SECTOR_ANGLE = 45; // 扇形张角（度）
var tempAlignMarker = null;
var tempSaveFile = null;
var tempSaveFileName = '';

// ========== 平面旋转与陀螺仪状态 ==========
var PLAN_ALIGNED = false;
var PLAN_HEADING_OFFSET = 0;
var GYRO_HEADING = null;
var GLOBAL_GYRO_LISTENER = null;
var NORTH_CALIBRATION = 0;
var PLAN_ROTATION = 0;
var smoothRotation = 0;
var GYRO_SMOOTH_HEADING = null;
var GYRO_FILTER_ALPHA = 0.08;
var GYRO_MAX_DELTA = 6;
var GYRO_DEADZONE = 2.5;
var GYRO_STILL_THRESHOLD = 1.5;
var GYRO_STILL_WINDOW = 20;
var gyroHistory = [];
var gyroZeroOffset = 0;
var gyroCalibrationCount = 0;
var lastGyroTimestamp = 0;
var ALIGN_MODE = 'realign';
var GYRO_AVAILABLE = false;
var GYRO_ACTIVE = false;

// ========== 手机拍摄模式 ==========
var PHONE_CAMERA_MODE = true;      // 默认启用本机拍摄模式
var PHONE_CAPTURE_TYPE = 'photo';
var PENDING_SAVE_AFTER_CAPTURE = false; // 标记是否从"保存到相册"流程触发拍摄
var PENDING_FINISH_AFTER_CAPTURE = false; // 标记拍摄完成后是否自动完成采集

// ========== 保存到相册临时数据 ==========
var lastPhotoBlob = null;
var lastPhotoName = '';

// ========== 交互状态 ==========
var isDragging = false;
var isScaling = false;
var isMovingMarker = false;
var touches = [];
var lastDist = 0;
var longPressTimer = null;
var clickStart = null;

// ========== 工具函数 ==========
function showMsg(s){
  var el = document.getElementById('msg');
  el.innerHTML = s;
  el.style.display = 'block';
  setTimeout(function(){ el.style.display = 'none'; }, 2000);
}

function $(id){ return document.getElementById(id); }

function generateId(){ return 'f' + Date.now() + '_' + Math.random().toString(36).substr(2,6); }

function normalizeAngleDelta(delta) { delta = delta % 360; if (delta > 180) delta -= 360; if (delta < -180) delta += 360; return delta; }

function detectStillnessAndCalibrate(rawHeading) {
  var now = Date.now();
  var angularVelocity = 0;
  if (lastGyroTimestamp > 0 && gyroHistory.length > 0) {
    var dt = (now - lastGyroTimestamp) / 1000;
    if (dt > 0) {
      var lastHeading = gyroHistory[gyroHistory.length - 1];
      var delta = normalizeAngleDelta(rawHeading - lastHeading);
      angularVelocity = Math.abs(delta / dt);
    }
  }
  lastGyroTimestamp = now;
  gyroHistory.push(rawHeading);
  if (gyroHistory.length > GYRO_STILL_WINDOW) gyroHistory.shift();
  if (gyroHistory.length >= GYRO_STILL_WINDOW) {
    var sum = 0, sumSq = 0;
    for (var i = 0; i < gyroHistory.length; i++) { sum += gyroHistory[i]; sumSq += gyroHistory[i] * gyroHistory[i]; }
    var mean = sum / gyroHistory.length;
    var variance = (sumSq / gyroHistory.length) - (mean * mean);
    if (variance < 4 && angularVelocity < GYRO_STILL_THRESHOLD) {
      gyroCalibrationCount++;
      if (gyroCalibrationCount > 5) {
        var oldZero = gyroZeroOffset;
        gyroZeroOffset = mean;
        if (Math.abs(gyroZeroOffset - oldZero) > 1) {
          gyroCalibrationCount = 0;
        }
      }
    } else {
      gyroCalibrationCount = 0;
    }
  }
  var calibrated = rawHeading - gyroZeroOffset;
  return ((calibrated % 360) + 360) % 360;
}

function smoothGyroInput(raw) {
  if (raw === null || isNaN(raw)) return;
  raw = detectStillnessAndCalibrate(raw);
  if (GYRO_SMOOTH_HEADING === null) { GYRO_SMOOTH_HEADING = raw; GYRO_HEADING = raw; return; }
  var delta = normalizeAngleDelta(raw - GYRO_SMOOTH_HEADING);
  if (Math.abs(delta) < GYRO_DEADZONE) { delta = 0; } else { delta = delta > 0 ? delta - GYRO_DEADZONE : delta + GYRO_DEADZONE; }
  if (Math.abs(delta) > GYRO_MAX_DELTA) { delta = delta > 0 ? GYRO_MAX_DELTA : -GYRO_MAX_DELTA; }
  GYRO_SMOOTH_HEADING += delta * GYRO_FILTER_ALPHA;
  GYRO_SMOOTH_HEADING = ((GYRO_SMOOTH_HEADING % 360) + 360) % 360;
  GYRO_HEADING = GYRO_SMOOTH_HEADING;
}

function startGlobalGyro() {
  if (OFFLINE_MODE) { GYRO_ACTIVE = false; updateGyroStatusBadge(); return; }
  if (GLOBAL_GYRO_LISTENER) return;
  GYRO_AVAILABLE = false;
  GYRO_ACTIVE = false;
  function onOrientation(event) {
    GYRO_AVAILABLE = true;
    GYRO_ACTIVE = true;
    updateGyroStatusBadge();
    var rawHeading = null;
    if (event.webkitCompassHeading !== undefined && !isNaN(event.webkitCompassHeading)) { rawHeading = event.webkitCompassHeading; }
    else if (event.alpha !== null && !isNaN(event.alpha)) { rawHeading = (360 - event.alpha) % 360; }
    if (rawHeading === null || isNaN(rawHeading)) return;
    smoothGyroInput(rawHeading);
    updatePlanRotation();
    updateCompassNeedle();
  }
  GLOBAL_GYRO_LISTENER = onOrientation;
  if (typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
    DeviceOrientationEvent.requestPermission().then(function(state) {
      if (state === 'granted') {
        GYRO_AVAILABLE = true;
        window.addEventListener('deviceorientation', onOrientation);
        updateGyroStatusBadge();
      } else {
        GYRO_AVAILABLE = false;
        updateGyroStatusBadge();
      }
    }).catch(function() {
      GYRO_AVAILABLE = false;
      updateGyroStatusBadge();
    });
  } else {
    window.addEventListener('deviceorientation', onOrientation);
    setTimeout(function() {
      if (!GYRO_AVAILABLE && GYRO_HEADING === null) { GYRO_AVAILABLE = false; } else { GYRO_AVAILABLE = true; }
      updateGyroStatusBadge();
    }, 1500);
  }
}

function stopGlobalGyro() {
  if (GLOBAL_GYRO_LISTENER) { window.removeEventListener('deviceorientation', GLOBAL_GYRO_LISTENER); GLOBAL_GYRO_LISTENER = null; }
  GYRO_HEADING = null;
  GYRO_SMOOTH_HEADING = null;
  GYRO_ACTIVE = false;
  updateGyroStatusBadge();
}

function updateGyroStatusBadge() {
  var badge = $('gyroStatusBadge');
  if (!badge) return;
  badge.classList.remove('gyro-active', 'gyro-inactive', 'gyro-unsupported');
  if (OFFLINE_MODE) { badge.innerHTML = '📴 陀螺仪已关闭'; badge.classList.add('gyro-inactive'); }
  else if (GYRO_ACTIVE && GYRO_AVAILABLE) { badge.innerHTML = '✅ 陀螺仪运行中'; badge.classList.add('gyro-active'); }
  else if (GYRO_AVAILABLE && !GYRO_ACTIVE) { badge.innerHTML = '⚠️ 陀螺仪待激活'; badge.classList.add('gyro-inactive'); }
  else if (!GYRO_AVAILABLE && GLOBAL_GYRO_LISTENER !== null) { badge.innerHTML = '⏳ 正在检测...'; badge.classList.add('gyro-inactive'); }
  else { badge.innerHTML = '❌ 设备不支持'; badge.classList.add('gyro-unsupported'); }
}

function updatePlanRotation() {
  if (!PLAN_ALIGNED || GYRO_HEADING === null || OFFLINE_MODE) return;
  var rawTarget = -(GYRO_HEADING - PLAN_HEADING_OFFSET - NORTH_CALIBRATION);
  var delta = normalizeAngleDelta(rawTarget - smoothRotation);
  smoothRotation += delta * 0.12;
  var layer = $('planLayer'); if (!layer) return;
  var cx = wrap.clientWidth / 2;
  var cy = wrap.clientHeight / 2;
  layer.style.transformOrigin = cx + 'px ' + cy + 'px';
  layer.style.transform = 'rotate(' + smoothRotation.toFixed(2) + 'deg)';
  PLAN_ROTATION = smoothRotation;
  updateCompassNeedle();
  updateDots();
}

function screenToImageCoords(sx, sy, rotation) {
  var rot = (rotation !== undefined) ? rotation : smoothRotation;
  if (!PLAN_ALIGNED || Math.abs(rot) < 0.1 || OFFLINE_MODE) {
    return { x: (sx - OFF_X) / (IMG_W * SCALE), y: (sy - OFF_Y) / (IMG_H * SCALE) };
  }
  var cx = wrap.clientWidth / 2;
  var cy = wrap.clientHeight / 2;
  var rad = rot * Math.PI / 180;
  var cos = Math.cos(rad), sin = Math.sin(rad);
  var dx = sx - cx;
  var dy = sy - cy;
  var rdx = dx * cos + dy * sin;
  var rdy = -dx * sin + dy * cos;
  var sx0 = cx + rdx;
  var sy0 = cy + rdy;
  return { x: (sx0 - OFF_X) / (IMG_W * SCALE), y: (sy0 - OFF_Y) / (IMG_H * SCALE) };
}

function imageToScreenCoords(ix, iy, rotation) {
  var rot = (rotation !== undefined) ? rotation : smoothRotation;
  if (!PLAN_ALIGNED || Math.abs(rot) < 0.1 || OFFLINE_MODE) {
    return { x: OFF_X + ix * IMG_W * SCALE, y: OFF_Y + iy * IMG_H * SCALE };
  }
  var cx = wrap.clientWidth / 2;
  var cy = wrap.clientHeight / 2;
  var rad = rot * Math.PI / 180;
  var cos = Math.cos(rad), sin = Math.sin(rad);
  var sx0 = OFF_X + ix * IMG_W * SCALE;
  var sy0 = OFF_Y + iy * IMG_H * SCALE;
  var dx = sx0 - cx;
  var dy = sy0 - cy;
  var rdx = dx * cos - dy * sin;
  var rdy = dx * sin + dy * cos;
  return { x: cx + rdx, y: cy + rdy };
}

function updateCompassNeedle() {
  var btn = $('compassBtn'); if (!btn) return;
  var rotator = $('compassRotator');
  if (rotator) {
    if (GYRO_HEADING !== null && PLAN_ALIGNED && !OFFLINE_MODE) {
      var compassRotation = -(GYRO_HEADING - NORTH_CALIBRATION);
      rotator.style.transform = 'rotate(' + compassRotation.toFixed(1) + 'deg)';
    } else { rotator.style.transform = 'rotate(0deg)'; }
  }
  if (PLAN_ALIGNED && !OFFLINE_MODE) btn.classList.add('plan-aligned');
  else btn.classList.remove('plan-aligned');
  if (OFFLINE_MODE) btn.classList.add('offline-mode');
  else btn.classList.remove('offline-mode');
}

function updateAlignCompass() {}

function checkAlignmentPrompt() {
  if (PLAN_ALIGNED || OFFLINE_MODE) return;
  if (!CURRENT_FLOOR || !FLOORPLANS[CURRENT_FLOOR]) return;
  $('alignPromptPanel').style.display = 'block';
}

function confirmAlignPrompt() { $('alignPromptPanel').style.display = 'none'; startPlanAlignment(); }

function declineAlignPrompt() { $('alignPromptPanel').style.display = 'none'; showMsg('已跳过方向对齐，可稍后通过指北针设置'); $('compassBtn').style.display = 'block'; }

function startPlanAlignment() {
  var plan = CURRENT_FLOOR ? FLOORPLANS[CURRENT_FLOOR] : null;
  if (!plan) { showMsg('请先导入平面图'); return; }
  ALIGN_MODE = 'realign';
  var img = $('planAlignImg');
  img.src = plan.imgData;
  img.style.display = 'block';
  img.style.maxWidth = '85%';
  img.style.maxHeight = '60%';
  img.style.opacity = '1';
  img.style.filter = 'none';
  var compass = $('alignCompassOverlay');
  if (compass) compass.style.display = 'none';
  $('planAlignPanel').style.display = 'flex';
  $('planAlignTitle').innerHTML = '🧭 平面图方向对齐';
  $('planAlignInstruction').innerHTML = '📐 <strong>重新对齐平面图</strong><br>请<strong>手持手机转动身体</strong>，观察屏幕上的平面图<br>使平面图的方位与<strong>现实场景平行对齐</strong>即可';
  $('planAlignBtn').innerHTML = '我已对齐，锁定方向';
  $('planAlignBtn').onclick = confirmPlanAlignment;
  startGlobalGyro();
  showMsg('请转动手机对齐平面图方向');
}

function confirmPlanAlignment() {
  var currentHeading = GYRO_HEADING;
  if (currentHeading !== null) PLAN_HEADING_OFFSET = currentHeading - NORTH_CALIBRATION;
  else PLAN_HEADING_OFFSET = 0;
  PLAN_ALIGNED = true;
  OFFLINE_MODE = false;
  try { localStorage.setItem('panorama_offline_mode', false); } catch (e) {}
  var toggle = $('offlineModeToggle'); if (toggle) toggle.checked = false;
  $('compassBtn').classList.remove('offline-mode');
  GYRO_SMOOTH_HEADING = null;
  gyroHistory = [];
  gyroZeroOffset = 0;
  gyroCalibrationCount = 0;
  lastGyroTimestamp = 0;
  if (currentHeading !== null) { GYRO_SMOOTH_HEADING = currentHeading; GYRO_HEADING = currentHeading; }
  smoothRotation = 0;
  $('planLayer').style.transform = 'rotate(0deg)';
  $('planAlignPanel').style.display = 'none';
  $('compassBtn').style.display = 'block';
  $('compassBtn').classList.add('plan-aligned');
  $('compassBtn').classList.remove('offline-mode');
  if (alignCompassInterval) { clearInterval(alignCompassInterval); alignCompassInterval = null; }
  updateCompassNeedle();
  updateGyroStatusBadge();
  savePlanAlignmentSettings();
  showMsg('✅ 方向导航已启动！漂移补偿已重置');
}

var alignCompassInterval = null;

function cancelPlanAlignment() {
  $('planAlignPanel').style.display = 'none';
  $('compassBtn').style.display = 'block';
  if (alignCompassInterval) { clearInterval(alignCompassInterval); alignCompassInterval = null; }
  var layer = $('planAlignLayer'); if (layer) { layer.style.transform = 'rotate(0deg)'; }
  showMsg('已取消平面方向对齐');
}

function reAlignPlan() {
  hideCompassPanel();
  PLAN_ALIGNED = false;
  $('planLayer').style.transform = 'rotate(0deg)';
  $('compassBtn').classList.remove('plan-aligned');
  savePlanAlignmentSettings();
  setTimeout(function() { startPlanAlignment(); }, 300);
}

function calibrateNorth() {
  hideCompassPanel();
  var plan = CURRENT_FLOOR ? FLOORPLANS[CURRENT_FLOOR] : null;
  if (!plan) { showMsg('请先导入平面图'); return; }
  ALIGN_MODE = 'calibrate';
  var img = $('planAlignImg');
  img.src = plan.imgData;
  img.style.display = 'block';
  img.style.maxWidth = '100%';
  img.style.maxHeight = '100%';
  img.style.opacity = '0.35';
  img.style.filter = 'brightness(0.6)';
  var compass = $('alignCompassOverlay');
  if (compass) compass.style.display = 'block';
  $('planAlignPanel').style.display = 'flex';
  $('planAlignTitle').innerHTML = '🧭 指北针对齐';
  $('planAlignInstruction').innerHTML = '📐 <strong>校准指北针</strong><br>请将手机<strong>竖向拿稳</strong>，<strong>手机顶部朝向北方</strong><br>观察下方平面图，使其与现实方向对齐';
  $('planAlignBtn').innerHTML = '手机顶部已朝北，确认校准';
  $('planAlignBtn').onclick = confirmNorthCalibration;
  startGlobalGyro();
  if (alignCompassInterval) { clearInterval(alignCompassInterval); }
  alignCompassInterval = setInterval(function() {
    if (GYRO_HEADING !== null && PLAN_ALIGNED && !OFFLINE_MODE) {
      var rawTarget = -(GYRO_HEADING - PLAN_HEADING_OFFSET - NORTH_CALIBRATION);
      var layer = $('planAlignLayer');
      if (layer) {
        var cx = layer.clientWidth / 2 || window.innerWidth / 2;
        var cy = layer.clientHeight / 2 || window.innerHeight / 2;
        layer.style.transformOrigin = cx + 'px ' + cy + 'px';
        layer.style.transform = 'rotate(' + rawTarget.toFixed(2) + 'deg)';
      }
    }
  }, 50);
  showMsg('请将手机顶部对准北方');
}

function confirmNorthCalibration() {
  if (GYRO_HEADING !== null) {
    var currentHeading = GYRO_HEADING;
    var oldNorth = NORTH_CALIBRATION;
    NORTH_CALIBRATION = currentHeading;
    PLAN_HEADING_OFFSET = PLAN_HEADING_OFFSET + oldNorth - NORTH_CALIBRATION;
    GYRO_SMOOTH_HEADING = null;
    gyroHistory = [];
    gyroZeroOffset = 0;
    gyroCalibrationCount = 0;
    lastGyroTimestamp = 0;
    GYRO_SMOOTH_HEADING = currentHeading;
    GYRO_HEADING = currentHeading;
  }
  $('planAlignPanel').style.display = 'none';
  $('compassBtn').style.display = 'block';
  $('compassBtn').classList.add('plan-aligned');
  if (alignCompassInterval) { clearInterval(alignCompassInterval); alignCompassInterval = null; }
  var layer = $('planAlignLayer'); if (layer) { layer.style.transform = 'rotate(0deg)'; }
  updateCompassNeedle();
  savePlanAlignmentSettings();
  showMsg('✅ 指北针已校准，漂移补偿已重置');
  startGlobalGyro();
}

function savePlanAlignmentSettings() {
  try {
    var settings = { planAligned: PLAN_ALIGNED, planHeadingOffset: PLAN_HEADING_OFFSET, northCalibration: NORTH_CALIBRATION, offlineMode: OFFLINE_MODE };
    localStorage.setItem('panorama_plan_alignment', JSON.stringify(settings));
    localStorage.setItem('panorama_offline_mode', OFFLINE_MODE);
  } catch (e) {}
}

function loadPlanAlignmentSettings() {
  try {
    var saved = localStorage.getItem('panorama_plan_alignment');
    if (saved) {
      var settings = JSON.parse(saved);
      PLAN_ALIGNED = settings.planAligned || false;
      PLAN_HEADING_OFFSET = settings.planHeadingOffset || 0;
      NORTH_CALIBRATION = settings.northCalibration || 0;
      OFFLINE_MODE = settings.offlineMode || false;
      if (PLAN_ALIGNED && !OFFLINE_MODE) { $('compassBtn').style.display = 'block'; $('compassBtn').classList.add('plan-aligned'); startGlobalGyro(); }
    }
  } catch (e) {}
  if (OFFLINE_MODE) {
    $('compassBtn').style.display = 'block';
    $('compassBtn').classList.add('offline-mode');
    $('compassBtn').classList.remove('plan-aligned');
    stopGlobalGyro();
  }
  var toggle = $('offlineModeToggle'); if (toggle) toggle.checked = OFFLINE_MODE;
  updateGyroStatusBadge();
}

function showCompassPanel() {
  $('compassStatus').innerHTML = PLAN_ALIGNED && !OFFLINE_MODE ? '✅ 已对齐' : (OFFLINE_MODE ? '📴 离线模式' : '⚠️ 未对齐');
  $('compassRotation').innerHTML = PLAN_ROTATION.toFixed(1) + '°';
  $('compassHeading').innerHTML = GYRO_HEADING !== null ? Math.round(GYRO_HEADING) + '°' : '--°';
  var toggle = $('offlineModeToggle');
  if (toggle) toggle.checked = OFFLINE_MODE;
  updateGyroStatusBadge();
  $('compassPanel').style.display = 'block';
  $('overlay').style.display = 'block';
  $('overlay').onclick = hideCompassPanel;
}

function hideCompassPanel() { $('compassPanel').style.display = 'none'; $('overlay').style.display = 'none'; $('overlay').onclick = hideSharePanel; }

function toggleOfflineMode(checked) {
  OFFLINE_MODE = checked;
  if (OFFLINE_MODE) { stopGlobalGyro(); $('compassBtn').classList.add('offline-mode'); $('compassBtn').classList.remove('plan-aligned'); }
  else { startGlobalGyro(); if (PLAN_ALIGNED) { $('compassBtn').classList.add('plan-aligned'); $('compassBtn').classList.remove('offline-mode'); } }
  savePlanAlignmentSettings();
  updateGyroStatusBadge();
  updateCompassNeedle();
}

// ========== 新建项目 ==========
function showNewProject(){
  if (PROJ) {
    if (!confirm('确定新建项目？当前项目数据将丢失，建议先导出。')) {
      return;
    }
  }
  $('newProjectPanel').style.display = 'block';
  $('newProjName').value = '';
  $('newFloorName').value = '1F';
  $('newProjName').focus();
}

function hideNewProject(){
  $('newProjectPanel').style.display = 'none';
}

// ========== 清理存储功能 ==========
function showClearStoragePanel(){
  var panel = $('clearStoragePanel');
  var infoDiv = $('storageInfo');
  
  var stats = StorageManager.getStats();
  
  var totalPoints = 0;
  for (var fid in MARKERS) {
    if (MARKERS[fid]) {
      totalPoints += MARKERS[fid].length;
    }
  }
  
  infoDiv.innerHTML = 
    '<div style="display:flex; justify-content:space-between; margin-bottom:8px;"><span>记录点数：</span><span style="color:#30d158;">' + totalPoints + ' 个</span></div>' +
    '<div style="display:flex; justify-content:space-between; margin-bottom:8px;"><span>存储块数：</span><span>' + stats.markerKeys + ' 个</span></div>' +
    '<div style="display:flex; justify-content:space-between; margin-bottom:8px;"><span>项目数据：</span><span style="color:#ff9500;">' + stats.markerSizeMB + ' MB</span></div>' +
    '<div style="display:flex; justify-content:space-between; margin-bottom:8px;"><span>总使用量：</span><span style="color:#ff9500;">' + stats.totalSizeMB + ' MB</span></div>' +
    '<div style="width:100%; height:8px; background:#333; border-radius:4px; margin-top:10px;">' +
    '<div style="width:' + stats.percent + '%; height:100%; background:' + (stats.percent > 80 ? '#ff453a' : '#0a84ff') + '; border-radius:4px;"></div></div>' +
    '<div style="text-align:center; font-size:12px; color:#8e8e93; margin-top:5px;">已使用 ' + stats.percent + '%（优化后支持 15,000-50,000 点）</div>';
  
  panel.style.display = 'block';
}

function hideClearStoragePanel(){
  $('clearStoragePanel').style.display = 'none';
}

function exportBeforeClear(){
  hideClearStoragePanel();
  setTimeout(function(){
    doExport();
  }, 100);
}

function doClearStorage(){
  if (!confirm('⚠️ 最后确认：确定要删除所有数据吗？此操作不可恢复！')) {
    return;
  }
  
  try {
    StorageManager.clear();
    localStorage.removeItem('panorama_capture_version');
    localStorage.removeItem('panorama_voice_text');
    localStorage.removeItem('panorama_voice_rate');
    localStorage.removeItem('panorama_floorbar_left');
    showMsg('✅ 存储已清理');
    hideClearStoragePanel();
    setTimeout(function(){
      alert('存储已清理完成！\n\n页面将在点击确定后刷新。\n请重新创建项目。');
      location.reload();
    }, 500);
  } catch(e) {
    alert('清理失败：' + e.message);
  }
}

function createNewProject(){
  var projName = $('newProjName').value.trim();
  var floorName = $('newFloorName').value.trim() || '1F';
  
  if (!projName) {
    showMsg('请输入项目名称');
    return;
  }
  
  PROJ = {
    name: projName,
    createdAt: new Date().toISOString(),
    timeOffset: 0,
    calibrated: false
  };
  
  FLOORS = [];
  CURRENT_FLOOR = null;
  MARKERS = {};
  FLOORPLANS = {};
  ACTIVE = null;
  IMG_W = 0;
  IMG_H = 0;
  
  var fid = generateId();
  FLOORS.push({id: fid, name: floorName, order: 0});
  CURRENT_FLOOR = fid;
  MARKERS[fid] = [];
  
  saveData();
  $('title').innerHTML = PROJ.name;
  renderFloorBar();
  showFloorPlanPrompt();
  hideNewProject();
  showMsg('项目创建成功，请导入平面图');
}

function showFloorPlanPrompt(){
  var currentPlan = FLOORPLANS[CURRENT_FLOOR];
  if (!currentPlan) {
    $('theImg').style.display = 'none';
    $('noPlanMsg').style.display = 'block';
    $('compassBtn').style.display = 'none';
    clearDots();
    updateFloorInfo();
  } else {
    $('noPlanMsg').style.display = 'none';
    loadFloorPlan(currentPlan);
    $('compassBtn').style.display = 'block';
    checkAlignmentPrompt();
  }
}

function importFloorPlan(){
  if (!PROJ) {
    showMsg('请先创建或导入项目');
    return;
  }
  if (!CURRENT_FLOOR) {
    showMsg('请先选择楼层');
    return;
  }
  $('floorPlanInput').click();
}

// 批量导入平面图 (原有完整逻辑，未作改动)
var batchImportQueue = [];
var batchImportIndex = 0;
var batchImportMapping = [];

function batchImportFloorPlans(){
  if (!PROJ) {
    showMsg('请先创建或导入项目');
    return;
  }
  $('batchPlanInput').click();
}

function handleBatchImport(e){
  var files = e.target.files;
  if (!files || files.length === 0) return;
  
  batchImportQueue = Array.from(files).sort(function(a, b) {
    return a.name.localeCompare(b.name);
  });
  
  batchImportMapping = [];
  var usedFloorIds = {};
  var autoFloorIndex = 1;
  
  var floorsWithoutPlan = FLOORS.filter(function(f) {
    return !FLOORPLANS[f.id];
  }).sort(function(a, b) {
    return a.order - b.order;
  });
  
  var startFloorNum = 2;
  
  for (var i = 0; i < batchImportQueue.length; i++) {
    var file = batchImportQueue[i];
    var floorName = file.name.replace(/\.[^/.]+$/, '');
    
    var matchedFloor = null;
    for (var j = 0; j < FLOORS.length; j++) {
      if (FLOORS[j].name === floorName && !usedFloorIds[FLOORS[j].id]) {
        matchedFloor = FLOORS[j];
        break;
      }
    }
    
    if (matchedFloor) {
      usedFloorIds[matchedFloor.id] = true;
      batchImportMapping.push({
        file: file,
        floor: matchedFloor,
        isNew: false
      });
    } else {
      var targetFloor = null;
      
      for (var k = 0; k < floorsWithoutPlan.length; k++) {
        if (!usedFloorIds[floorsWithoutPlan[k].id]) {
          targetFloor = floorsWithoutPlan[k];
          break;
        }
      }
      
      if (targetFloor) {
        usedFloorIds[targetFloor.id] = true;
        batchImportMapping.push({
          file: file,
          floor: targetFloor,
          isNew: false
        });
      } else {
        var newFloorName = (startFloorNum + autoFloorIndex - 1) + 'F';
        autoFloorIndex++;
        
        var nameExists = true;
        while (nameExists) {
          nameExists = false;
          for (var n = 0; n < FLOORS.length; n++) {
            if (FLOORS[n].name === newFloorName && !usedFloorIds[FLOORS[n].id]) {
              nameExists = true;
              newFloorName = autoFloorIndex + 'F';
              autoFloorIndex++;
              break;
            }
          }
          for (var m = 0; m < batchImportMapping.length; m++) {
            if (batchImportMapping[m].isNew && batchImportMapping[m].floor.name === newFloorName) {
              nameExists = true;
              newFloorName = autoFloorIndex + 'F';
              autoFloorIndex++;
              break;
            }
          }
        }
        
        var baseName = newFloorName;
        var suffix = 2;
        while (isNameUsed(newFloorName)) {
          newFloorName = baseName + '_' + suffix;
          suffix++;
        }
        
        var maxOrder = 0;
        for (var p = 0; p < FLOORS.length; p++) {
          maxOrder = Math.max(maxOrder, FLOORS[p].order);
        }
        
        var newFloor = {
          id: 'f' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
          name: newFloorName,
          order: maxOrder + 1
        };
        
        FLOORS.push(newFloor);
        MARKERS[newFloor.id] = [];
        usedFloorIds[newFloor.id] = true;
        
        batchImportMapping.push({
          file: file,
          floor: newFloor,
          isNew: true
        });
      }
    }
  }
  
  showMsg('准备批量导入 ' + batchImportQueue.length + ' 个平面图...');
  batchImportIndex = 0;
  processBatchImport();
}

function processBatchImport(){
  if (batchImportIndex >= batchImportMapping.length) {
    showMsg('✅ 批量导入完成！共导入 ' + batchImportMapping.length + ' 个平面图');
    batchImportQueue = [];
    batchImportMapping = [];
    batchImportIndex = 0;
    saveData();
    renderFloorBar();
    if (CURRENT_FLOOR) {
      showFloorPlanPrompt();
    }
    return;
  }
  
  var mapping = batchImportMapping[batchImportIndex];
  var file = mapping.file;
  var floor = mapping.floor;
  
  var reader = new FileReader();
  reader.onload = function(evt){
    var img = new Image();
    img.onload = function(){
      var w = img.naturalWidth, h = img.naturalHeight;
      var MAX = 2500;
      var finalData;
      
      if (w > MAX || h > MAX) {
        var r = Math.min(MAX/w, MAX/h);
        w = Math.round(w * r);
        h = Math.round(h * r);
        
        var canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        var ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        finalData = canvas.toDataURL('image/jpeg', 0.85);
      } else {
        finalData = evt.target.result;
      }
      
      FLOORPLANS[floor.id] = {
        imgData: finalData,
        imgW: w,
        imgH: h,
        originalName: file.name
      };
      
      showMsg('已导入 ' + (batchImportIndex + 1) + '/' + batchImportMapping.length + '：' + floor.name);
      
      if (floor.id === CURRENT_FLOOR) {
        loadFloorPlan(FLOORPLANS[floor.id]);
      }
      
      batchImportIndex++;
      setTimeout(function() {
        processBatchImport();
      }, 100);
    };
    img.src = evt.target.result;
  };
  reader.readAsDataURL(file);
}

// 旋转预览相关 (原样)
var rotateTempData = null;
var rotateCurrentAngle = 0;
var rotateTempFileName = '';

function onFloorPlanSelected(input){
  var file = input.files[0];
  if (!file) return;
  
  showMsg('加载预览...');
  var reader = new FileReader();
  reader.onload = function(e){
    rotateTempData = e.target.result;
    rotateCurrentAngle = 0;
    rotateTempFileName = file.name;
    $('importPreviewImg').src = rotateTempData;
    $('importChoicePanel').style.display = 'block';
    showMsg('请选择导入方式');
  };
  reader.readAsDataURL(file);
  input.value = '';
}

function directImport(){
  if (!rotateTempData || !CURRENT_FLOOR) return;
  showMsg('导入中...');
  var img = new Image();
  img.onload = function(){
    var w = img.naturalWidth;
    var h = img.naturalHeight;
    var MAX = 2500;
    var finalData = rotateTempData;
    
    if (w > MAX || h > MAX) {
      var r = Math.min(MAX/w, MAX/h);
      var newW = Math.round(w * r);
      var newH = Math.round(h * r);
      var canvas = document.createElement('canvas');
      canvas.width = newW;
      canvas.height = newH;
      var ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, newW, newH);
      finalData = canvas.toDataURL('image/jpeg', 0.85);
      w = newW;
      h = newH;
    }
    
    FLOORPLANS[CURRENT_FLOOR] = {
      imgData: finalData,
      imgW: w,
      imgH: h,
      originalName: rotateTempFileName
    };
    
    $('importChoicePanel').style.display = 'none';
    rotateTempData = null;
    rotateCurrentAngle = 0;
    rotateTempFileName = '';
    loadFloorPlan(FLOORPLANS[CURRENT_FLOOR]);
    $('noPlanMsg').style.display = 'none';
    saveData();
    renderFloorBar();
    showMsg('平面图导入成功');
  };
  img.src = rotateTempData;
}

function enterRotateMode(){
  $('importChoicePanel').style.display = 'none';
  $('rotatePreviewImg').src = rotateTempData;
  $('rotatePreviewImg').style.transform = 'rotate(0deg)';
  $('rotatePanel').style.display = 'block';
}

function cancelImportChoice(){
  $('importChoicePanel').style.display = 'none';
  rotateTempData = null;
  rotateCurrentAngle = 0;
  rotateTempFileName = '';
}

function rotateImage(deg){
  rotateCurrentAngle = (rotateCurrentAngle + deg) % 360;
  $('rotatePreviewImg').style.transform = 'rotate(' + rotateCurrentAngle + 'deg)';
}

function cancelRotate(){
  $('rotatePanel').style.display = 'none';
  rotateTempData = null;
  rotateCurrentAngle = 0;
  rotateTempFileName = '';
}

function confirmRotate(){
  if (!rotateTempData || !CURRENT_FLOOR) return;
  showMsg('处理中...');
  var img = new Image();
  img.onload = function(){
    var w = img.naturalWidth, h = img.naturalHeight;
    var finalW = w, finalH = h;
    if (Math.abs(rotateCurrentAngle) === 90 || Math.abs(rotateCurrentAngle) === 270) {
      finalW = h;
      finalH = w;
    }
    var canvas = document.createElement('canvas');
    canvas.width = finalW;
    canvas.height = finalH;
    var ctx = canvas.getContext('2d');
    ctx.save();
    ctx.translate(finalW / 2, finalH / 2);
    ctx.rotate(rotateCurrentAngle * Math.PI / 180);
    ctx.drawImage(img, -w / 2, -h / 2, w, h);
    ctx.restore();
    var MAX = 2500;
    var outputCanvas = canvas;
    if (finalW > MAX || finalH > MAX) {
      var r = Math.min(MAX / finalW, MAX / finalH);
      var newW = Math.round(finalW * r);
      var newH = Math.round(finalH * r);
      outputCanvas = document.createElement('canvas');
      outputCanvas.width = newW;
      outputCanvas.height = newH;
      var outputCtx = outputCanvas.getContext('2d');
      outputCtx.drawImage(canvas, 0, 0, newW, newH);
      finalW = newW;
      finalH = newH;
    }
    var finalData = outputCanvas.toDataURL('image/jpeg', 0.85);
    FLOORPLANS[CURRENT_FLOOR] = {
      imgData: finalData,
      imgW: finalW,
      imgH: finalH,
      originalName: rotateTempFileName
    };
    $('rotatePanel').style.display = 'none';
    rotateTempData = null;
    rotateCurrentAngle = 0;
    rotateTempFileName = '';
    loadFloorPlan(FLOORPLANS[CURRENT_FLOOR]);
    $('noPlanMsg').style.display = 'none';
    saveData();
    renderFloorBar();
    showMsg('平面图导入成功');
  };
  img.src = rotateTempData;
}

function loadFloorPlan(planData){
  IMG_W = planData.imgW;
  IMG_H = planData.imgH;
  var img = $('theImg');
  img.onload = function(){
    SCALE = 1;
    fitImage();
    updateDots();
  };
  img.src = planData.imgData;
  img.style.display = 'block';
}

function fitImage(){
  var wrap = $('wrap');
  var ww = wrap.clientWidth, wh = wrap.clientHeight;
  var s = Math.min(ww/IMG_W, wh/IMG_H) * 0.95;
  if(s > 2) s = 2;
  SCALE = s;
  OFF_X = (ww - IMG_W * s) / 2;
  OFF_Y = (wh - IMG_H * s) / 2;
  updateImage();
}

function updateImage(){
  var img = $('theImg');
  if(!img || img.style.display === 'none') return;
  img.style.width = (IMG_W * SCALE) + 'px';
  img.style.height = (IMG_H * SCALE) + 'px';
  img.style.left = OFF_X + 'px';
  img.style.top = OFF_Y + 'px';
  if (PLAN_ALIGNED && !OFFLINE_MODE) {
    var layer = $('planLayer');
    var cx = wrap.clientWidth / 2;
    var cy = wrap.clientHeight / 2;
    layer.style.transformOrigin = cx + 'px ' + cy + 'px';
  }
  updateDots();
}

// ========== 楼层管理 (完整保留) ==========
var FLOORBAR_ON_LEFT = true;

function renderFloorBar(){
  var bar = $('floorBar');
  var addBtn = $('btnAddFloor');
  var wrap = $('wrap');
  var floorInfo = $('floorInfo');
  
  if (FLOORBAR_ON_LEFT) {
    bar.classList.remove('right-side');
    bar.classList.add('left-side');
    wrap.classList.remove('floorbar-right');
    floorInfo.classList.remove('right-mode');
  } else {
    bar.classList.remove('left-side');
    bar.classList.add('right-side');
    wrap.classList.add('floorbar-right');
    floorInfo.classList.add('right-mode');
  }
  
  while (bar.firstChild && bar.firstChild !== addBtn) {
    bar.removeChild(bar.firstChild);
  }
  
  var sorted = FLOORS.slice().sort(function(a, b){ return a.order - b.order; });
  
  for(var i=0; i<sorted.length; i++){
    var f = sorted[i];
    var hasPlan = !!FLOORPLANS[f.id];
    var tab = document.createElement('div');
    tab.className = 'floorTab' + (f.id === CURRENT_FLOOR ? ' active' : '') + (hasPlan ? '' : ' no-plan');
    tab.innerHTML = escapeHtml(f.name);
    
    (function(fid){
      var lastTapTime = 0;
      var touchStartTime = 0;
      var isLongPress = false;
      var pressTimer = null;
      
      function handleDoubleClick() {
        var currentTime = Date.now();
        var tapLength = currentTime - lastTapTime;
        if (tapLength < 300 && tapLength > 0) {
          switchFloor(fid);
          lastTapTime = 0;
        } else {
          lastTapTime = currentTime;
        }
      }
      
      tab.addEventListener('touchstart', function(e){
        touchStartTime = Date.now();
        isLongPress = false;
        var self = this;
        pressTimer = setTimeout(function(){
          isLongPress = true;
          self.style.background = '#ff453a';
          if (navigator.vibrate) navigator.vibrate(50);
        }, 500);
      }, {passive:true});
      
      tab.addEventListener('touchend', function(e){
        var pressTime = Date.now() - touchStartTime;
        this.style.background = '';
        clearTimeout(pressTimer);
        if (isLongPress) {
          if (confirm('确定删除该楼层？该楼层所有点位和平面图将丢失')) {
            deleteFloor(fid);
          }
        } else {
          handleDoubleClick();
        }
      });
      
      tab.addEventListener('touchmove', function(e){
        clearTimeout(pressTimer);
        this.style.background = '';
      });
      
      tab.addEventListener('dblclick', function(e){
        switchFloor(fid);
      });
      
      tab.addEventListener('mousedown', function(e){
        touchStartTime = Date.now();
        isLongPress = false;
        var self = this;
        pressTimer = setTimeout(function(){
          isLongPress = true;
          self.style.background = '#ff453a';
        }, 500);
      });
      
      tab.addEventListener('mouseup', function(e){
        this.style.background = '';
        clearTimeout(pressTimer);
        if (isLongPress) {
          if (confirm('确定删除该楼层？该楼层所有点位和平面图将丢失')) {
            deleteFloor(fid);
          }
        }
      });
      
      tab.addEventListener('mouseleave', function(e){
        clearTimeout(pressTimer);
        this.style.background = '';
      });
    })(f.id);
    
    bar.insertBefore(tab, addBtn);
  }
  updateFloorInfo();
}

function toggleFloorBarSide(){
  FLOORBAR_ON_LEFT = !FLOORBAR_ON_LEFT;
  try {
    localStorage.setItem('panorama_floorbar_left', FLOORBAR_ON_LEFT);
  } catch(e) {}
  renderFloorBar();
  showMsg(FLOORBAR_ON_LEFT ? '楼层栏：左侧（左手模式）' : '楼层栏：右侧（右手模式）');
}

function loadFloorBarSettings(){
  try {
    var saved = localStorage.getItem('panorama_floorbar_left');
    if (saved !== null) {
      FLOORBAR_ON_LEFT = saved === 'true';
    }
  } catch(e) {}
}

function updateFloorInfo(){
  var info = $('floorInfo');
  var cf = getCurrentFloor();
  if(cf && PROJ){
    var mc = (MARKERS[CURRENT_FLOOR] || []).length;
    var cc = (MARKERS[CURRENT_FLOOR] || []).filter(function(m){ return m.status === 'captured'; }).length;
    var hasPlan = !!FLOORPLANS[CURRENT_FLOOR];
    info.innerHTML = escapeHtml(cf.name) + ' | ' + cc + '/' + mc + ' 已完成' + (hasPlan ? '' : ' | ⚠ 无平面图');
    info.style.display = 'block';
  } else {
    info.style.display = 'none';
  }
}

function escapeHtml(t){
  var d = document.createElement('div');
  d.innerText = t;
  return d.innerHTML;
}

function getCurrentFloor(){
  for(var i=0; i<FLOORS.length; i++){
    if(FLOORS[i].id === CURRENT_FLOOR) return FLOORS[i];
  }
  return null;
}

function getNextFloorName(){
  var maxFloor = 0;
  for(var i=0; i<FLOORS.length; i++){
    var name = FLOORS[i].name;
    var match = name.match(/^(\d+)F$/i);
    if(match){
      var num = parseInt(match[1]);
      if(num > maxFloor) maxFloor = num;
    }
  }
  if(maxFloor > 0){
    return (maxFloor + 1) + 'F';
  } else {
    return '1F';
  }
}

function isNameUsed(name){
  for(var i=0; i<FLOORS.length; i++){
    if(FLOORS[i].name === name) return true;
  }
  return false;
}

function addFloor(customName){
  if(!PROJ) { showMsg('请先创建项目'); return; }
  var newName = customName;
  if(!newName){
    newName = getNextFloorName();
    if(isNameUsed(newName)){
      var n = 1;
      while(isNameUsed('新楼层' + n)){ n++; }
      newName = '新楼层' + n;
    }
  }
  if(isNameUsed(newName)){
    var n = 1;
    var baseName = newName;
    while(isNameUsed(baseName + '_' + n)){ n++; }
    newName = baseName + '_' + n;
  }
  var fid = generateId();
  var order = FLOORS.length;
  FLOORS.push({id:fid, name:newName, order:order});
  MARKERS[fid] = [];
  CURRENT_FLOOR = fid;
  ACTIVE = null;
  saveData();
  renderFloorBar();
  showFloorPlanPrompt();
  showMsg('已添加 ' + newName + '，请导入平面图');
  return newName;
}

function quickAddFloor(count){
  if(!PROJ) { showMsg('请先创建项目'); return; }
  var added = [];
  for(var i=0; i<count; i++){
    var name = addFloor();
    added.push(name);
  }
  renderFloorList();
  showMsg('已批量添加 ' + added.join(', '));
}

function quickAddBasement(){
  if(!PROJ) { showMsg('请先创建项目'); return; }
  var maxBasement = 0;
  for(var i=0; i<FLOORS.length; i++){
    var name = FLOORS[i].name;
    var match = name.match(/^B(\d+)$/i);
    if(match){
      var num = parseInt(match[1]);
      if(num > maxBasement) maxBasement = num;
    }
  }
  var name = 'B' + (maxBasement + 1);
  addFloor(name);
  renderFloorList();
  showMsg('已添加地下室 ' + name);
}

function quickAddRoof(){
  if(!PROJ) { showMsg('请先创建项目'); return; }
  var names = ['RF', '屋顶层', '阁楼层', 'R层'];
  var usedNames = {};
  for(var i=0; i<FLOORS.length; i++){
    usedNames[FLOORS[i].name] = true;
  }
  var newName = 'RF';
  for(var i=0; i<names.length; i++){
    if(!usedNames[names[i]]){
      newName = names[i];
      break;
    }
  }
  if(usedNames[newName]){
    var n = 1;
    while(usedNames['RF_' + n]){ n++; }
    newName = 'RF_' + n;
  }
  addFloor(newName);
  renderFloorList();
  showMsg('已添加屋顶层 ' + newName);
}

function quickAddCustom(){
  if(!PROJ) { showMsg('请先创建项目'); return; }
  var name = prompt('请输入楼层名称（如：夹层、设备层、3A等）：', '');
  if(name && name.trim()){
    addFloor(name.trim());
    renderFloorList();
  }
}

function deleteFloor(fid){
  if(!confirm('确定删除该楼层？该楼层所有点位和平面图将丢失')) return;
  var idx = -1;
  for(var i=0; i<FLOORS.length; i++){
    if(FLOORS[i].id === fid){ idx = i; break; }
  }
  if(idx < 0) return;
  FLOORS.splice(idx, 1);
  delete MARKERS[fid];
  delete FLOORPLANS[fid];
  for(var i=0; i<FLOORS.length; i++) FLOORS[i].order = i;
  if(CURRENT_FLOOR === fid){
    CURRENT_FLOOR = FLOORS.length > 0 ? FLOORS[0].id : null;
  }
  ACTIVE = null;
  saveData();
  renderFloorBar();
  if (CURRENT_FLOOR) {
    showFloorPlanPrompt();
  }
  showMsg('已删除楼层');
}

function switchFloor(fid){
  if(fid === CURRENT_FLOOR) return;
  CURRENT_FLOOR = fid;
  ACTIVE = null;
  PENDING_MARKER_ID = null;
  CAPTURE_START_TIME = null;
  saveData();
  clearDots();
  updateDots();
  renderFloorBar();
  showFloorPlanPrompt();
  showMsg('切换到 ' + getCurrentFloor().name);
}

// 楼层管理面板 (保留完整功能，略)
var floorBackup = null;
function showFloorPanel(){
  if(!PROJ) { showMsg('请先创建项目'); return; }
  if(FLOORS.length === 0) { showMsg('请先添加楼层'); return; }
  floorBackup = JSON.stringify({floors: FLOORS, currentFloor: CURRENT_FLOOR});
  renderFloorList();
  $('floorPanel').style.display = 'block';
}
var swapSelectFirst = null;
var dragSrcEl = null;
var touchDragItem = null;
var touchStartY = 0;
var touchCurrentItem = null;

function renderFloorList(){
  var list = $('floorList');
  list.innerHTML = '';
  var sorted = FLOORS.slice().sort(function(a,b){ return a.order - b.order; });
  for(var i=0; i<sorted.length; i++){
    var f = sorted[i];
    var hasPlan = !!FLOORPLANS[f.id];
    var isSelected = (swapSelectFirst === f.id);
    var item = document.createElement('div');
    item.className = 'floorItem' + (isSelected ? ' selected' : '');
    item.setAttribute('draggable', 'true');
    item.setAttribute('data-floor-id', f.id);
    item.setAttribute('data-order', f.order);
    
    item.addEventListener('dragstart', handleDragStart);
    item.addEventListener('dragenter', handleDragEnter);
    item.addEventListener('dragover', handleDragOver);
    item.addEventListener('dragleave', handleDragLeave);
    item.addEventListener('drop', handleDrop);
    item.addEventListener('dragend', handleDragEnd);
    
    var dragHandle = document.createElement('span');
    dragHandle.className = 'dragHandle';
    dragHandle.innerHTML = '☰';
    dragHandle.setAttribute('data-floor-id', f.id);
    dragHandle.addEventListener('touchstart', handleTouchStart, {passive:false});
    dragHandle.addEventListener('touchmove', handleTouchMove, {passive:false});
    dragHandle.addEventListener('touchend', handleTouchEnd, {passive:false});
    item.appendChild(dragHandle);
    
    var nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.value = f.name;
    nameInput.onchange = (function(fid){ return function(){ renameFloor(fid, this.value); }; })(f.id);
    if (isSelected) {
      nameInput.style.background = '#ffcc00';
      nameInput.style.color = '#000';
    }
    item.appendChild(nameInput);
    
    var planBtn = document.createElement('button');
    planBtn.className = 'plan ' + (hasPlan ? '' : 'no-img');
    planBtn.onclick = (function(fid){ return function(){ importPlanForFloor(fid); }; })(f.id);
    planBtn.title = hasPlan ? '更换平面图' : '导入平面图';
    planBtn.innerHTML = '📷';
    item.appendChild(planBtn);
    
    var swapBtn = document.createElement('button');
    swapBtn.className = 'swap';
    swapBtn.onclick = (function(fid){ return function(){ selectFloorForSwap(fid); }; })(f.id);
    swapBtn.title = '选择互换平面图';
    swapBtn.innerHTML = '⇄';
    item.appendChild(swapBtn);
    
    var delBtn = document.createElement('button');
    delBtn.className = 'del';
    delBtn.onclick = (function(fid){ return function(){ deleteFloorFromPanel(fid); }; })(f.id);
    delBtn.innerHTML = '删';
    item.appendChild(delBtn);
    
    list.appendChild(item);
  }
  if(swapSelectFirst){
    var hint = document.createElement('div');
    hint.style.cssText = 'text-align:center;padding:10px;color:#ffcc00;font-size:13px;';
    hint.innerHTML = '已选择第一个楼层，请点击另一个楼层完成互换';
    list.insertBefore(hint, list.firstChild);
  }
}

function handleDragStart(e){ dragSrcEl = this; this.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/html', this.innerHTML); }
function handleDragOver(e){ if(e.preventDefault) e.preventDefault(); e.dataTransfer.dropEffect = 'move'; return false; }
function handleDragEnter(e){ if(this !== dragSrcEl) this.classList.add('drag-over'); }
function handleDragLeave(e){ this.classList.remove('drag-over'); }
function handleDrop(e){ if(e.stopPropagation) e.stopPropagation(); if(dragSrcEl !== this) swapFloorOrder(dragSrcEl.getAttribute('data-floor-id'), this.getAttribute('data-floor-id')); return false; }
function handleDragEnd(e){ this.classList.remove('dragging'); var items = $('floorList').querySelectorAll('.floorItem'); items.forEach(function(item){ item.classList.remove('drag-over'); }); }
function handleTouchStart(e){ e.preventDefault(); e.stopPropagation(); var floorId = this.getAttribute('data-floor-id'); var items = $('floorList').querySelectorAll('.floorItem'); for(var i=0;i<items.length;i++) if(items[i].getAttribute('data-floor-id')===floorId) touchDragItem=items[i]; if(touchDragItem){ touchDragItem.classList.add('dragging'); touchStartY=e.touches[0].clientY; } }
function handleTouchMove(e){ e.preventDefault(); e.stopPropagation(); if(!touchDragItem) return; var touch=e.touches[0]; var list=$('floorList'); var items=list.querySelectorAll('.floorItem'); items.forEach(function(item){ item.classList.remove('drag-over'); }); for(var i=0;i<items.length;i++){ var rect=items[i].getBoundingClientRect(); if(touch.clientY>=rect.top && touch.clientY<=rect.bottom){ if(items[i]!==touchDragItem){ items[i].classList.add('drag-over'); touchCurrentItem=items[i]; } break; } } }
function handleTouchEnd(e){ e.preventDefault(); e.stopPropagation(); if(touchDragItem && touchCurrentItem && touchDragItem!==touchCurrentItem) swapFloorOrder(touchDragItem.getAttribute('data-floor-id'), touchCurrentItem.getAttribute('data-floor-id')); if(touchDragItem) touchDragItem.classList.remove('dragging'); var items=$('floorList').querySelectorAll('.floorItem'); items.forEach(function(item){ item.classList.remove('drag-over'); }); touchDragItem=null; touchCurrentItem=null; }
function swapFloorOrder(srcId,targetId){ var srcFloor=findFloor(srcId); var targetFloor=findFloor(targetId); if(srcFloor&&targetFloor){ var tempOrder=srcFloor.order; srcFloor.order=targetFloor.order; targetFloor.order=tempOrder; FLOORS.sort(function(a,b){ return a.order-b.order; }); for(var i=0;i<FLOORS.length;i++) FLOORS[i].order=i; renderFloorList(); showMsg('楼层顺序已调整'); } }
function autoSortFloors(){ if(FLOORS.length===0) return; var roofFloors=[], normalFloors=[], basementFloors=[], otherFloors=[]; for(var i=0;i<FLOORS.length;i++){ var f=FLOORS[i]; var name=f.name.toUpperCase(); if(name==='RF'||name.indexOf('屋顶')>=0||name.indexOf('ROOF')>=0||name.indexOf('阁楼')>=0||name==='R层'||name.indexOf('机房屋面')>=0) roofFloors.push(f); else if(name.match(/^B\d+$/)||name.match(/^B\d+_.*$/)||name.indexOf('地下')>=0||name.indexOf('BASEMENT')>=0) basementFloors.push(f); else if(name.match(/^\d+F$/)||name.match(/^\d+_.*$/)||name.match(/^\d+层$/)||name.match(/^M\d+$/)||name.match(/^\d+A$/)||name.match(/^\d+B$/)) normalFloors.push(f); else otherFloors.push(f); } function getFloorNum(name){ var match=name.match(/(\d+)/); return match?parseInt(match[1]):0; } normalFloors.sort(function(a,b){ return getFloorNum(b.name)-getFloorNum(a.name); }); basementFloors.sort(function(a,b){ return getFloorNum(a.name)-getFloorNum(b.name); }); roofFloors.sort(function(a,b){ return a.name.localeCompare(b.name); }); otherFloors.sort(function(a,b){ return a.order-b.order; }); var sortedFloors=roofFloors.concat(normalFloors).concat(otherFloors).concat(basementFloors); for(var i=0;i<sortedFloors.length;i++) sortedFloors[i].order=i; FLOORS=sortedFloors; renderFloorList(); showMsg('✅ 楼层已自动排序：屋顶→普通→地下室（深层靠下）'); }
function selectFloorForSwap(fid){ if(!swapSelectFirst){ swapSelectFirst=fid; var f=findFloor(fid); showMsg('已选择：'+(f?f.name:fid)+'，请选择另一个楼层'); renderFloorList(); } else if(swapSelectFirst===fid){ swapSelectFirst=null; showMsg('已取消选择'); renderFloorList(); } else { var firstId=swapSelectFirst; var secondId=fid; swapSelectFirst=null; var tempPlan=FLOORPLANS[firstId]; FLOORPLANS[firstId]=FLOORPLANS[secondId]; FLOORPLANS[secondId]=tempPlan; var tempMarkers=MARKERS[firstId]; MARKERS[firstId]=MARKERS[secondId]; MARKERS[secondId]=tempMarkers; saveData(); renderFloorList(); renderFloorBar(); var first=findFloor(firstId); var second=findFloor(secondId); if(CURRENT_FLOOR===firstId||CURRENT_FLOOR===secondId) showFloorPlanPrompt(); showMsg('✅ 已互换平面图："'+(first?first.name:'')+'" ⇄ "'+(second?second.name:'')+'"'); } }
function findFloor(fid){ for(var i=0;i<FLOORS.length;i++) if(FLOORS[i].id===fid) return FLOORS[i]; return null; }
function importPlanForFloor(fid){ $('floorPlanInput').setAttribute('data-target-floor', fid); $('floorPlanInput').click(); }
function renameFloor(fid, name){ for(var i=0;i<FLOORS.length;i++) if(FLOORS[i].id===fid) FLOORS[i].name=name.trim()||'未命名'; }
function deleteFloorFromPanel(fid){ deleteFloor(fid); renderFloorList(); }
function saveFloors(){ saveData(); $('floorPanel').style.display='none'; renderFloorBar(); showMsg('楼层设置已保存'); }
function cancelFloors(){ if(floorBackup) { var data=JSON.parse(floorBackup); FLOORS=data.floors; CURRENT_FLOOR=data.currentFloor; } swapSelectFirst=null; $('floorPanel').style.display='none'; renderFloorBar(); }

// ========== 标记点相关 ==========
function clearDots(){
  var layer = $('dotsLayer');
  if (!layer) { layer = $('planLayer'); }
  var dots = layer.querySelectorAll('.dot');
  for(var i=0; i<dots.length; i++) layer.removeChild(dots[i]);
  var svg = layer.querySelector('#routeSvg');
  if(svg) layer.removeChild(svg);
  var sec = layer.querySelector('#directionSectors');
  if(sec) layer.removeChild(sec);
}

function updateDots(){
  clearDots();
  var layer = $('dotsLayer') || $('planLayer');
  var currentMarkers = CURRENT_FLOOR ? (MARKERS[CURRENT_FLOOR] || []) : [];
  var currentRotation = smoothRotation;
  drawRoute(currentMarkers, currentRotation);
  for(var i=0; i<currentMarkers.length; i++){
    var m = currentMarkers[i];
    var d = document.createElement('div');
    d.className = 'dot ' + m.status;
    if(m.id === ACTIVE) d.className += ' selected';
    var sp = imageToScreenCoords(m.x, m.y, currentRotation);
    d.style.left = sp.x + 'px';
    d.style.top = sp.y + 'px';
    var num = document.createElement('span');
    num.innerHTML = (i+1);
    d.appendChild(num);
    layer.appendChild(d);
  }
  updateTimeline(currentMarkers);
  updateFloorInfo();
  renderDirectionSectors();
}

function drawRoute(markers, rotation){
  var layer = $('dotsLayer') || $('planLayer');
  var old = layer.querySelector('#routeSvg');
  if(old) old.parentNode.removeChild(old);
  if(!markers || markers.length < 2) return;
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'routeSvg';
  svg.style.position = 'absolute';
  svg.style.left = '0';
  svg.style.top = '0';
  svg.style.width = '100%';
  svg.style.height = '100%';
  svg.style.pointerEvents = 'none';
  svg.style.zIndex = '5';
  var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  var d = '';
  var rot = (rotation !== undefined) ? rotation : smoothRotation;
  for(var i=0; i<markers.length; i++){
    var m = markers[i];
    var sp = imageToScreenCoords(m.x, m.y, rot);
    if(i === 0){
      d += 'M ' + sp.x.toFixed(1) + ' ' + sp.y.toFixed(1);
    } else {
      d += ' L ' + sp.x.toFixed(1) + ' ' + sp.y.toFixed(1);
    }
  }
  path.setAttribute('d', d);
  path.setAttribute('stroke', 'rgba(255, 204, 0, 0.6)');
  path.setAttribute('stroke-width', '3');
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke-dasharray', '8,4');
  svg.appendChild(path);
  layer.appendChild(svg);
}

function updateTimeline(markers){
  var panelTimeline = $('panelTimeline');
  var panelList = $('panelTimelineList');
  if(!markers || markers.length === 0){
    if(panelTimeline) panelTimeline.style.display = 'none';
    return;
  }
  if(panelTimeline) panelTimeline.style.display = 'block';
  if(!panelList) return;
  // 默认收起拍摄路线
  panelList.style.display = 'none';
  var toggleBtn = panelTimeline.querySelector('.toggle-btn');
  if(toggleBtn) toggleBtn.innerHTML = '展开';
  panelList.innerHTML = '';
  for(var i = markers.length - 1; i >= 0; i--){
    var m = markers[i];
    var item = document.createElement('div');
    item.className = 'tl-item';
    if (m.status === 'captured') item.className += ' captured';
    if (ACTIVE === m.id) item.className += ' active';
    var timeStr = '--:--:--';
    if(m.captureTime){
      var d = new Date(m.captureTime);
      var h = d.getHours(), mi = d.getMinutes(), s = d.getSeconds();
      timeStr = (h<10?'0':'')+h+':'+(mi<10?'0':'')+mi+':'+(s<10?'0':'')+s;
    }
    var dirIcon = (m.direction !== null && m.direction !== undefined) ? ' 🧭' + Math.round(m.direction) + '°' : '';
    item.innerHTML = '<span class="tl-num">' + (i+1) + '</span>' + 
                     '<span>' + (m.customName || '点位'+(i+1)) + dirIcon + '</span>' +
                     '<span class="tl-time">' + timeStr + '</span>' +
                     (m.status === 'captured' ? '<span class="tl-check">✓</span>' : '');
    panelList.appendChild(item);
  }
}

function togglePanelTimeline(){
  var list = $('panelTimelineList');
  var btn = event.target;
  if(!list || !btn) return;
  if (list.style.display === 'none') {
    list.style.display = 'block';
    btn.innerHTML = '收起';
  } else {
    list.style.display = 'none';
    btn.innerHTML = '展开';
  }
}

function findMarker(id){
  if(!CURRENT_FLOOR) return null;
  var currentMarkers = MARKERS[CURRENT_FLOOR] || [];
  for(var i=0; i<currentMarkers.length; i++){
    if(currentMarkers[i].id === id) return currentMarkers[i];
  }
  return null;
}

// ========== 触摸交互 ==========
var wrap = $('wrap');
wrap.addEventListener('touchstart', function(e){
  if (!FLOORPLANS[CURRENT_FLOOR]) return;
  e.preventDefault();
  if(longPressTimer){ clearTimeout(longPressTimer); longPressTimer = null; }
  var t = e.touches;
  if(t.length === 1){
    var p = {x:t[0].clientX, y:t[0].clientY};
    touches = [p];
    clickStart = {x:p.x, y:p.y, t:Date.now()};
    isDragging = false;
    var hit = hitTest(p.x, p.y);
    if(hit && hit.status === 'captured'){
      longPressTimer = setTimeout(function(){
        ACTIVE = hit.id;
        showEditPanel();
        longPressTimer = null;
      }, 600);
    }
  } else if(t.length === 2){
    touches = [
      {x:t[0].clientX, y:t[0].clientY},
      {x:t[1].clientX, y:t[1].clientY}
    ];
    isScaling = true;
    lastDist = Math.hypot(t[0].clientX-t[1].clientX, t[0].clientY-t[1].clientY);
    var wrapRect = wrap.getBoundingClientRect();
    pinchCenterX = ((t[0].clientX + t[1].clientX)/2) - wrapRect.left;
    pinchCenterY = ((t[0].clientY + t[1].clientY)/2) - wrapRect.top;
    pinchImgX = (pinchCenterX - OFF_X) / SCALE;
    pinchImgY = (pinchCenterY - OFF_Y) / SCALE;
  }
}, {passive:false});
var pinchCenterX,pinchCenterY,pinchImgX,pinchImgY;
wrap.addEventListener('touchmove', function(e){
  e.preventDefault();
  if(longPressTimer && clickStart){
    var dx = e.touches[0].clientX - clickStart.x;
    var dy = e.touches[0].clientY - clickStart.y;
    if(Math.hypot(dx,dy) > 10){ clearTimeout(longPressTimer); longPressTimer = null; }
  }
  var t = e.touches;
  if(t.length === 1 && touches.length >= 1 && !isScaling){
    if(isMovingMarker){
      var wrapRect = wrap.getBoundingClientRect();
      var mx = e.touches[0].clientX - wrapRect.left - OFF_X;
      var my = e.touches[0].clientY - wrapRect.top - OFF_Y;
      var m = findMarker(ACTIVE);
      if(m){
        m.x = Math.max(0, Math.min(1, mx / (IMG_W * SCALE)));
        m.y = Math.max(0, Math.min(1, my / (IMG_H * SCALE)));
        updateDots();
      }
    } else {
      var dx = t[0].clientX - touches[0].x;
      var dy = t[0].clientY - touches[0].y;
      if(Math.hypot(dx,dy) > 3) isDragging = true;
      OFF_X += dx;
      OFF_Y += dy;
      touches[0] = {x:t[0].clientX, y:t[0].clientY};
      updateImage();
    }
  } else if(t.length === 2 && isScaling){
    var dist = Math.hypot(t[0].clientX-t[1].clientX, t[0].clientY-t[1].clientY);
    if(lastDist > 0 && dist > 0){
      var scaleFactor = dist / lastDist;
      var newScale = SCALE * scaleFactor;
      if(newScale < 0.2) newScale = 0.2;
      if(newScale > 8) newScale = 8;
      OFF_X = pinchCenterX - pinchImgX * newScale;
      OFF_Y = pinchCenterY - pinchImgY * newScale;
      SCALE = newScale;
      updateImage();
    }
    lastDist = dist;
  }
}, {passive:false});
wrap.addEventListener('touchend', function(e){
  if(longPressTimer){ clearTimeout(longPressTimer); longPressTimer = null; }
  var t = e.touches;
  if(t.length === 0){
    if(!isDragging && !isScaling && clickStart && !isMovingMarker){
      var dx = e.changedTouches[0].clientX - clickStart.x;
      var dy = e.changedTouches[0].clientY - clickStart.y;
      var dt = Date.now() - clickStart.t;
      if(Math.hypot(dx,dy) < 10 && dt < 300){
        handleClick(e.changedTouches[0].clientX, e.changedTouches[0].clientY);
      }
    }
    isDragging = false;
    isScaling = false;
    touches = [];
    clickStart = null;
  }
}, {passive:false});

function hitTest(cx, cy){
  if(!FLOORPLANS[CURRENT_FLOOR]) return null;
  var currentMarkers = MARKERS[CURRENT_FLOOR] || [];
  if(currentMarkers.length === 0) return null;
  var wrapRect = wrap.getBoundingClientRect();
  var x = cx - wrapRect.left - OFF_X;
  var y = cy - wrapRect.top - OFF_Y;
  for(var i=0; i<currentMarkers.length; i++){
    var m = currentMarkers[i];
    var mx = m.x * IMG_W * SCALE;
    var my = m.y * IMG_H * SCALE;
    if(Math.hypot(x-mx, y-my) < 30) return m;
  }
  return null;
}

var PENDING_MARKER_ID = null;
function autoCompletePendingCapture(){
  if(!PENDING_MARKER_ID) return;
  var m = findMarker(PENDING_MARKER_ID);
  if(m && m.status === 'pending'){
    if(DIRECTION_MODE === 'north'){
      m.direction = GYRO_HEADING !== null ? Math.round(GYRO_HEADING - NORTH_CALIBRATION) : 0;
    } else if(DIRECTION_MODE === 'manual'){
      m.direction = 0;
    }
    m.status = 'captured';
    m.startTime = CAPTURE_START_TIME ? CAPTURE_START_TIME.toISOString() : new Date().toISOString();
    m.endTime = new Date().toISOString();
    m.captureTime = m.endTime;
    showMsg('✅ 已自动完成上一个点位的拍摄记录');
    saveData();
    updateDots();
  }
  PENDING_MARKER_ID = null;
  $('panel').style.display = 'none';
}

function handleClick(cx, cy){
  if(!PROJ) { showMsg('请先创建项目'); return; }
  if(!CURRENT_FLOOR) { showMsg('请先选择楼层'); return; }
  if(!FLOORPLANS[CURRENT_FLOOR]) { showMsg('请先导入平面图'); return; }
  autoCompletePendingCapture();
  var wrapRect = wrap.getBoundingClientRect();
  var sx = cx - wrapRect.left;
  var sy = cy - wrapRect.top;
  var currentMarkers = MARKERS[CURRENT_FLOOR] || [];
  var clickRotation = smoothRotation;
  var hit = null;
  for(var i=0; i<currentMarkers.length; i++){
    var m = currentMarkers[i];
    var sp = imageToScreenCoords(m.x, m.y, clickRotation);
    if(Math.hypot(sx-sp.x, sy-sp.y) < 30){ hit = m; break; }
  }
  if(hit){
    if(hit.status === 'pending'){
      ACTIVE = hit.id;
      showCapturePanel();
    } else if(hit.status === 'captured'){
      ACTIVE = hit.id;
      showEditPanel();
    }
  } else {
    var chx = wrapRect.width / 2;
    var chy = wrapRect.height / 2;
    var snapThreshold = Math.min(Math.min(wrapRect.width, wrapRect.height) * 0.05, 40);
    if (Math.hypot(sx - chx, sy - chy) <= snapThreshold) { sx = chx; sy = chy; }
    var coords = screenToImageCoords(sx, sy, clickRotation);
    var ix = coords.x;
    var iy = coords.y;
    var id = 'm' + Date.now();
    var m = {
      id: id,
      status: 'pending',
      captureTime: '',
      customName: '',
      x: Math.max(0, Math.min(1, ix)),
      y: Math.max(0, Math.min(1, iy)),
      direction: null
    };
    if(!MARKERS[CURRENT_FLOOR]) MARKERS[CURRENT_FLOOR] = [];
    MARKERS[CURRENT_FLOOR].push(m);
    ACTIVE = id;
    saveData();
    updateDots();
    centerOnMarker(m);
    showCapturePanel();
  }
}

// ========== 面板操作 ==========
var CAPTURE_START_TIME = null;
function speak(text){
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    var utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = VOICE_RATE;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    var voices = window.speechSynthesis.getVoices();
    var chineseVoice = voices.find(function(v) { return v.lang.includes('zh') || v.lang.includes('CN'); });
    if (chineseVoice) utterance.voice = chineseVoice;
    window.speechSynthesis.speak(utterance);
  }
}
function reSpeak() { speak(VOICE_TEXT); showMsg('🔊 已重新播放语音指令'); }
var PANEL_MINIMIZED = false;
var VOICE_TEXT = '拍张照片';
var VOICE_RATE = 1.0;

function showCapturePanel(){
  CAPTURE_START_TIME = new Date();
  PENDING_MARKER_ID = ACTIVE;
  var now = CAPTURE_START_TIME;
  var h = now.getHours(), mi = now.getMinutes(), s = now.getSeconds();
  $('tTime').innerHTML = (h<10?'0':'')+h+':'+(mi<10?'0':'')+mi+':'+(s<10?'0':'')+s;
  $('panel').style.display = 'block';
  if (PANEL_MINIMIZED) $('panel').classList.add('minimized');
  else $('panel').classList.remove('minimized');
  $('editPanel').style.display = 'none';
  updatePanelButtons();
  updateSaveAlbumButton();
  setDirMode(DIRECTION_MODE);
  if (PHONE_CAMERA_MODE) {
    setTimeout(function(){ openPhoneCamera(); }, 300);
  } else {
    speak(VOICE_TEXT);
  }
}
function togglePanelMinimize(){
  var panel = $('panel');
  if (panel.classList.contains('minimized')) {
    panel.classList.remove('minimized');
    PANEL_MINIMIZED = false;
  } else {
    panel.classList.add('minimized');
    PANEL_MINIMIZED = true;
  }
}
function showVoiceSettings(){
  $('voiceText').value = VOICE_TEXT;
  $('voiceRate').value = VOICE_RATE;
  $('rateValue').innerHTML = VOICE_RATE;
  $('voiceSettingsPanel').style.display = 'block';
}
function hideVoiceSettings(){ $('voiceSettingsPanel').style.display = 'none'; }
function testVoice(){
  var text = $('voiceText').value.trim() || '拍张照片';
  var rate = parseFloat($('voiceRate').value);
  if('speechSynthesis' in window){
    window.speechSynthesis.cancel();
    var u=new SpeechSynthesisUtterance(text);
    u.lang='zh-CN'; u.rate=rate;
    window.speechSynthesis.speak(u);
  }
}
function saveVoiceSettings(){
  VOICE_TEXT=$('voiceText').value.trim()||'拍张照片';
  VOICE_RATE=parseFloat($('voiceRate').value);
  localStorage.setItem('panorama_voice_text',VOICE_TEXT);
  localStorage.setItem('panorama_voice_rate',VOICE_RATE);
  hideVoiceSettings();
  showMsg('语音设置已保存');
}
function loadVoiceSettings(){
  try{ var t=localStorage.getItem('panorama_voice_text'); if(t) VOICE_TEXT=t; var r=localStorage.getItem('panorama_voice_rate'); if(r) VOICE_RATE=parseFloat(r); }catch(e){}
}

// ========== 手机拍摄模式功能（核心修复：强制启动相机） ==========
function togglePhoneCameraMode(){
  PHONE_CAMERA_MODE = !PHONE_CAMERA_MODE;
  localStorage.setItem('panorama_phone_camera_mode', PHONE_CAMERA_MODE);
  updatePanelButtons();
  if (PHONE_CAMERA_MODE) showMsg('📱 本机拍摄模式');
  else showMsg('📷 外设拍摄模式');
}

function updatePanelButtons(){
  var modeBtn = $('modeToggleBtn');
  var actionBtn = $('panelActionBtn');
  var settingsBtn = $('panelSettingsBtn');
  var saveBtn = $('btnSaveAlbum');
  if (!modeBtn || !actionBtn || !settingsBtn) return;
  if (PHONE_CAMERA_MODE) {
    modeBtn.innerHTML = '📱 本机';
    modeBtn.style.background = '#ff453a';
    modeBtn.style.color = '#fff';
    actionBtn.innerHTML = '🔄 重新拍摄';
    actionBtn.onclick = function(){ reCapture(); };
    settingsBtn.innerHTML = '拍摄设置';
    settingsBtn.onclick = function(){ showCaptureSettings(); };
    if (saveBtn) saveBtn.style.display = 'none';
  } else {
    modeBtn.innerHTML = '📷 外设';
    modeBtn.style.background = '#8e8e93';
    modeBtn.style.color = '#fff';
    actionBtn.innerHTML = '🔊 重新语音';
    actionBtn.onclick = function(){ reSpeak(); };
    settingsBtn.innerHTML = '语音设置';
    settingsBtn.onclick = function(){ showVoiceSettings(); };
    if (saveBtn) saveBtn.style.display = 'none';
  }
}

function detectBrowser(){
  var ua = navigator.userAgent;
  var isIOS = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  var isWeChat = /MicroMessenger/.test(ua);
  var isSafari = /Safari/.test(ua) && !/Chrome|CriOS/.test(ua) && isIOS;
  return { isIOS: isIOS, isWeChat: isWeChat, isSafari: isSafari };
}

// 【核心修改】强制启动相机，移除所有针对第三方浏览器的特殊阻塞
function openPhoneCamera(){
  var input = $('phoneCameraInput');
  if (!input) return;
  if (PHONE_CAPTURE_TYPE === 'video') input.accept = 'video/*';
  else input.accept = 'image/*';
  input.setAttribute('capture', 'environment');
  var browser = detectBrowser();
  if (browser.isWeChat) {
    showMsg('⚠️ 微信浏览器可能无法直接保存到相册，建议用 Safari 打开');
  }
  // 全景模式额外提示
  if (PHONE_CAPTURE_TYPE === 'panorama') {
    setTimeout(function(){
      showMsg('🌄 请在相机界面手动切换到全景模式');
    }, 800);
  }
  // 无论任何浏览器，都直接调用相机
  showMsg('📷 正在启动相机...');
  input.click();    // 直接触发文件选择（相机）
}

// 保存照片到相册（使用系统分享）—— iOS强制弹出系统分享面板

// ========== 保存到相册按钮状态更新 ==========
function updateSaveAlbumButton(){
  var btn = $('btnSaveAlbum');
  if (!btn) return;
  if (PHONE_CAMERA_MODE) {
    btn.disabled = false;
    btn.style.opacity = '1';
    if (lastPhotoBlob) {
      btn.innerHTML = '💾 保存到相册 (' + (lastPhotoName || '照片') + ')';
    } else {
      btn.innerHTML = '💾 点击拍摄并保存';
    }
  }
}

// 用户点击"保存到相册"按钮
function saveLastPhotoToAlbum(){
  if (!lastPhotoBlob) {
    PENDING_SAVE_AFTER_CAPTURE = true;
    showMsg('📷 请点击拍摄按钮拍摄照片');
    openPhoneCamera();
    return;
  }
  doSavePhotoToAlbum(lastPhotoBlob, lastPhotoName);
}

function doSavePhotoToAlbum(fileOrBlob, fileName){
  var browser = detectBrowser();
  var file = (fileOrBlob instanceof File) ? fileOrBlob : new File([fileOrBlob], fileName || 'photo.jpg', { type: fileOrBlob.type || 'image/jpeg' });

  if (navigator.share) {
    navigator.share({
      files: [file],
      title: '保存拍摄照片',
      text: '请选择"存储图像"或"保存到文件"存入相册'
    }).then(function(){
      showMsg('✅ 照片已处理');
      lastPhotoBlob = null;
      lastPhotoName = '';
      updateSaveAlbumButton();
    }).catch(function(err){
      if (err.name !== 'AbortError') {
        console.warn('分享失败:', err);
        triggerFileDownload(fileOrBlob, fileName);
        if (browser.isIOS) {
          showMsg('📂 照片已下载到"文件"App，请手动移到相册');
        } else {
          showMsg('📸 照片已下载');
        }
      }
    });
  } else {
    triggerFileDownload(fileOrBlob, fileName);
    if (browser.isIOS) {
      showMsg('📂 照片已下载到"文件"App，请手动移到相册');
    } else {
      showMsg('📸 照片已下载');
    }
  }
}

async function savePhotoToAlbum(file, fileName){
  var browser = detectBrowser();
  // iOS强制尝试系统分享面板（可显示"保存图像"选项）
  if (browser.isIOS && navigator.share) {
    try {
      await navigator.share({
        files: [file],
        title: '保存拍摄照片',
        text: '请选择"保存图像"存入相册'
      });
      showMsg('✅ 分享面板已打开，请选择"保存图像"存入相册');
      return true;
    } catch(err) {
      if (err.name === 'AbortError') {
        showMsg('已取消保存');
        return true;
      }
      console.warn('系统分享失败:', err);
    }
  }
  // 降级下载
  var url = URL.createObjectURL(file);
  var a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  setTimeout(function(){ document.body.removeChild(a); URL.revokeObjectURL(url); }, 1000);
  if (browser.isIOS) {
    showMsg('📂 照片已保存至"文件"App，请手动移到相册');
  } else {
    showMsg('📸 照片已下载');
  }
  return false;
}

function handlePhoneCapture(e){
  var files = e.target.files;
  if (files && files.length > 0) {
    var file = files[0];
    lastPhotoBlob = file;
    var markerNum = '';
    if (ACTIVE && MARKERS[CURRENT_FLOOR]) {
      var idx = MARKERS[CURRENT_FLOOR].findIndex(function(m){ return m.id === ACTIVE; });
      if (idx >= 0) markerNum = (idx + 1) + '_';
    }
    var floorName = getCurrentFloor() ? getCurrentFloor().name + '_' : '';
    lastPhotoName = floorName + markerNum + formatDateTime(new Date()) + '.' + (file.name.split('.').pop() || 'jpg');
    updateSaveAlbumButton();
    showMsg('📸 拍摄完成');
    // 如果是从保存流程触发的，自动执行保存
    if (PENDING_SAVE_AFTER_CAPTURE) {
      PENDING_SAVE_AFTER_CAPTURE = false;
      setTimeout(function(){
        doSavePhotoToAlbum(lastPhotoBlob, lastPhotoName);
      }, 300);
    }
    // 如果等待完成采集，自动执行方向设置和 finishCapture
    if (PENDING_FINISH_AFTER_CAPTURE) {
      PENDING_FINISH_AFTER_CAPTURE = false;
      var marker = findMarker(ACTIVE);
      if (marker) {
        setTimeout(function(){
          if(DIRECTION_MODE === 'north'){
            marker.direction = GYRO_HEADING !== null ? Math.round(GYRO_HEADING - NORTH_CALIBRATION) : 0;
            finishCapture(marker);
          } else if(DIRECTION_MODE === 'manual'){
            showAlignGuidePanel(marker);
          } else {
            finishCapture(marker);
          }
        }, 500);
      }
    }
  } else {
    if (PENDING_SAVE_AFTER_CAPTURE) {
      PENDING_SAVE_AFTER_CAPTURE = false;
    }
    if (PENDING_FINISH_AFTER_CAPTURE) {
      PENDING_FINISH_AFTER_CAPTURE = false;
      showMsg('拍摄已取消');
      updateSaveAlbumButton();
    } else {
      showMsg('未获取到拍摄文件');
    }
  }
  e.target.value = '';
}

function triggerFileDownload(file, fileName){
  var url = URL.createObjectURL(file);
  var a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  setTimeout(function(){ a.click(); setTimeout(function(){ document.body.removeChild(a); URL.revokeObjectURL(url); }, 1000); }, 100);
}

function formatDateTime(date){
  var y=date.getFullYear(), m=(date.getMonth()+1).toString().padStart(2,'0'), d=date.getDate().toString().padStart(2,'0');
  var h=date.getHours().toString().padStart(2,'0'), mi=date.getMinutes().toString().padStart(2,'0'), s=date.getSeconds().toString().padStart(2,'0');
  return y+m+d+'_'+h+mi+s;
}

function reCapture(){
  if (PHONE_CAMERA_MODE) openPhoneCamera();
  else reSpeak();
}
function showCaptureSettings(){ $('captureSettingsPanel').style.display='block'; updateCaptureTypeUI(); }
function hideCaptureSettings(){ $('captureSettingsPanel').style.display='none'; }
function setCaptureType(type){ PHONE_CAPTURE_TYPE=type; updateCaptureTypeUI(); }
function updateCaptureTypeUI(){
  var types=['photo','panorama','video']; var colors={photo:'#0a84ff',panorama:'#30d158',video:'#ff9500'};
  types.forEach(function(t){
    var btn=$('btnCap'+t.charAt(0).toUpperCase()+t.slice(1));
    if(btn) btn.style.background = t===PHONE_CAPTURE_TYPE ? colors[t] : '#2c2c2e';
  });
  $('captureTypeHint').innerHTML = {
  photo:'照片模式：调用普通相机，拍摄后请保存到相册',
  panorama:'全景模式：标记为全景拍摄，需在相机内手动切换到全景模式',
  video:'录像模式：调用摄像机进行录像'
}[PHONE_CAPTURE_TYPE];
}
function testCapture(){ openPhoneCamera(); }
function saveCaptureSettings(){ localStorage.setItem('panorama_phone_capture_type',PHONE_CAPTURE_TYPE); hideCaptureSettings(); showMsg('拍摄设置已保存'); }
function loadCaptureSettings(){
  try{
    var savedMode=localStorage.getItem('panorama_phone_camera_mode');
    if(savedMode===null) PHONE_CAMERA_MODE=true;
    else PHONE_CAMERA_MODE=savedMode==='true';
    var savedType=localStorage.getItem('panorama_phone_capture_type');
    if(savedType && ['photo','panorama','video'].indexOf(savedType)>=0) PHONE_CAPTURE_TYPE=savedType;
  }catch(e){}
}

function doCapture(){
  if(!ACTIVE) return;
  var m=findMarker(ACTIVE);
  if(!m) return;

  // 本机拍摄模式：先确保照片已保存
  if (PHONE_CAMERA_MODE) {
    if (!lastPhotoBlob) {
      // 还没有照片，唤起相机，拍摄后自动保存并完成采集
      PENDING_FINISH_AFTER_CAPTURE = true;
      PENDING_SAVE_AFTER_CAPTURE = true;
      openPhoneCamera();
      return;
    }
    // 已有照片，先保存再完成采集
    doSavePhotoToAlbum(lastPhotoBlob, lastPhotoName);
  }

  // 方向设置和完成采集
  if(DIRECTION_MODE === 'north'){
    m.direction = GYRO_HEADING !== null ? Math.round(GYRO_HEADING - NORTH_CALIBRATION) : 0;
    finishCapture(m);
  } else if(DIRECTION_MODE === 'manual'){
    showAlignGuidePanel(m);
  } else {
    finishCapture(m);
  }
}

function finishCapture(m){
  m.status='captured';
  m.startTime=CAPTURE_START_TIME?CAPTURE_START_TIME.toISOString():new Date().toISOString();
  m.endTime=new Date().toISOString();
  m.captureTime=m.endTime;
  saveData(); updateDots();
  $('panel').style.display='none';
  CAPTURE_START_TIME=null; PENDING_MARKER_ID=null;
  PENDING_SAVE_AFTER_CAPTURE=false;
  PENDING_FINISH_AFTER_CAPTURE=false;
  lastPhotoBlob=null; lastPhotoName='';
  updateSaveAlbumButton();
  centerOnMarker(m);
  showMsg('✅ 已记录时间，点位已居中');
}
function centerOnMarker(m){ var wrap=$('wrap'); var ww=wrap.clientWidth, wh=wrap.clientHeight; var tx=ww/2 - m.x*IMG_W*SCALE; var ty=wh/2 - m.y*IMG_H*SCALE; animateTo(tx,ty,SCALE); }
function animateTo(tx,ty,ts){ var sx=OFF_X, sy=OFF_Y, ss=SCALE, start=Date.now(), dur=300; function step(){ var p=Math.min((Date.now()-start)/dur,1); var e=1-Math.pow(1-p,3); OFF_X=sx+(tx-sx)*e; OFF_Y=sy+(ty-sy)*e; SCALE=ss+(ts-ss)*e; updateImage(); if(p<1) requestAnimationFrame(step); } requestAnimationFrame(step); }
function showEditPanel(){ var m=findMarker(ACTIVE); if(m){ $('panel').style.display='none'; $('editPanel').style.display='block'; $('editHint').innerHTML='点位：'+(m.customName||m.id); $('btnConfirmMove').style.display='none'; isMovingMarker=false; updateDots(); } }
function startMove(){ isMovingMarker=true; $('editHint').innerHTML='拖拽点位到新位置，点"确认位置"'; $('btnConfirmMove').style.display='block'; showMsg('拖拽移动点位'); }
function confirmMove(){ isMovingMarker=false; $('editPanel').style.display='none'; $('btnConfirmMove').style.display='none'; ACTIVE=null; saveData(); updateDots(); showMsg('位置已更新'); }
function doDelete(){ if(!ACTIVE) return; var idx=MARKERS[CURRENT_FLOOR].findIndex(m=>m.id===ACTIVE); if(idx>=0) MARKERS[CURRENT_FLOOR].splice(idx,1); ACTIVE=null; isMovingMarker=false; $('editPanel').style.display='none'; saveData(); updateDots(); showMsg('已删除'); }
function cancelEdit(){ isMovingMarker=false; ACTIVE=null; $('editPanel').style.display='none'; updateDots(); }
function doCalibrate(){ if(!PROJ) return; var now=new Date(); var ct=now.toLocaleTimeString(); var input=prompt('手机时间：'+ct+'\n请输入相机时间：',ct); if(input){ var parseSec=function(s){ var p=s.split(':'); return parseInt(p[0])*3600+parseInt(p[1])*60+(parseInt(p[2])||0); }; PROJ.timeOffset=parseSec(ct)-parseSec(input); PROJ.calibrated=true; saveData(); showMsg('校准完成'); } }

// ========== 预览与导出 (完整保留) ==========
function showPreview(){ if(!PROJ){showMsg('无数据');return} var content=$('previewContent'); content.innerHTML=''; var totalMarkers=0,totalCaptured=0,totalWithPlan=0; for(var fid in MARKERS){ var ms=MARKERS[fid]||[]; totalMarkers+=ms.length; totalCaptured+=ms.filter(m=>m.status==='captured').length; } for(var i=0;i<FLOORS.length;i++) if(FLOORPLANS[FLOORS[i].id]) totalWithPlan++; var summary=document.createElement('div'); summary.className='psummary'; summary.innerHTML='<div class="srow"><span>项目名称</span><span>'+escapeHtml(PROJ.name)+'</span></div><div class="srow"><span>楼层数量</span><span>'+FLOORS.length+'层('+totalWithPlan+'层有图)</span></div><div class="srow"><span>总点位</span><span>'+totalMarkers+'个</span></div><div class="srow"><span>已完成</span><span>'+totalCaptured+'个('+(totalMarkers>0?Math.round(totalCaptured/totalMarkers*100):0)+'%)</span></div>'; content.appendChild(summary); var sorted=FLOORS.slice().sort((a,b)=>a.order-b.order); for(var i=0;i<sorted.length;i++){ var f=sorted[i]; var fm=MARKERS[f.id]||[]; var hasPlan=!!FLOORPLANS[f.id]; var floorDiv=document.createElement('div'); floorDiv.className='pfloor'; var capturedCount=fm.filter(m=>m.status==='captured').length; floorDiv.innerHTML='<h4>'+escapeHtml(f.name)+' <span class="plan-status '+(hasPlan?'':'no-plan')+'">'+(hasPlan?'有平面图':'无平面图')+'</span> ('+capturedCount+'/'+fm.length+')</h4>'; if(fm.length===0) floorDiv.innerHTML+='<div class="pempty">暂无点位</div>'; else for(var j=0;j<fm.length;j++){ var m=fm[j]; var timeStr=m.captureTime?new Date(m.captureTime).toLocaleTimeString():'--:--:--'; var dirStr = (m.direction !== null && m.direction !== undefined) ? ' | 🧭' + Math.round(m.direction) + '°' : '';
floorDiv.innerHTML+='<div class="pmarker"><div class="pinfo"><span class="num">'+(j+1)+'</span>'+(m.customName||'点位')+'<span class="status '+m.status+'">'+(m.status==='captured'?'已拍':'待拍')+'</span>'+dirStr+'<div class="pcoord">坐标:('+m.x.toFixed(3)+','+m.y.toFixed(3)+')</div></div><div class="ptime">'+timeStr+'</div></div>'; } content.appendChild(floorDiv); } $('previewPanel').style.display='block'; }
function closePreview(){ $('previewPanel').style.display='none'; }
async function doExport(){ if(!PROJ||FLOORS.length===0){showMsg('无数据');return} var floorsWithPlan=FLOORS.filter(f=>!!FLOORPLANS[f.id]); if(floorsWithPlan.length===0){showMsg('请至少为一个楼层导入平面图');return} showMsg('打包中...'); try{ var zip=new JSZip(); var floorsExport=[]; var sorted=FLOORS.slice().sort((a,b)=>a.order-b.order); for(var i=0;i<sorted.length;i++){ var f=sorted[i]; var plan=FLOORPLANS[f.id]; var fm=MARKERS[f.id]||[]; floorsExport.push({id:f.id,name:f.name,order:f.order,hasPlan:!!plan,markers:fm.map(m=>({id:m.id,status:m.status,captureTime:m.captureTime||'',startTime:m.startTime||'',endTime:m.endTime||'',customName:m.customName||'',x:m.x,y:m.y,direction:m.direction!==undefined?m.direction:null}))}); if(plan){ var imgData=plan.imgData; var base64Data=imgData.split(',')[1]; zip.file('floorplan_'+f.id+'.jpg',base64Data,{base64:true}); } } var json={schemaVersion:'4.0',projectName:PROJ.name,createdAt:PROJ.createdAt,updatedAt:new Date().toISOString(),timeOffset:PROJ.timeOffset||0,calibrated:!!PROJ.calibrated,floors:floorsExport}; zip.file('project.json',JSON.stringify(json,null,2)); var zipBlob=await zip.generateAsync({type:'blob'}); tempZipBlob=zipBlob; var zipSize=(zipBlob.size/1024/1024).toFixed(2); var zipName=PROJ.name.replace(/[^\w\u4e00-\u9fa5]/g,'_')+'_'+formatDate(new Date())+'.zip'; $('zipSize').innerHTML=zipSize; $('zipName').innerHTML=zipName; $('overlay').style.display='block'; $('sharePanel').style.display='block'; $('shareHint').style.display='none'; var canNativeShare=navigator.canShare&&navigator.canShare({files:[new File([zipBlob],zipName,{type:'application/zip'})]}); var isIOS=/iPad|iPhone|iPod/.test(navigator.userAgent)&&!window.MSStream; if(canNativeShare&&isIOS){ $('nativeShareArea').style.display='block'; $('fallbackArea').style.display='none'; } else { $('nativeShareArea').style.display='none'; $('fallbackArea').style.display='block'; if(isIOS){ $('iosTip').innerHTML='如果无法自动下载，请点击「手动保存文件」按钮'; $('iosTip').style.display='block'; } } var url=URL.createObjectURL(zipBlob); var a=document.createElement('a'); a.href=url; a.download=zipName; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url); } catch(e){ console.error(e); showMsg('打包失败，降级JSON'); fallbackExport(); } }
function fallbackExport(){ var floorsExport=[]; var sorted=FLOORS.slice().sort((a,b)=>a.order-b.order); for(var i=0;i<sorted.length;i++){ var f=sorted[i]; var fm=MARKERS[f.id]||[]; floorsExport.push({id:f.id,name:f.name,order:f.order,markers:fm.map(m=>({id:m.id,status:m.status,captureTime:m.captureTime||'',startTime:m.startTime||'',endTime:m.endTime||'',customName:m.customName||'',x:m.x,y:m.y,direction:m.direction!==undefined?m.direction:null}))}); } var json={projectName:PROJ.name,floors:floorsExport}; var blob=new Blob([JSON.stringify(json,null,2)],{type:'application/json'}); var url=URL.createObjectURL(blob); var a=document.createElement('a'); a.href=url; a.download='project.json'; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url); showMsg('已导出JSON'); }
function formatDate(date){ var y=date.getFullYear(), m=(date.getMonth()+1).toString().padStart(2,'0'), d=date.getDate().toString().padStart(2,'0'); return y+m+d; }
function hideSharePanel(){ $('overlay').style.display='none'; $('sharePanel').style.display='none'; }
async function nativeShare(){ if(tempZipBlob){ var zipName=PROJ.name.replace(/[^\w\u4e00-\u9fa5]/g,'_')+'_'+formatDate(new Date())+'.zip'; var file=new File([tempZipBlob],zipName,{type:'application/zip'}); try{ await navigator.share({files:[file],title:PROJ.name}); showMsg('分享成功'); hideSharePanel(); } catch(e){ showMsg('分享取消或失败'); } } }
function shareByEmail(){ showMsg('请手动发送文件'); }
function shareToWeChat(){ showMsg('请手动发送文件'); }
function manualSaveFile(){ if(tempZipBlob){ var zipName=PROJ.name.replace(/[^\w\u4e00-\u9fa5]/g,'_')+'_'+formatDate(new Date())+'.zip'; var url=URL.createObjectURL(tempZipBlob); var a=document.createElement('a'); a.href=url; a.download=zipName; document.body.appendChild(a); a.click(); setTimeout(function(){ document.body.removeChild(a); URL.revokeObjectURL(url); },1000); showMsg('已尝试保存文件'); } }

// ========== 存储管理器 ==========
var StorageManager={ STORAGE_KEY:'pm_multi_floor', save:function(data){ try{ localStorage.setItem(this.STORAGE_KEY, JSON.stringify(data)); return {success:true}; }catch(e){return {success:false};} }, load:function(){ try{ var s=localStorage.getItem(this.STORAGE_KEY); if(s) return JSON.parse(s); return null; }catch(e){return null;} }, clear:function(){ localStorage.removeItem(this.STORAGE_KEY); }, getStats:function(){ try{ var s=localStorage.getItem(this.STORAGE_KEY); if(!s) return {totalSizeMB:'0.00',percent:0}; var sizeMB=(new Blob([s]).size/1024/1024).toFixed(2); return {totalSizeMB:sizeMB,percent:0}; }catch(e){ return {totalSizeMB:'0.00',percent:0}; } } };
function saveData(){ try{ if(!FLOORS) FLOORS=[]; if(!MARKERS) MARKERS={}; if(!FLOORPLANS) FLOORPLANS={}; for(var i=0;i<FLOORS.length;i++) if(!MARKERS[FLOORS[i].id]) MARKERS[FLOORS[i].id]=[]; var data={proj:PROJ, floors:FLOORS, currentFloor:CURRENT_FLOOR, markers:MARKERS, floorplans:FLOORPLANS}; StorageManager.save(data); } catch(e){ showMsg('保存失败'); } }
function loadData(){ try{ var chunkData=StorageManager.load(); if(chunkData){ PROJ=chunkData.proj; FLOORS=chunkData.floors||[]; CURRENT_FLOOR=chunkData.currentFloor; MARKERS=chunkData.markers||{}; FLOORPLANS=chunkData.floorplans||{}; } if(PROJ){ $('title').innerHTML=PROJ.name; renderFloorBar(); if(CURRENT_FLOOR&&FLOORPLANS[CURRENT_FLOOR]) loadFloorPlan(FLOORPLANS[CURRENT_FLOOR]); else showFloorPlanPrompt(); } } catch(e){ console.error(e); } }

window.onload=function(){ loadVoiceSettings(); loadFloorBarSettings(); loadCaptureSettings(); loadDirectionSettings(); loadPlanAlignmentSettings(); setTimeout(function(){ loadData(); setDirMode(DIRECTION_MODE); startGlobalGyro(); },100); };
$('floorPlanInput').addEventListener('change',function(e){ var targetFloor=this.getAttribute('data-target-floor'); if(targetFloor&&targetFloor!==CURRENT_FLOOR){ var file=e.target.files[0]; if(file){ var reader=new FileReader(); reader.onload=function(evt){ var img=new Image(); img.onload=function(){ var w=img.naturalWidth,h=img.naturalHeight,MAX=2500,finalData; if(w>MAX||h>MAX){ var r=Math.min(MAX/w,MAX/h); w=Math.round(w*r);h=Math.round(h*r); var c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(img,0,0,w,h); finalData=c.toDataURL('image/jpeg',0.85); } else finalData=evt.target.result; FLOORPLANS[targetFloor]={imgData:finalData,imgW:w,imgH:h,originalName:file.name}; saveData(); renderFloorList(); renderFloorBar(); showMsg('平面图导入成功'); }; img.src=evt.target.result; }; reader.readAsDataURL(file); } this.removeAttribute('data-target-floor'); this.value=''; } });

// ========== 方向设置功能 ==========
function loadDirectionSettings(){
  try {
    var saved = localStorage.getItem('panorama_direction_mode');
    if (saved && ['none', 'north', 'manual'].indexOf(saved) >= 0) {
      DIRECTION_MODE = saved;
    }
  } catch(e) {}
}

function setDirMode(mode){
  DIRECTION_MODE = mode;
  try { localStorage.setItem('panorama_direction_mode', mode); } catch(e) {}
  var radios = document.querySelectorAll('input[name="dirMode"]');
  for (var i = 0; i < radios.length; i++) {
    var r = radios[i];
    r.checked = (r.value === mode);
    if (r.parentElement) {
      if (r.value === mode) r.parentElement.classList.add('active');
      else r.parentElement.classList.remove('active');
    }
  }
  var hint = $('dirModeHint');
  if (hint) {
    if (mode === 'north') {
      hint.innerHTML = '📐 点击"我已拍完"时将自动记录当前手机顶部指向作为扇形视线方向。请确保手机顶部对准拍摄目标后再点击。';
    } else if (mode === 'manual') {
      hint.innerHTML = '⚠️ 扇形视线始终指向正北方向，适用于相机默认朝北拍摄的场景。请确保导入平面图时<strong>上北下南</strong>。';
    } else {
      hint.innerHTML = '';
    }
  }
}

// ========== 全屏对齐引导面板 ==========
function showAlignGuidePanel(m){
  tempAlignMarker = m;
  ALIGN_STEP = 1;
  $('alignGuidePanel').style.display = 'flex';
  $('alignStep').innerHTML = '步骤 1/2';
  $('alignTitle').innerHTML = '对齐手机方向';
  $('alignInstruction').innerHTML = '请将手机屏幕上的平面图方向与<strong>现场实际方向</strong>对齐<br>（例如：平面图的上方对应真实世界的北方）';
  $('alignBtn').innerHTML = '我已对齐';
  $('alignBtn').className = 'btn-align btn-align-primary';
  $('alignBtn').onclick = onAlignBtnClick;

  var plan = CURRENT_FLOOR ? FLOORPLANS[CURRENT_FLOOR] : null;
  if (plan) {
    $('alignPlanImg').src = plan.imgData;
    $('alignPlanImg').style.display = 'block';
  } else {
    $('alignPlanImg').style.display = 'none';
  }

  $('alignSectorSvg').style.display = 'none';
  $('gyroAngle').style.display = 'none';
}

function onAlignBtnClick(){
  if (ALIGN_STEP === 1) {
    ALIGN_STEP = 2;
    $('alignStep').innerHTML = '步骤 2/2';
    $('alignTitle').innerHTML = '调整拍摄方向';
    $('alignInstruction').innerHTML = '请<strong>转动手机</strong>，使黄色扇形对准刚才的拍摄目标<br>对准后点击确认保存';
    $('alignBtn').innerHTML = '确认方向并保存';
    $('alignBtn').className = 'btn-align btn-align-primary';
    $('alignBtn').onclick = confirmManualDirection;

    $('alignPlanImg').style.opacity = '0.3';
    $('alignSectorSvg').style.display = 'block';
    $('gyroAngle').style.display = 'block';

    startGyroTracking();
  }
}

function startGyroTracking(){
  GYRO_BASE_ANGLE = null;
  CURRENT_GYRO_ANGLE = 0;
  updateAlignSector(0);

  function onOrientation(event){
    var heading = null;
    if (event.webkitCompassHeading !== undefined && !isNaN(event.webkitCompassHeading)) {
      heading = event.webkitCompassHeading;
    } else if (event.alpha !== null && !isNaN(event.alpha)) {
      heading = 360 - event.alpha;
    }
    if (heading === null || isNaN(heading)) return;

    if (GYRO_BASE_ANGLE === null) {
      GYRO_BASE_ANGLE = heading;
    }

    CURRENT_GYRO_ANGLE = (heading - GYRO_BASE_ANGLE + 360) % 360;
    updateAlignSector(CURRENT_GYRO_ANGLE);
  }

  GYRO_LISTENER = onOrientation;

  if (typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
    DeviceOrientationEvent.requestPermission().then(function(permissionState){
      if (permissionState === 'granted') {
        window.addEventListener('deviceorientation', onOrientation);
      } else {
        showMsg('需要陀螺仪权限才能手动对齐方向');
        cancelAlign();
      }
    }).catch(function(err){
      showMsg('陀螺仪权限请求失败');
      cancelAlign();
    });
  } else {
    window.addEventListener('deviceorientation', onOrientation);
  }
}

function updateAlignSector(angle){
  $('gyroAngle').innerHTML = Math.round(angle) + '°';

  var r = 90;
  var half = SECTOR_ANGLE / 2;
  var startRad = (-90 - half) * Math.PI / 180;
  var endRad = (-90 + half) * Math.PI / 180;

  var x1 = r * Math.cos(startRad);
  var y1 = r * Math.sin(startRad);
  var x2 = r * Math.cos(endRad);
  var y2 = r * Math.sin(endRad);

  var d = 'M 0 0 L ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' A ' + r + ' ' + r + ' 0 0 1 ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + ' Z';
  $('alignSectorPath').setAttribute('d', d);

  $('alignSectorSvg').style.transform = 'translate(-50%, -50%) rotate(' + angle + 'deg)';
}

function confirmManualDirection(){
  if (tempAlignMarker) {
    tempAlignMarker.direction = Math.round(CURRENT_GYRO_ANGLE);
    finishCapture(tempAlignMarker);
  }
  stopGyroTracking();
  $('alignGuidePanel').style.display = 'none';
  $('alignPlanImg').style.opacity = '1';
  tempAlignMarker = null;
}

function cancelAlign(){
  stopGyroTracking();
  $('alignGuidePanel').style.display = 'none';
  $('alignPlanImg').style.opacity = '1';
  tempAlignMarker = null;
  PENDING_SAVE_AFTER_CAPTURE = false;
  PENDING_FINISH_AFTER_CAPTURE = false;
  showMsg('已取消方向设置');
}

function stopGyroTracking(){
  if (GYRO_LISTENER) {
    window.removeEventListener('deviceorientation', GYRO_LISTENER);
    GYRO_LISTENER = null;
  }
  GYRO_BASE_ANGLE = null;
}

// ========== 主界面扇形渲染 ==========
function renderDirectionSectors(){
  var layer = $('dotsLayer') || $('planLayer');
  var old = layer.querySelector('#directionSectors');
  if (old) old.parentNode.removeChild(old);
  var ms = CURRENT_FLOOR ? MARKERS[CURRENT_FLOOR] || [] : [];
  var dirs = ms.filter(function(m){ return m.direction !== null && m.direction !== undefined; });
  if (DIRECTION_MODE === 'manual' && ACTIVE && $('panel').style.display !== 'none' && GYRO_HEADING !== null) {
    var am = findMarker(ACTIVE);
    if (am && am.status === 'pending') { am._live = Math.round(GYRO_HEADING); if (dirs.indexOf(am) < 0) dirs.push(am); }
  }
  if (dirs.length === 0) return;
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'directionSectors';
  svg.style.position = 'absolute';
  svg.style.left = '0';
  svg.style.top = '0';
  svg.style.width = '100%';
  svg.style.height = '100%';
  svg.style.pointerEvents = 'none';
  svg.style.zIndex = '9';
  var r = 40 * SCALE;
  if (r < 20) r = 20;
  if (r > 80) r = 80;
  var half = SECTOR_ANGLE / 2;
  for (var i = 0; i < dirs.length; i++) {
    var m = dirs[i];
    var sp = imageToScreenCoords(m.x, m.y);
    var cx = sp.x, cy = sp.y;
    var ang = (m._live !== undefined) ? m._live : m.direction;
    if (PLAN_ALIGNED && !OFFLINE_MODE && Math.abs(smoothRotation) > 0.1) { ang = ang - smoothRotation; }
    var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('transform', 'translate(' + cx.toFixed(1) + ',' + cy.toFixed(1) + ') rotate(' + ang + ')');
    var sr = (-90 - half) * Math.PI / 180, er = (-90 + half) * Math.PI / 180;
    var x1 = r * Math.cos(sr), y1 = r * Math.sin(sr), x2 = r * Math.cos(er), y2 = r * Math.sin(er);
    var p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', 'M 0 0 L ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' A ' + r.toFixed(1) + ' ' + r.toFixed(1) + ' 0 0 1 ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + ' Z');
    var live = m._live !== undefined;
    p.setAttribute('fill', live ? 'rgba(10,132,255,0.35)' : 'rgba(255,204,0,0.25)');
    p.setAttribute('stroke', live ? '#0a84ff' : '#ffcc00');
    p.setAttribute('stroke-width', live ? '2' : '1.5');
    g.appendChild(p);
    svg.appendChild(g);
    if (m._live !== undefined) delete m._live;
  }
  layer.appendChild(svg);
}

// ========== 百度浏览器保存弹窗 ==========
function showSaveImagePanel(file, fileName){
  tempSaveFile = file;
  tempSaveFileName = fileName;
  var url = URL.createObjectURL(file);
  $('savePreviewImg').src = url;
  $('saveImagePanel').style.display = 'flex';

  $('saveImageBtn').onclick = function(){
    triggerFileDownload(tempSaveFile, tempSaveFileName);
    showMsg('照片已下载，请从浏览器下载管理中保存到相册');
  };
}

function hideSaveImagePanel(){
  $('saveImagePanel').style.display = 'none';
  var img = $('savePreviewImg');
  if (img.src && img.src.indexOf('blob:') === 0) {
    URL.revokeObjectURL(img.src);
    img.src = '';
  }
  tempSaveFile = null;
  tempSaveFileName = '';
}
