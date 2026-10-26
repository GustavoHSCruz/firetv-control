'use strict';
const $ = (selector) => document.querySelector(selector);
let token = location.hash.slice(1) || sessionStorage.getItem('firetv-token') || '';
if (location.hash.length > 1) { sessionStorage.setItem('firetv-token', token); history.replaceState(null, '', location.pathname); }
let connected = false, busy = false, activeTab = 'remote', apps = [], currentPath = '/sdcard', imageURL = '';
let mirrorRunning = false, mirrorPolling = false;
const titles = {
  remote: ['Seu controle ganhou espaço.', 'Navegue na TV sem sair do computador.'],
  apps: ['Seus apps, bem mais perto.', 'Instale, abra e gerencie aplicativos do Fire TV.'],
  files: ['Seus arquivos, de um lado ao outro.', 'Fotos, vídeos e documentos entre o computador e a TV.'],
  home: ['Abra espaço para o seu estilo.', 'Explore uma tela inicial mais simples e pessoal.'],
  help: ['Vamos conectar sua TV.', 'Tudo o que você precisa para começar.'],
};
function message(text, kind = '') { const node = $('#status'); node.hidden = !text; node.textContent = text; node.className = kind; }
function controls() {
  document.querySelectorAll('[data-device]').forEach(e => { e.disabled = !connected || busy; });
  document.querySelectorAll('button:not([data-device]):not(.nav), #address, #device-select').forEach(e => { e.disabled = busy; });
  $('#disconnect').hidden = !connected;
  $('#connection-status').textContent = connected ? '● Conectado' : 'Desconectado';
  $('#connection-status').classList.toggle('online', connected);
  $('#mirror-start').hidden = mirrorRunning;
  $('#mirror-stop').hidden = !mirrorRunning;
  $('#mirror-state').textContent = mirrorRunning ? '● Ao vivo' : 'Vídeo ao vivo';
}
function showMirror(running) {
  mirrorRunning = running;
  $('#live-video').hidden = !running;
  $('#screenshot').hidden = running || !imageURL;
  $('#screen-placeholder').hidden = running || Boolean(imageURL);
  if (running && !$('#live-video').hasAttribute('src')) $('#live-video').src = '/api/live';
  if (!running) $('#live-video').removeAttribute('src');
}
async function request(action, data = {}) {
  const response = await fetch('/api/action', { method: 'POST', headers: {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'}, body: JSON.stringify({action, ...data}) });
  const result = await response.json();
  if (!result.ok) throw new Error(result.error || 'A operação falhou.');
  return result.data;
}
async function work(label, callback, success = '') {
  if (busy) return;
  busy = true; controls(); message(label, 'working');
  try { await callback(); message(success); }
  catch (error) { message(error.message || 'Não foi possível concluir a operação.', 'error'); }
  finally { busy = false; controls(); }
}
function el(tag, text, cls) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; }
function actionButton(label, callback, cls = 'secondary') { const b = el('button', label, `button ${cls}`); b.dataset.device = ''; b.addEventListener('click', callback); return b; }
function resetDeviceView() {
  connected = false; apps = []; imageURL = ''; currentPath = '/sdcard';
  showMirror(false);
  $('#device-model').textContent = 'Conecte seu Fire TV'; $('#device-detail').textContent = 'Ative a depuração ADB e use a mesma rede Wi-Fi.';
  $('#screenshot').hidden = true; $('#screenshot').removeAttribute('src'); $('#screen-placeholder').hidden = false; $('#save-screenshot').hidden = true;
  $('#app-list').replaceChildren(el('div', 'Conecte o Fire TV para ver os aplicativos.', 'empty'));
  $('#file-list').replaceChildren(el('div', 'Abra uma pasta para começar.', 'empty')); $('#remote-path').value = currentPath; $('#file-count').textContent = '';
  $('#home-list').replaceChildren(el('div', 'Nenhuma consulta realizada.', 'empty')); $('#current-home').textContent = 'Consulte os aplicativos que declaram uma tela inicial.';
}
async function deviceInfo() {
  const info = await request('info'); connected = true;
  $('#device-model').textContent = info.model;
  $('#device-detail').textContent = [info.serial, info.software || (info.fire_os && `Fire OS ${info.fire_os}`), info.android && `Android ${info.android}`].filter(Boolean).join(' · ');
  if (info.serial.includes(':')) $('#address').value = info.serial;
}
async function refresh() {
  const doctor = await request('doctor'); const notice = $('#setup-notice');
  notice.hidden = doctor.ready;
  if (!doctor.ready) { notice.textContent = doctor.error; resetDeviceView(); return; }
  const devices = await request('devices');
  const select = $('#device-select'); select.replaceChildren(el('option', 'Selecione…')); select.firstChild.value = '';
  devices.forEach(d => { const option = el('option', `${d.model || d.serial} · ${d.serial} · ${d.state}`); option.value = d.serial; option.disabled = d.state !== 'device'; select.append(option); });
  $('#device-options').hidden = !devices.length;
  const selected = devices.find(d => d.serial === doctor.selected);
  if (selected && selected.state === 'device') { select.value = selected.serial; await deviceInfo(); }
  else { resetDeviceView(); if (selected) throw new Error(`Dispositivo ${selected.state}. Autorize a depuração na TV e conecte novamente.`); }
}
async function loadApps() { apps = await request('apps', {all: $('#all-apps').checked}); renderApps(); }
function renderApps() {
  const list = $('#app-list'); list.replaceChildren();
  const filtered = apps.filter(a => a.package.toLowerCase().includes($('#app-search').value.toLowerCase()));
  if (!filtered.length) list.append(el('div', apps.length ? 'Nenhum pacote corresponde à busca.' : 'Nenhum app encontrado. Clique em Carregar para consultar.', 'empty'));
  filtered.forEach(a => {
    const row = el('div', undefined, 'list-row'); row.append(el('span', '▦', 'item-icon'), el('span', a.package, 'item-name'));
    row.append(actionButton('Abrir ↗', () => work('Abrindo aplicativo…', () => request('launch', {package: a.package}), 'Aplicativo aberto na TV.')));
    if (!$('#all-apps').checked) row.append(actionButton('Desinstalar', () => {
      if (confirm(`Desinstalar ${a.package}?\n\nOs dados locais deste app serão apagados.`)) work('Desinstalando aplicativo…', async () => { await request('uninstall', {package: a.package, confirmed: true}); await loadApps(); }, 'Aplicativo desinstalado.');
    }, 'quiet danger'));
    list.append(row);
  }); controls();
}
async function loadFiles(path = currentPath) {
  const result = await request('files', {path}); currentPath = result.path; $('#remote-path').value = currentPath;
  const list = $('#file-list'); list.replaceChildren(); $('#file-count').textContent = `${result.entries.length} itens`;
  if (!result.entries.length) list.append(el('div', 'Esta pasta está vazia.', 'empty'));
  result.entries.forEach(item => {
    const row = el('div', undefined, 'list-row'); const name = el('span', item.name, 'item-name');
    name.append(el('small', item.kind === 'directory' ? 'Pasta' : item.kind === 'link' ? 'Link simbólico' : 'Arquivo'));
    row.append(el('span', item.kind === 'directory' ? '▱' : '▤', 'item-icon'), name);
    if (item.kind === 'directory') row.append(actionButton('Abrir →', () => work('Abrindo pasta…', () => loadFiles(item.path))));
    else if (item.kind === 'file') row.append(actionButton('Baixar ↓', () => work('Copiando arquivo da TV…', () => download(item.path, item.name), 'Download preparado. Confira os downloads do navegador.')));
    list.append(row);
  }); controls();
}
async function loadHome() {
  const data = await request('home'); $('#current-home').textContent = `Home atual: ${data.current || 'não identificada'}`;
  const list = $('#home-list'); list.replaceChildren();
  if (!data.launchers.length) list.append(el('div', 'Nenhum launcher declarado como HOME foi encontrado.', 'empty'));
  data.launchers.forEach(item => {
    const row = el('div', undefined, 'list-row'); const name = el('span', item.package, 'item-name');
    name.append(el('small', item.helper ? 'Componente auxiliar do sistema' : item.component === data.current ? 'Home atual' : 'Launcher disponível'));
    row.append(el('span', '⌂', 'item-icon'), name);
    if (!item.helper) row.append(actionButton('Abrir na TV ↗', () => work('Abrindo launcher…', () => request('open_launcher', {component: item.component}), 'Launcher aberto. Configure o visual diretamente na TV.')));
    list.append(row);
  });
  controls();
}
function upload(file, mode, path = '') {
  return new Promise((resolve, reject) => {
    if (file.size > 2 * 1024 * 1024 * 1024) return reject(new Error('O limite por envio é 2 GB.'));
    const params = new URLSearchParams({mode, path, overwrite: String($('#overwrite').checked)});
    const xhr = new XMLHttpRequest(); xhr.open('POST', `/api/upload?${params}`); xhr.setRequestHeader('Authorization', `Bearer ${token}`); xhr.setRequestHeader('Content-Type', 'application/octet-stream'); xhr.timeout = 600000;
    xhr.upload.onprogress = e => { if (e.lengthComputable) message(`Enviando ${file.name}: ${Math.round(e.loaded / e.total * 100)}% — aguarde a conclusão na TV.`, 'working'); };
    xhr.onload = () => { try { const result = JSON.parse(xhr.responseText); result.ok ? resolve(result.data) : reject(new Error(result.error)); } catch { reject(new Error('Resposta inválida durante o envio.')); } };
    xhr.onerror = () => reject(new Error('Falha de rede durante o envio.')); xhr.ontimeout = () => reject(new Error('Tempo de envio excedido. Confira o resultado na TV antes de repetir.')); xhr.send(file);
  });
}
async function download(path, name) {
  const response = await fetch('/api/download', {method: 'POST', headers: {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'}, body: JSON.stringify({path})});
  if (!response.ok) { const error = await response.json(); throw new Error(error.error); }
  const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = el('a'); link.href = url; link.download = name; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
}
async function activateTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab').forEach(n => { n.hidden = n.id !== `tab-${tab}`; });
  document.querySelectorAll('.nav').forEach(n => { n.classList.toggle('active', n.dataset.tab === tab); n.setAttribute('aria-current', n.dataset.tab === tab ? 'page' : 'false'); });
  $('#page-title').textContent = titles[tab][0]; $('#page-description').textContent = titles[tab][1];
  if (connected && !busy) {
    if (tab === 'apps') await work('Consultando aplicativos…', loadApps);
    else if (tab === 'files') await work('Lendo arquivos…', () => loadFiles());
    else if (tab === 'home') await work('Consultando launchers…', loadHome);
  }
}
document.querySelectorAll('.nav').forEach(b => b.addEventListener('click', () => activateTab(b.dataset.tab)));
$('.brand').addEventListener('click', e => { e.preventDefault(); activateTab('remote'); });
$('#refresh').addEventListener('click', () => work('Consultando conexão…', async () => { await refresh(); if (connected && activeTab === 'apps') await loadApps(); else if (connected && activeTab === 'files') await loadFiles(); else if (connected && activeTab === 'home') await loadHome(); }));
$('#connect-form').addEventListener('submit', e => { e.preventDefault(); work('Conectando… aceite o aviso de depuração na TV.', async () => { await request('connect', {address: $('#address').value.trim()}); resetDeviceView(); await refresh(); }, 'Fire TV conectado.'); });
$('#select-device').addEventListener('click', () => work('Selecionando dispositivo…', async () => { await request('select', {serial: $('#device-select').value}); resetDeviceView(); await refresh(); }, 'Dispositivo selecionado.'));
$('#disconnect').addEventListener('click', () => work('Desconectando…', async () => { await request('disconnect'); resetDeviceView(); await refresh(); }, 'Desconectado.'));
document.querySelectorAll('[data-key]').forEach(b => b.addEventListener('click', () => work('Enviando comando…', () => request('key', {key: b.dataset.key}))));
document.addEventListener('keydown', e => {
  if (!connected || busy || activeTab !== 'remote' || /^(INPUT|TEXTAREA|SELECT|BUTTON|A)$/.test(e.target.tagName) || e.ctrlKey || e.altKey || e.metaKey) return;
  const key = {ArrowUp:'up', ArrowDown:'down', ArrowLeft:'left', ArrowRight:'right', Enter:'ok', Escape:'back', ' ':'play'}[e.key];
  if (key) { e.preventDefault(); work('Enviando comando…', () => request('key', {key})); }
});
$('#text-form').addEventListener('submit', e => { e.preventDefault(); work('Enviando texto…', async () => { await request('text', {text: $('#remote-text').value}); $('#remote-text').value = ''; }, 'Texto enviado.'); });
$('#capture').addEventListener('click', () => work('Capturando a tela da TV…', async () => { const data = await request('screenshot'); imageURL = data.image; $('#screenshot').src = imageURL; $('#screenshot').hidden = mirrorRunning; $('#screen-placeholder').hidden = true; $('#save-screenshot').href = imageURL; $('#save-screenshot').hidden = false; }, 'Captura atualizada.'));
$('#mirror-start').addEventListener('click', () => work('Iniciando vídeo ao vivo…', async () => {
  const result = await request('mirror_start'); showMirror(result.running);
}, 'Vídeo ao vivo iniciado. O áudio continua na TV.'));
$('#mirror-stop').addEventListener('click', () => work('Encerrando vídeo ao vivo…', async () => {
  await request('mirror_stop'); showMirror(false);
}, 'Vídeo ao vivo encerrado.'));
async function updateMirrorStatus() {
  if (!connected || busy || mirrorPolling || document.hidden) return;
  mirrorPolling = true;
  try {
    const result = await request('mirror_status');
    if (busy) return;
    const ended = mirrorRunning && !result.running; showMirror(result.running); controls();
    if (ended && result.error) message(`Vídeo ao vivo interrompido: ${result.error}`, 'error');
  } catch { /* Normal requests report connection failures; polling stays quiet. */ }
  finally { mirrorPolling = false; }
}
setInterval(updateMirrorStatus, 3000);
$('#load-apps').addEventListener('click', () => work('Consultando aplicativos…', loadApps));
$('#app-search').addEventListener('input', renderApps);
$('#all-apps').addEventListener('change', () => { if (connected) work('Consultando aplicativos…', loadApps); });
$('#apk-file').addEventListener('change', e => { const file = e.target.files[0]; e.target.value = ''; if (!file) return; if (!file.name.toLowerCase().endsWith('.apk')) { message('Selecione um arquivo .apk.', 'error'); return; } if (confirm(`Instalar ou atualizar ${file.name} no Fire TV?`)) work('Enviando APK…', async () => { await upload(file, 'install'); await loadApps(); }, 'APK instalado com sucesso.'); });
$('#path-form').addEventListener('submit', e => { e.preventDefault(); work('Abrindo pasta…', () => loadFiles($('#remote-path').value)); });
$('#parent-folder').addEventListener('click', () => { const root = currentPath.startsWith('/storage/emulated/0') ? '/storage/emulated/0' : '/sdcard'; const parent = currentPath === root ? root : currentPath.slice(0, currentPath.lastIndexOf('/')); work('Abrindo pasta…', () => loadFiles(parent)); });
$('#transfer-file').addEventListener('change', e => { const file = e.target.files[0]; e.target.value = ''; if (!file) return; const path = `${currentPath}/${file.name}`; if ($('#overwrite').checked && !confirm(`Enviar para ${path}?\nUm arquivo com esse nome será substituído.`)) return; work('Enviando arquivo…', async () => { await upload(file, 'push', path); await loadFiles(); }, 'Arquivo enviado para a TV.'); });
$('#load-home').addEventListener('click', () => work('Consultando launchers…', loadHome));
controls();
work('Verificando ADB…', refresh);
