const { app, BrowserWindow, Menu, session, shell } = require('electron');
const path = require('path');
const http = require('http');

const BASE_URL = 'http://127.0.0.1:8000';
const HEALTH_URL = `${BASE_URL}/api/health`;
const APP_URL = `${BASE_URL}/?desktop=zonexplay-v0352`;
const ALLOWED_ORIGIN = new URL(BASE_URL).origin;
let mainWindow = null;
let loading = false;

const dataRoot = process.env.PROGRAMDATA
  ? path.join(process.env.PROGRAMDATA, 'PlayZone Manager', 'desktop-profile')
  : path.join(app.getPath('userData'), 'PlayZone Manager');
app.setPath('userData', dataRoot);
app.setName('ZoneXplay');
app.setAppUserModelId('ZoneXplay.Desktop');
app.commandLine.appendSwitch('disable-features', 'AutofillServerCommunication,PasswordManagerOnboarding');

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function healthCheck(timeoutMs = 1200) {
  return new Promise((resolve) => {
    const req = http.get(HEALTH_URL, { timeout: timeoutMs }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.on('error', () => resolve(false));
  });
}

function waitingHtml() {
  const html = `<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>ZoneXplay</title>
  <style>html,body{height:100%;margin:0;font-family:Segoe UI,Tahoma,Arial;background:#06101c;color:#eaf3ff}body{display:grid;place-items:center}.box{width:min(560px,90vw);background:#0d1d2e;border:1px solid #1d4268;border-radius:18px;padding:32px;text-align:center;box-shadow:0 25px 80px #0008}h1{margin:0 0 10px;color:#48a7ff}.spin{width:34px;height:34px;border:4px solid #163652;border-top-color:#4aa8ff;border-radius:50%;margin:24px auto;animation:s 1s linear infinite}@keyframes s{to{transform:rotate(360deg)}}p{color:#9db3ca;line-height:1.8}</style>
  <body><div class="box"><h1>ZoneXplay</h1><div class="spin"></div><h2>جاري تشغيل النظام...</h2><p>التطبيق ينتظر خدمة ZoneXplay المحلية على هذا الجهاز.<br>لو استمر الانتظار راجع خدمة النظام المحلية.</p></div></body></html>`;
  return 'data:text/html;charset=utf-8,' + encodeURIComponent(html);
}

async function loadAppWhenReady() {
  if (!mainWindow || loading) return;
  loading = true;
  try {
    if (await healthCheck()) {
      await mainWindow.loadURL(APP_URL);
      return;
    }
    await mainWindow.loadURL(waitingHtml());
    const timer = setInterval(async () => {
      if (!mainWindow || mainWindow.isDestroyed()) { clearInterval(timer); return; }
      if (await healthCheck()) {
        clearInterval(timer);
        try { await mainWindow.loadURL(APP_URL); } catch (_) {}
      }
    }, 1200);
  } finally {
    loading = false;
  }
}

function isAllowedNavigation(url) {
  try {
    const u = new URL(url);
    return u.origin === ALLOWED_ORIGIN || u.protocol === 'data:';
  } catch (_) {
    return false;
  }
}

function createWindow() {
  const installRoot = path.resolve(__dirname, '..');
  mainWindow = new BrowserWindow({
    title: 'ZoneXplay',
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    backgroundColor: '#06101c',
    autoHideMenuBar: true,
    icon: path.join(installRoot, 'PlayStation.ico'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      devTools: false,
      spellcheck: false,
      navigateOnDragDrop: false,
      safeDialogs: true,
    }
  });

  Menu.setApplicationMenu(null);
  mainWindow.setMenuBarVisibility(false);
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // Keep the desktop client locked to its local ZoneXplay service.
    if (isAllowedNavigation(url)) return { action: 'allow' };
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedNavigation(url)) event.preventDefault();
  });
  mainWindow.webContents.on('before-input-event', (event, input) => {
    const key = String(input.key || '').toUpperCase();
    if (key === 'F12' || (input.control && input.shift && ['I','J','C'].includes(key))) {
      event.preventDefault();
    }
  });
  mainWindow.webContents.on('context-menu', (event) => event.preventDefault());
  mainWindow.once('ready-to-show', () => {
    mainWindow.maximize();
    mainWindow.show();
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  loadAppWhenReady();
}

app.whenReady().then(async () => {
  // Avoid stale frontend bundles between ZoneXplay upgrades while preserving localStorage/login state.
  try { await session.defaultSession.clearCache(); } catch (_) {}
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => app.quit());
