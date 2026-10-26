/**
 * 119 AI 데이터 비서 — 바닐라 JavaScript 프론트엔드 (app.js)
 * - 프레임워크 없이 순수 DOM API & Fetch API & Canvas 2D로 구현
 * - 기능: 데이터 요약 표시, 시계열 차트 시각화, 데이터 CRUD, 대화 기록 저장/불러오기, 컨텍스트 주입 + Function Calling AI 채팅, CSV/JSON 내보내기, 다크모드 토글
 */

const state = {
  apiBaseUrl: window.APP_CONFIG.API_BASE_URL.replace(/\/+$/, ""),
  summary: null,
  statistics: null,
  dataList: [],
  conversations: [],
  currentConversationId: null,
  currentMessages: [],
  highlightedRowId: null,
  chartPointsMeta: [],
  theme: localStorage.getItem("M12_THEME") || "dark",
};

// =========================================================
// 유틸리티 함수
// =========================================================
function formatNumber(num) {
  if (num === null || num === undefined || isNaN(num)) return "-";
  return Number(num).toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMarkdown(md) {
  let html = escapeHtml(md);
  html = html.replace(/^#### (.*$)/gm, "<h4>$1</h4>");
  html = html.replace(/^### (.*$)/gm, "<h3>$1</h3>");
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/^\s*-\s+(.*$)/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>");
  html = html.replace(/<\/ul>\s*<ul>/g, "");
  html = html.replace(/\n/g, "<br/>");
  return html;
}

function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.style.borderLeftColor =
    type === "error" ? "#ef4444" : type === "info" ? "#3b82f6" : "#10b981";
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 3500);
}

async function apiFetch(path, options = {}) {
  const url = `${state.apiBaseUrl}${path}`;
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    let errDetail = `HTTP ${response.status}`;
    try {
      const errJson = await response.json();
      errDetail = errJson.detail || JSON.stringify(errJson);
    } catch (_) {}
    throw new Error(errDetail);
  }
  return response.json();
}

// =========================================================
// 1. 서버 헬스체크 & 데이터 요약(/api/data/summary) 로드
// =========================================================
async function checkServerHealth() {
  const dot = document.getElementById("server-status-dot");
  const txt = document.getElementById("server-status-text");
  try {
    const health = await apiFetch("/api/health");
    dot.className = "status-dot online";
    const dbMode = health.firestore_connected
      ? `Firestore 실시간 연동 (${health.firebase_project_id})`
      : "로컬 백업 스토리지 연동";
    txt.textContent = `백엔드 정상 연결 | ${dbMode} | 시계열 ${health.data_count}건`;
  } catch (err) {
    dot.className = "status-dot offline";
    txt.textContent = `백엔드 연결 대기 중 (${state.apiBaseUrl}) — 슬립 해제 중일 수 있습니다.`;
  }
}

async function loadSummaryAndStats() {
  try {
    const [summary, stats] = await Promise.all([
      apiFetch("/api/data/summary"),
      apiFetch("/api/data/statistics"),
    ]);
    state.summary = summary;
    state.statistics = stats;
    renderSummaryKPI(summary);
    renderSeasonalInsights(stats);
    drawTimeseriesChart(stats);
  } catch (err) {
    showToast(`요약 데이터 로드 실패: ${err.message}`, "error");
  }
}

function renderSummaryKPI(summary) {
  if (!summary || !summary.metrics) return;
  const m = summary.metrics;

  document.getElementById("kpi-period").textContent = summary.period;
  document.getElementById("kpi-count").textContent = `총 ${formatNumber(summary.count)}개 주간 시계열 포인트`;
  document.getElementById("kpi-average").textContent = `주간 평균 ${formatNumber(m.average)}건`;
  document.getElementById("kpi-total").textContent = `누적 합계: ${formatNumber(m.total)}건`;
  document.getElementById("kpi-max").textContent = `최대 ${formatNumber(m.max)}건 (${m.max_date || "-"})`;
  document.getElementById("kpi-min").textContent = `최소 ${formatNumber(m.min)}건 (${m.min_date || "-"})`;
  document.getElementById("kpi-trend").textContent = summary.trend;
  document.getElementById("kpi-volatility").textContent =
    `표준편차: ${formatNumber(m.std_dev)}건 | 변동계수(CV): ${m.cv_percent || 0}%`;

  const promptText = `당신은 데이터 분석 비서입니다.

[사용자 데이터 요약]
- 데이터 기간: ${summary.period}
- 총 레코드: ${summary.count}개
- 주요 지표: {"total": ${m.total}, "average": ${m.average}, "max": "${formatNumber(m.max)} (${m.max_date})", "min": "${formatNumber(m.min)} (${m.min_date})", "cv_percent": "${m.cv_percent}%"}
- 최근 트렌드: ${summary.trend}

위 데이터를 기반으로 맞춤형 답변을 제공하세요.`;

  document.getElementById("prompt-preview-code").textContent = promptText;
}

function renderSeasonalInsights(stats) {
  const bar = document.getElementById("seasonal-insight-bar");
  if (!stats || !stats.seasonal_statistics) return;
  const s = stats.seasonal_statistics;
  const forecast = stats.forecast_next_4_weeks || [];
  const nextWeek = forecast.length > 0 ? `${formatNumber(forecast[0].predicted_value)}건` : "-";

  const chips = [];
  for (const season of ["겨울", "봄", "여름", "가을"]) {
    if (s[season]) {
      chips.push(
        `<span class="stat-chip"><strong>${season} 평균:</strong> ${formatNumber(s[season].average)}건 (최대 ${formatNumber(s[season].max)}건)</span>`
      );
    }
  }
  chips.push(
    `<span class="stat-chip"><strong>이상치(Z≥1.5):</strong> ${stats.outliers_count || 0}회 탐지</span>`
  );
  chips.push(
    `<span class="stat-chip"><strong>다음 주 예측:</strong> ${nextWeek}</span>`
  );
  bar.innerHTML = chips.join("");
}

// =========================================================
// 2. [보너스 과제 2] 시계열 추세 & 이동평균·예측 Canvas 차트
// =========================================================
function drawTimeseriesChart(stats) {
  const canvas = document.getElementById("timeseries-chart");
  if (!canvas || !stats || !stats.series || stats.series.length === 0) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = rect.width || 740;
  const height = 240;
  canvas.width = width * dpr;
  canvas.height = height * dpr;

  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);

  const series = stats.series;
  const forecast = stats.forecast_next_4_weeks || [];
  const totalPoints = series.length + forecast.length;

  const allValues = [
    ...series.map((d) => d.value),
    ...forecast.map((f) => f.predicted_value),
  ];
  const minVal = Math.max(0, Math.min(...allValues) * 0.85);
  const maxVal = Math.max(...allValues) * 1.08;

  const padLeft = 58;
  const padRight = 20;
  const padTop = 18;
  const padBottom = 28;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const isLight = state.theme === "light";
  const gridColor = isLight ? "rgba(71, 85, 105, 0.16)" : "rgba(148, 163, 184, 0.15)";
  const axisTextColor = isLight ? "#475569" : "#94a3b8";

  const xOf = (idx) => padLeft + (idx / Math.max(1, totalPoints - 1)) * plotW;
  const yOf = (val) => padTop + plotH - ((val - minVal) / Math.max(1, maxVal - minVal)) * plotH;

  // 가로 그리드 및 Y축 레이블
  ctx.strokeStyle = gridColor;
  ctx.lineWidth = 1;
  ctx.fillStyle = axisTextColor;
  ctx.font = "11px sans-serif";
  ctx.textAlign = "right";

  for (let i = 0; i <= 4; i++) {
    const v = minVal + ((maxVal - minVal) * i) / 4;
    const y = yOf(v);
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(width - padRight, y);
    ctx.stroke();
    ctx.fillText(`${Math.round(v / 10000)}만`, padLeft - 6, y + 4);
  }

  // X축 연도/월 레이블
  ctx.textAlign = "center";
  const stepX = Math.max(1, Math.floor(series.length / 6));
  for (let i = 0; i < series.length; i += stepX) {
    const x = xOf(i);
    ctx.fillText(series[i].date.slice(0, 7), x, height - 8);
  }

  // 1) 주간 접수 건수 영역 그라데이션 & 실선
  const grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
  grad.addColorStop(0, "rgba(59, 130, 246, 0.32)");
  grad.addColorStop(1, "rgba(59, 130, 246, 0.02)");

  ctx.beginPath();
  series.forEach((pt, idx) => {
    const x = xOf(idx);
    const y = yOf(pt.value);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.lineTo(xOf(series.length - 1), padTop + plotH);
  ctx.lineTo(xOf(0), padTop + plotH);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  series.forEach((pt, idx) => {
    const x = xOf(idx);
    const y = yOf(pt.value);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = "#3b82f6";
  ctx.lineWidth = 2;
  ctx.stroke();

  // 2) 4주 이동평균선 (MA4)
  ctx.beginPath();
  series.forEach((pt, idx) => {
    const x = xOf(idx);
    const y = yOf(pt.ma4);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = "#10b981";
  ctx.lineWidth = 1.8;
  ctx.stroke();

  // 3) 향후 4주 예측 점선
  if (forecast.length > 0) {
    ctx.save();
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    const lastIdx = series.length - 1;
    ctx.moveTo(xOf(lastIdx), yOf(series[lastIdx].value));
    forecast.forEach((f, fIdx) => {
      const x = xOf(series.length + fIdx);
      const y = yOf(f.predicted_value);
      ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#a855f7";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();
  }

  // 4) 이상치 포인트 마커 & 호버 메타 저장
  state.chartPointsMeta = [];
  series.forEach((pt, idx) => {
    const x = xOf(idx);
    const y = yOf(pt.value);
    state.chartPointsMeta.push({ x, y, pt });

    if (Math.abs(pt.z_score) >= 1.5) {
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = pt.z_score > 0 ? "#ef4444" : "#f59e0b";
      ctx.fill();
    }
  });
}

function setupChartHover() {
  const canvas = document.getElementById("timeseries-chart");
  const tooltip = document.getElementById("chart-tooltip");
  if (!canvas || !tooltip) return;

  canvas.addEventListener("mousemove", (e) => {
    if (!state.chartPointsMeta.length) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;

    let closest = null;
    let minDist = Infinity;
    for (const item of state.chartPointsMeta) {
      const d = Math.abs(item.x - mx);
      if (d < minDist) {
        minDist = d;
        closest = item;
      }
    }

    if (closest && minDist <= 18) {
      const { pt } = closest;
      tooltip.classList.remove("hidden");
      tooltip.style.left = `${Math.min(rect.width - 280, Math.max(10, closest.x - 100))}px`;
      tooltip.style.top = `${Math.max(10, closest.y - 78)}px`;
      tooltip.innerHTML = `
        <div><strong>📅 ${pt.date} (${pt.season})</strong></div>
        <div>• 주간 접수: <strong>${formatNumber(pt.value)}건</strong> (4주평균: ${formatNumber(pt.ma4)}건)</div>
        <div style="color:#94a3b8; font-size:11px; margin-top:2px;">${escapeHtml(pt.memo)}</div>
      `;
    } else {
      tooltip.classList.add("hidden");
    }
  });

  canvas.addEventListener("mouseleave", () => {
    tooltip.classList.add("hidden");
  });
}

// =========================================================
// 3. 데이터 관리 (CRUD: 조회 / 추가 / 수정 / 삭제)
// =========================================================
async function loadDataList(searchQuery = "") {
  try {
    const qParam = searchQuery ? `?search=${encodeURIComponent(searchQuery)}` : "";
    const items = await apiFetch(`/api/data${qParam}`);
    state.dataList = items;
    renderDataTable(items);
  } catch (err) {
    showToast(`데이터 목록 조회 실패: ${err.message}`, "error");
  }
}

function renderDataTable(items) {
  const tbody = document.getElementById("data-table-body");
  document.getElementById("table-record-count").textContent = formatNumber(items.length);

  if (!items || items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-row">조건에 맞는 시계열 데이터가 없습니다.</td></tr>`;
    return;
  }

  // 테이블에서는 최근 추가/수정된 최신 날짜부터 상단에 표시
  const reversed = [...items].reverse();
  tbody.innerHTML = reversed
    .map((item) => {
      const isHighlight = state.highlightedRowId === item.id ? "row-highlight" : "";
      return `
        <tr class="${isHighlight}" data-id="${escapeHtml(item.id)}">
          <td><strong>${escapeHtml(item.date)}</strong></td>
          <td class="val-cell">${formatNumber(item.value)}건</td>
          <td class="memo-cell">${escapeHtml(item.memo)}</td>
          <td class="action-cell">
            <button type="button" class="btn-row-edit" onclick="startEditData('${escapeHtml(item.id)}')">✏️ 수정</button>
            <button type="button" class="btn-row-del" onclick="removeDataItem('${escapeHtml(item.id)}')">🗑️ 삭제</button>
          </td>
        </tr>
      `;
    })
    .join("");
}

window.startEditData = function (itemId) {
  const item = state.dataList.find((x) => x.id === itemId);
  if (!item) return;

  document.getElementById("form-item-id").value = item.id;
  document.getElementById("input-date").value = item.date;
  document.getElementById("input-value").value = item.value;
  document.getElementById("input-memo").value = item.memo || "";

  const submitBtn = document.getElementById("btn-submit-data");
  submitBtn.textContent = "💾 수정 저장";
  document.getElementById("btn-cancel-edit").classList.remove("hidden");
  document.getElementById("input-value").focus();
  showToast(`수정 모드: ${item.date} 데이터를 편집합니다.`, "info");
};

function resetDataForm() {
  document.getElementById("form-item-id").value = "";
  document.getElementById("btn-submit-data").textContent = "➕ 데이터 추가";
  document.getElementById("btn-cancel-edit").classList.add("hidden");
}

window.removeDataItem = async function (itemId) {
  const item = state.dataList.find((x) => x.id === itemId);
  if (!item) return;

  try {
    await apiFetch(`/api/data/${encodeURIComponent(itemId)}`, {
      method: "DELETE",
    });
    showToast(`삭제 완료: ${item.date} (${formatNumber(item.value)}건) 데이터가 삭제되었습니다.`);
    await Promise.all([loadDataList(document.getElementById("input-search").value), loadSummaryAndStats()]);
  } catch (err) {
    showToast(`데이터 삭제 실패: ${err.message}`, "error");
  }
};

async function handleDataFormSubmit(e) {
  e.preventDefault();
  const editId = document.getElementById("form-item-id").value.trim();
  const date = document.getElementById("input-date").value.trim();
  const value = Number(document.getElementById("input-value").value);
  const memo = document.getElementById("input-memo").value.trim();

  try {
    if (editId) {
      const updated = await apiFetch(`/api/data/${encodeURIComponent(editId)}`, {
        method: "PUT",
        body: JSON.stringify({ date, value, memo }),
      });
      state.highlightedRowId = updated.id;
      showToast(`수정 완료: ${updated.date} (${formatNumber(updated.value)}건) 저장됨!`);
    } else {
      const created = await apiFetch("/api/data", {
        method: "POST",
        body: JSON.stringify({ date, value, memo }),
      });
      state.highlightedRowId = created.id;
      showToast(`추가 완료: ${created.date} (${formatNumber(created.value)}건) Firestore 저장됨!`);
    }
    resetDataForm();
    await Promise.all([loadDataList(), loadSummaryAndStats(), checkServerHealth()]);
  } catch (err) {
    showToast(`저장 실패: ${err.message}`, "error");
  }
}

// =========================================================
// 4. 대화 기록 저장 및 불러오기 (Conversations API)
// =========================================================
async function loadConversations() {
  try {
    const convs = await apiFetch("/api/conversations?include_messages=true");
    state.conversations = convs;
    renderConversationList(convs);

    // 초기 진입 시 첫 번째 대화 자동 표시
    if (!state.currentConversationId && convs.length > 0 && state.currentMessages.length === 0) {
      selectConversation(convs[0].id, false);
    }
  } catch (err) {
    showToast(`대화 목록 조회 실패: ${err.message}`, "error");
  }
}

function renderConversationList(convs) {
  const container = document.getElementById("conversation-list");
  if (!convs || convs.length === 0) {
    container.innerHTML = `<div style="font-size:12px; color:var(--text-secondary);">저장된 대화 기록이 없습니다.</div>`;
    return;
  }

  container.innerHTML = convs
    .map((c) => {
      const isActive = c.id === state.currentConversationId ? "active" : "";
      const dateStr = (c.updated_at || "").slice(0, 16).replace("T", " ");
      return `
        <div class="conv-card ${isActive}" onclick="selectConversation('${escapeHtml(c.id)}', true)">
          <div class="conv-card-title">💬 ${escapeHtml(c.title)}</div>
          <div class="conv-card-meta">
            <span>메시지 ${c.message_count || (c.messages ? c.messages.length : 0)}개 · ${escapeHtml(dateStr)}</span>
            <button type="button" class="btn-conv-del" title="대화 삭제" onclick="event.stopPropagation(); removeConversation('${escapeHtml(c.id)}')">✕</button>
          </div>
        </div>
      `;
    })
    .join("");
}

window.selectConversation = async function (convId, notify = true) {
  try {
    const detail = await apiFetch(`/api/conversations/${encodeURIComponent(convId)}`);
    state.currentConversationId = detail.id;
    state.currentMessages = detail.messages || [];
    renderConversationList(state.conversations);
    renderChatMessages(state.currentMessages);
    if (notify) {
      showToast(`대화 불러오기 완료: "${detail.title}" (${state.currentMessages.length}개 메시지)`, "info");
    }
  } catch (err) {
    showToast(`대화 불러오기 실패: ${err.message}`, "error");
  }
};

window.removeConversation = async function (convId) {
  try {
    await apiFetch(`/api/conversations/${encodeURIComponent(convId)}`, {
      method: "DELETE",
    });
    if (state.currentConversationId === convId) {
      startNewChat(false);
    }
    showToast("대화 기록이 삭제되었습니다.");
    await loadConversations();
  } catch (err) {
    showToast(`대화 삭제 실패: ${err.message}`, "error");
  }
};

function startNewChat(notify = true) {
  state.currentConversationId = null;
  state.currentMessages = [
    {
      role: "assistant",
      content:
        "안녕하세요! **전국 119 신고접수 시계열 데이터(2022~2025) 분석 비서**입니다.\n\n" +
        "현재 **151개 주간 시계열 요약(/api/data/summary)**이 시스템 프롬프트에 주입되어 있으며, 질문에 따라 **Function Calling 도구**를 호출해 정확한 통계·피크 시점·예측치를 답변해 드립니다. 무엇이 궁금하신가요?",
      timestamp: new Date().toISOString(),
      tool_calls: [{ tool: "get_data_summary", reason: "초기 컨텍스트 주입 완료" }],
    },
  ];
  renderConversationList(state.conversations);
  renderChatMessages(state.currentMessages);
  if (notify) {
    showToast("새 대화를 시작합니다.", "info");
  }
}

async function saveCurrentConversationManual() {
  if (!state.currentMessages || state.currentMessages.length === 0) {
    showToast("저장할 대화 메시지가 없습니다.", "error");
    return;
  }
  try {
    const saved = await apiFetch("/api/conversations", {
      method: "POST",
      body: JSON.stringify({
        messages: state.currentMessages,
      }),
    });
    state.currentConversationId = saved.id;
    showToast(`대화가 Firestore에 저장되었습니다: "${saved.title}"`);
    await loadConversations();
  } catch (err) {
    showToast(`대화 저장 실패: ${err.message}`, "error");
  }
}

// =========================================================
// 5. 데이터 기반 AI 채팅 (POST /api/chat)
// =========================================================
function renderChatMessages(messages) {
  const box = document.getElementById("chat-messages");
  if (!messages || messages.length === 0) {
    box.innerHTML = `<div style="color:var(--text-secondary); font-size:13px;">질문을 입력하거나 상단 추천 질문 버튼을 클릭해 보세요.</div>`;
    return;
  }

  box.innerHTML = messages
    .map((m) => {
      const roleClass = m.role === "user" ? "user" : "assistant";
      const roleLabel = m.role === "user" ? "👤 사용자" : "🤖 119 AI 데이터 비서";
      const timeLabel = m.timestamp ? m.timestamp.slice(11, 19) : "";

      let toolsHtml = "";
      if (m.tool_calls && m.tool_calls.length > 0) {
        const badges = m.tool_calls
          .map(
            (tc) =>
              `<span class="tool-badge" title="${escapeHtml(tc.reason || "")}">🛠️ Function Call: <strong>${escapeHtml(tc.tool)}</strong> (${escapeHtml(tc.reason || "자동 호출")})</span>`
          )
          .join("");
        toolsHtml = `<div class="tool-call-badges">${badges}</div>`;
      }

      return `
        <div class="msg-row ${roleClass}">
          <div class="msg-bubble">${renderMarkdown(m.content)}</div>
          ${toolsHtml}
          <div class="msg-meta">
            <span>${roleLabel}</span>
            ${timeLabel ? `<span>· ${escapeHtml(timeLabel)}</span>` : ""}
          </div>
        </div>
      `;
    })
    .join("");

  box.scrollTop = box.scrollHeight;
}

async function sendChatMessage(messageText) {
  const input = document.getElementById("chat-input");
  const loading = document.getElementById("chat-loading");
  const sendBtn = document.getElementById("btn-send-chat");
  const useTools = document.getElementById("chk-use-tools").checked;

  const text = (messageText || input.value).trim();
  if (!text) return;

  input.value = "";
  const nowStr = new Date().toISOString();
  state.currentMessages.push({
    role: "user",
    content: text,
    timestamp: nowStr,
  });
  renderChatMessages(state.currentMessages);

  loading.classList.remove("hidden");
  sendBtn.disabled = true;

  try {
    const res = await apiFetch("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message: text,
        conversation_id: state.currentConversationId,
        use_tools: useTools,
      }),
    });

    state.currentConversationId = res.conversation_id;
    state.currentMessages.push({
      role: "assistant",
      content: res.reply,
      timestamp: new Date().toISOString(),
      tool_calls: res.tool_calls_used || [],
    });

    if (res.summary_injected) {
      state.summary = res.summary_injected;
      renderSummaryKPI(res.summary_injected);
    }

    renderChatMessages(state.currentMessages);
    await loadConversations();
  } catch (err) {
    state.currentMessages.push({
      role: "assistant",
      content: `⚠️ 요청 처리 중 오류가 발생했습니다: ${err.message}`,
      timestamp: new Date().toISOString(),
    });
    renderChatMessages(state.currentMessages);
    showToast(`AI 응답 오류: ${err.message}`, "error");
  } finally {
    loading.classList.add("hidden");
    sendBtn.disabled = false;
  }
}

// =========================================================
// 6. 테마 토글(다크/라이트) · 내보내기 · 탭 전환
// =========================================================
function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("M12_THEME", theme);
  const btn = document.getElementById("btn-theme-toggle");
  if (btn) {
    btn.textContent = theme === "dark" ? "☀️ 라이트 모드" : "🌙 다크 모드";
  }
  if (state.statistics) {
    drawTimeseriesChart(state.statistics);
  }
}

function setupViewTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  const grid = document.getElementById("workspace-grid");
  const leftCol = document.querySelector(".left-column");
  const rightCol = document.querySelector(".right-column");
  const panelChart = document.getElementById("panel-chart");
  const panelCrud = document.getElementById("panel-crud");
  const panelHistory = document.getElementById("panel-history");
  const panelChat = document.getElementById("panel-chat");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const view = tab.dataset.view;

      if (view === "all") {
        grid.classList.remove("single-col");
        leftCol.classList.remove("hidden");
        rightCol.classList.remove("hidden");
        panelChart.classList.remove("hidden");
        panelCrud.classList.remove("hidden");
        panelHistory.classList.remove("hidden");
        panelChat.classList.remove("hidden");
      } else if (view === "chat") {
        grid.classList.remove("single-col");
        leftCol.classList.remove("hidden");
        rightCol.classList.remove("hidden");
        panelChart.classList.remove("hidden");
        panelCrud.classList.add("hidden");
        panelHistory.classList.add("hidden");
        panelChat.classList.remove("hidden");
      } else if (view === "crud") {
        grid.classList.add("single-col");
        leftCol.classList.remove("hidden");
        rightCol.classList.add("hidden");
        panelChart.classList.remove("hidden");
        panelCrud.classList.remove("hidden");
      } else if (view === "history") {
        grid.classList.add("single-col");
        leftCol.classList.add("hidden");
        rightCol.classList.remove("hidden");
        panelHistory.classList.remove("hidden");
        panelChat.classList.remove("hidden");
      }

      if (state.statistics) {
        setTimeout(() => drawTimeseriesChart(state.statistics), 50);
      }
    });
  });
}

// =========================================================
// 초기화 및 이벤트 바인딩
// =========================================================
document.addEventListener("DOMContentLoaded", async () => {
  applyTheme(state.theme);
  setupViewTabs();
  setupChartHover();

  // 프롬프트 원문 토글
  document.getElementById("btn-toggle-prompt-preview").addEventListener("click", () => {
    document.getElementById("prompt-preview-box").classList.toggle("hidden");
  });

  // 전체 새로고침
  document.getElementById("btn-refresh-all").addEventListener("click", async () => {
    await Promise.all([checkServerHealth(), loadSummaryAndStats(), loadDataList(), loadConversations()]);
    showToast("최신 데이터 및 요약 지표를 갱신했습니다.");
  });

  // 테마 토글
  document.getElementById("btn-theme-toggle").addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  });

  // 데이터 내보내기 (CSV / JSON)
  document.getElementById("btn-export-csv").addEventListener("click", () => {
    window.open(`${state.apiBaseUrl}/api/data/export?format=csv`, "_blank");
    showToast("CSV 파일 다운로드를 시작합니다.");
  });
  document.getElementById("btn-export-json").addEventListener("click", () => {
    window.open(`${state.apiBaseUrl}/api/data/export?format=json`, "_blank");
    showToast("JSON 파일 다운로드를 시작합니다.");
  });

  // CRUD 폼 이벤트
  document.getElementById("data-form").addEventListener("submit", handleDataFormSubmit);
  document.getElementById("btn-cancel-edit").addEventListener("click", resetDataForm);

  // 검색 필터
  document.getElementById("btn-search").addEventListener("click", () => {
    loadDataList(document.getElementById("input-search").value.trim());
  });
  document.getElementById("input-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      loadDataList(e.target.value.trim());
    }
  });
  document.getElementById("btn-reset-search").addEventListener("click", () => {
    document.getElementById("input-search").value = "";
    loadDataList("");
  });

  // 대화 기록 액션
  document.getElementById("btn-new-chat").addEventListener("click", () => startNewChat(true));
  document.getElementById("btn-save-conv").addEventListener("click", saveCurrentConversationManual);

  // 채팅 전송 및 추천 질문 칩
  document.getElementById("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    sendChatMessage();
  });
  document.querySelectorAll(".chip-btn").forEach((chip) => {
    chip.addEventListener("click", () => {
      sendChatMessage(chip.dataset.prompt);
    });
  });

  // API 서버 주소 설정 모달
  const modal = document.getElementById("modal-api-config");
  document.getElementById("btn-api-config").addEventListener("click", () => {
    document.getElementById("input-api-base-url").value = state.apiBaseUrl;
    modal.classList.remove("hidden");
  });
  document.getElementById("btn-close-modal").addEventListener("click", () => {
    modal.classList.add("hidden");
  });
  document.getElementById("btn-save-api-url").addEventListener("click", async () => {
    const newUrl = document.getElementById("input-api-base-url").value.trim().replace(/\/+$/, "");
    if (newUrl) {
      state.apiBaseUrl = newUrl;
      localStorage.setItem("M12_API_BASE_URL", newUrl);
      modal.classList.add("hidden");
      showToast(`API 서버 주소가 변경되었습니다: ${newUrl}`);
      await Promise.all([checkServerHealth(), loadSummaryAndStats(), loadDataList(), loadConversations()]);
    }
  });

  window.addEventListener("resize", () => {
    if (state.statistics) drawTimeseriesChart(state.statistics);
  });

  // 초기 데이터 병렬 로드
  await Promise.all([
    checkServerHealth(),
    loadSummaryAndStats(),
    loadDataList(),
    loadConversations(),
  ]);

  // URL 쿼리 파라미터(?view=chat|crud|history)가 있으면 해당 탭 자동 활성화
  const urlParams = new URLSearchParams(window.location.search);
  const initialView = urlParams.get("view");
  if (initialView) {
    const targetTab = document.querySelector(`.tab-btn[data-view="${initialView}"]`);
    if (targetTab) targetTab.click();
  }
});
