const state = { page: 1, pageSize: 20, total: 0, filters: [] };

const $ = (selector) => document.querySelector(selector);
const money = (value) => {
  const number = Number(value || 0);
  if (!number) return '-';
  return `${number.toLocaleString('ko-KR')}원`;
};

function toast(message) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('show');
  setTimeout(() => node.classList.remove('show'), 2800);
}

async function api(path, options = {}) {
  const response = await fetch(`/site5${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
  return data;
}

function renderStats(data) {
  const stats = data.stats || {};
  $('#stats').innerHTML = `
    <div class="stat"><b>${stats.total_notices || 0}</b><span>저장 공고</span></div>
    <div class="stat"><b>${stats.enabled_filters || 0}</b><span>활성 필터</span></div>
    <div class="stat"><b>${stats.notified_notices || 0}</b><span>알림 발송 공고</span></div>
    <div class="stat"><b>${stats.filters || 0}</b><span>전체 필터</span></div>
  `;
  $('#jobs').innerHTML = (data.jobs || []).map((job) => `
    <div class="job ${job.status}">
      <strong>${job.job_name} · ${job.status}</strong>
      <small>${job.message || ''}</small>
      <small>${job.finished_at || job.started_at || ''}</small>
    </div>
  `).join('') || '<div class="job"><strong>작업 기록 없음</strong></div>';
}

async function loadStatus() {
  const data = await api('/api/status');
  renderStats(data);
}

function fillForm(filter = {}) {
  const form = $('#filterForm');
  form.id.value = filter.id || '';
  form.name.value = filter.name || '';
  form.enabled.checked = filter.enabled !== 0;
  form.keywords.value = filter.keywords || '';
  form.exclude_keywords.value = filter.exclude_keywords || '';
  form.business_types.value = filter.business_types || '';
  form.regions.value = filter.regions || '';
  form.institutions.value = filter.institutions || '';
  form.min_amount.value = filter.min_amount || '';
  form.max_amount.value = filter.max_amount || '';
  form.require_region_limit.value = filter.require_region_limit || 'any';
}

function renderFilters(filters) {
  $('#filters').innerHTML = filters.map((filter) => `
    <div class="filter-item ${filter.enabled ? '' : 'off'}" data-id="${filter.id}">
      <strong>${escapeHtml(filter.name)}</strong>
      <small>${filter.enabled ? '활성' : '비활성'} · ${escapeHtml(filter.keywords || '키워드 없음')}</small>
    </div>
  `).join('') || '<p class="muted">저장된 필터가 없습니다.</p>';
  document.querySelectorAll('.filter-item').forEach((item) => {
    item.addEventListener('click', () => {
      const filter = state.filters.find((entry) => String(entry.id) === item.dataset.id);
      fillForm(filter);
    });
  });
}

async function loadFilters() {
  const data = await api('/api/filters');
  state.filters = data.items || [];
  renderFilters(state.filters);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));
}

function noticeUrl(notice) {
  return notice.bid_ntce_url || '#';
}

function renderNotices(result) {
  state.total = result.total || 0;
  $('#noticeCount').textContent = `${state.total.toLocaleString('ko-KR')}건`;
  $('#pageInfo').textContent = `${result.page} / ${Math.max(1, Math.ceil(state.total / state.pageSize))}`;
  $('#notices').innerHTML = (result.items || []).map((notice) => `
    <article class="notice">
      <h3><a href="${escapeHtml(noticeUrl(notice))}" target="_blank" rel="noreferrer">${escapeHtml(notice.bid_ntce_nm || '제목 없음')}</a></h3>
      <div class="meta">
        <span>${escapeHtml(notice.bsns_div_nm || '-')}</span>
        <span>${escapeHtml(notice.bid_ntce_sttus_nm || '-')}</span>
        <span>공고 ${escapeHtml(notice.bid_ntce_date || '-')} ${escapeHtml(notice.bid_ntce_bgn || '')}</span>
        <span>마감 ${escapeHtml(notice.bid_clse_date || '-')} ${escapeHtml(notice.bid_clse_tm || '')}</span>
        <span>개찰 ${escapeHtml(notice.openg_date || '-')} ${escapeHtml(notice.openg_tm || '')}</span>
        <span class="amount">${money(notice.presmpt_prce || notice.asign_bdgt_amt)}</span>
      </div>
      <div class="meta" style="margin-top: 10px">
        <span>공고기관 ${escapeHtml(notice.ntce_instt_nm || '-')}</span>
        <span>수요기관 ${escapeHtml(notice.dmnd_instt_nm || '-')}</span>
        <span>지역 ${escapeHtml(notice.prtcpt_psbl_rgn_nm || notice.rgn_lmt_yn || '-')}</span>
      </div>
    </article>
  `).join('') || '<p>조건에 맞는 공고가 없습니다.</p>';
}

async function loadNotices() {
  const params = new URLSearchParams({ page: state.page, page_size: state.pageSize });
  const search = $('#search').value.trim();
  const businessType = $('#businessType').value;
  const region = $('#region').value.trim();
  const minAmount = $('#minAmount').value;
  if (search) params.set('search', search);
  if (businessType) params.set('business_type', businessType);
  if (region) params.set('region', region);
  if (minAmount) params.set('min_amount', minAmount);
  const data = await api(`/api/notices?${params.toString()}`);
  renderNotices(data);
}

function formPayload() {
  const form = $('#filterForm');
  return {
    name: form.name.value,
    enabled: form.enabled.checked,
    keywords: form.keywords.value,
    exclude_keywords: form.exclude_keywords.value,
    business_types: form.business_types.value,
    regions: form.regions.value,
    institutions: form.institutions.value,
    min_amount: form.min_amount.value || null,
    max_amount: form.max_amount.value || null,
    require_region_limit: form.require_region_limit.value,
  };
}

async function saveFilter(event) {
  event.preventDefault();
  const form = $('#filterForm');
  const id = form.id.value;
  if (!form.name.value.trim()) {
    toast('필터명을 입력하세요.');
    return;
  }
  if (id) {
    await api(`/api/filters/${id}`, { method: 'PUT', body: JSON.stringify(formPayload()) });
  } else {
    await api('/api/filters', { method: 'POST', body: JSON.stringify(formPayload()) });
  }
  toast('필터를 저장했습니다.');
  await loadFilters();
  await loadStatus();
}

async function deleteFilter() {
  const id = $('#filterForm').id.value;
  if (!id) {
    fillForm({});
    return;
  }
  if (!confirm('이 필터를 삭제할까요?')) return;
  await api(`/api/filters/${id}`, { method: 'DELETE' });
  fillForm({});
  toast('필터를 삭제했습니다.');
  await loadFilters();
  await loadStatus();
}

async function runJob(path, label) {
  const buttons = document.querySelectorAll('button');
  buttons.forEach((button) => button.disabled = true);
  try {
    const result = await api(path, { method: 'POST', body: '{}' });
    toast(`${label}: ${result.status || 'ok'}`);
    await Promise.all([loadStatus(), loadNotices()]);
  } catch (error) {
    toast(`${label} 실패: ${error.message}`);
  } finally {
    buttons.forEach((button) => button.disabled = false);
  }
}

function bind() {
  $('#refreshStatus').addEventListener('click', loadStatus);
  $('#runCollect').addEventListener('click', () => runJob('/api/jobs/collect', '수집'));
  $('#runNotify').addEventListener('click', () => runJob('/api/jobs/notify', '알림 검사'));
  $('#runSheet').addEventListener('click', () => runJob('/api/jobs/sync-sheet', '시트 동기화'));
  $('#filterForm').addEventListener('submit', saveFilter);
  $('#newFilter').addEventListener('click', () => fillForm({}));
  $('#deleteFilter').addEventListener('click', deleteFilter);
  $('#searchButton').addEventListener('click', () => { state.page = 1; loadNotices(); });
  $('#search').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { state.page = 1; loadNotices(); }
  });
  $('#prevPage').addEventListener('click', () => {
    state.page = Math.max(1, state.page - 1);
    loadNotices();
  });
  $('#nextPage').addEventListener('click', () => {
    const last = Math.max(1, Math.ceil(state.total / state.pageSize));
    state.page = Math.min(last, state.page + 1);
    loadNotices();
  });
}

bind();
Promise.all([loadStatus(), loadFilters(), loadNotices()]).catch((error) => toast(error.message));
setInterval(loadStatus, 30000);
