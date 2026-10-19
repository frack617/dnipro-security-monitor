// Create a NEW Apps Script project. Do not replace any existing backup script.
// Script property GITHUB_ACTIONS_TOKEN: fine-grained PAT, this repository only,
// repository permission Actions: Read and write (Metadata read is automatic).
// No Gemini or Telegram credentials belong in this script.
const MONITOR_REPO = 'frack617/dnipro-security-monitor';

function monitorWatchdog() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    const props = PropertiesService.getScriptProperties();
    const token = props.getProperty('GITHUB_ACTIONS_TOKEN');
    if (!token) throw new Error('Set GITHUB_ACTIONS_TOKEN in Script properties');
    const now = new Date();
    const lastDispatch = Number(props.getProperty('LAST_DISPATCH_MS') || 0);
    if (now.getTime() - lastDispatch < 10 * 60 * 1000) return;
    let fresh = false;
    try {
      const response = UrlFetchApp.fetch(
        'https://raw.githubusercontent.com/' + MONITOR_REPO + '/main/data/status.json?t=' + now.getTime(),
        {muteHttpExceptions: true});
      if (response.getResponseCode() === 200) {
        const checked = Date.parse(JSON.parse(response.getContentText()).checked_at);
        const age = now.getTime() - checked;
        fresh = Number.isFinite(checked) && age >= 0 && age < 25 * 60 * 1000;
      }
    } catch (_) { /* No current status: request a bounded recovery run. */ }
    const kyiv = Utilities.formatDate(now, 'Europe/Kyiv', 'yyyy-MM-dd HH:mm');
    const today = kyiv.slice(0, 10);
    // After 08:00, check date delivery even if a 07:59 poll is still fresh.
    let delivered = kyiv.slice(11) < '08:00';
    if (!delivered) {
      try {
        const state = UrlFetchApp.fetch(
          'https://raw.githubusercontent.com/' + MONITOR_REPO + '/main/data/alert_state.json?t=' + now.getTime(),
          {muteHttpExceptions: true});
        if (state.getResponseCode() === 200)
          delivered = JSON.parse(state.getContentText()).last_daily_report === today;
      } catch (_) {}
    }
    if (fresh && delivered) return;
    const dispatched = UrlFetchApp.fetch(
      'https://api.github.com/repos/' + MONITOR_REPO + '/actions/workflows/collect.yml/dispatches', {
        method: 'post', contentType: 'application/json', muteHttpExceptions: true,
        headers: {Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json',
                  'X-GitHub-Api-Version': '2022-11-28'},
        payload: JSON.stringify({ref: 'main', inputs: {
          report_provider: 'auto', force_report: false, send_report: true}})
      });
    const code = dispatched.getResponseCode();
    if (code !== 204) throw new Error('GitHub dispatch failed: HTTP ' + code);
    props.setProperty('LAST_DISPATCH_MS', String(now.getTime()));
    console.log('Recovery dispatch accepted at ' + kyiv);
  } finally { lock.releaseLock(); }
}

function installMonitorWatchdog() {
  // Idempotent setup in this NEW project; unrelated triggers are preserved.
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'monitorWatchdog')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('monitorWatchdog').timeBased().everyMinutes(5).create();
  monitorWatchdog();
}
