/* ============================================================
   CORE STATE & HELPERS
============================================================ */

const $ = (id) => document.getElementById(id);
const log = (msg) => {
  const el = $("appLog");
  if (el) {
    el.textContent += `[${new Date().toLocaleTimeString()}] ${msg}\n`;
    el.scrollTop = el.scrollHeight;
  }
};

const scanLog = (msg) => {
  const el = $("scanLog");
  if (el) {
    el.textContent += `[${new Date().toLocaleTimeString()}] ${msg}\n`;
    el.scrollTop = el.scrollHeight;
  }
};

// Global state
let currentProfile = null;
let currentExpectations = [];
let currentScanResults = [];
let currentResolveItem = null;
let currentScanTargetTaskId = null;

// Scan panel DOM home (so we can move it inline under a month/KPA and restore safely)
let scanPanelHome = null;

function rememberScanPanelHome() {
  if (scanPanelHome) return;
  const section = $("scanEvidenceSection");
  if (!section || !section.parentNode) return;
  scanPanelHome = {
    parent: section.parentNode,
    nextSibling: section.nextSibling
  };
}

function restoreScanPanelHome({ hide = true } = {}) {
  const section = $("scanEvidenceSection");
  if (!section || !scanPanelHome?.parent) return;

  const { parent, nextSibling } = scanPanelHome;
  if (nextSibling && nextSibling.parentNode === parent) {
    parent.insertBefore(section, nextSibling);
  } else {
    parent.appendChild(section);
  }

  if (hide) section.style.display = "none";
}

function attachScanPanelTo(hostEl) {
  const section = $("scanEvidenceSection");
  if (!section || !hostEl) return;
  rememberScanPanelHome();
  hostEl.appendChild(section);
  section.style.display = "block";
}

function clearTargetedScanState() {
  currentScanTargetTaskId = null;
  const targetInput = $("scanTargetTaskId");
  if (targetInput) targetInput.value = "";
  const targetLabel = $("scanTargetTaskLabel");
  if (targetLabel) targetLabel.style.display = "none";
}

/* ============================================================
   VAMP AGENT CONTROL — VIDEO STATE MANAGEMENT
============================================================ */

const vampVideo = $("vamp-video");
const vampBubbles = $("vamp-bubbles");
const vampInput = $("ask-vamp-input");
const vampBtn = $("ask-vamp-btn");
const vampOverlay = $("vampThinking");
const vampOverlayText = $("vampThinkingText");

// Video States
const VAMP_STATE = {
  IDLE: 'idle',
  BUSY: 'busy',
  SPEAKING: 'speaking'
};

let currentVampState = VAMP_STATE.IDLE;

function vampIdle(text = "Awaiting instruction…") {
  currentVampState = VAMP_STATE.IDLE;
  if (vampVideo) {
    vampVideo.pause();
    vampVideo.currentTime = 0;
  }
  hideVampOverlay();
  pushBubble(text, "idle");
}

function vampBusy(text = "Analysing…") {
  currentVampState = VAMP_STATE.BUSY;
  if (vampVideo) {
    vampVideo.pause();
    vampVideo.currentTime = 0;
  }
  showVampOverlay(text);
}

function vampSpeak(text) {
  currentVampState = VAMP_STATE.SPEAKING;
  if (vampVideo) {
    vampVideo.loop = true;
    vampVideo.currentTime = 0;
    vampVideo.play().catch(() => {});
  }
  hideVampOverlay();
  pushBubble(text, "speak");
  
  // Auto-return to idle after speaking (simulate reading time)
  setTimeout(() => {
    if (currentVampState === VAMP_STATE.SPEAKING) {
      vampIdle();
    }
  }, 3000 + (text.length * 30)); // ~30ms per character
}

function showVampOverlay(text) {
  if (vampOverlay) {
    vampOverlay.style.display = 'flex';
    if (vampOverlayText) {
      vampOverlayText.textContent = text;
    }
  }
}

function hideVampOverlay() {
  if (vampOverlay) {
    vampOverlay.style.display = 'none';
  }
}

function pushBubble(text, mode = "speak") {
  if (!vampBubbles) return;
  const div = document.createElement("div");
  div.className = "vamp-bubble " + mode;
  div.textContent = text;
  vampBubbles.appendChild(div);
  vampBubbles.scrollTop = vampBubbles.scrollHeight;
  
  // Limit bubble count
  while (vampBubbles.children.length > 10) {
    vampBubbles.removeChild(vampBubbles.firstChild);
  }
}

/* ============================================================
   ASK VAMP — AI INTERACTION SURFACE
============================================================ */

if (vampBtn) {
  vampBtn.addEventListener("click", async () => {
    const q = vampInput.value.trim();
    if (!q) return;

    pushBubble(q, "user");
    vampInput.value = "";

    vampBusy("Consulting the archives…");

    try {
      const res = await fetch("/api/vamp/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          context: collectContext()
        })
      });

      if (!res.ok) throw new Error("VAMP unavailable");

      const data = await res.json();
      vampSpeak(data.answer || "I have nothing further to add.");
      log(`Ask-VAMP: ${q.substring(0, 50)}...`);
    } catch (e) {
      vampSpeak(
        "I am unable to reach my cognitive core. Please ensure Ollama is running."
      );
      log("Ask-VAMP error: " + e.message);
    }
  });
}

// Allow Enter to submit (Shift+Enter for newline)
if (vampInput) {
  vampInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      vampBtn?.click();
    }
  });
}

/* ============================================================
   CONTEXT GATHERING (SAFE, NON-INTRUSIVE)
============================================================ */

function collectContext() {
  return {
    staff_id: $("staffId")?.value || null,
    cycle_year: $("cycleYear")?.value || null,
    stage: $("stagePill")?.textContent || null,
    scan_month: $("scanMonth")?.value || null,
    current_tab: document.querySelector(".tab.active")?.dataset.tab || null,
    expectations_count: currentExpectations.length,
    scan_results_count: currentScanResults.length
  };
}

/* ============================================================
   TAB NAVIGATION (UNCHANGED BEHAVIOUR)
============================================================ */

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));

    tab.classList.add("active");
    const target = "tab-" + tab.dataset.tab;
    const panel = document.getElementById(target);
    if (panel) panel.classList.add("active");
    
    log(`Switched to: ${tab.textContent}`);
  });
});

/* ============================================================
   ENROLMENT FLOW (PRESERVED)
============================================================ */

$("enrolBtn")?.addEventListener("click", async () => {
  vampBusy("Registering your academic identity…");

  const profile = {
    staff_id: $("staffId").value,
    cycle_year: $("cycleYear").value,
    name: $("name").value,
    position: $("position").value,
    faculty: $("faculty").value,
    manager: $("manager").value
  };

  try {
    const res = await fetch("/api/profile/enrol", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile)
    });

    if (res.ok) {
      currentProfile = profile;
      $("chipProfile").textContent = "Profile ✓";
      $("chipProfile").classList.remove("bad");
      $("chipProfile").classList.add("ok");
      $("profilePill").textContent = "Profile loaded";
      $("profilePill").classList.remove("bad");
      $("profilePill").classList.add("ok");
      $("stagePill").textContent = "Stage: Profile loaded";
      vampSpeak("Your profile is set. Upload your Task Agreement when ready.");
      log(`Enrolled: ${profile.name} (${profile.staff_id})`);
    } else {
      vampSpeak("Enrolment failed. Please review your details.");
      log("Enrolment failed: " + (await res.text()));
    }
  } catch (e) {
    vampSpeak("Cannot reach the server. Please ensure it is running.");
    log("Enrolment error: " + e.message);
  }
});

/* ============================================================
   TASK AGREEMENT IMPORT
============================================================ */

$("taUploadBtn")?.addEventListener("click", async () => {
  const f = $("taFile").files[0];
  if (!f) {
    vampSpeak("Please select a Task Agreement file first.");
    return;
  }

  vampBusy("Reading your Task Agreement…");

  const fd = new FormData();
  fd.append("file", f);
  fd.append("staff_id", $("staffId").value);
  fd.append("cycle_year", $("cycleYear").value);

  try {
    const res = await fetch("/api/ta/import", { method: "POST", body: fd });

    if (res.ok) {
      const data = await res.json();
      $("chipTA").textContent = "TA ✓";
      $("chipTA").classList.remove("bad");
      $("chipTA").classList.add("ok");
      $("taPill").textContent = "TA imported";
      $("taPill").classList.remove("bad");
      $("taPill").classList.add("ok");
      $("stagePill").textContent = "Stage: TA imported";
      const tasksCount = data.tasks_count || 0;
      vampSpeak(`Your agreed work has been fully understood. ${tasksCount} tasks extracted.`);
      log(`TA imported: ${tasksCount} tasks found`);
      
      // Auto-load expectations
      setTimeout(() => loadExpectations(), 500);
      
      // If less than 10 tasks, something went wrong - try rebuild
      if (tasksCount < 10) {
        log("Warning: Low task count. Attempting rebuild...");
        setTimeout(() => $("rebuildExpBtn")?.click(), 1000);
      }
    } else {
      vampSpeak("I could not interpret the Task Agreement.");
      log("TA import failed: " + (await res.text()));
    }
  } catch (e) {
    vampSpeak("Upload failed. Check your connection.");
    log("TA upload error: " + e.message);
  }
});

/* ============================================================
   EXPECTATIONS TAB — TABLE RENDERING
============================================================ */

// Global task completion map
let taskCompletionMap = {};

async function loadExpectations() {
  vampBusy("Loading expectations…");
  
  try {
    const res = await fetch(`/api/expectations?staff_id=${$("staffId").value}&year=${$("cycleYear").value}`);
    
    if (!res.ok) throw new Error("Failed to load expectations");
    
    const data = await res.json();
    console.log("Expectations data received:", data);
    
    // Use tasks array from the response
    const tasks = data.tasks || data.expectations || [];
    currentExpectations = tasks;
    
    console.log("Tasks count:", tasks.length);
    console.log("By month keys:", Object.keys(data.by_month || {}));
    console.log("KPA summary:", data.kpa_summary);
    
    // Load progress/completion status
    await loadProgress();
    
    renderMonthlyExpectations(data.by_month || {}, tasks);
    renderPAExpectationsTable(tasks);
    
    $("chipExp").textContent = "Expectations ✓";
    $("chipExp").classList.remove("bad");
    $("chipExp").classList.add("ok");
    
    const kpaCount = Object.keys(data.kpa_summary || {}).length;
    const completedCount = Object.keys(taskCompletionMap).length;
    vampSpeak(`Loaded ${tasks.length} tasks across ${kpaCount} KPAs. ${completedCount} tasks completed.`);
    log(`Expectations loaded: ${tasks.length} tasks, ${kpaCount} KPAs, ${completedCount} completed`);
  } catch (e) {
    vampSpeak("Could not load expectations. Import a Task Agreement first.");
    log("Expectations error: " + e.message);
    console.error("Expectations error:", e);
  }
}

async function loadProgress() {
  try {
    const res = await fetch(`/api/progress?staff_id=${$("staffId").value}&year=${$("cycleYear").value}`);
    if (res.ok) {
      const progressData = await res.json();
      taskCompletionMap = progressData.task_completion || {};
      console.log("Progress loaded:", progressData.stats);
    }
  } catch (e) {
    console.warn("Could not load progress:", e);
    taskCompletionMap = {};
  }
}

function renderMonthlyExpectations(byMonth, allTasks) {
  const container = $("monthlyExpectationsContainer");
  const monthSelect = $("currentMonthSelect");
  if (!container || !monthSelect) return;
  
  if (Object.keys(byMonth).length === 0) {
    container.innerHTML = '<div class="muted" style="text-align:center;padding:20px;">Import a Task Agreement to see monthly expectations.</div>';
    return;
  }
  
  // Store for later use
  window.currentByMonth = byMonth;
  window.currentAllTasks = allTasks;
  
  // Initial render for current month
  renderMonthView(monthSelect.value);
  
  // Update when month changes
  monthSelect.addEventListener("change", () => {
    renderMonthView(monthSelect.value);
  });
}

function renderMonthView(monthKey) {
  const container = $("monthlyExpectationsContainer");
  if (!container || !window.currentByMonth) return;

  // If the scan panel was previously moved inside the month container,
  // restore it before wiping the container to avoid losing it.
  restoreScanPanelHome({ hide: true });
  
  container.innerHTML = "";
  
  const tasks = window.currentByMonth[monthKey] || [];
  
  if (tasks.length === 0) {
    container.innerHTML = `<div class="muted" style="text-align:center;padding:20px;">No expectations for this month.</div>`;
    return;
  }
  
  // Group tasks by KPA
  const kpaGroups = {};
  tasks.forEach(task => {
    const code = task.kpa_code || 'KPA1';
    if (!kpaGroups[code]) {
      kpaGroups[code] = {
        code: code,
        name: task.kpa_name || code,
        tasks: []
      };
    }
    kpaGroups[code].tasks.push(task);
  });
  
  // Render each KPA section
  const monthName = new Date(monthKey + "-01").toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  
  const headerDiv = document.createElement("div");
  headerDiv.style.cssText = "margin-bottom:16px;padding:12px;background:var(--panel);border-radius:8px;";
  headerDiv.innerHTML = `
    <h3 style="margin:0;color:var(--purple);">${monthName} Expectations</h3>
    <div style="color:var(--grey-muted);font-size:12px;margin-top:4px;">
      ${tasks.length} tasks across ${Object.keys(kpaGroups).length} KPAs
    </div>
  `;
  container.appendChild(headerDiv);
  
  // Sort KPAs by code
  const sortedKPAs = Object.entries(kpaGroups).sort((a, b) => a[0].localeCompare(b[0]));
  
  sortedKPAs.forEach(([code, kpaData]) => {
    const kpaSection = document.createElement("div");
    kpaSection.style.cssText = "margin-bottom:16px;border:1px solid var(--grey-dim);border-radius:8px;overflow:hidden;";
    
    // KPA Header
    const kpaHeader = document.createElement("div");
    kpaHeader.style.cssText = "background:var(--purple);color:white;padding:12px 16px;font-weight:bold;";
    kpaHeader.innerHTML = `${code}: ${kpaData.name}`;

    // Host container where the scan panel can be moved inline for this KPA
    const scanHost = document.createElement("div");
    scanHost.id = `scanHost-${monthKey}-${code}`;
    scanHost.dataset.month = monthKey;
    scanHost.dataset.kpa = code;
    scanHost.style.cssText = "padding:12px;background:var(--panel-dark);";
    
    // Tasks for this KPA
    const tasksList = document.createElement("div");
    tasksList.style.cssText = "padding:12px;background:var(--panel-dark);";
    
    kpaData.tasks.forEach(task => {
      const taskItem = document.createElement("div");
      taskItem.style.cssText = "display:flex;align-items:flex-start;padding:10px;margin-bottom:8px;background:var(--panel);border-radius:4px;border-left:3px solid var(--purple);";
      
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.id = `task-${task.id}`;
      checkbox.style.cssText = "margin-right:12px;margin-top:4px;";
      checkbox.dataset.taskId = task.id;
      checkbox.checked = !!taskCompletionMap[task.id];
      checkbox.disabled = true;
      
      const label = document.createElement("label");
      label.htmlFor = `task-${task.id}`;
      label.style.cssText = "flex:1;cursor:pointer;";

      const outputsText = (task.outputs || task.output || "").toString().trim();
      const whatToDoText = (task.what_to_do || task.description || "").toString().trim();
      const evidenceReqText = (task.evidence_required || "").toString().trim();
      const hintsArr = Array.isArray(task.evidence_hints) ? task.evidence_hints : [];
      const hintsText = hintsArr.length ? hintsArr.join(", ") : "";

      label.innerHTML = `
        <div style="font-weight:bold;margin-bottom:4px;">${task.title}</div>
        <div style="font-size:11px;color:var(--grey-muted);">
          <span style="margin-right:12px;">📅 ${task.cadence}</span>
          <span style="margin-right:12px;">🎯 Required: ${task.minimum_count}</span>
          <span>⭐ Stretch: ${task.stretch_count}</span>
        </div>
        ${whatToDoText ? `<div style="font-size:11px;color:var(--grey-dim);margin-top:6px;"><strong>What to do:</strong> ${whatToDoText}</div>` : ''}
        ${outputsText ? `<div style="font-size:11px;color:var(--grey-dim);margin-top:6px;"><strong>Activity / output:</strong> ${outputsText}</div>` : ''}
        ${evidenceReqText ? `<div style="font-size:11px;color:var(--grey-dim);margin-top:4px;"><strong>Evidence required:</strong> ${evidenceReqText}</div>` : ''}
        ${hintsText ? `<div style="font-size:11px;color:var(--grey-dim);margin-top:4px;"><strong>Evidence examples:</strong> ${hintsText}</div>` : ''}
      `;
      
      const aiBtn = document.createElement("button");
      aiBtn.className = "btn-small";
      aiBtn.textContent = "🤖 AI";
      aiBtn.onclick = () => openAIGuidance(task.id);

      const scanBtn = document.createElement("button");
      scanBtn.className = "btn-small";
      scanBtn.textContent = "📎 Scan";
      scanBtn.style.marginLeft = "8px";
      scanBtn.onclick = () => {
        currentScanTargetTaskId = task.id;
        const targetInput = $("scanTargetTaskId");
        if (targetInput) targetInput.value = task.id;

        const targetLabel = $("scanTargetTaskLabel");
        const targetText = $("scanTargetTaskText");
        if (targetText) targetText.textContent = task.title;
        if (targetLabel) targetLabel.style.display = "block";

        const scanMonth = $("scanMonth");
        if (scanMonth) scanMonth.value = monthKey;

        // Move scan panel inline under this KPA section
        attachScanPanelTo(scanHost);
        vampSpeak("Upload evidence for the selected task.");
      };
      
      taskItem.appendChild(checkbox);
      taskItem.appendChild(label);
      taskItem.appendChild(aiBtn);
      taskItem.appendChild(scanBtn);
      
      tasksList.appendChild(taskItem);
    });
    
    kpaSection.appendChild(kpaHeader);
    kpaSection.appendChild(scanHost);
    kpaSection.appendChild(tasksList);
    container.appendChild(kpaSection);
  });
}

function renderPAExpectationsTable(tasks) {
  const tbody = $("paExpectationsTableBody");
  if (!tbody) return;
  
  tbody.innerHTML = "";
  
  if (tasks.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="no-data">No expectations loaded. Import Task Agreement first.</td></tr>';
    return;
  }
  
  tasks.forEach(task => {
    const row = document.createElement("tr");
    const months = (task.months || []).join(", ");
    const hints = (task.evidence_hints || []).join(", ");
    const outputs = task.outputs || "N/A";
    
    row.innerHTML = `
      <td>${task.kpa_code || 'N/A'}</td>
      <td>${task.title || 'N/A'}</td>
      <td>${months}</td>
      <td>${task.cadence || 'N/A'}</td>
      <td>${task.minimum_count || 0}</td>
      <td>${task.stretch_count || 0}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">${outputs}</td>
      <td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;">${hints}</td>
    `;
    
    tbody.appendChild(row);
  });
}

$("rebuildExpBtn")?.addEventListener("click", async () => {
  vampBusy("Rebuilding expectations from contract...");
  
  try {
    const res = await fetch("/api/expectations/rebuild", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        staff_id: $("staffId").value,
        year: $("cycleYear").value
      })
    });
    
    if (!res.ok) throw new Error("Rebuild failed");
    
    const data = await res.json();
    vampSpeak(`Rebuilt ${data.tasks_count} tasks across ${data.kpas_count} KPAs.`);
    log(`Expectations rebuilt: ${data.tasks_count} tasks`);
    
    // Reload expectations
    setTimeout(() => loadExpectations(), 500);
  } catch (e) {
    vampSpeak("Could not rebuild expectations.");
    log("Rebuild error: " + e.message);
    console.error("Rebuild error:", e);
  }
});

$("checkMonthStatusBtn")?.addEventListener("click", () => checkMonthStatus());

async function checkMonthStatus() {
  const monthKey = $("currentMonthSelect").value;
  const staffId = $("staffId").value;
  
  vampBusy("Analyzing month completion status…");
  
  try {
    const res = await fetch("/api/expectations/check-month", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        staff_id: staffId,
        month: monthKey
      })
    });
    
    if (!res.ok) throw new Error("Month check failed");
    
    const data = await res.json();
    
    const statusPill = $("monthStatusPill");
    const reviewBox = $("monthReviewBox");
    
    if (data.complete) {
      statusPill.textContent = "Complete ✓";
      statusPill.className = "pill ok";
      reviewBox.innerHTML = `
        <div style="color:#8ff0b2;font-weight:bold;margin-bottom:8px;">✓ Month Complete</div>
        <div>${data.message || 'All expectations for this month have been met.'}</div>
        <div style="margin-top:12px;padding:12px;background:var(--panel);border-radius:4px;">
          <strong>Summary:</strong><br/>
          ${data.summary || 'Evidence uploaded meets or exceeds minimum requirements.'}
        </div>
      `;
      vampSpeak(`${monthKey} is complete! All expectations met.`);
    } else {
      statusPill.textContent = "Incomplete ⚠️";
      statusPill.className = "pill bad";
      reviewBox.innerHTML = `
        <div style="color:#ff6b9d;font-weight:bold;margin-bottom:8px;">⚠️ Month Incomplete</div>
        <div>${data.message || 'Some expectations are not yet met.'}</div>
        <div style="margin-top:12px;padding:12px;background:var(--panel);border-radius:4px;">
          <strong>Missing:</strong><br/>
          ${data.missing || 'Upload more evidence to meet minimum requirements.'}
        </div>
      `;
      vampSpeak("This month needs more evidence to meet expectations.");
    }
    
    log(`Month ${monthKey} status: ${data.complete ? 'Complete' : 'Incomplete'}`);
  } catch (e) {
    vampSpeak("Could not check month status.");
    log("Month check error: " + e.message);
  }
}

/* ============================================================
   SCAN FLOW — FILE UPLOAD & AI CLASSIFICATION
============================================================ */

$("scanUploadBtn")?.addEventListener("click", async () => {
  const files = $("scanFiles").files;
  if (files.length === 0) {
    vampSpeak("Please select files to scan.");
    return;
  }
  
  vampBusy(`Scanning ${files.length} files…`);
  $("scanStatus").textContent = "Scanning…";
  scanLog(`Starting scan of ${files.length} files...`);
  
  const fd = new FormData();
  for (let i = 0; i < files.length; i++) {
    fd.append("files", files[i]);
  }
  fd.append("staff_id", $("staffId").value);
  fd.append("month", $("scanMonth").value);
  fd.append("use_brain", $("scanUseBrain").checked);
  fd.append("use_contextual", $("scanUseContextual").checked);

  const targetTaskId = $("scanTargetTaskId")?.value;
  if (targetTaskId) {
    fd.append("target_task_id", targetTaskId);
  }
  
  try {
    const res = await fetch("/api/scan/upload", {
      method: "POST",
      body: fd
    });
    
    if (!res.ok) throw new Error("Scan failed");
    
    const data = await res.json();
    currentScanResults = data.results || [];
    
    renderScanResults(currentScanResults);
    
    $("scanStatus").textContent = "Complete";
    $("scanProgress").textContent = `${currentScanResults.length} items scanned`;
    
    vampSpeak(`Scan complete. ${currentScanResults.length} items classified.`);
    scanLog(`Scan complete: ${currentScanResults.length} items processed`);
    log(`Scan complete: ${files.length} files → ${currentScanResults.length} evidence items`);
    
    // Count how many tasks were mapped
    const mappedCount = currentScanResults.reduce((sum, r) => sum + (r.mapped_tasks || 0), 0);
    if (mappedCount > 0) {
      vampSpeak(`${mappedCount} task mappings created. Refreshing expectations...`);
      // Reload progress and expectations to show updated checkboxes
      setTimeout(() => loadExpectations(), 1000);
    }
    
    // Auto-refresh evidence log
    loadEvidenceLog();
    
    // Close + restore scan section after successful scan
    restoreScanPanelHome({ hide: true });
    clearTargetedScanState();
  } catch (e) {
    vampSpeak("Scan failed. Please check the server logs.");
    $("scanStatus").textContent = "Error";
    scanLog(`Error: ${e.message}`);
    log("Scan error: " + e.message);
  }
});

function renderScanResults(results) {
  const tbody = $("scanResultsTableBody");
  if (!tbody) return;
  
  tbody.innerHTML = "";
  
  if (results.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="no-data">No scans performed yet. Upload files to begin.</td></tr>';
    return;
  }
  
  results.forEach((item, idx) => {
    const row = document.createElement("tr");
    
    const confidence = item.confidence || 0;
    const confidenceClass = confidence >= 0.7 ? 'confidence-high' : confidence >= 0.5 ? 'confidence-medium' : 'confidence-low';
    const needsResolve = confidence < 0.6;
    
    row.innerHTML = `
      <td>${item.date || new Date().toLocaleDateString()}</td>
      <td>${item.file || 'N/A'}</td>
      <td>${item.kpa || 'Unknown'}</td>
      <td>${item.task || 'N/A'}</td>
      <td>${item.tier || 'N/A'}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">${item.impact_summary || 'N/A'}</td>
      <td class="${confidenceClass}">${(confidence * 100).toFixed(0)}%</td>
      <td>${item.status || 'Pending'}</td>
      <td>
        ${needsResolve ? `<button class="btn-small" onclick="openResolveModal(${idx})">🔧 Resolve</button>` : '<span style="color:#8ff0b2;">✓</span>'}
      </td>
    `;
    
    tbody.appendChild(row);
  });
  
  // Update insights
  const lowConfidence = results.filter(r => (r.confidence || 0) < 0.6).length;
  const insights = $("scanInsights");
  if (insights) {
    insights.innerHTML = `
      <div style="margin-bottom:8px;">✓ ${results.length} items scanned</div>
      <div style="margin-bottom:8px;">⚠️ ${lowConfidence} items need review</div>
      <div>Average confidence: ${(results.reduce((sum, r) => sum + (r.confidence || 0), 0) / results.length * 100).toFixed(1)}%</div>
    `;
  }
}

$("scanRefreshEvidenceBtn")?.addEventListener("click", () => loadEvidence());

/* ============================================================
   EVIDENCE TAB
============================================================ */

async function loadEvidence() {
  vampBusy("Loading stored evidence…");
  
  try {
    const res = await fetch(`/api/evidence?staff_id=${$("staffId").value}`);
    
    if (!res.ok) throw new Error("Failed to load evidence");
    
    const data = await res.json();
    const evidence = data.evidence || [];
    
    const container = $("evidenceTable");
    if (!container) return;
    
    if (evidence.length === 0) {
      container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--grey-dim);">No evidence stored yet. Scan files to begin.</div>';
    } else {
      container.innerHTML = `
        <div style="margin-bottom:10px;font-size:13px;color:var(--grey-muted);">
          Total evidence items: ${evidence.length}
        </div>
        <table class="vamp-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>File</th>
              <th>KPA</th>
              <th>Task</th>
              <th>Impact</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            ${evidence.map(e => {
              const conf = e.confidence || 0;
              const confClass = conf >= 0.7 ? 'confidence-high' : conf >= 0.5 ? 'confidence-medium' : 'confidence-low';
              return `
                <tr>
                  <td>${e.date || 'N/A'}</td>
                  <td>${e.file || 'N/A'}</td>
                  <td>${e.kpa || 'N/A'}</td>
                  <td>${e.task || 'N/A'}</td>
                  <td style="max-width:250px;">${e.impact || 'N/A'}</td>
                  <td class="${confClass}">${(conf * 100).toFixed(0)}%</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      `;
    }
    
    vampIdle();
    log(`Evidence loaded: ${evidence.length} items`);
  } catch (e) {
    vampSpeak("Could not load evidence.");
    log("Evidence error: " + e.message);
  }
}

$("evidenceReloadBtn")?.addEventListener("click", () => loadEvidence());

/* ============================================================
   REPORT GENERATION
============================================================ */

$("genPABtn")?.addEventListener("click", async () => {
  vampBusy("Forging your Performance Agreement…");

  try {
    const res = await fetch(`/api/report/generate?staff_id=${$("staffId").value}&year=${$("cycleYear").value}&export=true`);
    
    if (!res.ok) throw new Error("Report generation failed");
    
    const data = await res.json();

    // Render PA in table format
    renderPAReportTable(data);
    
    const reportBox = $("reportBox");
    if (reportBox) {
      reportBox.innerHTML = `
        <div class="pill ok" style="margin-bottom:10px;">✓ PA Generated: ${data.title || 'Performance Agreement'}</div>
        <div style="color:var(--grey-muted);font-size:12px;">
          ✓ ${data.rows?.length || 0} KPAs included<br/>
          ${data.excel_path ? `✓ Saved to: ${data.excel_path.split('/').pop()}` : ''}
        </div>
      `;
    }
    
    vampSpeak("Your Performance Agreement is complete.");
    log(`PA generated: ${data.rows?.length || 0} KPAs`);
  } catch (e) {
    vampSpeak("The report could not be generated.");
    log("Report error: " + e.message);
  }
});

function renderPAReportTable(paData) {
  const tbody = $("paExpectationsTableBody");
  if (!tbody) return;
  
  tbody.innerHTML = "";
  
  if (!paData.rows || paData.rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="no-data">No PA data. Import TA first.</td></tr>';
    return;
  }
  
  paData.rows.forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong style="color:var(--purple);">${row.kpa_name}</strong></td>
      <td style="white-space:pre-wrap;font-size:11px;">${row.outputs || '-'}</td>
      <td style="white-space:pre-wrap;font-size:11px;">${row.kpis || '-'}</td>
      <td>${row.weight.toFixed(2)}%</td>
      <td>${row.hours.toFixed(1)}</td>
      <td style="white-space:pre-wrap;font-size:10px;">${row.outcomes || '-'}</td>
      <td style="text-align:center;">${row.active}</td>
    `;
    tbody.appendChild(tr);
  });
}

/* ============================================================
   MODALS — AI GUIDANCE & CLASSIFICATION RESOLUTION
============================================================ */

function openAIGuidance(taskId) {
  const modal = $("aiGuidanceModal");
  const task = currentExpectations.find(e => e.id === taskId || e.task === taskId);
  
  if (!task) {
    vampSpeak("Could not find that task.");
    return;
  }
  
  const contextDiv = $("aiTaskContext");
  if (contextDiv) {
    contextDiv.innerHTML = `
      <strong>${task.task}</strong><br/>
      KPA: ${task.kpa}<br/>
      Goal: ${task.goal}<br/>
      Weight: ${task.weight}%
    `;
  }
  
  modal?.classList.add("active");
  $("aiGuidanceInput")?.focus();
  
  log(`Opened AI guidance for: ${task.task}`);
}

function openResolveModal(resultIndex) {
  const item = currentScanResults[resultIndex];
  if (!item) return;
  
  currentResolveItem = { ...item, index: resultIndex };
  
  const modal = $("resolveModal");
  $("resolveFileName").textContent = item.file || 'Unknown file';
  $("resolveInitialClass").textContent = `AI classified as: ${item.kpa || 'Unknown'} (${(item.confidence * 100).toFixed(0)}% confidence)`;
  
  modal?.classList.add("active");
  $("resolveKpaSelect")?.focus();
  
  log(`Opened resolve modal for: ${item.file}`);
}

function closeModal(modalId) {
  const modal = $(modalId);
  modal?.classList.remove("active");
}

// AI Guidance submission
$("submitGuidanceBtn")?.addEventListener("click", async () => {
  const question = $("aiGuidanceInput")?.value.trim();
  if (!question) return;
  
  vampBusy("Consulting VAMP…");
  
  try {
    const res = await fetch("/api/ai/guidance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        context: collectContext()
      })
    });
    
    if (!res.ok) throw new Error("AI guidance failed");
    
    const data = await res.json();
    
    const responseSection = $("aiGuidanceResponse");
    const responseDiv = responseSection?.querySelector(".modal-response");
    
    if (responseDiv) {
      responseDiv.textContent = data.guidance || data.answer || "No guidance available.";
      responseSection.style.display = "block";
    }
    
    vampSpeak("I have provided guidance in the modal.");
    log("AI guidance received");
  } catch (e) {
    vampSpeak("Could not get AI guidance. Ensure Ollama is running.");
    log("AI guidance error: " + e.message);
  }
});

// Classification resolution
$("submitResolveBtn")?.addEventListener("click", async () => {
  if (!currentResolveItem) return;
  
  const kpa = $("resolveKpaSelect")?.value;
  const explanation = $("resolveExplanation")?.value.trim();
  
  if (!kpa || !explanation) {
    vampSpeak("Please select a KPA and provide an explanation.");
    return;
  }
  
  vampBusy("Saving resolved classification…");
  
  try {
    const res = await fetch("/api/evidence/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file: currentResolveItem.file,
        original_kpa: currentResolveItem.kpa,
        resolved_kpa: kpa,
        explanation,
        staff_id: $("staffId").value
      })
    });
    
    if (!res.ok) throw new Error("Resolution failed");
    
    // Update the scan results
    currentScanResults[currentResolveItem.index].kpa = kpa;
    currentScanResults[currentResolveItem.index].confidence = 1.0;
    currentScanResults[currentResolveItem.index].status = "Resolved";
    
    renderScanResults(currentScanResults);
    closeModal("resolveModal");
    
    vampSpeak("Classification resolved and saved.");
    log(`Resolved: ${currentResolveItem.file} → ${kpa}`);
    
    currentResolveItem = null;
  } catch (e) {
    vampSpeak("Could not save the resolution.");
    log("Resolution error: " + e.message);
  }
});

/* ============================================================
   SERVER-SENT EVENTS (REAL-TIME SCAN FEEDBACK)
============================================================ */

let eventSource = null;

function connectEventStream() {
  if (eventSource) return;
  
  try {
    eventSource = new EventSource("/api/scan/events");
    
    eventSource.onmessage = (e) => {
      const data = JSON.parse(e.data);
      
      if (data.type === "file_scanned") {
        scanLog(`✓ Scanned: ${data.file}`);
        $("scanProgress").textContent = `${data.current || 0} / ${data.total || 0}`;
      }
      
      if (data.type === "classification") {
        scanLog(`→ ${data.file}: ${data.kpa} (${(data.confidence * 100).toFixed(0)}%)`);
      }
      
      if (data.type === "needs_clarification") {
        vampSpeak("This evidence is unclear. Please check the scan results.");
        scanLog(`⚠️ Low confidence: ${data.file}`);
      }
      
      if (data.type === "scan_finished") {
        $("scanStatus").textContent = "Complete";
        vampSpeak("Evidence scan complete.");
        scanLog("Scan finished");
      }
      
      if (data.type === "error") {
        scanLog(`❌ Error: ${data.message}`);
      }
    };
    
    eventSource.onerror = () => {
      log("Event stream disconnected");
      eventSource = null;
    };
  } catch (e) {
    log("Could not connect event stream: " + e.message);
  }
}

/* ============================================================
   SCAN SECTION TOGGLE (IN EXPECTATIONS TAB)
============================================================ */

$("scanEvidenceBtn")?.addEventListener("click", () => {
  const section = $("scanEvidenceSection");
  if (!section) return;

  const isVisible = section.style.display !== "none";
  if (isVisible) {
    restoreScanPanelHome({ hide: true });
    clearTargetedScanState();
    return;
  }

  // Prefer showing inline under the first KPA of the currently selected month
  const monthKey = $("currentMonthSelect")?.value;
  let host = null;
  if (monthKey) {
    host = document.querySelector(`#monthlyExpectationsContainer [id^="scanHost-${monthKey}-"]`);
  }

  if (host) {
    attachScanPanelTo(host);
  } else {
    rememberScanPanelHome();
    section.style.display = "block";
  }

  vampSpeak("Upload your evidence files and I'll classify them for you.");
});

$("closeScanSection")?.addEventListener("click", () => {
  restoreScanPanelHome({ hide: true });
  clearTargetedScanState();
});

/* ============================================================
   EVIDENCE LOG WITH FILTERING
============================================================ */

async function loadEvidenceLog(monthFilter = 'all') {
  try {
    const staffId = $("staffId")?.value;
    const year = $("cycleYear")?.value;

    if (!staffId || !year) {
      vampSpeak("Please enrol your profile first.");
      return;
    }
    
    const res = await fetch(`/api/progress?staff_id=${staffId}&year=${year}`);
    if (!res.ok) throw new Error("Could not load evidence log");
    
    const data = await res.json();
    const evidence = data.evidence || [];
    
    // Filter by month if specified
    const filtered = monthFilter === 'all' 
      ? evidence 
      : evidence.filter(e => e.month === monthFilter);
    
    renderEvidenceLogTable(filtered);
    
    log(`Evidence log loaded: ${filtered.length} items${monthFilter !== 'all' ? ` for ${monthFilter}` : ''}`);
  } catch (e) {
    vampSpeak("Could not load evidence log.");
    log("Evidence log error: " + e.message);
  }
}

function renderEvidenceLogTable(evidence) {
  const tbody = $("evidenceLogTableBody");
  if (!tbody) return;
  
  tbody.innerHTML = "";
  
  if (evidence.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="no-data">No evidence logged yet. Use "Scan Evidence" in the Expectations tab.</td></tr>';
    return;
  }
  
  evidence.forEach(item => {
    const row = document.createElement("tr");
    const confidence = item.confidence || 0;
    const confidenceClass = confidence >= 0.7 ? 'confidence-high' : confidence >= 0.5 ? 'confidence-medium' : 'confidence-low';
    
    row.innerHTML = `
      <td>${item.date || item.timestamp || 'N/A'}</td>
      <td>${item.filename || item.file || 'N/A'}</td>
      <td>${item.kpa || 'Unknown'}</td>
      <td>${item.month || 'N/A'}</td>
      <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;">${item.task || item.title || 'N/A'}</td>
      <td>${item.tier || 'N/A'}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;">${item.impact_summary || item.impact || 'N/A'}</td>
      <td class="${confidenceClass}">${(confidence * 100).toFixed(0)}%</td>
    `;
    tbody.appendChild(row);
  });
}

$("evidenceReloadBtn")?.addEventListener("click", () => {
  const monthFilter = $("evidenceMonthFilter")?.value || 'all';
  loadEvidenceLog(monthFilter);
});

$("evidenceMonthFilter")?.addEventListener("change", () => {
  const monthFilter = $("evidenceMonthFilter")?.value || 'all';
  loadEvidenceLog(monthFilter);
});

/* ============================================================
   INIT
============================================================ */

document.addEventListener("DOMContentLoaded", () => {
  vampIdle();
  log("VAMP interface initialised.");
  log("System ready. Begin by enrolling your profile.");

  // Capture the scan panel's original DOM location so we can move it inline and restore safely
  rememberScanPanelHome();
  
  // Connect event stream for real-time updates
  connectEventStream();
  
  // Add keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    // Ctrl+K to focus Ask VAMP
    if (e.ctrlKey && e.key === 'k') {
      e.preventDefault();
      vampInput?.focus();
    }
    
    // Escape to close modals
    if (e.key === 'Escape') {
      closeModal('aiGuidanceModal');
      closeModal('resolveModal');
    }
  });
});
