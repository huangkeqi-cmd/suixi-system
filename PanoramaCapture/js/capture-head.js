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
  var old = document.getElementById('directionSectors');
  if (old) old.parentNode.removeChild(old);

  var currentMarkers = CURRENT_FLOOR ? (MARKERS[CURRENT_FLOOR] || []) : [];
  var markersWithDir = [];
  for (var i = 0; i < currentMarkers.length; i++) {
    var m = currentMarkers[i];
    if (m.direction !== null && m.direction !== undefined) markersWithDir.push(m);
  }
  if (markersWithDir.length === 0) return;

  var wrap = $('wrap');
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

  for (var i = 0; i < markersWithDir.length; i++) {
    var m = markersWithDir[i];
    var cx = OFF_X + m.x * IMG_W * SCALE;
    var cy = OFF_Y + m.y * IMG_H * SCALE;
    var angle = m.direction || 0;

    var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('transform', 'translate(' + cx.toFixed(1) + ',' + cy.toFixed(1) + ') rotate(' + angle + ')');

    var startRad = (-90 - half) * Math.PI / 180;
    var endRad = (-90 + half) * Math.PI / 180;
    var x1 = r * Math.cos(startRad);
    var y1 = r * Math.sin(startRad);
    var x2 = r * Math.cos(endRad);
    var y2 = r * Math.sin(endRad);

    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M 0 0 L ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' A ' + r.toFixed(1) + ' ' + r.toFixed(1) + ' 0 0 1 ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + ' Z');
    path.setAttribute('fill', 'rgba(255, 204, 0, 0.25)');
    path.setAttribute('stroke', '#ffcc00');
    path.setAttribute('stroke-width', '1.5');

    g.appendChild(path);
    svg.appendChild(g);
  }

  wrap.appendChild(svg);
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

// 版本号和强制刷新机制
const APP_VERSION = '20250423-0017';  // 修复第三方浏览器相机启动
const CHECK_INTERVAL = 10000;

(function() {
  var savedVersion = localStorage.getItem('panorama_capture_version');
  if (savedVersion !== APP_VERSION) {
    localStorage.setItem('panorama_capture_version', APP_VERSION);
    if (savedVersion) {
      alert('检测到新版本，即将刷新页面...');
      location.reload(true);
    }
  }
  setInterval(checkForUpdates, CHECK_INTERVAL);
})();

function checkForUpdates() {}

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
  var old = document.getElementById('directionSectors');
  if (old) old.parentNode.removeChild(old);

  var currentMarkers = CURRENT_FLOOR ? (MARKERS[CURRENT_FLOOR] || []) : [];
  var markersWithDir = [];
  for (var i = 0; i < currentMarkers.length; i++) {
    var m = currentMarkers[i];
    if (m.direction !== null && m.direction !== undefined) markersWithDir.push(m);
  }
  if (markersWithDir.length === 0) return;

  var wrap = $('wrap');
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

  for (var i = 0; i < markersWithDir.length; i++) {
    var m = markersWithDir[i];
    var cx = OFF_X + m.x * IMG_W * SCALE;
    var cy = OFF_Y + m.y * IMG_H * SCALE;
    var angle = m.direction || 0;

    var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('transform', 'translate(' + cx.toFixed(1) + ',' + cy.toFixed(1) + ') rotate(' + angle + ')');

    var startRad = (-90 - half) * Math.PI / 180;
    var endRad = (-90 + half) * Math.PI / 180;
    var x1 = r * Math.cos(startRad);
    var y1 = r * Math.sin(startRad);
    var x2 = r * Math.cos(endRad);
    var y2 = r * Math.sin(endRad);

    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M 0 0 L ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' A ' + r.toFixed(1) + ' ' + r.toFixed(1) + ' 0 0 1 ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + ' Z');
    path.setAttribute('fill', 'rgba(255, 204, 0, 0.25)');
    path.setAttribute('stroke', '#ffcc00');
    path.setAttribute('stroke-width', '1.5');

    g.appendChild(path);
    svg.appendChild(g);
  }

  wrap.appendChild(svg);
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
