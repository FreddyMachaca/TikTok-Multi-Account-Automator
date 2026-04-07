    const state = {
      accounts: [],
      settings: {},
      progressCursor: 0,
      pollingTimer: null,
      running: false,
      lastSummary: null,
      waitingJobStart: false,
      uploadRequestedAt: 0
    };

    const ui = {
      apiStatus: document.getElementById('apiStatus'),
      tabs: Array.from(document.querySelectorAll('.tab')),
      panels: Array.from(document.querySelectorAll('.panel')),
      startBtn: document.getElementById('startBtn'),
      stopBtn: document.getElementById('stopBtn'),
      videosInfo: document.getElementById('videosInfo'),
      progressFill: document.getElementById('progressFill'),
      progressPercent: document.getElementById('progressPercent'),
      progressText: document.getElementById('progressText'),
      currentTask: document.getElementById('currentTask'),
      timeStarted: document.getElementById('timeStarted'),
      timeElapsed: document.getElementById('timeElapsed'),
      timeRemaining: document.getElementById('timeRemaining'),
      dashboardAccountCards: document.getElementById('dashboardAccountCards'),
      liveLog: document.getElementById('liveLog'),
      finalSummary: document.getElementById('finalSummary'),
      refreshAccountsBtn: document.getElementById('refreshAccountsBtn'),
      newAccountForm: document.getElementById('newAccountForm'),
      accountsList: document.getElementById('accountsList'),
      saveSettingsBtn: document.getElementById('saveSettingsBtn'),
      settingsState: document.getElementById('settingsState'),
      loadHistoryBtn: document.getElementById('loadHistoryBtn'),
      historyRows: document.getElementById('historyRows'),
      historyAccountFilter: document.getElementById('historyAccountFilter'),
      historyStartDate: document.getElementById('historyStartDate'),
      historyEndDate: document.getElementById('historyEndDate'),
      historyLimit: document.getElementById('historyLimit')
    };

    const settingsIds = {
      brand_hashtag: 'brandHashtag',
      fixed_location_hashtags: 'fixedLocationHashtags',
      primary_youtube_mention: 'primaryYoutubeMention',
      secondary_primary_mention: 'secondaryPrimaryMention',
      primary_description_template: 'primaryDescriptionTemplate',
      secondary_description_template: 'secondaryDescriptionTemplate',
      videos_folder: 'videosFolder',
      delay_between_uploads: 'delayBetweenUploads',
      max_daily_per_account: 'maxDailyPerAccount',
      playwright_headless: 'playwrightHeadless',
      tiktok_upload_url: 'selectorUploadUrl',
      tiktok_file_input_selector: 'selectorFileInput',
      tiktok_description_selector: 'selectorDescription',
      tiktok_upload_button_selector: 'selectorUploadButton',
      tiktok_success_selector: 'selectorSuccess',
      tiktok_captcha_selector: 'selectorCaptcha',
      tiktok_preview_wait_ms: 'previewWaitMs',
      tiktok_publish_timeout_seconds: 'publishTimeoutSeconds'
    };

    async function api(path, options = {}) {
      const request = {
        method: options.method || 'GET',
        headers: {
          'Content-Type': 'application/json',
          ...(options.headers || {})
        }
      };
      if (options.body !== undefined) {
        request.body = JSON.stringify(options.body);
      }
      const response = await fetch(path, request);
      if (!response.ok) {
        let message = `Error ${response.status}`;
        try {
          const data = await response.json();
          if (data.detail) {
            message = data.detail;
          }
        } catch {}
        throw new Error(message);
      }
      const text = await response.text();
      if (!text) {
        return null;
      }
      return JSON.parse(text);
    }

    function formatSeconds(total) {
      if (total === null || total === undefined) {
        return 'calculando...';
      }
      const value = Math.max(0, Number(total));
      const h = Math.floor(value / 3600);
      const m = Math.floor((value % 3600) / 60);
      const s = Math.floor(value % 60);
      if (h > 0) {
        return `${h}h ${m}m ${s}s`;
      }
      if (m > 0) {
        return `${m}m ${s}s`;
      }
      return `${s}s`;
    }

    function setStartButton(mode) {
      ui.startBtn.classList.remove('idle', 'running', 'retry');
      if (mode === 'running') {
        ui.startBtn.classList.add('running');
        ui.startBtn.disabled = true;
        ui.startBtn.textContent = 'SUBIDA EN PROGRESO...';
        return;
      }
      if (mode === 'retry') {
        ui.startBtn.classList.add('retry');
        ui.startBtn.disabled = false;
        ui.startBtn.textContent = 'REINTENTAR FALLIDAS';
        return;
      }
      ui.startBtn.classList.add('idle');
      ui.startBtn.disabled = false;
      ui.startBtn.textContent = 'INICIAR SUBIDA';
    }

    function isWaitingStartupWindow(data) {
      if (!state.waitingJobStart) {
        return false;
      }
      const elapsed = Date.now() - state.uploadRequestedAt;
      if (elapsed > 20000) {
        return false;
      }
      return !data.running && Number(data.total || 0) === 0 && Number(data.done || 0) === 0;
    }

    function appendLogs(items) {
      if (!items || items.length === 0) {
        return;
      }
      const lines = items.map(item => `${item.timestamp}  [${item.level}]  ${item.message}`);
      const prefix = ui.liveLog.textContent ? '\n' : '';
      ui.liveLog.textContent += prefix + lines.join('\n');
      ui.liveLog.scrollTop = ui.liveLog.scrollHeight;
    }

    function clearLogs() {
      ui.liveLog.textContent = '';
    }

    function renderDashboardCards(cards) {
      if (!cards || cards.length === 0) {
        ui.dashboardAccountCards.innerHTML = '<div class="muted">No hay cuentas activas configuradas.</div>';
        return;
      }
      ui.dashboardAccountCards.innerHTML = cards.map(card => {
        const totalDone = Number(card.completed) + Number(card.failed) + Number(card.skipped);
        const percent = card.total > 0 ? Math.round((totalDone / card.total) * 100) : 0;
        return `
          <div class="account-card">
            <h4>${card.name} (${Number(card.speed).toFixed(1)}x)</h4>
            <div class="muted">Actual: ${card.current_video || 'esperando'}</div>
            <div class="mini-progress"><span style="width:${percent}%;"></span></div>
            <div class="muted">${totalDone} de ${card.total} completados</div>
            <div class="muted">Estado: ${card.status}</div>
          </div>
        `;
      }).join('');
    }

    function renderSummary(summary) {
      if (!summary) {
        ui.finalSummary.classList.remove('show');
        ui.finalSummary.innerHTML = '';
        return;
      }
      const total = Number(summary.total_processed || 0);
      const success = Number(summary.success_count || 0);
      const failed = Number(summary.failed_count || 0);
      const skipped = Number(summary.skipped_count || 0);
      const successPercent = total > 0 ? ((success / total) * 100).toFixed(1) : '0.0';
      const failedItems = Array.isArray(summary.failed_items) ? summary.failed_items : [];
      const failedHtml = failedItems.length > 0
        ? failedItems.map(item => `<div class="summary-line">Fallo: ${item.video} | cuenta ${item.account_id} | ${item.error}</div>`).join('')
        : '<div class="summary-line">Sin fallas registradas</div>';

      ui.finalSummary.innerHTML = `
        <div class="summary-line">Total procesado: ${total} / ${summary.total_planned}</div>
        <div class="summary-line">Exitosas: ${success} (${successPercent}%)</div>
        <div class="summary-line">Fallidas: ${failed}</div>
        <div class="summary-line">Saltadas: ${skipped}</div>
        <div class="summary-line">Tiempo total: ${formatSeconds(summary.elapsed_seconds)}</div>
        ${failedHtml}
      `;
      ui.finalSummary.classList.add('show');
    }

    function applyProgress(data) {
      if (data.running) {
        state.waitingJobStart = false;
      }

      if (isWaitingStartupWindow(data)) {
        state.running = true;
        setStartButton('running');
        ui.currentTask.textContent = 'Preparando job...';
        return;
      }

      const percent = Number(data.progress_percent || 0);
      ui.progressFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
      ui.progressPercent.textContent = `${Math.round(percent)}%`;
      ui.progressText.textContent = `${data.done} de ${data.total} operaciones completadas`;
      ui.currentTask.textContent = data.current_task || 'Sin actividad';
      ui.timeStarted.textContent = data.start_time ? new Date(data.start_time).toLocaleTimeString() : '--:--';
      ui.timeElapsed.textContent = formatSeconds(data.elapsed_seconds);
      ui.timeRemaining.textContent = formatSeconds(data.remaining_seconds);
      renderDashboardCards(data.account_cards || []);
      if (Array.isArray(data.new_logs) && data.new_logs.length > 0) {
        appendLogs(data.new_logs);
      }
      if (data.log_cursor !== undefined) {
        state.progressCursor = Number(data.log_cursor);
      }
      if (data.running) {
        state.running = true;
        setStartButton('running');
        return;
      }
      state.waitingJobStart = false;
      state.running = false;
      if (data.summary) {
        state.lastSummary = data.summary;
        renderSummary(data.summary);
        if (Number(data.summary.failed_count || 0) > 0) {
          setStartButton('retry');
        } else {
          setStartButton('idle');
        }
      } else {
        setStartButton('idle');
      }
    }

    async function pollProgress() {
      const data = await api(`/progress?since=${state.progressCursor}`);
      applyProgress(data);
      if (!data.running && !state.waitingJobStart && state.pollingTimer) {
        clearInterval(state.pollingTimer);
        state.pollingTimer = null;
      }
    }

    function ensurePolling() {
      if (state.pollingTimer) {
        return;
      }
      state.pollingTimer = setInterval(async () => {
        try {
          await pollProgress();
        } catch (error) {
          ui.apiStatus.textContent = `API: ${error.message}`;
        }
      }, 2000);
    }

    function stopPolling() {
      if (!state.pollingTimer) {
        return;
      }
      clearInterval(state.pollingTimer);
      state.pollingTimer = null;
    }

    function buildStatusBadge(status) {
      const normalized = String(status || '').toLowerCase();
      return `<span class="badge ${normalized}">${normalized}</span>`;
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    async function loadAccounts() {
      const accounts = await api('/accounts');
      state.accounts = accounts;
      ui.accountsList.innerHTML = accounts.length === 0
        ? '<div class="muted">No hay cuentas registradas.</div>'
        : accounts.map(account => {
            const checked = account.active ? 'checked' : '';
            const primaryChecked = account.is_primary ? 'checked' : '';
            const safeName = escapeHtml(account.name);
            const safeProfile = escapeHtml(account.chrome_profile);
            const safeUserData = escapeHtml(account.chrome_user_data_dir);
            const tipo = account.is_primary ? 'Principal' : 'Secundaria';
            return `
              <div class="account-row">
                <div class="account-row-top">
                  <div>
                    <p class="account-name">${safeName}</p>
                    <p class="account-meta">Tipo: ${tipo} | Perfil: ${safeProfile} | Subidas exitosas: ${account.success_uploads}</p>
                    <p class="account-meta" title="${safeUserData}">User Data: ${safeUserData}</p>
                  </div>
                  <div class="row-actions">
                    <button class="btn danger" data-delete-account="${account.id}">Eliminar</button>
                  </div>
                </div>
                <div class="form-grid" style="margin: 0;">
                  <div class="field">
                    <label>Nombre</label>
                    <input type="text" data-name-account="${account.id}" value="${safeName}" />
                  </div>
                  <div class="field">
                    <label>Perfil de Chrome</label>
                    <input type="text" data-profile-account="${account.id}" value="${safeProfile}" />
                  </div>
                  <div class="field">
                    <label>Ruta User Data</label>
                    <input type="text" data-userdata-account="${account.id}" value="${safeUserData}" title="${safeUserData}" />
                  </div>
                  <div class="field">
                    <label>Velocidad</label>
                    <input type="number" min="1.0" max="1.3" step="0.1" data-speed-account="${account.id}" value="${Number(account.speed).toFixed(1)}" />
                  </div>
                  <div class="field">
                    <label>Activo</label>
                    <div class="toggle">
                      <input type="checkbox" data-active-account="${account.id}" ${checked} />
                      <span>${account.active ? 'Activa' : 'Inactiva'}</span>
                    </div>
                  </div>
                  <div class="field">
                    <label>Cuenta principal</label>
                    <div class="toggle">
                      <input type="checkbox" data-primary-account="${account.id}" ${primaryChecked} />
                      <span>${account.is_primary ? 'Principal' : 'Secundaria'}</span>
                    </div>
                  </div>
                  <div class="row-actions" style="align-self:end;">
                    <button class="btn primary" data-save-account="${account.id}">Guardar Cambios</button>
                  </div>
                </div>
              </div>
            `;
          }).join('');

      ui.historyAccountFilter.innerHTML = '<option value="">Todas las cuentas</option>' + accounts.map(account => `<option value="${account.id}">${account.name}</option>`).join('');
      if (!state.running) {
        renderDashboardCards(accounts.map(account => ({
          account_id: account.id,
          name: account.name,
          speed: account.speed,
          total: 0,
          completed: 0,
          failed: 0,
          skipped: 0,
          current_video: '',
          status: 'pendiente'
        })));
      }
    }

    async function saveAccount(accountId, buttonEl = null) {
      const nameInput = document.querySelector(`[data-name-account="${accountId}"]`);
      const profileInput = document.querySelector(`[data-profile-account="${accountId}"]`);
      const userDataInput = document.querySelector(`[data-userdata-account="${accountId}"]`);
      const speedInput = document.querySelector(`[data-speed-account="${accountId}"]`);
      const activeInput = document.querySelector(`[data-active-account="${accountId}"]`);
      const primaryInput = document.querySelector(`[data-primary-account="${accountId}"]`);

      const name = nameInput.value.trim();
      const chromeProfile = profileInput.value.trim();
      const chromeUserDataDir = userDataInput.value.trim();
      const speed = Number(speedInput.value);

      if (!name || !chromeProfile || !chromeUserDataDir) {
        throw new Error('Nombre, perfil y ruta User Data son obligatorios');
      }

      if (Number.isNaN(speed) || speed < 1.0 || speed > 1.3) {
        throw new Error('La velocidad debe estar entre 1.0 y 1.3');
      }

      const payload = {
        name,
        chrome_profile: chromeProfile,
        chrome_user_data_dir: chromeUserDataDir,
        speed,
        active: activeInput.checked,
        is_primary: primaryInput.checked
      };

      let originalText = '';
      if (buttonEl) {
        originalText = buttonEl.textContent;
        buttonEl.disabled = true;
        buttonEl.textContent = 'Guardando...';
      }

      await api(`/accounts/${accountId}`, { method: 'PUT', body: payload });

      if (buttonEl) {
        buttonEl.textContent = 'Guardado';
        setTimeout(() => {
          buttonEl.textContent = originalText || 'Guardar Cambios';
          buttonEl.disabled = false;
        }, 900);
      }

      await loadAccounts();
    }

    async function deleteAccount(accountId) {
      const confirmed = confirm('Esta accion eliminara la cuenta y su historial. Deseas continuar?');
      if (!confirmed) {
        return;
      }
      await api(`/accounts/${accountId}`, { method: 'DELETE' });
      await loadAccounts();
      await loadHistory();
    }

    async function addAccount(event) {
      event.preventDefault();
      const payload = {
        name: document.getElementById('accountName').value.trim(),
        chrome_user_data_dir: document.getElementById('accountUserDataDir').value.trim(),
        chrome_profile: document.getElementById('accountProfile').value.trim(),
        speed: Number(document.getElementById('accountSpeed').value),
        active: document.getElementById('accountActive').value === '1',
        is_primary: document.getElementById('accountIsPrimary').value === '1'
      };
      await api('/accounts', { method: 'POST', body: payload });
      ui.newAccountForm.reset();
      document.getElementById('accountSpeed').value = '1.0';
      document.getElementById('accountActive').value = '1';
      document.getElementById('accountIsPrimary').value = '0';
      await loadAccounts();
    }

    async function loadSettings() {
      const settings = await api('/settings');
      state.settings = settings;
      Object.keys(settingsIds).forEach(key => {
        const field = document.getElementById(settingsIds[key]);
        if (!field) {
          return;
        }
        field.value = settings[key] ?? '';
      });
    }

    async function saveSettings() {
      const payload = {};
      Object.keys(settingsIds).forEach(key => {
        const field = document.getElementById(settingsIds[key]);
        if (field) {
          payload[key] = field.value;
        }
      });
      await api('/settings', { method: 'POST', body: payload });
      ui.settingsState.textContent = 'Configuracion guardada';
      setTimeout(() => {
        ui.settingsState.textContent = '';
      }, 2000);
      await loadVideos();
    }

    async function loadVideos() {
      const data = await api('/videos');
      ui.videosInfo.textContent = `Videos detectados: ${data.total} | Carpeta: ${data.folder}`;
    }

    async function loadHistory() {
      const params = new URLSearchParams();
      if (ui.historyAccountFilter.value) {
        params.set('account_id', ui.historyAccountFilter.value);
      }
      if (ui.historyStartDate.value) {
        params.set('start_date', ui.historyStartDate.value);
      }
      if (ui.historyEndDate.value) {
        params.set('end_date', ui.historyEndDate.value);
      }
      params.set('limit', ui.historyLimit.value || '200');

      const rows = await api(`/history?${params.toString()}`);
      if (!rows || rows.length === 0) {
        ui.historyRows.innerHTML = '<tr><td colspan="6" class="muted">Sin registros</td></tr>';
        return;
      }

      ui.historyRows.innerHTML = rows.map(row => {
        const date = row.uploaded_at ? new Date(row.uploaded_at).toLocaleString() : '-';
        const error = row.error_message || '-';
        return `
          <tr>
            <td>${date}</td>
            <td>${row.account_name}</td>
            <td>${row.video_filename}</td>
            <td>${buildStatusBadge(row.status)}</td>
            <td>${row.duration_seconds}</td>
            <td>${error}</td>
          </tr>
        `;
      }).join('');
    }

    async function startUpload() {
      if (state.running) {
        return;
      }
      if (state.lastSummary && Number(state.lastSummary.failed_count || 0) > 0) {
        const ok = confirm(`Hay ${state.lastSummary.failed_count} fallidas del proceso anterior. Deseas iniciar un nuevo proceso?`);
        if (!ok) {
          return;
        }
      }
      clearLogs();
      renderSummary(null);
      state.progressCursor = 0;
      state.waitingJobStart = true;
      state.uploadRequestedAt = Date.now();
      state.running = true;
      setStartButton('running');
      const data = await api('/upload', { method: 'POST' });
      appendLogs([{ timestamp: new Date().toLocaleTimeString(), level: 'INFO', message: `Job iniciado: ${data.total_operations} operaciones` }]);
      ensurePolling();
      await pollProgress();
    }

    async function stopUpload() {
      await api('/stop', { method: 'POST' });
      appendLogs([{ timestamp: new Date().toLocaleTimeString(), level: 'WARN', message: 'Solicitud de detencion enviada' }]);
    }

    function setupTabs() {
      ui.tabs.forEach(tab => {
        tab.addEventListener('click', () => {
          ui.tabs.forEach(item => item.classList.remove('active'));
          ui.panels.forEach(panel => panel.classList.remove('active'));
          tab.classList.add('active');
          const target = tab.dataset.tab;
          document.getElementById(target).classList.add('active');
        });
      });
    }

    function setupEvents() {
      ui.startBtn.addEventListener('click', async () => {
        try {
          await startUpload();
        } catch (error) {
          state.waitingJobStart = false;
          state.running = false;
          alert(error.message);
          setStartButton('idle');
        }
      });

      ui.stopBtn.addEventListener('click', async () => {
        try {
          await stopUpload();
        } catch (error) {
          alert(error.message);
        }
      });

      ui.refreshAccountsBtn.addEventListener('click', async () => {
        try {
          await loadAccounts();
        } catch (error) {
          alert(error.message);
        }
      });

      ui.newAccountForm.addEventListener('submit', async event => {
        try {
          await addAccount(event);
        } catch (error) {
          alert(error.message);
        }
      });

      ui.accountsList.addEventListener('click', async event => {
        const target = event.target;
        const saveId = target.getAttribute('data-save-account');
        const deleteId = target.getAttribute('data-delete-account');
        try {
          if (saveId) {
            await saveAccount(Number(saveId), target);
          }
          if (deleteId) {
            await deleteAccount(Number(deleteId));
          }
        } catch (error) {
          alert(error.message);
        }
      });

      ui.saveSettingsBtn.addEventListener('click', async () => {
        try {
          await saveSettings();
        } catch (error) {
          alert(error.message);
        }
      });

      ui.loadHistoryBtn.addEventListener('click', async () => {
        try {
          await loadHistory();
        } catch (error) {
          alert(error.message);
        }
      });
    }

    async function refreshHealth() {
      try {
        await api('/health');
        ui.apiStatus.textContent = 'API: conectada';
      } catch (error) {
        ui.apiStatus.textContent = `API: ${error.message}`;
      }
    }

    async function bootstrap() {
      setupTabs();
      setupEvents();
      setStartButton('idle');

      try {
        await refreshHealth();
        await loadSettings();
        await loadAccounts();
        await loadVideos();
        await loadHistory();
        const progress = await api('/progress?since=0');
        applyProgress(progress);
        if (progress.running) {
          ensurePolling();
        }
      } catch (error) {
        ui.apiStatus.textContent = `API: ${error.message}`;
      }
    }

    bootstrap();
    window.addEventListener('beforeunload', () => stopPolling());
  
