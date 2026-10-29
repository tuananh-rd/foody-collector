/**
 * FoodTour Hà Nội - Collector WebUI Application (Vanilla JS)
 * Compliant with docs/QUALITY_V3.md section 13 and docs/V2_CONTRACT.md.
 * Pure Vanilla JS, zero external libraries, zero inline handlers (CSP-strict compliant).
 */

(function () {
  'use strict';

  // --- State Management ---
  const state = {
    csrfToken: '',
    activeJob: null,
    viewingJobId: null,
    viewingJobData: null,
    currentLayer: 'normalized', // default layer per v0.3 contract
    allPreviewRecords: [],
    pollTimer: null,
    pollIntervalMs: 1500,
    isPolling: false,
    historyLoaded: false,

    // Section 2.8: Menu & Photos (v0.5)
    mediaStatus: null,
    mediaTaskPollTimer: null,
    mediaPollIntervalMs: 2000,
    mediaScopeMode: 'selected',
    mediaSelectedVenueIds: new Set(),
    mediaVenues: [],
    mediaVenuesTotal: 0,
    mediaFilter: '',
    mediaQuery: '',
    mediaOffset: 0,
    mediaLimit: 25,
    mediaLimitsTouched: false,
    mediaDefaultSelectionDone: false,
    mediaLastJobId: null,
  };

  // --- DOM Element References ---
  const elements = {
    // Browser Readiness
    browserDot: document.getElementById('browser-indicator-dot'),
    browserTitle: document.getElementById('browser-readiness-title'),
    browserMessage: document.getElementById('browser-readiness-message'),

    // System Alert Banner
    systemBanner: document.getElementById('system-banner'),
    systemBannerIcon: document.getElementById('system-banner-icon'),
    systemBannerText: document.getElementById('system-banner-text'),
    btnCloseBanner: document.getElementById('btn-close-banner'),

    // Form Inputs & Controls
    collectorForm: document.getElementById('collector-form'),
    modeSample: document.getElementById('mode-sample'),
    modeAll: document.getElementById('mode-all'),
    groupLimit: document.getElementById('group-limit'),
    inputLimit: document.getElementById('input-limit'),
    inputInterval: document.getElementById('input-interval'),
    inputShowBrowser: document.getElementById('input-show-browser'),
    scopeHint: document.getElementById('scope-hint'),

    // Action Buttons
    btnStart: document.getElementById('btn-start'),
    btnPause: document.getElementById('btn-pause'),
    btnResume: document.getElementById('btn-resume'),
    btnStop: document.getElementById('btn-stop'),
    btnRefresh: document.getElementById('btn-refresh'),
    btnShutdown: document.getElementById('btn-shutdown'),

    // Dashboard Badges & Meta
    badgeJobState: document.getElementById('badge-job-state'),
    badgeJobStage: document.getElementById('badge-job-stage'),
    displayJobId: document.getElementById('display-job-id'),
    displayJobMode: document.getElementById('display-job-mode'),
    displayJobUpdated: document.getElementById('display-job-updated'),

    // Termination & Incomplete Notice
    terminationNotice: document.getElementById('termination-notice'),
    terminationIcon: document.getElementById('termination-icon'),
    terminationTitle: document.getElementById('termination-title'),
    terminationDesc: document.getElementById('termination-desc'),
    badgeIncomplete: document.getElementById('badge-incomplete'),
    badgeCoverage: document.getElementById('badge-coverage'),

    // Progress
    progressStatusLabel: document.getElementById('progress-status-label'),
    progressCounterText: document.getElementById('progress-counter-text'),
    progressBarContainer: document.getElementById('progress-bar-container'),
    progressFill: document.getElementById('progress-fill'),
    progressExplanation: document.getElementById('progress-explanation'),

    // Metrics
    metricDiscovered: document.getElementById('metric-discovered'),
    metricProcessed: document.getElementById('metric-processed'),
    metricSuccess: document.getElementById('metric-success'),
    metricDuplicates: document.getElementById('metric-duplicates'),
    metricFailed: document.getElementById('metric-failed'),
    metricClicks: document.getElementById('metric-clicks'),
    metricRequests: document.getElementById('metric-requests'),

    // Last Message & Logs
    displayJobMessage: document.getElementById('display-job-message'),
    logsContainer: document.getElementById('logs-container'),

    // Compact Quality Panel (v0.3)
    qualitySection: document.getElementById('quality-section'),
    qualityViewingJob: document.getElementById('quality-viewing-job'),
    badgeQualityLayer: document.getElementById('badge-quality-layer'),
    badgeQualityFallback: document.getElementById('badge-quality-fallback'),
    qualityLegacyAlert: document.getElementById('quality-legacy-alert'),
    qualityFallbackTitle: document.getElementById('quality-fallback-title'),
    qualityFallbackDesc: document.getElementById('quality-fallback-desc'),
    btnReclassifyQuality: document.getElementById('btn-reclassify-quality'),

    statPriceOk: document.getElementById('stat-price-ok'),
    statPriceZero: document.getElementById('stat-price-zero'),
    statPriceReversed: document.getElementById('stat-price-reversed'),
    statPriceOther: document.getElementById('stat-price-other'),

    badgeTotalIssues: document.getElementById('badge-total-issues'),
    statIssuesError: document.getElementById('stat-issues-error'),
    statIssuesWarning: document.getElementById('stat-issues-warning'),
    statIssuesInfo: document.getElementById('stat-issues-info'),

    statEligSearch: document.getElementById('stat-elig-search'),
    statEligLocation: document.getElementById('stat-elig-location'),
    statEligPriceFilter: document.getElementById('stat-elig-price-filter'),
    statEligBudget: document.getElementById('stat-elig-budget'),
    statEligHours: document.getElementById('stat-elig-hours'),

    // Preview
    previewTotalText: document.getElementById('preview-total-text'),
    previewTbody: document.getElementById('preview-tbody'),
    previewTheadRow: document.getElementById('preview-thead-row'),
    btnRefreshPreview: document.getElementById('btn-refresh-preview'),
    layerEnriched: document.getElementById('layer-enriched'),
    layerNormalized: document.getElementById('layer-normalized'),
    layerRaw: document.getElementById('layer-raw'),
    badgePreviewLayer: document.getElementById('badge-preview-layer'),
    enrichmentDisclaimer: document.getElementById('enrichment-disclaimer'),

    // Filters (v0.4)
    previewFilterToolbar: document.getElementById('preview-filter-toolbar'),
    filterStatusHint: document.getElementById('filter-status-hint'),
    filterCuisine: document.getElementById('filter-cuisine'),
    filterVenueType: document.getElementById('filter-venue-type'),
    filterDishGroup: document.getElementById('filter-dish-group'),
    filterSuitableMeal: document.getElementById('filter-suitable-meal'),
    filterAudience: document.getElementById('filter-audience'),
    filterMinRating: document.getElementById('filter-min-rating'),
    filterMinReviews: document.getElementById('filter-min-reviews'),
    filterAmenity: document.getElementById('filter-amenity'),
    filterPrepTime: document.getElementById('filter-prep-time'),
    filterCapacity: document.getElementById('filter-capacity'),
    btnResetFilters: document.getElementById('btn-reset-filters'),

    // Downloads
    btnDownloadCsv: document.getElementById('btn-download-csv'),
    btnDownloadJson: document.getElementById('btn-download-json'),
    btnDownloadReport: document.getElementById('btn-download-report'),
    btnDownloadNormCsv: document.getElementById('btn-download-norm-csv'),
    btnDownloadNormJson: document.getElementById('btn-download-norm-json'),
    btnDownloadIssuesCsv: document.getElementById('btn-download-issues-csv'),
    btnDownloadIssuesJson: document.getElementById('btn-download-issues-json'),
    btnDownloadQuality: document.getElementById('btn-download-quality'),
    btnDownloadRaw: document.getElementById('btn-download-raw'),
    btnDownloadEnrichedCsv: document.getElementById('btn-download-enriched-csv'),
    btnDownloadEnrichedJson: document.getElementById('btn-download-enriched-json'),
    btnDownloadEnrichmentReport: document.getElementById('btn-download-enrichment-report'),
    btnEnrichJob: document.getElementById('btn-enrich-job'),

    // History
    btnRefreshHistory: document.getElementById('btn-refresh-history'),
    historyTbody: document.getElementById('history-tbody'),

    // Section 2.8: Menu & Media Elements (v0.5)
    mediaSection: document.getElementById('media-section'),
    mediaViewingJob: document.getElementById('media-viewing-job'),
    badgeMediaScanned: document.getElementById('badge-media-scanned'),
    badgeMediaTaskState: document.getElementById('badge-media-task-state'),
    mediaBusySpinner: document.getElementById('media-busy-spinner'),
    mediaEmptyAlert: document.getElementById('media-empty-alert'),
    mediaMainContent: document.getElementById('media-main-content'),

    // Actions & Controls
    btnMediaScan: document.getElementById('btn-media-scan'),
    btnMediaCollect: document.getElementById('btn-media-collect'),
    btnMediaImages: document.getElementById('btn-media-images'),
    btnMediaOcr: document.getElementById('btn-media-ocr'),
    btnMediaDlOcrCsv: document.getElementById('btn-media-dl-ocr-csv'),
    btnMediaDlOcrJson: document.getElementById('btn-media-dl-ocr-json'),
    btnMediaPause: document.getElementById('btn-media-pause'),
    btnMediaResume: document.getElementById('btn-media-resume'),
    btnMediaStop: document.getElementById('btn-media-stop'),

    // Progress Box
    mediaTaskProgressBox: document.getElementById('media-task-progress-box'),
    mediaTaskKindBadge: document.getElementById('media-task-kind-badge'),
    mediaTaskStateBadge: document.getElementById('media-task-state-badge'),
    mediaTaskMsg: document.getElementById('media-task-msg'),
    mediaTaskLimitBadge: document.getElementById('media-task-limit-badge'),
    mediaTaskStopAlert: document.getElementById('media-task-stop-alert'),
    mediaTaskStopTitle: document.getElementById('media-task-stop-title'),
    mediaTaskStopDesc: document.getElementById('media-task-stop-desc'),
    mediaProgressLabel: document.getElementById('media-progress-label'),
    mediaProgressCounter: document.getElementById('media-progress-counter'),
    mediaProgressBarContainer: document.getElementById('media-progress-bar-container'),
    mediaProgressFill: document.getElementById('media-progress-fill'),

    // Metrics
    mediaMetricVenuesDone: document.getElementById('media-metric-venues-done'),
    mediaMetricPageReqs: document.getElementById('media-metric-page-reqs'),
    mediaMetricPageBytesLabel: document.getElementById('media-metric-page-bytes-label'),
    mediaMetricImageReqs: document.getElementById('media-metric-image-reqs'),
    mediaMetricImageBytesLabel: document.getElementById('media-metric-image-bytes-label'),
    mediaMetricApiReqs: document.getElementById('media-metric-api-reqs'),
    mediaMetricMenuItems: document.getElementById('media-metric-menu-items'),
    mediaMetricPhotosListed: document.getElementById('media-metric-photos-listed'),
    mediaMetricImagesOk: document.getElementById('media-metric-images-ok'),
    mediaMetricImagesSkipped: document.getElementById('media-metric-images-skipped'),
    mediaMetricImagesFailed: document.getElementById('media-metric-images-failed'),
    mediaMetricImagesDuplicate: document.getElementById('media-metric-images-duplicate'),
    mediaTaskErrorsAccordion: document.getElementById('media-task-errors-accordion'),
    mediaErrorsSummaryText: document.getElementById('media-errors-summary-text'),
    mediaErrorsContainer: document.getElementById('media-errors-container'),

    // Coverage Summary Cards
    covVenuesTotal: document.getElementById('cov-venues-total'),
    covVenuesCached: document.getElementById('cov-venues-cached'),
    covVenuesDelivery: document.getElementById('cov-venues-delivery'),
    covDeliveryBadgeBox: document.getElementById('cov-delivery-badge-box'),
    covPagesFetched: document.getElementById('cov-pages-fetched'),
    covMenuNotCollected: document.getElementById('cov-menu-not-collected'),
    covMenuItemsSummary: document.getElementById('cov-menu-items-summary'),
    covMenuEmpty: document.getElementById('cov-menu-empty'),
    covMenuBlocked: document.getElementById('cov-menu-blocked'),
    covMenuError: document.getElementById('cov-menu-error'),
    covVenuesMenuDeclared: document.getElementById('cov-venues-menu-declared'),
    covMenuImagesKnown: document.getElementById('cov-menu-images-known'),
    covVenuesPhotosDeclared: document.getElementById('cov-venues-photos-declared'),
    covPhotosKnownSummary: document.getElementById('cov-photos-known-summary'),
    covPhotosDownloadedSummary: document.getElementById('cov-photos-downloaded-summary'),

    // Scope & Limits
    scopeSelected: document.getElementById('scope-selected'),
    scopeMenuImages: document.getElementById('scope-menu-images'),
    scopeAll: document.getElementById('scope-all'),
    scopeCountSelected: document.getElementById('scope-count-selected'),
    scopeCountMenuImages: document.getElementById('scope-count-menu-images'),
    scopeCountAll: document.getElementById('scope-count-all'),
    displayScopeCount: document.getElementById('display-scope-count'),
    mediaScopeConfirmBox: document.getElementById('media-scope-confirm-box'),
    chkMediaConfirmNetwork: document.getElementById('chk-media-confirm-network'),

    inputMediaMaxImagesPerVenue: document.getElementById('input-media-max-images-per-venue'),
    inputMediaMaxTotalImages: document.getElementById('input-media-max-total-images'),
    inputMediaMaxBytesPerImageMb: document.getElementById('input-media-max-bytes-per-image-mb'),
    inputMediaMaxTotalMb: document.getElementById('input-media-max-total-mb'),
    inputMediaMaxPages: document.getElementById('input-media-max-pages'),
    inputMediaInterval: document.getElementById('input-media-interval'),

    chkAlbumThucDon: document.getElementById('chk-album-thuc-don'),
    chkAlbumMonAn: document.getElementById('chk-album-mon-an'),
    chkAlbumKhongGian: document.getElementById('chk-album-khong-gian'),
    chkAlbumTongHop: document.getElementById('chk-album-tong-hop'),
    chkAlbumHome: document.getElementById('chk-album-home'),
    chkMediaMenu: document.getElementById('chk-media-menu'),
    chkMediaMenuImagesOnly: document.getElementById('chk-media-menu-images-only'),
    chkMediaRefresh: document.getElementById('chk-media-refresh'),

    // Downloads
    btnMediaDlMenuCsv: document.getElementById('btn-media-dl-menu-csv'),
    btnMediaDlMenuJson: document.getElementById('btn-media-dl-menu-json'),
    btnMediaDlPhotosCsv: document.getElementById('btn-media-dl-photos-csv'),
    btnMediaDlPhotosJson: document.getElementById('btn-media-dl-photos-json'),
    btnMediaDlMenuImagesCsv: document.getElementById('btn-media-dl-menu-images-csv'),
    btnMediaDlVenuesCsv: document.getElementById('btn-media-dl-venues-csv'),
    btnMediaDlArchive: document.getElementById('btn-media-dl-archive'),

    // Venues Table
    inputMediaSearch: document.getElementById('input-media-search'),
    selectMediaFilter: document.getElementById('select-media-filter'),
    selectMediaLimit: document.getElementById('select-media-limit'),
    btnMediaSelectPage: document.getElementById('btn-media-select-page'),
    btnMediaClearSelection: document.getElementById('btn-media-clear-selection'),
    chkMediaSelectAllPage: document.getElementById('chk-media-select-all-page'),
    mediaVenuesTable: document.getElementById('media-venues-table'),
    mediaVenuesTbody: document.getElementById('media-venues-tbody'),
    mediaVenuesTotalLabel: document.getElementById('media-venues-total-label'),
    mediaPagingInfo: document.getElementById('media-paging-info'),
    btnMediaPrev: document.getElementById('btn-media-prev'),
    btnMediaNext: document.getElementById('btn-media-next'),

    // Venue Detail Drawer / Modal
    mediaVenueDetailModal: document.getElementById('media-venue-detail-modal'),
    venueDetailBackdrop: document.getElementById('venue-detail-backdrop'),
    detailVenueName: document.getElementById('detail-venue-name'),
    detailVenueId: document.getElementById('detail-venue-id'),
    detailVenueUrl: document.getElementById('detail-venue-url'),
    btnCloseVenueDetail: document.getElementById('btn-close-venue-detail'),
    tabBtnPhotos: document.getElementById('tab-btn-photos'),
    tabBtnMenu: document.getElementById('tab-btn-menu'),
    tabPanelPhotos: document.getElementById('tab-panel-photos'),
    tabPanelMenu: document.getElementById('tab-panel-menu'),
    detailPhotosCount: document.getElementById('detail-photos-count'),
    detailMenuItemsCount: document.getElementById('detail-menu-items-count'),
    detailPhotosContainer: document.getElementById('detail-photos-container'),
    detailMenuTbody: document.getElementById('detail-menu-tbody'),
  };

  // --- Vietnamese Localization Maps ---
  const STATE_LABELS = {
    queued: { text: 'Đang xếp hàng', class: 'badge-idle' },
    running: { text: 'Đang chạy', class: 'badge-running' },
    paused: { text: 'Đang tạm dừng', class: 'badge-paused' },
    stopped: { text: 'Đã dừng', class: 'badge-stopped' },
    blocked: { text: 'Bị chặn', class: 'badge-blocked' },
    completed: { text: 'Đã hoàn tất', class: 'badge-completed' },
    partial: { text: 'Hoàn thành một phần', class: 'badge-partial' },
    error: { text: 'Gặp lỗi', class: 'badge-error' },
  };

  const STAGE_LABELS = {
    discovering: 'Đang dò tìm liên kết quán',
    collecting: 'Đang thu thập chi tiết quán',
    finished: 'Đã kết thúc phiên',
  };

  const TERMINATION_REASONS = {
    exhausted: {
      title: 'Đã quét hết danh sách quán',
      desc: 'Trình duyệt đã cuộn và tải hết toàn bộ danh sách địa điểm khả dụng trên trang Foody.',
      incomplete: false,
    },
    limit: {
      title: 'Đã hoàn thành mẫu thu thập',
      desc: 'Phiên thu thập đã hoàn thành đủ số lượng địa điểm của đợt mẫu (không phải quét hết toàn bộ thành phố).',
      incomplete: false,
    },
    stopped: {
      title: 'Người dùng đã dừng phiên',
      desc: 'Tiến trình thu thập đã dừng theo lệnh của người dùng trước khi duyệt hết toàn bộ.',
      incomplete: true,
    },
    blocked: {
      title: 'Truy cập bị chặn',
      desc: 'Trang web phản hồi mã 403/429 hoặc yêu cầu xác thực bảo mật. Tiến trình chưa hoàn tất đầy đủ.',
      incomplete: true,
    },
    stalled: {
      title: 'Trang không còn phản hồi dữ liệu mới',
      desc: 'Sau nhiều lần bấm Tải thêm, danh sách không xuất hiện thêm địa điểm mới. Tiến trình chưa hoàn tất.',
      incomplete: true,
    },
    timeout: {
      title: 'Hết thời gian chờ kết nối',
      desc: 'Quá thời gian kết nối đến máy chủ nguồn. Tiến trình dừng lại và chưa hoàn thành.',
      incomplete: true,
    },
    error: {
      title: 'Phát sinh lỗi kỹ thuật',
      desc: 'Đã xảy ra lỗi trong quá trình thu thập hoặc điều khiển trình duyệt. Tiến trình chưa hoàn thành.',
      incomplete: true,
    },
    safety_limit: {
      title: 'Chạm giới hạn an toàn tối đa',
      desc: 'Đạt ngưỡng số lần nhấn hoặc số yêu cầu tối đa để bảo vệ tài nguyên hệ thống.',
      incomplete: true,
    },
  };

  // --- Notification Banner Utilities ---
  function showBanner(message, type = 'error') {
    if (!elements.systemBanner) return;
    elements.systemBanner.classList.remove('hidden', 'banner-info', 'banner-success');
    if (type === 'info') {
      elements.systemBanner.classList.add('banner-info');
      elements.systemBannerIcon.textContent = 'ℹ️';
    } else if (type === 'success') {
      elements.systemBanner.classList.add('banner-success');
      elements.systemBannerIcon.textContent = '✅';
    } else {
      elements.systemBannerIcon.textContent = '⚠️';
    }
    elements.systemBannerText.textContent = message;
  }

  function hideBanner() {
    if (!elements.systemBanner) return;
    elements.systemBanner.classList.add('hidden');
  }

  // --- Safe HTTP Client ---
  async function apiGet(endpoint) {
    try {
      const response = await fetch(endpoint, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
        },
      });

      if (!response.ok) {
        let errDetail = `Lỗi HTTP ${response.status}`;
        try {
          const errJson = await response.json();
          if (errJson && errJson.error) {
            errDetail = errJson.error;
          }
        } catch (_) {
          // Keep default status
        }
        throw new Error(errDetail);
      }

      return await response.json();
    } catch (err) {
      console.warn(`[API GET ${endpoint}]`, err);
      throw err;
    }
  }

  async function apiPost(endpoint, bodyData) {
    try {
      // Ensure we have a valid CSRF token
      if (!state.csrfToken) {
        await fetchStatus();
      }

      const headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      };

      if (state.csrfToken) {
        headers['X-CSRF-Token'] = state.csrfToken;
      }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(bodyData || {}),
      });

      if (!response.ok) {
        let errDetail = `Lỗi HTTP ${response.status}`;
        try {
          const errJson = await response.json();
          if (errJson && errJson.error) {
            errDetail = errJson.error;
          }
        } catch (_) {
          // Keep default
        }
        throw new Error(errDetail);
      }

      return await response.json();
    } catch (err) {
      console.warn(`[API POST ${endpoint}]`, err);
      throw err;
    }
  }

  /**
   * Determine whether a job has enrichment data (v0.4).
   * Central helper used across all download and preview logic.
   */
  function computeHasEnrichment(job) {
    return Boolean(job && (job.has_enrichment || job.hasEnrichment));
  }

  /**
   * Determine whether a job has quality assessment data (v0.3).
   */
  function computeHasQuality(job) {
    return Boolean(job && (job.quality_summary || (job.report && job.report.quality)));
  }

  // --- Safe Value & String Formatting Helpers ---
  function safeText(val, fallback = '(Chưa có thông tin)') {
    if (val === null || val === undefined || val === '') {
      return fallback;
    }
    return String(val);
  }

  /**
   * Format numeric price range safely.
   * Reversed or 0 prices are NEVER usable in preview.
   */
  function formatPrice(minVnd, maxVnd) {
    if (minVnd === null && maxVnd === null) {
      return null;
    }
    // Unknown zero or partial zero: never treat as free, not usable as price filter
    if (minVnd !== null && minVnd !== undefined && maxVnd !== null && maxVnd !== undefined &&
        Number(minVnd) === 0 && Number(maxVnd) === 0) {
      return 'Chưa có giá tham khảo';
    }
    if ((minVnd !== null && Number(minVnd) === 0) || (maxVnd !== null && Number(maxVnd) === 0)) {
      return 'Chưa có giá tham khảo';
    }

    const minNum = typeof minVnd === 'number' ? minVnd : parseFloat(minVnd);
    const maxNum = typeof maxVnd === 'number' ? maxVnd : parseFloat(maxVnd);

    const hasMin = !isNaN(minNum) && minNum > 0;
    const hasMax = !isNaN(maxNum) && maxNum > 0;

    // Reversed price: min > max
    if (hasMin && hasMax && minNum > maxNum) {
      return 'Giá đảo chiều (không sử dụng)';
    }

    if (hasMin && hasMax) {
      if (minNum === maxNum) {
        return `${minNum.toLocaleString('vi-VN')} ₫`;
      }
      return `${minNum.toLocaleString('vi-VN')} ₫ – ${maxNum.toLocaleString('vi-VN')} ₫`;
    } else if (hasMin) {
      return `Từ ${minNum.toLocaleString('vi-VN')} ₫`;
    } else if (hasMax) {
      return `Đến ${maxNum.toLocaleString('vi-VN')} ₫`;
    }
    return null;
  }

  /**
   * Price display model for preview row:
   * Returns { text, className, isUsable }
   */
  function getRecordPriceInfo(record) {
    // 1. Normalized row with price_status
    if (record && record.price_status) {
      if (record.price_status === 'ok') {
        const lo = record.price_min_vnd_norm !== null && record.price_min_vnd_norm !== undefined
          ? record.price_min_vnd_norm
          : record.price_min_raw;
        const hi = record.price_max_vnd_norm !== null && record.price_max_vnd_norm !== undefined
          ? record.price_max_vnd_norm
          : record.price_max_raw;
        return {
          text: formatPrice(lo, hi) || 'Chưa có giá tham khảo',
          className: '',
          isUsable: true,
        };
      }
      if (record.price_status === 'invalid_range') {
        return {
          text: 'Giá đảo chiều (không sử dụng)',
          className: 'price-invalid',
          isUsable: false,
        };
      }
      if (record.price_status === 'unknown_zero' || record.price_status === 'partial_zero') {
        return {
          text: 'Chưa có giá tham khảo',
          className: 'null-value',
          isUsable: false,
        };
      }
      if (record.price_status === 'nonfinite') {
        return {
          text: 'Giá không hợp lệ (không sử dụng)',
          className: 'price-invalid',
          isUsable: false,
        };
      }
      if (record.price_status === 'missing') {
        return {
          text: 'Chưa có giá tham khảo',
          className: 'null-value',
          isUsable: false,
        };
      }
      return {
        text: 'Chưa có giá tham khảo',
        className: 'null-value',
        isUsable: false,
      };
    }

    // 2. Legacy row (fallback or raw layer)
    const lo = record.price_min_vnd !== undefined ? record.price_min_vnd : record.price_min_raw;
    const hi = record.price_max_vnd !== undefined ? record.price_max_vnd : record.price_max_raw;

    if ((lo === null || lo === undefined || lo === '') && (hi === null || hi === undefined || hi === '')) {
      return {
        text: '(Không khả dụng)',
        className: 'null-value',
        isUsable: false,
      };
    }

    const priceText = formatPrice(lo, hi);
    if (!priceText) {
      return {
        text: '(Không khả dụng)',
        className: 'null-value',
        isUsable: false,
      };
    }

    if (priceText === 'Giá đảo chiều (không sử dụng)') {
      return {
        text: priceText,
        className: 'price-invalid',
        isUsable: false,
      };
    }
    if (priceText === 'Chưa có giá tham khảo') {
      return {
        text: priceText,
        className: 'null-value',
        isUsable: false,
      };
    }

    return {
      text: priceText,
      className: '',
      isUsable: true,
    };
  }

  /**
   * Opening hours display model for preview row:
   * Preserves all multi-shift intervals, appends (Chưa rõ quy ước thứ) note when mapping unknown,
   * never assumes closed.
   */
  function getRecordHoursInfo(record) {
    if (!record) {
      return {
        text: 'Chưa có thông tin giờ mở cửa',
        className: 'null-value',
      };
    }
    const rawHours = record.opening_hours_raw;
    const hoursStatus = record.hours_status;
    const displayed = record.hours_displayed;

    if (hoursStatus === 'missing') {
      return {
        text: 'Chưa có thông tin giờ mở cửa',
        className: 'null-value',
      };
    }
    if (hoursStatus === 'malformed') {
      return {
        text: 'Giờ mở cửa không đúng định dạng',
        className: 'null-value',
      };
    }

    if (!rawHours && !displayed) {
      return {
        text: 'Chưa có thông tin giờ mở cửa',
        className: 'null-value',
      };
    }

    let hoursList = rawHours;
    if (typeof hoursList === 'string') {
      try {
        const parsed = JSON.parse(hoursList);
        if (Array.isArray(parsed)) hoursList = parsed;
      } catch (_) {}
    }

    if (Array.isArray(hoursList)) {
      if (hoursList.length === 0) {
        return {
          text: 'Chưa có thông tin giờ mở cửa',
          className: 'null-value',
        };
      }

      // Extract all shifts preserving order
      const parts = hoursList.map((h) => {
        if (h && typeof h === 'object') {
          if (h.open && h.close) return `${h.open} - ${h.close}`;
          if (h.open) return `Mở cửa: ${h.open}`;
        } else if (typeof h === 'string' && h.trim()) {
          return h.trim();
        }
        return null;
      }).filter(Boolean);

      if (parts.length > 0) {
        let text = parts.join(', ');
        // Append day mapping unknown note when in normalized layer or status indicates it
        if (hoursStatus === 'day_mapping_unknown' || record.hours_status !== undefined) {
          text += ' (Chưa rõ quy ước thứ)';
        }
        return {
          text: text,
          className: '',
        };
      }
    }

    if (displayed && typeof displayed === 'string' && displayed.trim() !== '') {
      let text = displayed.trim();
      if (hoursStatus === 'day_mapping_unknown' || record.hours_status !== undefined) {
        if (!text.includes('Chưa rõ quy ước thứ')) {
          text += ' (Chưa rõ quy ước thứ)';
        }
      }
      return {
        text: text,
        className: '',
      };
    }

    if (typeof rawHours === 'string' && rawHours.trim() !== '') {
      let text = rawHours.trim();
      if (hoursStatus === 'day_mapping_unknown' || record.hours_status !== undefined) {
        if (!text.includes('Chưa rõ quy ước thứ')) {
          text += ' (Chưa rõ quy ước thứ)';
        }
      }
      return {
        text: text,
        className: '',
      };
    }

    return {
      text: 'Chưa có thông tin giờ mở cửa',
      className: 'null-value',
    };
  }

  function formatTimestamp(isoStr) {
    if (!isoStr) return '--';
    try {
      const dt = new Date(isoStr);
      if (isNaN(dt.getTime())) return isoStr;
      return dt.toLocaleTimeString('vi-VN') + ' ' + dt.toLocaleDateString('vi-VN');
    } catch (_) {
      return isoStr;
    }
  }

  // --- Browser Readiness UI ---
  function updateBrowserReadiness(ready, message) {
    if (!elements.browserDot) return;
    elements.browserDot.classList.remove('dot-checking', 'dot-ready', 'dot-not-ready');

    if (ready) {
      elements.browserDot.classList.add('dot-ready');
      elements.browserTitle.textContent = 'Trình duyệt tự động: Sẵn sàng';
      elements.browserMessage.textContent = safeText(message, 'Sử dụng Edge/Chromium trên máy tính');
    } else {
      elements.browserDot.classList.add('dot-not-ready');
      elements.browserTitle.textContent = 'Trình duyệt: Chưa sẵn sàng';
      elements.browserMessage.textContent = safeText(message, 'Cần cài đặt trình duyệt hỗ trợ để thu thập');
    }
  }

  // --- Form Controls Logic ---
  function handleModeChange() {
    const isSample = elements.modeSample.checked;
    if (isSample) {
      elements.inputLimit.disabled = false;
      elements.groupLimit.classList.remove('group-disabled');
      elements.scopeHint.textContent = 'Chế độ mẫu giới hạn số lượng quán để kiểm tra nhanh. Hoàn thành chế độ này là hoàn tất gói mẫu, không phải quét hết toàn bộ thành phố.';
    } else {
      elements.inputLimit.disabled = true;
      elements.groupLimit.classList.add('group-disabled');
      elements.scopeHint.textContent = 'Chế độ toàn bộ sẽ tự động tải tiếp cho đến khi duyệt hết danh sách trên Foody. Không giới hạn số lượng.';
    }
  }

  function validateInterval() {
    let val = parseFloat(elements.inputInterval.value);
    if (isNaN(val) || val < 2.0) {
      val = 2.0;
      elements.inputInterval.value = '2.0';
    }
    return val;
  }

  // --- Action Button State Controller ---
  function updateActionButtons(job) {
    const isRunning = job && job.state === 'running';
    const isPaused = job && job.state === 'paused';
    const isQueued = job && job.state === 'queued';
    const hasJob = Boolean(job);

    elements.btnStart.disabled = isRunning || isPaused || isQueued;
    elements.btnPause.disabled = !isRunning;
    elements.btnResume.disabled = !(isPaused || (hasJob && ['stopped', 'partial', 'blocked'].includes(job.state)));
    elements.btnStop.disabled = !(isRunning || isPaused || isQueued);
  }

  // --- Live Dashboard & Metrics Rendering ---
  function updateDashboard(job) {
    state.activeJob = job;
    updateActionButtons(job);

    if (!job) {
      elements.badgeJobState.className = 'badge badge-idle';
      elements.badgeJobState.textContent = 'Chưa hoạt động';
      elements.badgeJobStage.textContent = 'Chờ lệnh';
      elements.displayJobId.textContent = 'Chưa có';
      elements.displayJobMode.textContent = '--';
      elements.displayJobUpdated.textContent = '--';
      elements.terminationNotice.classList.add('hidden');
      elements.displayJobMessage.textContent = 'Hệ thống đang ở trạng thái chờ.';

      // Reset progress
      elements.progressStatusLabel.textContent = 'Tiến độ thu thập:';
      elements.progressCounterText.textContent = '0 / 48 (0%)';
      elements.progressFill.className = 'progress-fill pct-0';
      elements.progressExplanation.textContent = 'Chọn cấu hình và nhấn "Bắt đầu" để thực hiện.';

      // Reset metrics
      elements.metricDiscovered.textContent = '0';
      elements.metricProcessed.textContent = '0';
      elements.metricSuccess.textContent = '0';
      elements.metricDuplicates.textContent = '0';
      elements.metricFailed.textContent = '0';
      elements.metricClicks.textContent = '0';
      elements.metricRequests.textContent = '0';

      // If nothing selected yet, reset quality panel and download links
      if (!state.viewingJobId) {
        renderQualityPanelFallback(null);
        updateDownloadLinks(null);
        loadMediaForJob(null);
      }
      return;
    }

    // Set viewing job id to active job if not currently viewing another specific history job
    const isInitialLoad = !state.viewingJobId;
    if (!state.viewingJobId || state.viewingJobId === job.id) {
      state.viewingJobId = job.id;
      state.viewingJobData = job;
      renderQualityPanel(job.id, job);
      const hasQuality = computeHasQuality(job);
      const hasEnrichment = computeHasEnrichment(job);
      updateDownloadLinks(job.id, hasQuality, hasEnrichment);
      if (isInitialLoad && hasEnrichment) {
        state.currentLayer = 'enriched';
      }
      if (isInitialLoad) {
        loadMediaForJob(job.id);
      }
    }

    // State Badge
    const stateMeta = STATE_LABELS[job.state] || { text: job.state, class: 'badge-secondary' };
    let stateText = stateMeta.text;
    if (job.state === 'completed') {
      stateText = job.mode === 'sample' ? 'Hoàn thành mẫu' : 'Hoàn tất toàn bộ';
    }
    elements.badgeJobState.className = `badge ${stateMeta.class}`;
    elements.badgeJobState.textContent = stateText;

    // Stage Badge
    elements.badgeJobStage.textContent = STAGE_LABELS[job.stage] || safeText(job.stage, 'Chờ');

    // Meta Bar
    elements.displayJobId.textContent = safeText(job.id);
    elements.displayJobMode.textContent = job.mode === 'all' ? 'Toàn bộ Hà Nội' : 'Mẫu thử nghiệm';
    elements.displayJobUpdated.textContent = formatTimestamp(job.updated_at);

    // Metrics Values
    elements.metricDiscovered.textContent = Number(job.discovered || 0).toLocaleString('vi-VN');
    elements.metricProcessed.textContent = Number(job.processed || 0).toLocaleString('vi-VN');
    elements.metricSuccess.textContent = Number(job.success || 0).toLocaleString('vi-VN');
    elements.metricDuplicates.textContent = Number(job.duplicates || 0).toLocaleString('vi-VN');
    elements.metricFailed.textContent = Number(job.failed || 0).toLocaleString('vi-VN');
    elements.metricClicks.textContent = Number(job.clicks || 0).toLocaleString('vi-VN');
    elements.metricRequests.textContent = Number(job.request_count || 0).toLocaleString('vi-VN');

    // Message
    elements.displayJobMessage.textContent = safeText(job.message, 'Đang xử lý...');

    // Progress Bar Logic (Strict: No fake percent in all mode)
    const isSample = job.mode === 'sample';
    const isRunning = job.state === 'running';

    if (isSample) {
      const limit = job.limit || 48;
      const processed = job.processed || 0;
      const pct = Math.min(100, Math.max(0, Math.round((processed / limit) * 100)));

      elements.progressStatusLabel.textContent = 'Tiến độ thu thập (mẫu):';
      elements.progressCounterText.textContent = `${processed} / ${limit} (${pct}%)`;
      elements.progressBarContainer.setAttribute('aria-valuenow', pct);
      elements.progressFill.className = `progress-fill pct-${pct}${isRunning ? ' running' : ''}`;
      if (job.state === 'completed' || job.termination_reason === 'limit') {
        elements.progressExplanation.textContent = `Đã hoàn thành mẫu ${limit} địa điểm (chưa quét toàn bộ thành phố).`;
      } else {
        elements.progressExplanation.textContent = `Mục tiêu lấy tối đa ${limit} địa điểm để kiểm thử nhanh.`;
      }
    } else {
      // All mode: NO fake percent. Show clear discovered/processed counts.
      const discovered = job.discovered || 0;
      const processed = job.processed || 0;

      elements.progressStatusLabel.textContent = 'Tiến độ thu thập (toàn bộ):';
      elements.progressCounterText.textContent = `Đã phát hiện: ${discovered} | Đã xử lý: ${processed}`;
      elements.progressBarContainer.removeAttribute('aria-valuenow');

      if (isRunning) {
        elements.progressFill.className = 'progress-fill indeterminate';
        elements.progressExplanation.textContent = 'Chế độ toàn bộ: Trình duyệt liên tục tìm kiếm và tải thêm danh sách cho tới khi hết trang. Không tính phần trăm ước tính.';
      } else {
        elements.progressFill.className = 'progress-fill pct-100';
        elements.progressExplanation.textContent = `Chế độ toàn bộ: Đã xử lý ${processed} / ${discovered} liên kết tìm thấy.`;
      }
    }

    // Termination Notice & Incomplete / Verification Badges
    const isTerminated = ['stopped', 'completed', 'partial', 'error', 'blocked'].includes(job.state);
    const reasonKey = job.termination_reason;

    if (isTerminated || reasonKey) {
      const reasonMeta = (reasonKey && TERMINATION_REASONS[reasonKey]) || {
        title: 'Phiên kết thúc',
        desc: job.message || 'Phiên thu thập đã dừng lại.',
        incomplete: job.state !== 'completed',
      };

      elements.terminationNotice.classList.remove('hidden');
      elements.terminationTitle.textContent = reasonMeta.title;
      elements.terminationDesc.textContent = reasonMeta.desc;

      const isExplicitIncomplete = reasonMeta.incomplete || ['stalled', 'blocked', 'limit', 'stopped', 'error', 'timeout'].includes(reasonKey) || job.state === 'partial';

      if (isExplicitIncomplete && job.state !== 'completed') {
        elements.badgeIncomplete.classList.remove('hidden');
        elements.badgeIncomplete.textContent = '⚠️ Chưa hoàn thành đầy đủ';
      } else {
        elements.badgeIncomplete.classList.add('hidden');
      }

      if (job.coverage_verified) {
        elements.badgeCoverage.classList.remove('hidden');
        elements.badgeCoverage.textContent = '✓ Đã xác minh kết thúc trang';
      } else {
        elements.badgeCoverage.classList.add('hidden');
      }
    } else {
      elements.terminationNotice.classList.add('hidden');
    }

    renderLogs(job.logs);
  }

  // --- Safe Activity Log Rendering ---
  function renderLogs(logs) {
    if (!elements.logsContainer) return;
    elements.logsContainer.textContent = '';

    if (!Array.isArray(logs) || logs.length === 0) {
      const placeholder = document.createElement('div');
      placeholder.className = 'log-entry log-placeholder';
      placeholder.textContent = 'Chưa có nhật ký hoạt động.';
      elements.logsContainer.appendChild(placeholder);
      return;
    }

    logs.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'log-entry';

      const timeSpan = document.createElement('span');
      timeSpan.className = 'log-time';
      timeSpan.textContent = item.time ? `[${item.time}]` : '[--:--:--]';

      const textSpan = document.createElement('span');
      textSpan.className = 'log-text';
      textSpan.textContent = safeText(item.message, '');

      row.appendChild(timeSpan);
      row.appendChild(textSpan);
      elements.logsContainer.appendChild(row);
    });

    elements.logsContainer.scrollTop = elements.logsContainer.scrollHeight;
  }

  // --- Quality Panel Controller (v0.3) ---
  /**
   * Renders the quality panel for a specific job.
   * "Selected history quality must match selected job, not active job."
   */
  function renderQualityPanel(jobId, jobData) {
    if (elements.qualityViewingJob) {
      elements.qualityViewingJob.textContent = jobId || 'Chưa có';
    }

    const q = (jobData && jobData.report && jobData.report.quality) || null;
    const qs = (jobData && jobData.quality_summary) || null;
    const hasQuality = Boolean(q || qs);

    if (!hasQuality) {
      renderQualityPanelFallback(jobId);
      return;
    }

    // Quality data available
    if (elements.qualityLegacyAlert) {
      elements.qualityLegacyAlert.classList.add('hidden');
    }
    if (elements.badgeQualityLayer) {
      elements.badgeQualityLayer.classList.remove('hidden');
      elements.badgeQualityLayer.textContent = 'Dữ liệu chuẩn hóa (v0.3)';
    }
    if (elements.badgeQualityFallback) {
      elements.badgeQualityFallback.classList.add('hidden');
    }

    const priceCounts = (qs && qs.price_status_counts) || (q && q.price_status_counts) || {};
    const issueCounts = (qs && qs.issue_counts_by_severity) || (q && q.issue_counts_by_severity) || {};
    const elig = (qs && qs.eligibility) || (q && q.eligibility) || {};

    // 1. Price analysis
    if (elements.statPriceOk) {
      elements.statPriceOk.textContent = Number(priceCounts.ok || 0).toLocaleString('vi-VN');
    }
    if (elements.statPriceZero) {
      elements.statPriceZero.textContent = Number(priceCounts.unknown_zero || 0).toLocaleString('vi-VN');
    }
    if (elements.statPriceReversed) {
      elements.statPriceReversed.textContent = Number(priceCounts.invalid_range || 0).toLocaleString('vi-VN');
    }
    if (elements.statPriceOther) {
      const other = (priceCounts.partial_zero || 0) + (priceCounts.missing || 0) + (priceCounts.nonfinite || 0);
      elements.statPriceOther.textContent = Number(other).toLocaleString('vi-VN');
    }

    // 2. Issue severities
    const errCount = issueCounts.error || 0;
    const warnCount = issueCounts.warning || 0;
    const infoCount = issueCounts.info || 0;
    if (elements.statIssuesError) {
      elements.statIssuesError.textContent = Number(errCount).toLocaleString('vi-VN');
    }
    if (elements.statIssuesWarning) {
      elements.statIssuesWarning.textContent = Number(warnCount).toLocaleString('vi-VN');
    }
    if (elements.statIssuesInfo) {
      elements.statIssuesInfo.textContent = Number(infoCount).toLocaleString('vi-VN');
    }
    if (elements.badgeTotalIssues) {
      elements.badgeTotalIssues.textContent = `${Number(errCount + warnCount + infoCount).toLocaleString('vi-VN')} vấn đề`;
    }

    // 3. Eligibility
    function fmtElig(item, fallback = '0') {
      if (!item) return fallback;
      if (typeof item === 'object') {
        const num = item.num !== undefined ? item.num : 0;
        const den = item.den !== undefined ? item.den : 0;
        return `${Number(num).toLocaleString('vi-VN')} / ${Number(den).toLocaleString('vi-VN')}`;
      }
      return String(item);
    }

    if (elements.statEligSearch) {
      elements.statEligSearch.textContent = fmtElig(elig.search_eligible, '0');
    }
    if (elements.statEligLocation) {
      elements.statEligLocation.textContent = fmtElig(elig.location_eligible, '0');
    }
    if (elements.statEligPriceFilter) {
      elements.statEligPriceFilter.textContent = fmtElig(elig.price_filter_eligible, '0');
    }
    if (elements.statEligBudget) {
      elements.statEligBudget.textContent = '0 (Khoảng giá quán không phải ngân sách món)';
    }
    if (elements.statEligHours) {
      elements.statEligHours.textContent = '0 (Chưa rõ quy ước thứ - không kết luận đóng cửa)';
    }
  }

  function renderQualityPanelFallback(jobId) {
    if (elements.qualityViewingJob) {
      elements.qualityViewingJob.textContent = jobId || 'Chưa có';
    }
    if (elements.qualityLegacyAlert) {
      elements.qualityLegacyAlert.classList.remove('hidden');
    }
    if (elements.badgeQualityLayer) {
      elements.badgeQualityLayer.classList.add('hidden');
    }
    if (elements.badgeQualityFallback) {
      elements.badgeQualityFallback.classList.remove('hidden');
      elements.badgeQualityFallback.textContent = 'Chưa kiểm tra chất lượng (phiên cũ)';
    }

    // Reset stats to unverified state
    if (elements.statPriceOk) elements.statPriceOk.textContent = '--';
    if (elements.statPriceZero) elements.statPriceZero.textContent = '--';
    if (elements.statPriceReversed) elements.statPriceReversed.textContent = '--';
    if (elements.statPriceOther) elements.statPriceOther.textContent = '--';

    if (elements.statIssuesError) elements.statIssuesError.textContent = '--';
    if (elements.statIssuesWarning) elements.statIssuesWarning.textContent = '--';
    if (elements.statIssuesInfo) elements.statIssuesInfo.textContent = '--';
    if (elements.badgeTotalIssues) elements.badgeTotalIssues.textContent = 'Chưa kiểm tra';

    if (elements.statEligSearch) elements.statEligSearch.textContent = '--';
    if (elements.statEligLocation) elements.statEligLocation.textContent = '--';
    if (elements.statEligPriceFilter) elements.statEligPriceFilter.textContent = '--';
    if (elements.statEligBudget) elements.statEligBudget.textContent = 'Chưa kiểm tra';
    if (elements.statEligHours) elements.statEligHours.textContent = 'Chưa kiểm tra';
  }

  // --- Preview Table & Layer Switching ---
  /**
   * Load data preview for the viewing job.
   * Follows contract: Enriched preview if available, else normalized preview default if exists, old job fallback labeled not checked.
   */
  async function loadPreview(jobId) {
    if (!jobId) {
      renderEmptyPreview('Chưa chọn phiên thu thập nào.');
      return;
    }

    const preferredLayer = state.currentLayer;

    // 1. If preferred layer is enriched, try layer=enriched first
    if (preferredLayer === 'enriched') {
      try {
        const enrichedData = await apiGet(`/api/preview?job_id=${encodeURIComponent(jobId)}&layer=enriched&limit=500&offset=0`);
        if (enrichedData && Array.isArray(enrichedData.records) && enrichedData.records.length > 0) {
          state.allPreviewRecords = enrichedData.records;
          setLayerState('enriched');
          applyFiltersAndRender();
          return;
        }
      } catch (_) {
        // Fallback to normalized check
      }

      // If enriched returned empty or failed, try normalized layer fallback
      try {
        const normData = await apiGet(`/api/preview?job_id=${encodeURIComponent(jobId)}&layer=normalized&limit=50&offset=0`);
        if (normData && Array.isArray(normData.records) && normData.records.length > 0) {
          state.allPreviewRecords = normData.records;
          setLayerState('normalized');
          renderPreviewTable(normData.records, normData.total, 'normalized');
          return;
        }
      } catch (_) {
        // Fallback to legacy check
      }

      // If normalized layer returned empty or failed, try legacy layer fallback
      try {
        const legacyData = await apiGet(`/api/preview?job_id=${encodeURIComponent(jobId)}&limit=50&offset=0`);
        if (legacyData && Array.isArray(legacyData.records) && legacyData.records.length > 0) {
          state.allPreviewRecords = legacyData.records;
          setLayerState('raw_fallback');
          renderPreviewTable(legacyData.records, legacyData.total, 'raw_fallback');
          return;
        }
      } catch (_) {
        // No legacy records either
      }

      // Empty preview
      state.allPreviewRecords = [];
      setLayerState('enriched');
      renderEmptyPreview('Phiên này chưa có địa điểm nào được làm giàu thành công.');
      return;
    }

    // 2. If preferred layer is normalized, try layer=normalized first
    if (preferredLayer === 'normalized') {
      try {
        const normData = await apiGet(`/api/preview?job_id=${encodeURIComponent(jobId)}&layer=normalized&limit=50&offset=0`);
        if (normData && Array.isArray(normData.records) && normData.records.length > 0) {
          state.allPreviewRecords = normData.records;
          setLayerState('normalized');
          renderPreviewTable(normData.records, normData.total, 'normalized');
          return;
        }
      } catch (_) {
        // Fallback to legacy check
      }

      // If normalized layer returned empty or failed, try legacy layer fallback
      try {
        const legacyData = await apiGet(`/api/preview?job_id=${encodeURIComponent(jobId)}&limit=50&offset=0`);
        if (legacyData && Array.isArray(legacyData.records) && legacyData.records.length > 0) {
          state.allPreviewRecords = legacyData.records;
          setLayerState('raw_fallback');
          renderPreviewTable(legacyData.records, legacyData.total, 'raw_fallback');
          return;
        }
      } catch (_) {
        // No legacy records either
      }

      // Empty preview
      state.allPreviewRecords = [];
      setLayerState('normalized');
      renderEmptyPreview('Phiên này chưa có địa điểm nào được thu thập thành công.');
      return;
    }

    // 3. User explicitly selected raw layer (v1)
    try {
      const rawData = await apiGet(`/api/preview?job_id=${encodeURIComponent(jobId)}&limit=50&offset=0`);
      state.allPreviewRecords = (rawData && rawData.records) || [];
      setLayerState('raw');
      renderPreviewTable(rawData.records, rawData.total, 'raw');
    } catch (err) {
      console.warn('Lỗi tải bảng xem trước:', err);
      state.allPreviewRecords = [];
      renderEmptyPreview(`Không thể tải dữ liệu xem trước (${err.message})`);
    }
  }

  function setLayerState(mode) {
    if (mode === 'enriched') {
      if (elements.layerEnriched) elements.layerEnriched.checked = true;
      if (elements.badgePreviewLayer) {
        elements.badgePreviewLayer.className = 'badge badge-info';
        elements.badgePreviewLayer.textContent = 'Dữ liệu đã làm giàu (v0.4)';
      }
      if (elements.previewFilterToolbar) elements.previewFilterToolbar.classList.remove('hidden');
      if (elements.enrichmentDisclaimer) elements.enrichmentDisclaimer.classList.remove('hidden');
    } else if (mode === 'normalized') {
      if (elements.layerNormalized) elements.layerNormalized.checked = true;
      if (elements.badgePreviewLayer) {
        elements.badgePreviewLayer.className = 'badge badge-info';
        elements.badgePreviewLayer.textContent = 'Dữ liệu đã chuẩn hóa (v0.3)';
      }
      if (elements.previewFilterToolbar) elements.previewFilterToolbar.classList.add('hidden');
      if (elements.enrichmentDisclaimer) elements.enrichmentDisclaimer.classList.add('hidden');
    } else if (mode === 'raw_fallback') {
      if (elements.layerRaw) elements.layerRaw.checked = true;
      if (elements.badgePreviewLayer) {
        elements.badgePreviewLayer.className = 'badge badge-warning';
        elements.badgePreviewLayer.textContent = 'Chưa kiểm tra chất lượng (phiên cũ)';
      }
      if (elements.previewFilterToolbar) elements.previewFilterToolbar.classList.add('hidden');
      if (elements.enrichmentDisclaimer) elements.enrichmentDisclaimer.classList.add('hidden');
    } else {
      if (elements.layerRaw) elements.layerRaw.checked = true;
      if (elements.badgePreviewLayer) {
        elements.badgePreviewLayer.className = 'badge badge-secondary';
        elements.badgePreviewLayer.textContent = 'Dữ liệu gốc (v1)';
      }
      if (elements.previewFilterToolbar) elements.previewFilterToolbar.classList.add('hidden');
      if (elements.enrichmentDisclaimer) elements.enrichmentDisclaimer.classList.add('hidden');
    }
  }

  function ensureTableHeader(mode) {
    if (!elements.previewTheadRow) return;
    elements.previewTheadRow.textContent = '';

    if (mode === 'enriched') {
      const cols = [
        { text: 'STT', class: 'col-index' },
        { text: 'Tên quán', class: 'col-name' },
        { text: 'Điểm đánh giá', class: 'col-rating', title: 'Tín hiệu từ nền tảng Foody, không phải chứng nhận chất lượng đã kiểm định' },
        { text: 'Phong cách ẩm thực', class: 'col-cuisine' },
        { text: 'Thể loại', class: 'col-venue-type' },
        { text: 'Nhóm món', class: 'col-dish-group', title: 'Nhóm món là phân loại danh mục tổng quát, không phải thực đơn chi tiết' },
        { text: 'Bữa ăn thích hợp', class: 'col-suitable-meal' },
        { text: 'Phù hợp với', class: 'col-audience' },
        { text: 'Tiện ích (Có / Chưa xác nhận)', class: 'col-amenities', title: 'Tiện ích màu xanh là nền tảng ghi nhận có; tiện ích màu xám là chưa xác nhận (nền tảng không đánh dấu có, không phải xác minh là không có; platform-asserted, chưa kiểm định độc lập)' },
        { text: 'TG chuẩn bị', class: 'col-prep-time' },
        { text: 'Sức chứa', class: 'col-capacity' },
        { text: 'Địa chỉ', class: 'col-address' },
        { text: 'Quận', class: 'col-district' },
        { text: 'Khoảng giá quán', class: 'col-price', title: 'Khoảng giá toàn quán, không tương đương ngân sách một món' },
        { text: 'Giờ mở cửa', class: 'col-hours', title: 'Giờ nguồn tại thời điểm thu thập, không phải lịch tuần đã xác minh' },
        { text: 'Nguồn', class: 'col-link' }
      ];
      cols.forEach(col => {
        const th = document.createElement('th');
        th.scope = 'col';
        th.className = col.class;
        th.textContent = col.text;
        if (col.title) th.title = col.title;
        elements.previewTheadRow.appendChild(th);
      });
    } else {
      const cols = [
        { text: 'STT', class: 'col-index' },
        { text: 'Tên quán', class: 'col-name' },
        { text: 'Địa chỉ', class: 'col-address' },
        { text: 'Khoảng giá tham khảo', class: 'col-price' },
        { text: 'Giờ mở cửa', class: 'col-hours' },
        { text: 'Liên kết', class: 'col-link' }
      ];
      cols.forEach(col => {
        const th = document.createElement('th');
        th.scope = 'col';
        th.className = col.class;
        th.textContent = col.text;
        elements.previewTheadRow.appendChild(th);
      });
    }
  }

  function renderEmptyPreview(message) {
    elements.previewTbody.textContent = '';
    const tr = document.createElement('tr');
    tr.className = 'empty-row';
    const td = document.createElement('td');
    td.colSpan = (state.currentLayer === 'enriched') ? 14 : 6;
    td.className = 'text-center text-muted';
    td.textContent = message;
    tr.appendChild(td);
    elements.previewTbody.appendChild(tr);
    elements.previewTotalText.textContent = 'Hiển thị 0 địa điểm';
  }

  function renderPreviewTable(records, totalCount, layerMode) {
    ensureTableHeader('legacy');
    elements.previewTbody.textContent = '';

    const count = typeof totalCount === 'number' ? totalCount : (Array.isArray(records) ? records.length : 0);
    const suffix = layerMode === 'raw_fallback'
      ? ' · Chưa kiểm tra chất lượng (phiên cũ)'
      : (layerMode === 'normalized' ? ' · Đã chuẩn hóa v0.3' : ' · Dữ liệu gốc v1');
    elements.previewTotalText.textContent = `Hiển thị ${Array.isArray(records) ? records.length : 0} / ${count} địa điểm đã trích xuất${suffix}`;

    if (!Array.isArray(records) || records.length === 0) {
      renderEmptyPreview('Phiên này chưa có địa điểm nào được thu thập thành công.');
      return;
    }

    records.forEach((record, index) => {
      const tr = document.createElement('tr');

      // 1. STT
      const tdIndex = document.createElement('td');
      tdIndex.textContent = String(index + 1);
      tr.appendChild(tdIndex);

      // 2. Name
      const tdName = document.createElement('td');
      const nameVal = record.name;
      if (nameVal) {
        tdName.textContent = nameVal;
      } else {
        tdName.textContent = '(Chưa có tên)';
        tdName.className = 'null-value';
      }
      tr.appendChild(tdName);

      // 3. Address
      const tdAddress = document.createElement('td');
      let addrParts = [];
      if (record.address) addrParts.push(record.address);
      if (record.district && !String(record.address || '').includes(record.district)) {
        addrParts.push(record.district);
      }
      if (addrParts.length > 0) {
        tdAddress.textContent = addrParts.join(', ');
      } else {
        tdAddress.textContent = '(Chưa có thông tin)';
        tdAddress.className = 'null-value';
      }
      tr.appendChild(tdAddress);

      // 4. Price (Reversed/0 prices never usable in preview)
      const tdPrice = document.createElement('td');
      const priceInfo = getRecordPriceInfo(record);
      tdPrice.textContent = priceInfo.text;
      if (priceInfo.className) {
        tdPrice.className = priceInfo.className;
      }
      tr.appendChild(tdPrice);

      // 5. Opening Hours (All raw shifts with day mapping unknown note; never assumed closed)
      const tdHours = document.createElement('td');
      const hoursInfo = getRecordHoursInfo(record);
      tdHours.textContent = hoursInfo.text;
      if (hoursInfo.className) {
        tdHours.className = hoursInfo.className;
      }
      tr.appendChild(tdHours);

      // 6. Source Link
      const tdLink = document.createElement('td');
      const url = record.source_url;
      if (url && (url.startsWith('https://') || url.startsWith('http://'))) {
        const link = document.createElement('a');
        link.href = url;
        link.textContent = 'Mở Foody ↗';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        tdLink.appendChild(link);
      } else {
        tdLink.textContent = '--';
        tdLink.className = 'null-value';
      }
      tr.appendChild(tdLink);

      elements.previewTbody.appendChild(tr);
    });
  }

  function filterEnrichedRecords(records) {
    if (!Array.isArray(records)) return [];

    const cuisine = (elements.filterCuisine && elements.filterCuisine.value || '').trim().toLowerCase();
    const venueType = (elements.filterVenueType && elements.filterVenueType.value || '').trim().toLowerCase();
    const dishGroup = (elements.filterDishGroup && elements.filterDishGroup.value || '').trim().toLowerCase();
    const suitableMeal = (elements.filterSuitableMeal && elements.filterSuitableMeal.value || '').trim().toLowerCase();
    const audience = (elements.filterAudience && elements.filterAudience.value || '').trim().toLowerCase();

    const minRatingVal = elements.filterMinRating && elements.filterMinRating.value !== ''
      ? parseFloat(elements.filterMinRating.value) : null;
    const minReviewsVal = elements.filterMinReviews && elements.filterMinReviews.value !== ''
      ? parseInt(elements.filterMinReviews.value, 10) : null;

    const amenity = (elements.filterAmenity && elements.filterAmenity.value || '').trim().toLowerCase();
    const prepTime = (elements.filterPrepTime && elements.filterPrepTime.value || '').trim().toLowerCase();
    const capacityVal = elements.filterCapacity && elements.filterCapacity.value !== ''
      ? parseInt(elements.filterCapacity.value, 10) : null;

    return records.filter(r => {
      // 1. Cuisine style
      if (cuisine) {
        const val = String(r.cuisine_styles || '').toLowerCase();
        if (!val.includes(cuisine)) return false;
      }
      // 2. Venue type
      if (venueType) {
        const val = String(r.venue_types || '').toLowerCase();
        if (!val.includes(venueType)) return false;
      }
      // 3. Dish group
      if (dishGroup) {
        const val = String(r.dish_groups || '').toLowerCase();
        if (!val.includes(dishGroup)) return false;
      }
      // 4. Suitable meal
      if (suitableMeal) {
        const val = String(r.suitable_meals || '').toLowerCase();
        if (!val.includes(suitableMeal)) return false;
      }
      // 5. Audience
      if (audience) {
        const val = String(r.audiences || '').toLowerCase();
        if (!val.includes(audience)) return false;
      }
      // 6. Rating >= N (with review-count minimum)
      if (minRatingVal !== null) {
        if (r.rating_value === null || r.rating_value === undefined) return false;
        if (parseFloat(r.rating_value) < minRatingVal) return false;
      }
      if (minReviewsVal !== null) {
        if (r.review_count === null || r.review_count === undefined) return false;
        if (parseInt(r.review_count, 10) < minReviewsVal) return false;
      }
      // 7. Amenity yes filter (only status yes matches!)
      if (amenity) {
        const yesVal = String(r.amenities_yes || '').toLowerCase();
        if (!yesVal.includes(amenity)) return false;
      }
      // 8. Prep time
      if (prepTime) {
        const val = String(r.prep_time_raw || '').toLowerCase();
        const escaped = prepTime.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
                               .replace(/\b(\d+)\b/g, '(?<!\\d)$1(?!\\d)');
        try {
          const regex = new RegExp(escaped, 'i');
          if (!regex.test(val)) return false;
        } catch (e) {
          if (!val.includes(prepTime)) return false;
        }
      }
      // 9. Capacity
      if (capacityVal !== null) {
        const capNum = (r.capacity_value !== null && r.capacity_value !== undefined)
          ? parseInt(r.capacity_value, 10) : null;
        if (capNum !== null) {
          if (capNum < capacityVal) return false;
        } else {
          const raw = String(r.capacity_raw || '');
          const match = raw.match(/\d+/);
          if (!match || parseInt(match[0], 10) < capacityVal) return false;
        }
      }
      return true;
    });
  }

  function applyFiltersAndRender() {
    if (state.currentLayer !== 'enriched') {
      renderPreviewTable(state.allPreviewRecords, state.allPreviewRecords.length, state.currentLayer);
      return;
    }

    const filtered = filterEnrichedRecords(state.allPreviewRecords);
    renderEnrichedTable(filtered, state.allPreviewRecords.length);
  }

  function renderEnrichedTable(records, totalCount) {
    ensureTableHeader('enriched');
    elements.previewTbody.textContent = '';

    const count = typeof totalCount === 'number' ? totalCount : (Array.isArray(records) ? records.length : 0);
    const displayedCount = Array.isArray(records) ? records.length : 0;
    const isFiltered = displayedCount !== count;
    const filterSuffix = isFiltered ? ` (đã lọc ${displayedCount}/${count} địa điểm)` : '';
    elements.previewTotalText.textContent = `Hiển thị ${displayedCount} / ${count} địa điểm đã trích xuất · Đã làm giàu v0.4${filterSuffix}`;

    if (elements.filterStatusHint) {
      elements.filterStatusHint.textContent = isFiltered
        ? `Khớp ${displayedCount}/${count} địa điểm theo điều kiện lọc`
        : `Hiển thị tất cả ${count} địa điểm`;
    }

    if (!Array.isArray(records) || records.length === 0) {
      renderEmptyPreview(isFiltered ? 'Không có địa điểm nào phù hợp với bộ lọc đã chọn.' : 'Phiên này chưa có địa điểm nào được làm giàu thành công.');
      return;
    }

    records.forEach((record, index) => {
      const tr = document.createElement('tr');

      // 1. STT
      const tdIndex = document.createElement('td');
      tdIndex.textContent = String(index + 1);
      tr.appendChild(tdIndex);

      // 2. Name
      const tdName = document.createElement('td');
      if (record.name) {
        tdName.textContent = record.name;
      } else {
        tdName.textContent = '(Chưa có tên)';
        tdName.className = 'null-value';
      }
      tr.appendChild(tdName);

      // 3. Rating
      const tdRating = document.createElement('td');
      tdRating.className = 'rating-cell';
      if (record.rating_value !== null && record.rating_value !== undefined) {
        const scoreSpan = document.createElement('span');
        scoreSpan.className = 'rating-score';
        scoreSpan.textContent = `★ ${record.rating_value} / ${record.rating_scale_max || 10}`;
        scoreSpan.title = 'Tín hiệu từ nền tảng Foody, không phải chứng nhận chất lượng đã kiểm định';
        tdRating.appendChild(scoreSpan);

        if (record.review_count !== null && record.review_count !== undefined) {
          const countSpan = document.createElement('span');
          countSpan.className = 'rating-reviews';
          countSpan.textContent = `(${record.review_count} bình luận)`;
          tdRating.appendChild(countSpan);
        }
      } else {
        const noRating = document.createElement('span');
        noRating.className = 'null-value';
        noRating.textContent = 'Chưa có điểm';
        tdRating.appendChild(noRating);
      }
      tr.appendChild(tdRating);

      // 4. Cuisine style
      const tdCuisine = document.createElement('td');
      tdCuisine.className = 'cuisine-cell';
      tdCuisine.textContent = record.cuisine_styles || '--';
      if (!record.cuisine_styles) tdCuisine.className = 'null-value';
      tr.appendChild(tdCuisine);

      // 5. Venue type
      const tdVenue = document.createElement('td');
      tdVenue.className = 'venue-type-cell';
      tdVenue.textContent = record.venue_types || '--';
      if (!record.venue_types) tdVenue.className = 'null-value';
      tr.appendChild(tdVenue);

      // 6. Dish groups (Honest copy: categories, not itemized menu)
      const tdDish = document.createElement('td');
      tdDish.className = 'dish-group-cell';
      tdDish.textContent = record.dish_groups || '--';
      tdDish.title = 'Nhóm món là phân loại danh mục tổng quát, không phải thực đơn chi tiết';
      if (!record.dish_groups) tdDish.className = 'null-value';
      tr.appendChild(tdDish);

      // 7. Suitable meals
      const tdMeal = document.createElement('td');
      tdMeal.textContent = record.suitable_meals || '--';
      if (!record.suitable_meals) tdMeal.className = 'null-value';
      tr.appendChild(tdMeal);

      // 8. Audience
      const tdAudience = document.createElement('td');
      tdAudience.textContent = record.audiences || '--';
      if (!record.audiences) tdAudience.className = 'null-value';
      tr.appendChild(tdAudience);

      // 9. Amenities (yes / unknown; status no is never emitted)
      const tdAmenities = document.createElement('td');
      const amenContainer = document.createElement('div');
      amenContainer.className = 'amenities-container';

      const yesList = (record.amenities_yes || '').split(' | ').filter(Boolean);
      const noList = (record.amenities_no || '').split(' | ').filter(Boolean);
      const unkList = (record.amenities_unknown || '').split(' | ').filter(Boolean);

      // Never render any badge implying not available; legacy no items merge into unconfirmed
      const unkAll = [...unkList];
      for (const item of noList) {
        if (!unkAll.includes(item)) unkAll.push(item);
      }

      if (yesList.length === 0 && unkAll.length === 0) {
        tdAmenities.textContent = '--';
        tdAmenities.className = 'null-value';
      } else {
        yesList.forEach(item => {
          const badge = document.createElement('span');
          badge.className = 'amenity-badge amenity-yes';
          badge.textContent = `✓ ${item}`;
          badge.title = 'Nền tảng ghi nhận có (chưa kiểm định độc lập)';
          amenContainer.appendChild(badge);
        });
        unkAll.forEach(item => {
          const badge = document.createElement('span');
          badge.className = 'amenity-badge amenity-unknown';
          badge.textContent = `? ${item} (chưa xác nhận)`;
          badge.title = 'Nền tảng không đánh dấu có (chưa xác nhận), không phải xác minh là không có (platform did not mark it as offered, which is not verification that it is absent; chưa kiểm định độc lập)';
          amenContainer.appendChild(badge);
        });
        tdAmenities.appendChild(amenContainer);
      }
      tr.appendChild(tdAmenities);

      // 10. Prep time
      const tdPrep = document.createElement('td');
      tdPrep.textContent = record.prep_time_raw || '--';
      if (!record.prep_time_raw) tdPrep.className = 'null-value';
      tr.appendChild(tdPrep);

      // 11. Capacity
      const tdCap = document.createElement('td');
      tdCap.textContent = record.capacity_raw || (record.capacity_value ? `${record.capacity_value} người` : '--');
      if (!record.capacity_raw && !record.capacity_value) tdCap.className = 'null-value';
      tr.appendChild(tdCap);

      // 12. Address
      const tdAddress = document.createElement('td');
      tdAddress.className = 'col-address';
      tdAddress.textContent = record.address || 'Chưa có thông tin địa chỉ';
      if (!record.address) tdAddress.className += ' null-value';
      tr.appendChild(tdAddress);

      // 13. District
      const tdDistrict = document.createElement('td');
      tdDistrict.className = 'col-district';
      tdDistrict.textContent = record.district || '--';
      if (!record.district) tdDistrict.className += ' null-value';
      tr.appendChild(tdDistrict);

      // 14. Price (Venue range)
      const tdPrice = document.createElement('td');
      const priceInfo = getRecordPriceInfo(record);
      tdPrice.textContent = priceInfo.text;
      if (priceInfo.className) tdPrice.className = priceInfo.className;
      tdPrice.title = 'Khoảng giá toàn quán, không tương đương ngân sách một suất ăn';
      tr.appendChild(tdPrice);

      // 15. Hours
      const tdHours = document.createElement('td');
      const hoursInfo = getRecordHoursInfo(record);
      tdHours.textContent = hoursInfo.text;
      if (hoursInfo.className) tdHours.className = hoursInfo.className;
      tdHours.title = 'Giờ mở cửa nguồn, không phải lịch tuần đã xác minh';
      tr.appendChild(tdHours);

      // 14. Source Link (source_url)
      const tdLink = document.createElement('td');
      const url = record.source_url;
      if (url && (url.startsWith('https://') || url.startsWith('http://'))) {
        const link = document.createElement('a');
        link.href = url;
        link.textContent = 'Mở Foody ↗';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        tdLink.appendChild(link);
      } else {
        tdLink.textContent = '--';
        tdLink.className = 'null-value';
      }
      tr.appendChild(tdLink);

      elements.previewTbody.appendChild(tr);
    });
  }

  // --- Download Links Configuration ---
  function updateDownloadLinks(jobId, hasQuality = true, hasEnrichment = undefined) {
    if (!jobId) {
      setDownloadDisabled(elements.btnDownloadCsv, true);
      setDownloadDisabled(elements.btnDownloadJson, true);
      setDownloadDisabled(elements.btnDownloadReport, true);
      setDownloadDisabled(elements.btnDownloadNormCsv, true);
      setDownloadDisabled(elements.btnDownloadNormJson, true);
      setDownloadDisabled(elements.btnDownloadIssuesCsv, true);
      setDownloadDisabled(elements.btnDownloadIssuesJson, true);
      setDownloadDisabled(elements.btnDownloadQuality, true);
      setDownloadDisabled(elements.btnDownloadRaw, true);
      setDownloadDisabled(elements.btnDownloadEnrichedCsv, true);
      setDownloadDisabled(elements.btnDownloadEnrichedJson, true);
      setDownloadDisabled(elements.btnDownloadEnrichmentReport, true);
      if (elements.btnEnrichJob) elements.btnEnrichJob.disabled = true;
      return;
    }

    const viewingJob = (state.viewingJobData && state.viewingJobData.id === jobId)
      ? state.viewingJobData
      : (state.activeJob && state.activeJob.id === jobId ? state.activeJob : state.viewingJobData);

    if (hasQuality === undefined) {
      hasQuality = viewingJob ? computeHasQuality(viewingJob) : true;
    }

    if (hasEnrichment === undefined) {
      hasEnrichment = computeHasEnrichment(viewingJob);
    }

    // Legacy Downloads (always available)
    setDownloadHref(elements.btnDownloadCsv, `/api/download?job_id=${encodeURIComponent(jobId)}&format=csv`);
    setDownloadHref(elements.btnDownloadJson, `/api/download?job_id=${encodeURIComponent(jobId)}&format=json`);
    setDownloadHref(elements.btnDownloadReport, `/api/download?job_id=${encodeURIComponent(jobId)}&format=report`);

    // Quality v0.3 Downloads
    if (hasQuality) {
      setDownloadHref(elements.btnDownloadNormCsv, `/api/download?job_id=${encodeURIComponent(jobId)}&format=normalized_csv`);
      setDownloadHref(elements.btnDownloadNormJson, `/api/download?job_id=${encodeURIComponent(jobId)}&format=normalized`);
      setDownloadHref(elements.btnDownloadIssuesCsv, `/api/download?job_id=${encodeURIComponent(jobId)}&format=issues_csv`);
      setDownloadHref(elements.btnDownloadIssuesJson, `/api/download?job_id=${encodeURIComponent(jobId)}&format=issues`);
      setDownloadHref(elements.btnDownloadQuality, `/api/download?job_id=${encodeURIComponent(jobId)}&format=quality`);
      setDownloadHref(elements.btnDownloadRaw, `/api/download?job_id=${encodeURIComponent(jobId)}&format=raw`);
    } else {
      // Old jobs without quality files: disable v0.3 downloads
      setDownloadDisabled(elements.btnDownloadNormCsv, true);
      setDownloadDisabled(elements.btnDownloadNormJson, true);
      setDownloadDisabled(elements.btnDownloadIssuesCsv, true);
      setDownloadDisabled(elements.btnDownloadIssuesJson, true);
      setDownloadDisabled(elements.btnDownloadQuality, true);
      setDownloadDisabled(elements.btnDownloadRaw, true);
    }

    // Enriched v0.4 Downloads
    if (hasEnrichment) {
      setDownloadHref(elements.btnDownloadEnrichedCsv, `/api/download?job_id=${encodeURIComponent(jobId)}&format=enriched_csv`);
      setDownloadHref(elements.btnDownloadEnrichedJson, `/api/download?job_id=${encodeURIComponent(jobId)}&format=enriched`);
      setDownloadHref(elements.btnDownloadEnrichmentReport, `/api/download?job_id=${encodeURIComponent(jobId)}&format=enrichment_report`);
    } else {
      setDownloadDisabled(elements.btnDownloadEnrichedCsv, true);
      setDownloadDisabled(elements.btnDownloadEnrichedJson, true);
      setDownloadDisabled(elements.btnDownloadEnrichmentReport, true);
    }

    // Enrich button: enabled for any saved job when not active/running
    if (elements.btnEnrichJob) {
      const isRunning = state.activeJob && (state.activeJob.id === jobId) &&
        ['queued', 'running', 'paused'].includes(state.activeJob.state);
      elements.btnEnrichJob.disabled = !!isRunning;
    }
  }

  function setDownloadHref(el, href) {
    if (!el) return;
    el.href = href;
    el.removeAttribute('aria-disabled');
    el.classList.remove('btn-disabled');
  }

  function setDownloadDisabled(el, disabled) {
    if (!el) return;
    if (disabled) {
      el.href = '#';
      el.setAttribute('aria-disabled', 'true');
      el.classList.add('btn-disabled');
    } else {
      el.removeAttribute('aria-disabled');
      el.classList.remove('btn-disabled');
    }
  }

  // --- Job Selection (History & Active Sync) ---
  /**
   * Select a specific job to view in Quality Panel and Preview.
   * "Selected history quality must match selected job, not active job."
   */
  async function selectJob(jobId) {
    if (!jobId) return;
    state.viewingJobId = jobId;

    let jobData = null;
    try {
      const res = await apiGet(`/api/jobs/${encodeURIComponent(jobId)}`);
      jobData = res && res.job ? res.job : null;
    } catch (err) {
      console.warn(`Lỗi lấy chi tiết phiên ${jobId}:`, err);
    }

    if (jobData) {
      state.viewingJobData = jobData;
    } else if (!state.viewingJobData || state.viewingJobData.id !== jobId) {
      state.viewingJobData = null;
    }

    const currentJob = state.viewingJobData || jobData;
    const hasQuality = computeHasQuality(currentJob);
    const hasEnrichment = computeHasEnrichment(currentJob);

    renderQualityPanel(jobId, currentJob);
    updateDownloadLinks(jobId, hasQuality, hasEnrichment);

    if (hasEnrichment) {
      if (state.currentLayer !== 'raw') {
        state.currentLayer = 'enriched';
      }
    } else {
      if (state.currentLayer === 'enriched') {
        state.currentLayer = 'normalized';
      }
    }
    await loadPreview(jobId);
    await loadMediaForJob(jobId);
  }

  // --- Enrich Saved Job (POST /api/enrich) ---
  async function handleEnrichJob(targetJobId) {
    hideBanner();
    const jobId = targetJobId || state.viewingJobId || (state.activeJob && state.activeJob.id);
    if (!jobId) {
      showBanner('Vui lòng chọn một phiên đã lưu để làm giàu dữ liệu.', 'warning');
      return;
    }

    if (elements.btnEnrichJob) elements.btnEnrichJob.disabled = true;
    showBanner(`Đang làm giàu dữ liệu cho phiên ${jobId.substring(0, 8)} từ bộ nhớ đệm HTML...`, 'info');

    try {
      const res = await apiPost('/api/enrich', { job_id: jobId });
      const pagesParsed = res.pages_parsed || (res.report && res.report.pages_parsed) || 0;
      showBanner(`Làm giàu dữ liệu thành công! Đã trích xuất ${pagesParsed} trang.`, 'success');
      state.currentLayer = 'enriched';

      if (state.viewingJobData && state.viewingJobData.id === jobId) {
        state.viewingJobData.has_enrichment = true;
      }
      if (state.activeJob && state.activeJob.id === jobId) {
        state.activeJob.has_enrichment = true;
      }

      await selectJob(jobId);
      await loadHistory();

      // Ensure download buttons are explicitly updated and enabled without reload
      const currentJob = (state.viewingJobData && state.viewingJobData.id === jobId)
        ? state.viewingJobData
        : (state.activeJob && state.activeJob.id === jobId ? state.activeJob : null);
      const hasQuality = currentJob ? computeHasQuality(currentJob) : true;
      updateDownloadLinks(jobId, hasQuality, true);
    } catch (err) {
      showBanner(`Không thể làm giàu dữ liệu: ${err.message}`, 'danger');
    } finally {
      if (elements.btnEnrichJob) elements.btnEnrichJob.disabled = false;
    }
  }

  // --- Reclassify Saved Job (POST /api/quality) ---
  async function handleReclassifyQuality(targetJobId) {
    hideBanner();
    const jobId = targetJobId || state.viewingJobId || (state.activeJob && state.activeJob.id);
    if (!jobId) {
      showBanner('Vui lòng chọn một phiên để kiểm định dữ liệu.');
      return;
    }

    try {
      showBanner(`Đang kiểm định dữ liệu đã lưu cho phiên ${jobId}...`, 'info');
      const res = await apiPost('/api/quality', { job_id: jobId });
      showBanner(`Kiểm định chất lượng thành công cho phiên ${jobId}!`, 'success');
      // Refresh current viewing job with newly generated quality report
      await selectJob(jobId);
      await loadHistory();
    } catch (err) {
      showBanner(`Không thể kiểm định dữ liệu: ${err.message}`);
    }
  }

  // --- Session History Rendering ---
  async function loadHistory() {
    try {
      const data = await apiGet('/api/history');
      renderHistoryTable(data.jobs || []);
      state.historyLoaded = true;
    } catch (err) {
      console.warn('Lỗi tải lịch sử phiên:', err);
      elements.historyTbody.textContent = '';
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 6;
      td.className = 'text-center text-muted';
      td.textContent = `Không thể tải lịch sử phiên (${err.message})`;
      tr.appendChild(td);
      elements.historyTbody.appendChild(tr);
    }
  }

  function renderHistoryTable(jobs) {
    elements.historyTbody.textContent = '';

    if (!Array.isArray(jobs) || jobs.length === 0) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 6;
      td.className = 'text-center text-muted';
      td.textContent = 'Chưa có phiên thu thập nào được lưu trữ.';
      tr.appendChild(td);
      elements.historyTbody.appendChild(tr);
      return;
    }

    jobs.forEach((job) => {
      const tr = document.createElement('tr');

      // 1. Job ID
      const tdId = document.createElement('td');
      const code = document.createElement('code');
      code.className = 'meta-code';
      code.textContent = safeText(job.id);
      tdId.appendChild(code);
      tr.appendChild(tdId);

      // 2. Mode
      const tdMode = document.createElement('td');
      tdMode.textContent = job.mode === 'all' ? 'Toàn bộ' : 'Mẫu';
      tr.appendChild(tdMode);

      // 3. State
      const tdState = document.createElement('td');
      const stateMeta = STATE_LABELS[job.state] || { text: job.state, class: 'badge-secondary' };
      const badge = document.createElement('span');
      badge.className = `badge ${stateMeta.class}`;
      badge.textContent = job.state === 'completed' ? (job.mode === 'sample' ? 'Hoàn thành mẫu' : 'Hoàn tất toàn bộ') : stateMeta.text;
      tdState.appendChild(badge);
      tr.appendChild(tdState);

      // 4. Progress
      const tdProg = document.createElement('td');
      if (job.mode === 'sample') {
        tdProg.textContent = `${job.processed || 0} / ${job.limit || 48} quán`;
      } else {
        tdProg.textContent = `${job.processed || 0} / ${job.discovered || 0} quán`;
      }
      tr.appendChild(tdProg);

      // 5. Started At
      const tdTime = document.createElement('td');
      tdTime.textContent = formatTimestamp(job.started_at);
      tr.appendChild(tdTime);

      // 6. Action Buttons
      const tdActions = document.createElement('td');
      const actionGroup = document.createElement('div');
      actionGroup.className = 'table-action-group';

      // View Button (loads preview AND selected quality panel)
      const btnView = document.createElement('button');
      btnView.type = 'button';
      btnView.className = 'btn btn-secondary btn-sm';
      btnView.textContent = '👁 Xem dữ liệu';
      btnView.onclick = async () => {
        await selectJob(job.id);
      };
      actionGroup.appendChild(btnView);

      // Reclassify Quality Button
      const btnQuality = document.createElement('button');
      btnQuality.type = 'button';
      btnQuality.className = 'btn btn-outline btn-sm';
      btnQuality.textContent = '🛡️ Kiểm định';
      btnQuality.title = 'Kiểm định dữ liệu đã lưu (v0.3)';
      btnQuality.onclick = async () => {
        await handleReclassifyQuality(job.id);
      };
      actionGroup.appendChild(btnQuality);

      // Resume Button (for paused/stopped/partial jobs)
      const canResume = ['paused', 'stopped', 'partial', 'blocked'].includes(job.state);
      if (canResume) {
        const btnResumeJob = document.createElement('button');
        btnResumeJob.type = 'button';
        btnResumeJob.className = 'btn btn-success btn-sm';
        btnResumeJob.textContent = '⏯ Tiếp tục';
        btnResumeJob.onclick = async () => {
          await handleResume(job.id);
        };
        actionGroup.appendChild(btnResumeJob);
      }

      tdActions.appendChild(actionGroup);
      tr.appendChild(tdActions);

      elements.historyTbody.appendChild(tr);
    });
  }

  // --- API Actions ---
  async function handleStart() {
    hideBanner();
    const mode = elements.modeAll.checked ? 'all' : 'sample';
    const limit = parseInt(elements.inputLimit.value, 10) || 48;
    const interval = validateInterval();
    const showBrowser = elements.inputShowBrowser.checked;

    const payload = {
      mode: mode,
      limit: limit,
      interval: interval,
      show_browser: showBrowser,
    };

    try {
      elements.btnStart.disabled = true;
      const res = await apiPost('/api/start', payload);
      if (res && res.job) {
        state.activeJob = res.job;
        state.viewingJobId = res.job.id;
        state.viewingJobData = res.job;
        updateDashboard(res.job);
        showBanner(`Đã khởi tạo phiên thu thập thành công (${res.job.id})`, 'success');
        await loadPreview(res.job.id);
        await loadHistory();
      }
    } catch (err) {
      showBanner(`Không thể bắt đầu thu thập: ${err.message}`);
      updateActionButtons(state.activeJob);
    }
  }

  async function handlePause() {
    hideBanner();
    if (!state.activeJob || !state.activeJob.id) return;
    try {
      elements.btnPause.disabled = true;
      const res = await apiPost('/api/pause', { job_id: state.activeJob.id });
      if (res && res.job) {
        state.activeJob = res.job;
        updateDashboard(res.job);
        showBanner('Tiến trình đã tạm dừng. Bạn có thể nhấn Tiếp tục bất kỳ lúc nào.', 'info');
      }
    } catch (err) {
      showBanner(`Lỗi khi tạm dừng: ${err.message}`);
      updateActionButtons(state.activeJob);
    }
  }

  async function handleResume(targetJobId) {
    hideBanner();
    const jobId = targetJobId || (state.activeJob && state.activeJob.id) || state.viewingJobId;
    if (!jobId) {
      showBanner('Không xác định được phiên cần tiếp tục.');
      return;
    }

    try {
      elements.btnResume.disabled = true;
      const res = await apiPost('/api/resume', { job_id: jobId });
      if (res && res.job) {
        state.activeJob = res.job;
        state.viewingJobId = res.job.id;
        state.viewingJobData = res.job;
        updateDashboard(res.job);
        showBanner(`Đã tiếp tục phiên thu thập (${res.job.id}). Các quán đã lấy trước đó sẽ được bỏ qua.`, 'success');
        await loadHistory();
      }
    } catch (err) {
      showBanner(`Lỗi khi tiếp tục phiên: ${err.message}`);
      updateActionButtons(state.activeJob);
    }
  }

  async function handleStop() {
    hideBanner();
    if (!state.activeJob || !state.activeJob.id) return;
    try {
      elements.btnStop.disabled = true;
      const res = await apiPost('/api/stop', { job_id: state.activeJob.id });
      if (res && res.job) {
        state.activeJob = res.job;
        updateDashboard(res.job);
        showBanner(`Đã dừng phiên thu thập. Dữ liệu đã lấy được bảo toàn an toàn.`, 'info');
        await selectJob(res.job.id);
        await loadHistory();
      }
    } catch (err) {
      showBanner(`Lỗi khi dừng phiên: ${err.message}`);
      updateActionButtons(state.activeJob);
    }
  }

  async function handleShutdown() {
    hideBanner();
    try {
      if (elements.btnShutdown) {
        elements.btnShutdown.disabled = true;
      }
      stopPolling();
      const res = await apiPost('/api/shutdown', {});
      const closingMsg = (res && res.message) ? res.message : 'Đang lưu tiến độ và đóng ứng dụng.';
      showBanner(`${closingMsg} Bạn có thể đóng tab trình duyệt này.`, 'info');
      if (elements.displayJobMessage) {
        elements.displayJobMessage.textContent = closingMsg;
      }
      if (elements.browserTitle) {
        elements.browserTitle.textContent = 'Máy chủ đã dừng';
      }
      if (elements.browserMessage) {
        elements.browserMessage.textContent = 'Ứng dụng đã thoát an toàn.';
      }
      if (elements.browserDot) {
        elements.browserDot.className = 'indicator-dot dot-not-ready';
      }
      elements.btnStart.disabled = true;
      elements.btnPause.disabled = true;
      elements.btnResume.disabled = true;
      elements.btnStop.disabled = true;
    } catch (err) {
      showBanner(`Lỗi khi yêu cầu thoát: ${err.message}`);
      if (elements.btnShutdown) {
        elements.btnShutdown.disabled = false;
      }
    }
  }

  // --- Periodic Polling & Status Sync ---
  async function fetchStatus() {
    if (state.isPolling) return;
    state.isPolling = true;

    try {
      const data = await apiGet('/api/status');

      if (data && data.csrf_token) {
        state.csrfToken = data.csrf_token;
      }

      updateBrowserReadiness(data.browser_ready, data.browser_message);

      const prevJob = state.activeJob;
      const newJob = data.active_job || null;
      updateDashboard(newJob);

      // If active job has new records or changed state, update preview only if viewing active job
      if (newJob) {
        const hasCountChanged = !prevJob || prevJob.processed !== newJob.processed || prevJob.state !== newJob.state;
        if (hasCountChanged && (!state.viewingJobId || state.viewingJobId === newJob.id)) {
          loadPreview(newJob.id);
        }
      }

      if (prevJob && prevJob.state === 'running' && newJob && newJob.state !== 'running') {
        loadHistory();
      }
    } catch (err) {
      console.warn('Lỗi kiểm tra trạng thái máy chủ:', err.message);
      if (elements.browserTitle && elements.browserDot && elements.browserDot.classList.contains('dot-checking')) {
        updateBrowserReadiness(false, 'Không thể kết nối đến máy chủ cục bộ.');
      }
    } finally {
      state.isPolling = false;
    }
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    state.isPolling = false;
  }

  function startPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    fetchStatus();
    state.pollTimer = setInterval(fetchStatus, state.pollIntervalMs);
  }

  // --- Event Listeners Initialization ---
  function initEventListeners() {
    // Prevent Form Submit Reload (strict CSP compliance, no inline onsubmit)
    if (elements.collectorForm) {
      elements.collectorForm.addEventListener('submit', (e) => {
        e.preventDefault();
      });
    }

    // Mode Radio Change
    if (elements.modeSample) elements.modeSample.addEventListener('change', handleModeChange);
    if (elements.modeAll) elements.modeAll.addEventListener('change', handleModeChange);

    // Interval Input Validation
    if (elements.inputInterval) {
      elements.inputInterval.addEventListener('change', validateInterval);
      elements.inputInterval.addEventListener('blur', validateInterval);
    }

    // Control Buttons
    if (elements.btnStart) elements.btnStart.addEventListener('click', handleStart);
    if (elements.btnPause) elements.btnPause.addEventListener('click', handlePause);
    if (elements.btnResume) elements.btnResume.addEventListener('click', () => handleResume());
    if (elements.btnStop) elements.btnStop.addEventListener('click', handleStop);
    if (elements.btnRefresh) {
      elements.btnRefresh.addEventListener('click', async () => {
        await fetchStatus();
        if (state.viewingJobId) {
          await selectJob(state.viewingJobId);
        }
        await loadHistory();
      });
    }

    // Discreet Shutdown Button
    if (elements.btnShutdown) {
      elements.btnShutdown.addEventListener('click', handleShutdown);
    }

    // Preview Layer Radio Switching
    if (elements.layerEnriched) {
      elements.layerEnriched.addEventListener('change', () => {
        if (elements.layerEnriched.checked) {
          state.currentLayer = 'enriched';
          const targetId = state.viewingJobId || (state.activeJob && state.activeJob.id);
          if (targetId) loadPreview(targetId);
        }
      });
    }
    if (elements.layerNormalized) {
      elements.layerNormalized.addEventListener('change', () => {
        if (elements.layerNormalized.checked) {
          state.currentLayer = 'normalized';
          const targetId = state.viewingJobId || (state.activeJob && state.activeJob.id);
          if (targetId) loadPreview(targetId);
        }
      });
    }
    if (elements.layerRaw) {
      elements.layerRaw.addEventListener('change', () => {
        if (elements.layerRaw.checked) {
          state.currentLayer = 'raw';
          const targetId = state.viewingJobId || (state.activeJob && state.activeJob.id);
          if (targetId) loadPreview(targetId);
        }
      });
    }

    // Enrich Job Button
    if (elements.btnEnrichJob) {
      elements.btnEnrichJob.addEventListener('click', () => {
        const targetId = state.viewingJobId || (state.activeJob && state.activeJob.id);
        handleEnrichJob(targetId);
      });
    }

    // Filter Inputs (v0.4)
    const filterInputs = [
      elements.filterCuisine,
      elements.filterVenueType,
      elements.filterDishGroup,
      elements.filterSuitableMeal,
      elements.filterAudience,
      elements.filterMinRating,
      elements.filterMinReviews,
      elements.filterAmenity,
      elements.filterPrepTime,
      elements.filterCapacity,
    ];
    filterInputs.forEach((el) => {
      if (el) {
        el.addEventListener('input', applyFiltersAndRender);
        el.addEventListener('change', applyFiltersAndRender);
      }
    });

    // Reset Filters Button
    if (elements.btnResetFilters) {
      elements.btnResetFilters.addEventListener('click', () => {
        filterInputs.forEach((el) => {
          if (el) el.value = '';
        });
        applyFiltersAndRender();
      });
    }

    // Preview Refresh
    if (elements.btnRefreshPreview) {
      elements.btnRefreshPreview.addEventListener('click', () => {
        const targetId = state.viewingJobId || (state.activeJob && state.activeJob.id);
        if (targetId) loadPreview(targetId);
      });
    }

    // History Refresh
    if (elements.btnRefreshHistory) {
      elements.btnRefreshHistory.addEventListener('click', loadHistory);
    }

    // Reclassify Quality Button on Legacy Fallback Box
    if (elements.btnReclassifyQuality) {
      elements.btnReclassifyQuality.addEventListener('click', () => {
        const targetId = state.viewingJobId || (state.activeJob && state.activeJob.id);
        handleReclassifyQuality(targetId);
      });
    }

    // Close Notification Banner
    if (elements.btnCloseBanner) {
      elements.btnCloseBanner.addEventListener('click', hideBanner);
    }

    // Section 2.8: Menu & Media Event Listeners (v0.5)
    if (elements.btnMediaScan) {
      elements.btnMediaScan.addEventListener('click', handleMediaScan);
    }
    if (elements.btnMediaCollect) {
      elements.btnMediaCollect.addEventListener('click', handleMediaCollect);
    }
    if (elements.btnMediaOcr) elements.btnMediaOcr.addEventListener('click', handleMediaOcr);
    if (elements.btnMediaDlOcrCsv) elements.btnMediaDlOcrCsv.addEventListener('click', () => handleMediaDownload('menu_ocr_csv'));
    if (elements.btnMediaDlOcrJson) elements.btnMediaDlOcrJson.addEventListener('click', () => handleMediaDownload('menu_ocr_json'));
    if (elements.btnMediaImages) {
      elements.btnMediaImages.addEventListener('click', handleMediaImages);
    }
    if (elements.btnMediaPause) {
      elements.btnMediaPause.addEventListener('click', () => handleMediaControl('pause'));
    }
    if (elements.btnMediaResume) {
      elements.btnMediaResume.addEventListener('click', () => handleMediaControl('resume'));
    }
    if (elements.btnMediaStop) {
      elements.btnMediaStop.addEventListener('click', () => handleMediaControl('stop'));
    }

    // Media Downloads
    if (elements.btnMediaDlMenuCsv) {
      elements.btnMediaDlMenuCsv.addEventListener('click', () => handleMediaDownload('menu_csv'));
    }
    if (elements.btnMediaDlMenuJson) {
      elements.btnMediaDlMenuJson.addEventListener('click', () => handleMediaDownload('menu_json'));
    }
    if (elements.btnMediaDlPhotosCsv) {
      elements.btnMediaDlPhotosCsv.addEventListener('click', () => handleMediaDownload('photos_csv'));
    }
    if (elements.btnMediaDlPhotosJson) {
      elements.btnMediaDlPhotosJson.addEventListener('click', () => handleMediaDownload('photos_json'));
    }
    if (elements.btnMediaDlMenuImagesCsv) {
      elements.btnMediaDlMenuImagesCsv.addEventListener('click', () => handleMediaDownload('menu_images_csv'));
    }
    if (elements.btnMediaDlVenuesCsv) {
      elements.btnMediaDlVenuesCsv.addEventListener('click', () => handleMediaDownload('venues_csv'));
    }
    if (elements.btnMediaDlArchive) {
      elements.btnMediaDlArchive.addEventListener('click', () => handleMediaDownload('archive'));
    }

    // Media Scope Radios
    const scopeRadios = [elements.scopeSelected, elements.scopeMenuImages, elements.scopeAll];
    scopeRadios.forEach((radio) => {
      if (radio) {
        radio.addEventListener('change', () => {
          if (radio.checked) {
            state.mediaScopeMode = radio.value;
            if (state.mediaStatus && state.mediaStatus.summary) {
              updateScopeCounts(state.mediaStatus.summary);
            }
          }
        });
      }
    });

    // Mark limits touched on user edits
    const limitInputs = [
      elements.inputMediaMaxImagesPerVenue,
      elements.inputMediaMaxTotalImages,
      elements.inputMediaMaxBytesPerImageMb,
      elements.inputMediaMaxTotalMb,
      elements.inputMediaMaxPages,
      elements.inputMediaInterval,
    ];
    limitInputs.forEach((inp) => {
      if (inp) {
        inp.addEventListener('input', () => { state.mediaLimitsTouched = true; });
        inp.addEventListener('change', () => { state.mediaLimitsTouched = true; });
      }
    });

    // Venues Search & Filter
    if (elements.inputMediaSearch) {
      let searchTimeout = null;
      elements.inputMediaSearch.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          state.mediaQuery = elements.inputMediaSearch.value;
          state.mediaOffset = 0;
          if (state.viewingJobId) loadMediaVenues(state.viewingJobId);
        }, 300);
      });
    }

    if (elements.selectMediaFilter) {
      elements.selectMediaFilter.addEventListener('change', () => {
        state.mediaFilter = elements.selectMediaFilter.value;
        state.mediaOffset = 0;
        if (state.viewingJobId) loadMediaVenues(state.viewingJobId);
      });
    }

    if (elements.selectMediaLimit) {
      elements.selectMediaLimit.addEventListener('change', () => {
        state.mediaLimit = parseInt(elements.selectMediaLimit.value, 10) || 25;
        state.mediaOffset = 0;
        if (state.viewingJobId) loadMediaVenues(state.viewingJobId);
      });
    }

    // Paging
    if (elements.btnMediaPrev) {
      elements.btnMediaPrev.addEventListener('click', () => {
        if (state.mediaOffset > 0) {
          state.mediaOffset = Math.max(0, state.mediaOffset - state.mediaLimit);
          if (state.viewingJobId) loadMediaVenues(state.viewingJobId);
        }
      });
    }

    if (elements.btnMediaNext) {
      elements.btnMediaNext.addEventListener('click', () => {
        if (state.mediaOffset + state.mediaLimit < state.mediaVenuesTotal) {
          state.mediaOffset += state.mediaLimit;
          if (state.viewingJobId) loadMediaVenues(state.viewingJobId);
        }
      });
    }

    // Select Page / Clear Selection
    if (elements.btnMediaSelectPage) {
      elements.btnMediaSelectPage.addEventListener('click', () => {
        state.mediaVenues.forEach(v => state.mediaSelectedVenueIds.add(String(v.venue_id)));
        renderMediaVenuesTable();
        if (state.mediaStatus && state.mediaStatus.summary) {
          updateScopeCounts(state.mediaStatus.summary);
        }
      });
    }

    if (elements.btnMediaClearSelection) {
      elements.btnMediaClearSelection.addEventListener('click', () => {
        state.mediaSelectedVenueIds.clear();
        renderMediaVenuesTable();
        if (state.mediaStatus && state.mediaStatus.summary) {
          updateScopeCounts(state.mediaStatus.summary);
        }
      });
    }

    if (elements.chkMediaSelectAllPage) {
      elements.chkMediaSelectAllPage.addEventListener('change', () => {
        const isChecked = elements.chkMediaSelectAllPage.checked;
        state.mediaVenues.forEach((v) => {
          if (isChecked) {
            state.mediaSelectedVenueIds.add(String(v.venue_id));
          } else {
            state.mediaSelectedVenueIds.delete(String(v.venue_id));
          }
        });
        renderMediaVenuesTable();
        if (state.mediaStatus && state.mediaStatus.summary) {
          updateScopeCounts(state.mediaStatus.summary);
        }
      });
    }

    // Modal Close
    if (elements.btnCloseVenueDetail) {
      elements.btnCloseVenueDetail.addEventListener('click', closeVenueDetail);
    }
    if (elements.venueDetailBackdrop) {
      elements.venueDetailBackdrop.addEventListener('click', closeVenueDetail);
    }
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeVenueDetail();
      }
    });

    // Detail Tabs
    if (elements.tabBtnPhotos && elements.tabBtnMenu) {
      elements.tabBtnPhotos.addEventListener('click', () => {
        elements.tabBtnPhotos.classList.add('active');
        elements.tabBtnPhotos.setAttribute('aria-selected', 'true');
        elements.tabBtnMenu.classList.remove('active');
        elements.tabBtnMenu.setAttribute('aria-selected', 'false');
        if (elements.tabPanelPhotos) elements.tabPanelPhotos.classList.remove('hidden');
        if (elements.tabPanelMenu) elements.tabPanelMenu.classList.add('hidden');
      });

      elements.tabBtnMenu.addEventListener('click', () => {
        elements.tabBtnMenu.classList.add('active');
        elements.tabBtnMenu.setAttribute('aria-selected', 'true');
        elements.tabBtnPhotos.classList.remove('active');
        elements.tabBtnPhotos.setAttribute('aria-selected', 'false');
        if (elements.tabPanelMenu) elements.tabPanelMenu.classList.remove('hidden');
        if (elements.tabPanelPhotos) elements.tabPanelPhotos.classList.add('hidden');
      });
    }
  }

  // ==========================================================================
  // Section 2.8: Menu & Media Management Functions (v0.5)
  // ==========================================================================

  const MEDIA_MENU_STATUS_LABELS = {
    not_collected: { text: 'Chưa thu thập', class: 'badge-secondary' },
    empty_confirmed: { text: 'Nguồn trả về thực đơn chữ trống', class: 'badge-warning' },
    blocked: { text: 'Bị chặn', class: 'badge-danger' },
    error: { text: 'Lỗi tạm thời', class: 'badge-danger' },
  };

  const MEDIA_STOP_REASONS = {
    user_stop: 'Người dùng dừng tiến trình.',
    max_pages: 'Đạt giới hạn số trang tối đa.',
    max_total_mb: 'Đạt giới hạn dung lượng tải tối đa.',
  };

  function translateMediaStopReason(reason) {
    if (!reason) return '';
    if (MEDIA_STOP_REASONS[reason]) return MEDIA_STOP_REASONS[reason];
    if (typeof reason === 'string' && reason.startsWith('blocked')) {
      return `Nguồn chặn hoặc yêu cầu xác minh (${reason}). Đã dừng, không vượt qua.`;
    }
    return String(reason);
  }

  function formatBytes(bytes) {
    if (bytes === null || bytes === undefined || isNaN(bytes) || bytes <= 0) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function setBtnDisabled(el, disabled) {
    if (!el) return;
    el.disabled = Boolean(disabled);
    if (disabled) {
      el.setAttribute('aria-disabled', 'true');
      el.classList.add('btn-disabled');
    } else {
      el.removeAttribute('aria-disabled');
      el.classList.remove('btn-disabled');
    }
  }

  async function loadMediaForJob(jobId) {
    if (!jobId) {
      if (elements.mediaEmptyAlert) elements.mediaEmptyAlert.classList.remove('hidden');
      if (elements.mediaMainContent) elements.mediaMainContent.classList.add('hidden');
      if (elements.mediaViewingJob) elements.mediaViewingJob.textContent = 'Chưa chọn phiên';
      stopMediaPolling();
      updateMediaDownloadButtons(false, {});
      return;
    }

    if (elements.mediaEmptyAlert) elements.mediaEmptyAlert.classList.add('hidden');
    if (elements.mediaMainContent) elements.mediaMainContent.classList.remove('hidden');
    if (elements.mediaViewingJob) elements.mediaViewingJob.textContent = jobId;

    // Reset selection and paging when switching jobs
    if (state.mediaLastJobId !== jobId) {
      state.mediaLastJobId = jobId;
      state.mediaOffset = 0;
      state.mediaSelectedVenueIds.clear();
      state.mediaDefaultSelectionDone = false;
      state.mediaLimitsTouched = false;
    }

    await fetchMediaStatus(jobId);
    await loadMediaVenues(jobId);
  }

  async function fetchMediaStatus(jobId) {
    if (!jobId) return;
    try {
      const res = await apiGet(`/api/media/status?job_id=${encodeURIComponent(jobId)}`);
      state.mediaStatus = res;
      renderMediaStatus(res);
      return res;
    } catch (err) {
      console.warn(`[Media Status] Lỗi tải trạng thái phiên ${jobId}:`, err);
    }
  }

  function renderMediaStatus(res) {
    if (!res) return;
    const { scanned, summary, task, limits } = res;
    const sum = summary || {};

    // Header scanned badge
    if (elements.badgeMediaScanned) {
      if (scanned) {
        elements.badgeMediaScanned.textContent = 'Đã quét dữ liệu';
        elements.badgeMediaScanned.className = 'badge badge-success';
      } else {
        elements.badgeMediaScanned.textContent = 'Chưa quét dữ liệu';
        elements.badgeMediaScanned.className = 'badge badge-secondary';
      }
    }

    // Populate Limits form defaults from API limits if user hasn't touched the form
    if (limits && !state.mediaLimitsTouched) {
      if (elements.inputMediaMaxImagesPerVenue && limits.max_images_per_venue !== undefined) {
        elements.inputMediaMaxImagesPerVenue.value = limits.max_images_per_venue;
      }
      if (elements.inputMediaMaxTotalImages && limits.max_total_images !== undefined) {
        elements.inputMediaMaxTotalImages.value = limits.max_total_images;
      }
      if (elements.inputMediaMaxBytesPerImageMb && limits.max_bytes_per_image !== undefined) {
        elements.inputMediaMaxBytesPerImageMb.value = Math.round(limits.max_bytes_per_image / (1024 * 1024));
      }
      if (elements.inputMediaMaxTotalMb && limits.max_total_mb !== undefined) {
        elements.inputMediaMaxTotalMb.value = limits.max_total_mb;
      }
      if (elements.inputMediaMaxPages && limits.max_pages !== undefined) {
        elements.inputMediaMaxPages.value = limits.max_pages;
      }
    }

    // Render Coverage Cards (Requirement 5)
    renderMediaCoverage(sum);

    // Update Scope Counts (Requirement 2)
    updateScopeCounts(sum);

    // Update Download Buttons (Requirement 1 & 17)
    updateMediaDownloadButtons(scanned, sum);

    // Render Task (Requirement 4)
    renderMediaTask(task);
  }

  function renderMediaCoverage(sum) {
    // Card 1: Venues & Cache
    if (elements.covVenuesTotal) elements.covVenuesTotal.textContent = String(sum.venues_total || 0);
    if (elements.covVenuesCached) elements.covVenuesCached.textContent = String(sum.venues_with_cached_page || 0);
    if (elements.covVenuesDelivery) elements.covVenuesDelivery.textContent = String(sum.venues_delivery_listed || 0);
    if (elements.covPagesFetched) elements.covPagesFetched.textContent = String(sum.pages_fetched || 0);

    if (elements.covDeliveryBadgeBox) {
      if ((sum.venues_delivery_listed || 0) > 0) {
        elements.covDeliveryBadgeBox.classList.remove('hidden');
      } else {
        elements.covDeliveryBadgeBox.classList.add('hidden');
      }
    }

    // Card 2: Menu Text States
    const textStates = sum.menu_text_states || {};
    if (elements.covMenuNotCollected) elements.covMenuNotCollected.textContent = String(textStates.not_collected || 0);
    if (elements.covMenuEmpty) elements.covMenuEmpty.textContent = String(textStates.empty_confirmed || 0);
    if (elements.covMenuBlocked) elements.covMenuBlocked.textContent = String(textStates.blocked || 0);
    if (elements.covMenuError) elements.covMenuError.textContent = String(textStates.error || 0);

    if (elements.covMenuItemsSummary) {
      const vCount = sum.venues_with_menu_items || 0;
      const mCount = sum.menu_items_total || 0;
      elements.covMenuItemsSummary.textContent = `${vCount} quán (${mCount} món)`;
    }

    // Card 3: Photos & Albums
    if (elements.covVenuesMenuDeclared) elements.covVenuesMenuDeclared.textContent = String(sum.venues_menu_album_declared || 0);
    if (elements.covMenuImagesKnown) elements.covMenuImagesKnown.textContent = String(sum.menu_images_known || 0);
    if (elements.covVenuesPhotosDeclared) elements.covVenuesPhotosDeclared.textContent = String(sum.venues_with_photos_declared || 0);

    if (elements.covPhotosKnownSummary) {
      const pCount = sum.photos_known || 0;
      const pvCount = sum.venues_with_photos_known || 0;
      elements.covPhotosKnownSummary.textContent = `${pCount} ảnh (${pvCount} quán)`;
    }

    if (elements.covPhotosDownloadedSummary) {
      const dlCount = (sum.photo_download_states && sum.photo_download_states.ok) || 0;
      const dlBytes = formatBytes(sum.bytes_downloaded || 0);
      elements.covPhotosDownloadedSummary.textContent = `${dlCount} ảnh (${dlBytes})`;
    }
  }

  function updateScopeCounts(sum) {
    const selectedCount = state.mediaSelectedVenueIds.size;
    const menuImagesCount = sum.venues_menu_album_declared || 0;
    const allCount = sum.venues_total || 0;

    if (elements.scopeCountSelected) elements.scopeCountSelected.textContent = String(selectedCount);
    if (elements.scopeCountMenuImages) elements.scopeCountMenuImages.textContent = String(menuImagesCount);
    if (elements.scopeCountAll) elements.scopeCountAll.textContent = String(allCount);

    let activeCount = 0;
    if (state.mediaScopeMode === 'selected') {
      activeCount = selectedCount;
    } else if (state.mediaScopeMode === 'menu_images') {
      activeCount = menuImagesCount;
    } else if (state.mediaScopeMode === 'all') {
      activeCount = allCount;
    }

    if (elements.displayScopeCount) {
      elements.displayScopeCount.textContent = String(activeCount);
    }

    // Show guard confirmation checkbox when activeCount > 25
    if (elements.mediaScopeConfirmBox) {
      if (activeCount > 25) {
        elements.mediaScopeConfirmBox.classList.remove('hidden');
      } else {
        elements.mediaScopeConfirmBox.classList.add('hidden');
      }
    }
  }

  function updateMediaDownloadButtons(scanned, sum) {
    const isScanned = Boolean(scanned);
    const hasVenues = Boolean(isScanned && ((sum.venues_total || 0) > 0));
    const hasPhotos = Boolean(isScanned && ((sum.photos_known || 0) > 0));
    const hasMenuImages = Boolean(isScanned && ((sum.menu_images_known || 0) > 0));
    const hasMenuItems = Boolean(isScanned && ((sum.menu_items_total || 0) > 0));
    const hasDownloadedPhotos = Boolean(isScanned && sum.photo_download_states && ((sum.photo_download_states.ok || 0) > 0));

    setBtnDisabled(elements.btnMediaDlVenuesCsv, !hasVenues);
    setBtnDisabled(elements.btnMediaDlPhotosCsv, !hasPhotos);
    setBtnDisabled(elements.btnMediaDlPhotosJson, !hasPhotos);
    setBtnDisabled(elements.btnMediaDlMenuImagesCsv, !hasMenuImages);
    setBtnDisabled(elements.btnMediaDlMenuCsv, !hasMenuItems);
    setBtnDisabled(elements.btnMediaDlMenuJson, !hasMenuItems);
    setBtnDisabled(elements.btnMediaDlArchive, !hasDownloadedPhotos);
  }

  function renderMediaTask(task) {
    if (!task) {
      if (elements.badgeMediaTaskState) elements.badgeMediaTaskState.classList.add('hidden');
      if (elements.mediaTaskProgressBox) elements.mediaTaskProgressBox.classList.add('hidden');
      setBtnDisabled(elements.btnMediaPause, true);
      setBtnDisabled(elements.btnMediaResume, true);
      setBtnDisabled(elements.btnMediaStop, true);
      setBtnDisabled(elements.btnMediaScan, false);
      setBtnDisabled(elements.btnMediaCollect, false);
      setBtnDisabled(elements.btnMediaImages, false);
      stopMediaPolling();
      return;
    }

    if (elements.badgeMediaTaskState) elements.badgeMediaTaskState.classList.remove('hidden');
    if (elements.mediaTaskProgressBox) elements.mediaTaskProgressBox.classList.remove('hidden');

    const stateMeta = STATE_LABELS[task.state] || { text: task.state, class: 'badge-secondary' };
    if (elements.badgeMediaTaskState) {
      elements.badgeMediaTaskState.className = `badge ${stateMeta.class}`;
      elements.badgeMediaTaskState.textContent = stateMeta.text;
    }
    if (elements.mediaTaskStateBadge) {
      elements.mediaTaskStateBadge.className = `badge ${stateMeta.class}`;
      elements.mediaTaskStateBadge.textContent = stateMeta.text;
    }

    if (elements.mediaTaskKindBadge) {
      elements.mediaTaskKindBadge.textContent = task.kind === 'collect' ? 'Thu thập menu & danh sách ảnh' : (task.kind === 'ocr' ? 'OCR ảnh thực đơn (thử nghiệm)' : 'Tải hình ảnh về máy');
    }

    if (elements.mediaTaskMsg) {
      elements.mediaTaskMsg.textContent = task.message || (task.state === 'running' ? 'Đang thực hiện...' : '');
    }

    const counts = task.counts || {};
    const vTotal = counts.venues_total || 0;
    const vDone = counts.venues_done || 0;
    const pct = vTotal > 0 ? Math.min(100, Math.round((vDone / vTotal) * 100)) : 0;

    if (elements.mediaProgressCounter) elements.mediaProgressCounter.textContent = `${vDone} / ${vTotal} (${pct}%)`;
    if (elements.mediaProgressFill) {
      elements.mediaProgressFill.className = `progress-fill pct-${Math.min(100, Math.max(0, pct))}`;
    }

    if (elements.mediaMetricVenuesDone) elements.mediaMetricVenuesDone.textContent = `${vDone} / ${vTotal}`;
    if (elements.mediaMetricPageReqs) elements.mediaMetricPageReqs.textContent = String(counts.page_requests || 0);
    if (elements.mediaMetricPageBytesLabel) {
      elements.mediaMetricPageBytesLabel.textContent = `Yêu cầu trang (${formatBytes(counts.page_bytes || 0)})`;
    }
    if (elements.mediaMetricImageReqs) elements.mediaMetricImageReqs.textContent = String(counts.image_requests || 0);
    if (elements.mediaMetricImageBytesLabel) {
      elements.mediaMetricImageBytesLabel.textContent = `Yêu cầu ảnh (${formatBytes(counts.image_bytes || 0)})`;
    }
    if (elements.mediaMetricApiReqs) elements.mediaMetricApiReqs.textContent = '0';
    if (elements.mediaMetricMenuItems) elements.mediaMetricMenuItems.textContent = String(counts.menu_items || 0);
    if (elements.mediaMetricPhotosListed) elements.mediaMetricPhotosListed.textContent = String(counts.photos_listed || 0);
    if (elements.mediaMetricImagesOk) elements.mediaMetricImagesOk.textContent = String(counts.images_ok || 0);
    if (elements.mediaMetricImagesSkipped) elements.mediaMetricImagesSkipped.textContent = String(counts.images_skipped_existing || 0);
    if (elements.mediaMetricImagesFailed) elements.mediaMetricImagesFailed.textContent = String(counts.images_failed || 0);
    if (elements.mediaMetricImagesDuplicate) elements.mediaMetricImagesDuplicate.textContent = String(counts.images_duplicate || 0);

    // Stop reason / limit notice
    if (task.stop_reason) {
      if (elements.mediaTaskStopAlert) elements.mediaTaskStopAlert.classList.remove('hidden');
      if (elements.mediaTaskStopDesc) elements.mediaTaskStopDesc.textContent = translateMediaStopReason(task.stop_reason);
      if (elements.mediaTaskLimitBadge) {
        elements.mediaTaskLimitBadge.classList.remove('hidden');
        elements.mediaTaskLimitBadge.textContent = task.stop_reason;
      }
    } else {
      if (elements.mediaTaskStopAlert) elements.mediaTaskStopAlert.classList.add('hidden');
      if (elements.mediaTaskLimitBadge) elements.mediaTaskLimitBadge.classList.add('hidden');
    }

    // Errors
    const errors = task.errors || [];
    if (errors.length > 0) {
      if (elements.mediaTaskErrorsAccordion) elements.mediaTaskErrorsAccordion.classList.remove('hidden');
      if (elements.mediaErrorsSummaryText) elements.mediaErrorsSummaryText.textContent = `⚠️ Danh sách lỗi trong tiến trình (${errors.length} lỗi)`;
      if (elements.mediaErrorsContainer) {
        elements.mediaErrorsContainer.textContent = '';
        errors.forEach((err) => {
          const row = document.createElement('div');
          row.className = 'log-entry';
          row.textContent = safeText(err);
          elements.mediaErrorsContainer.appendChild(row);
        });
      }
    } else {
      if (elements.mediaTaskErrorsAccordion) elements.mediaTaskErrorsAccordion.classList.add('hidden');
    }

    // Buttons state
    const isRunning = task.state === 'running';
    const isPaused = task.state === 'paused';
    const isActive = isRunning || isPaused;

    setBtnDisabled(elements.btnMediaPause, !isRunning);
    setBtnDisabled(elements.btnMediaResume, !isPaused);
    setBtnDisabled(elements.btnMediaStop, !isActive);

    setBtnDisabled(elements.btnMediaScan, isActive);
    setBtnDisabled(elements.btnMediaCollect, isActive);
    setBtnDisabled(elements.btnMediaImages, isActive);
    setBtnDisabled(elements.btnMediaOcr, isActive);

    if (isActive) {
      startMediaPolling(state.viewingJobId);
    } else {
      stopMediaPolling();
    }
  }

  function startMediaPolling(jobId) {
    if (state.mediaTaskPollTimer) return;
    state.mediaTaskPollTimer = setInterval(async () => {
      if (!state.viewingJobId || state.viewingJobId !== jobId) {
        stopMediaPolling();
        return;
      }
      const res = await fetchMediaStatus(jobId);
      if (res && res.task && !['running', 'paused'].includes(res.task.state)) {
        stopMediaPolling();
        await loadMediaVenues(jobId);
      }
    }, state.mediaPollIntervalMs);
  }

  function stopMediaPolling() {
    if (state.mediaTaskPollTimer) {
      clearInterval(state.mediaTaskPollTimer);
      state.mediaTaskPollTimer = null;
    }
  }

  async function loadMediaVenues(jobId) {
    if (!jobId) return;
    try {
      const q = state.mediaQuery.trim();
      const flt = state.mediaFilter;
      const offset = state.mediaOffset;
      const limit = state.mediaLimit;
      const url = `/api/media/venues?job_id=${encodeURIComponent(jobId)}&offset=${offset}&limit=${limit}&filter=${encodeURIComponent(flt)}&q=${encodeURIComponent(q)}`;
      const res = await apiGet(url);

      state.mediaVenues = res.venues || [];
      state.mediaVenuesTotal = res.total || 0;

      // On initial load of venues for this job, select first up to 25 filtered venues
      if (!state.mediaDefaultSelectionDone && state.mediaVenues.length > 0) {
        state.mediaVenues.slice(0, 25).forEach(v => state.mediaSelectedVenueIds.add(String(v.venue_id)));
        state.mediaDefaultSelectionDone = true;
        if (state.mediaStatus && state.mediaStatus.summary) {
          updateScopeCounts(state.mediaStatus.summary);
        }
      }

      renderMediaVenuesTable();
    } catch (err) {
      console.warn(`[Media Venues] Lỗi tải danh sách quán cho ${jobId}:`, err);
    }
  }

  function renderMediaVenuesTable() {
    if (!elements.mediaVenuesTbody) return;
    elements.mediaVenuesTbody.textContent = '';

    const venues = state.mediaVenues || [];
    const total = state.mediaVenuesTotal || 0;
    const offset = state.mediaOffset;
    const limit = state.mediaLimit;

    // Total label
    if (elements.mediaVenuesTotalLabel) {
      const start = venues.length > 0 ? offset + 1 : 0;
      const end = offset + venues.length;
      elements.mediaVenuesTotalLabel.textContent = `Hiển thị ${start} - ${end} / ${total} quán`;
    }

    // Paging info
    const currentPage = total > 0 ? Math.floor(offset / limit) + 1 : 1;
    const totalPages = total > 0 ? Math.ceil(total / limit) : 1;
    if (elements.mediaPagingInfo) {
      elements.mediaPagingInfo.textContent = `Trang ${currentPage} / ${totalPages}`;
    }
    setBtnDisabled(elements.btnMediaPrev, offset === 0);
    setBtnDisabled(elements.btnMediaNext, offset + limit >= total);

    if (venues.length === 0) {
      const tr = document.createElement('tr');
      tr.className = 'empty-row';
      const td = document.createElement('td');
      td.colSpan = 7;
      td.className = 'text-center text-muted';
      td.textContent = 'Không có quán nào phù hợp với bộ lọc hiện tại.';
      tr.appendChild(td);
      elements.mediaVenuesTbody.appendChild(tr);
      return;
    }

    // Header checkbox state
    if (elements.chkMediaSelectAllPage) {
      const allOnPageSelected = venues.every(v => state.mediaSelectedVenueIds.has(String(v.venue_id)));
      elements.chkMediaSelectAllPage.checked = allOnPageSelected && venues.length > 0;
    }

    venues.forEach((v) => {
      const tr = document.createElement('tr');
      const vidStr = String(v.venue_id);

      // Col 1: Checkbox
      const tdCheck = document.createElement('td');
      tdCheck.className = 'col-checkbox';
      tdCheck.addEventListener('click', (e) => {
        e.stopPropagation();
      });
      const chk = document.createElement('input');
      chk.type = 'checkbox';
      chk.className = 'form-checkbox';
      chk.checked = state.mediaSelectedVenueIds.has(vidStr);
      chk.addEventListener('click', (e) => {
        e.stopPropagation();
      });
      chk.addEventListener('change', (e) => {
        e.stopPropagation();
        if (chk.checked) {
          state.mediaSelectedVenueIds.add(vidStr);
        } else {
          state.mediaSelectedVenueIds.delete(vidStr);
        }
        if (state.mediaStatus && state.mediaStatus.summary) {
          updateScopeCounts(state.mediaStatus.summary);
        }
        if (elements.chkMediaSelectAllPage) {
          elements.chkMediaSelectAllPage.checked = venues.every(item => state.mediaSelectedVenueIds.has(String(item.venue_id)));
        }
      });
      tdCheck.appendChild(chk);
      tr.appendChild(tdCheck);

      // Col 2: Name
      const tdName = document.createElement('td');
      const nameStrong = document.createElement('strong');
      nameStrong.textContent = v.name || `Quán ${v.venue_id}`;
      tdName.appendChild(nameStrong);

      const subDiv = document.createElement('div');
      subDiv.className = 'text-muted';
      const code = document.createElement('code');
      code.className = 'meta-code';
      code.textContent = v.venue_id;
      subDiv.appendChild(code);

      if (v.venue_url) {
        const link = document.createElement('a');
        link.href = v.venue_url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'venue-table-link ml-2';
        link.textContent = ' Foody ↗';
        link.addEventListener('click', e => e.stopPropagation());
        subDiv.appendChild(link);
      }
      tdName.appendChild(subDiv);
      tr.appendChild(tdName);

      // Col 3: Menu text status (honest state label)
      const tdMenu = document.createElement('td');
      const menuStatus = v.menu_text_status || 'not_collected';
      const menuBadge = document.createElement('span');
      if (menuStatus === 'menu_items' || (v.menu_text_items && v.menu_text_items > 0)) {
        menuBadge.className = 'badge badge-success';
        menuBadge.textContent = `Có ${v.menu_text_items} món`;
      } else {
        const meta = MEDIA_MENU_STATUS_LABELS[menuStatus] || { text: menuStatus, class: 'badge-secondary' };
        menuBadge.className = `badge ${meta.class}`;
        menuBadge.textContent = meta.text;
      }
      tdMenu.appendChild(menuBadge);
      tr.appendChild(tdMenu);

      // Col 4: Menu images count (declared vs listed)
      const tdMenuImg = document.createElement('td');
      const declCount = v.menu_image_count;
      const listCount = v.menu_images_listed;
      let imgText = '0';
      if (declCount !== null && declCount !== undefined) {
        imgText = `Khai báo: ${declCount}`;
        if (listCount !== null && listCount !== undefined) {
          imgText += ` (Đã liệt kê: ${listCount})`;
        }
      } else if (listCount !== null && listCount !== undefined) {
        imgText = `Đã liệt kê: ${listCount}`;
      }
      tdMenuImg.textContent = imgText;
      tr.appendChild(tdMenuImg);

      // Col 5: Photo counts (known / downloaded / total pictures)
      const tdPhotos = document.createElement('td');
      const pKnown = v.photos_known || 0;
      const pDl = v.photos_downloaded || 0;
      const pTot = v.total_pictures !== null && v.total_pictures !== undefined ? ` (tổng ${v.total_pictures})` : '';
      tdPhotos.textContent = `${pKnown} phát hiện / ${pDl} đã tải${pTot}`;
      tr.appendChild(tdPhotos);

      // Col 6: Flags
      const tdFlags = document.createElement('td');
      if (v.delivery_listed) {
        const delBadge = document.createElement('span');
        delBadge.className = 'badge badge-info mr-1';
        delBadge.title = 'Có giao hàng trên nguồn (menu chưa thu thập)';
        delBadge.textContent = 'Giao hàng';
        tdFlags.appendChild(delBadge);
      }
      const cacheBadge = document.createElement('span');
      if (v.cache_status === 'ok') {
        cacheBadge.className = 'badge badge-success';
        cacheBadge.textContent = 'Đã lưu đệm';
      } else if (v.cache_status === 'missing') {
        cacheBadge.className = 'badge badge-secondary';
        cacheBadge.textContent = 'Chưa có đệm';
      } else {
        cacheBadge.className = 'badge badge-warning';
        cacheBadge.textContent = v.cache_status || 'Chưa rõ';
      }
      tdFlags.appendChild(cacheBadge);
      tr.appendChild(tdFlags);

      // Col 7: Actions
      const tdAction = document.createElement('td');
      const btnView = document.createElement('button');
      btnView.type = 'button';
      btnView.className = 'btn btn-outline btn-xs';
      btnView.textContent = 'Xem chi tiết';
      btnView.addEventListener('click', (e) => {
        e.stopPropagation();
        openVenueDetail(state.viewingJobId, vidStr);
      });
      tdAction.appendChild(btnView);
      tr.appendChild(tdAction);

      // Row click opens detail
      tr.addEventListener('click', () => {
        openVenueDetail(state.viewingJobId, vidStr);
      });

      elements.mediaVenuesTbody.appendChild(tr);
    });
  }

  async function openVenueDetail(jobId, venueId) {
    if (!jobId || !venueId) return;
    try {
      showBanner(`Đang tải chi tiết quán ${venueId}...`, 'info');
      const res = await apiGet(`/api/media/venue?job_id=${encodeURIComponent(jobId)}&venue_id=${encodeURIComponent(venueId)}`);
      hideBanner();

      const venue = res.venue || {};
      const photos = res.photos || [];
      const menuItems = res.menu_items || [];

      // Update Header
      if (elements.detailVenueName) elements.detailVenueName.textContent = venue.name || `Quán ${venueId}`;
      if (elements.detailVenueId) elements.detailVenueId.textContent = venueId;
      if (elements.detailVenueUrl) {
        elements.detailVenueUrl.href = venue.venue_url || '#';
      }

      // Tab Badges Counts
      if (elements.detailPhotosCount) elements.detailPhotosCount.textContent = String(photos.length);
      if (elements.detailMenuItemsCount) elements.detailMenuItemsCount.textContent = String(menuItems.length);

      // Render Tab 1: Photos Gallery
      renderDetailPhotos(photos, jobId);

      // Render Tab 2: Menu Items Table
      renderDetailMenu(menuItems);

      // Reset active tab to photos by default
      if (elements.tabBtnPhotos && elements.tabBtnMenu) {
        elements.tabBtnPhotos.classList.add('active');
        elements.tabBtnPhotos.setAttribute('aria-selected', 'true');
        elements.tabBtnMenu.classList.remove('active');
        elements.tabBtnMenu.setAttribute('aria-selected', 'false');
      }
      if (elements.tabPanelPhotos && elements.tabPanelMenu) {
        elements.tabPanelPhotos.classList.remove('hidden');
        elements.tabPanelMenu.classList.add('hidden');
      }

      // Show Modal
      if (elements.mediaVenueDetailModal) elements.mediaVenueDetailModal.classList.remove('hidden');
    } catch (err) {
      showBanner(`Không thể mở chi tiết quán: ${err.message}`, 'danger');
    }
  }

  function closeVenueDetail() {
    if (elements.mediaVenueDetailModal) {
      elements.mediaVenueDetailModal.classList.add('hidden');
    }
  }

  function renderDetailPhotos(photos, jobId) {
    if (!elements.detailPhotosContainer) return;
    elements.detailPhotosContainer.textContent = '';

    if (!photos || photos.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'text-muted text-center py-4';
      empty.textContent = 'Chưa có ảnh nào cho quán này.';
      elements.detailPhotosContainer.appendChild(empty);
      return;
    }

    // Group photos by source_album_label (or fallback to 'Ảnh cộng đồng trên trang chủ')
    const groups = new Map();
    photos.forEach((ph) => {
      const album = ph.source_album_label || 'Ảnh cộng đồng trên trang chủ';
      if (!groups.has(album)) groups.set(album, []);
      groups.get(album).push(ph);
    });

    groups.forEach((albumPhotos, albumName) => {
      const groupSection = document.createElement('div');
      groupSection.className = 'album-group-section';

      const title = document.createElement('h4');
      title.className = 'album-group-title';
      title.textContent = `📁 ${albumName} (${albumPhotos.length} ảnh)`;
      groupSection.appendChild(title);

      const grid = document.createElement('div');
      grid.className = 'photos-gallery-grid';

      albumPhotos.forEach((ph) => {
        const card = document.createElement('div');
        card.className = 'photo-card';

        const thumbWrap = document.createElement('div');
        thumbWrap.className = 'photo-thumb-wrap';

        const img = document.createElement('img');
        img.loading = 'lazy';
        img.referrerPolicy = 'no-referrer';
        img.alt = ph.caption || `Ảnh ${ph.photo_id}`;

        if (ph.download_status === 'ok') {
          img.src = `/api/media/file?job_id=${encodeURIComponent(jobId)}&photo_id=${encodeURIComponent(ph.photo_id)}`;
        } else {
          img.src = ph.thumb_url || ph.image_url || '';
        }

        thumbWrap.appendChild(img);
        card.appendChild(thumbWrap);

        const cardBody = document.createElement('div');
        cardBody.className = 'photo-card-body';

        const badgesWrap = document.createElement('div');
        badgesWrap.className = 'photo-badges';

        if (ph.is_menu_image) {
          const menuBadge = document.createElement('span');
          menuBadge.className = 'badge badge-warning badge-xs';
          menuBadge.textContent = 'Ảnh thực đơn';
          badgesWrap.appendChild(menuBadge);
        }

        const dlBadge = document.createElement('span');
        if (ph.download_status === 'ok') {
          dlBadge.className = 'badge badge-success badge-xs';
          dlBadge.textContent = 'Đã tải';
        } else if (ph.download_status === 'not_downloaded') {
          dlBadge.className = 'badge badge-secondary badge-xs';
          dlBadge.textContent = 'Chưa tải';
        } else if (ph.download_status === 'duplicate') {
          dlBadge.className = 'badge badge-info badge-xs';
          dlBadge.textContent = 'Trùng';
        } else {
          dlBadge.className = 'badge badge-danger badge-xs';
          dlBadge.textContent = `Lỗi: ${ph.download_status}`;
          if (ph.download_error) dlBadge.title = ph.download_error;
        }
        badgesWrap.appendChild(dlBadge);
        cardBody.appendChild(badgesWrap);

        if (ph.caption) {
          const cap = document.createElement('p');
          cap.className = 'photo-caption';
          cap.textContent = ph.caption;
          cardBody.appendChild(cap);
        }

        const metaRow = document.createElement('div');
        metaRow.className = 'photo-meta';
        if (ph.width && ph.height) {
          const dim = document.createElement('span');
          dim.textContent = `${ph.width} × ${ph.height}`;
          metaRow.appendChild(dim);
        }
        if (ph.bytes) {
          const sz = document.createElement('span');
          sz.textContent = formatBytes(ph.bytes);
          metaRow.appendChild(sz);
        }
        cardBody.appendChild(metaRow);

        card.appendChild(cardBody);
        grid.appendChild(card);
      });

      groupSection.appendChild(grid);
      elements.detailPhotosContainer.appendChild(groupSection);
    });
  }

  function renderDetailMenu(menuItems) {
    if (!elements.detailMenuTbody) return;
    elements.detailMenuTbody.textContent = '';

    if (!menuItems || menuItems.length === 0) {
      const tr = document.createElement('tr');
      tr.className = 'empty-row';
      const td = document.createElement('td');
      td.colSpan = 4;
      td.className = 'text-center text-muted';
      td.textContent = 'Chưa có món ăn nào trong thực đơn chữ.';
      tr.appendChild(td);
      elements.detailMenuTbody.appendChild(tr);
      return;
    }

    menuItems.forEach((it, idx) => {
      const tr = document.createElement('tr');

      const tdIdx = document.createElement('td');
      tdIdx.textContent = String(idx + 1);
      tr.appendChild(tdIdx);

      const tdGroup = document.createElement('td');
      tdGroup.textContent = it.group || it.group_raw || '(Không phân nhóm)';
      tr.appendChild(tdGroup);

      const tdName = document.createElement('td');
      tdName.className = 'font-bold';
      tdName.textContent = it.name || it.name_raw || '';
      tr.appendChild(tdName);

      const tdPrice = document.createElement('td');
      if (it.price_vnd !== null && it.price_vnd !== undefined && Number(it.price_vnd) > 0) {
        tdPrice.textContent = `${Number(it.price_vnd).toLocaleString('vi-VN')} ₫`;
      } else {
        tdPrice.className = 'text-muted';
        tdPrice.textContent = 'Không có giá';
      }
      tr.appendChild(tdPrice);

      elements.detailMenuTbody.appendChild(tr);
    });
  }

  async function handleMediaScan() {
    hideBanner();
    const jobId = state.viewingJobId;
    if (!jobId) {
      showBanner('Vui lòng chọn một phiên đã lưu để quét menu/ảnh.', 'warning');
      return;
    }

    if (elements.mediaBusySpinner) elements.mediaBusySpinner.classList.remove('hidden');
    setBtnDisabled(elements.btnMediaScan, true);
    showBanner(`Đang quét menu/ảnh từ các trang HTML đã lưu trong bộ nhớ đệm cho phiên ${jobId.substring(0, 8)}... (không gửi yêu cầu mạng)`, 'info');

    try {
      await apiPost('/api/media/scan', { job_id: jobId });
      showBanner('Quét menu/ảnh từ bộ nhớ đệm thành công!', 'success');
      await fetchMediaStatus(jobId);
      await loadMediaVenues(jobId);
    } catch (err) {
      showBanner(`Không thể quét menu/ảnh: ${err.message}`, 'danger');
    } finally {
      if (elements.mediaBusySpinner) elements.mediaBusySpinner.classList.add('hidden');
      setBtnDisabled(elements.btnMediaScan, false);
    }
  }

  async function getMediaScopeVenueIds(jobId) {
    if (state.mediaScopeMode === 'selected') {
      return Array.from(state.mediaSelectedVenueIds);
    }
    if (state.mediaScopeMode === 'menu_images') {
      let allIds = [];
      let offset = 0;
      const limit = 200;
      while (true) {
        const res = await apiGet(`/api/media/venues?job_id=${encodeURIComponent(jobId)}&filter=menu_images&offset=${offset}&limit=${limit}`);
        const venues = res.venues || [];
        venues.forEach(v => allIds.push(String(v.venue_id)));
        offset += limit;
        if (offset >= (res.total || 0) || venues.length === 0) break;
      }
      return allIds;
    }
    return null;
  }

  function checkScopeConfirmation(venueCount) {
    if (venueCount > 25) {
      if (!elements.chkMediaConfirmNetwork || !elements.chkMediaConfirmNetwork.checked) {
        showBanner(`Số lượng quán sẽ gửi yêu cầu là ${venueCount} (> 25). Vui lòng đánh dấu vào ô "Tôi hiểu sẽ gửi yêu cầu tới foody.vn" trước khi thực hiện.`, 'warning');
        if (elements.mediaScopeConfirmBox) {
          elements.mediaScopeConfirmBox.classList.remove('hidden');
          elements.mediaScopeConfirmBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        return false;
      }
    }
    return true;
  }

  async function handleMediaCollect() {
    hideBanner();
    const jobId = state.viewingJobId;
    if (!jobId) {
      showBanner('Vui lòng chọn một phiên đã lưu.', 'warning');
      return;
    }

    const venueIds = await getMediaScopeVenueIds(jobId);
    if (venueIds !== null && venueIds.length === 0) {
      showBanner('Vui lòng chọn ít nhất một quán trong danh sách bên dưới.', 'warning');
      return;
    }

    const targetCount = venueIds !== null ? venueIds.length : (state.mediaStatus && state.mediaStatus.summary && state.mediaStatus.summary.venues_total) || 0;
    if (!checkScopeConfirmation(targetCount)) return;

    const albums = [];
    if (elements.chkAlbumThucDon && elements.chkAlbumThucDon.checked) albums.push('album-thuc-don');
    if (elements.chkAlbumMonAn && elements.chkAlbumMonAn.checked) albums.push('album-mon-an');
    if (elements.chkAlbumKhongGian && elements.chkAlbumKhongGian.checked) albums.push('album-khong-gian');
    if (elements.chkAlbumTongHop && elements.chkAlbumTongHop.checked) albums.push('album-tong-hop');

    const wantMenu = elements.chkMediaMenu ? elements.chkMediaMenu.checked : true;
    const refresh = elements.chkMediaRefresh ? elements.chkMediaRefresh.checked : false;

    const intervalVal = elements.inputMediaInterval ? parseFloat(elements.inputMediaInterval.value) : 3.0;
    const interval = Math.max(2.0, isNaN(intervalVal) ? 3.0 : intervalVal);

    const maxPagesVal = elements.inputMediaMaxPages ? parseInt(elements.inputMediaMaxPages.value, 10) : 300;
    const max_pages = Math.max(1, isNaN(maxPagesVal) ? 300 : maxPagesVal);

    const payload = {
      job_id: jobId,
      menu: wantMenu,
      albums: albums,
      interval: interval,
      max_pages: max_pages,
      refresh: refresh,
    };
    if (venueIds !== null) {
      payload.venue_ids = venueIds;
    }

    try {
      showBanner(`Bắt đầu thu thập menu & danh sách ảnh cho ${targetCount} quán...`, 'info');
      const res = await apiPost('/api/media/collect', payload);
      renderMediaTask(res.task);
      startMediaPolling(jobId);
    } catch (err) {
      showBanner(`Lỗi bắt đầu thu thập: ${err.message}`, 'danger');
    }
  }

  async function handleMediaImages() {
    hideBanner();
    const jobId = state.viewingJobId;
    if (!jobId) {
      showBanner('Vui lòng chọn một phiên đã lưu.', 'warning');
      return;
    }

    const venueIds = await getMediaScopeVenueIds(jobId);
    if (venueIds !== null && venueIds.length === 0) {
      showBanner('Vui lòng chọn ít nhất một quán trong danh sách bên dưới.', 'warning');
      return;
    }

    const targetCount = venueIds !== null ? venueIds.length : (state.mediaStatus && state.mediaStatus.summary && state.mediaStatus.summary.venues_total) || 0;
    if (!checkScopeConfirmation(targetCount)) return;

    const categories = [];
    if (elements.chkAlbumThucDon && elements.chkAlbumThucDon.checked) categories.push('album-thuc-don');
    if (elements.chkAlbumMonAn && elements.chkAlbumMonAn.checked) categories.push('album-mon-an');
    if (elements.chkAlbumKhongGian && elements.chkAlbumKhongGian.checked) categories.push('album-khong-gian');
    if (elements.chkAlbumTongHop && elements.chkAlbumTongHop.checked) categories.push('album-tong-hop');
    if (elements.chkAlbumHome && elements.chkAlbumHome.checked) categories.push('home');

    const menuImagesOnly = elements.chkMediaMenuImagesOnly ? elements.chkMediaMenuImagesOnly.checked : false;

    const intervalVal = elements.inputMediaInterval ? parseFloat(elements.inputMediaInterval.value) : 1.0;
    const interval = Math.max(0.5, isNaN(intervalVal) ? 1.0 : intervalVal);

    const maxImagesPerVenue = elements.inputMediaMaxImagesPerVenue ? parseInt(elements.inputMediaMaxImagesPerVenue.value, 10) : 8;
    const maxTotalImages = elements.inputMediaMaxTotalImages ? parseInt(elements.inputMediaMaxTotalImages.value, 10) : 200;
    const maxBytesMb = elements.inputMediaMaxBytesPerImageMb ? parseFloat(elements.inputMediaMaxBytesPerImageMb.value) : 8;
    const maxTotalMb = elements.inputMediaMaxTotalMb ? parseInt(elements.inputMediaMaxTotalMb.value, 10) : 400;

    const payload = {
      job_id: jobId,
      categories: categories.length > 0 ? categories : undefined,
      menu_images_only: menuImagesOnly,
      max_images_per_venue: Math.max(1, isNaN(maxImagesPerVenue) ? 8 : maxImagesPerVenue),
      max_total_images: Math.max(1, isNaN(maxTotalImages) ? 200 : maxTotalImages),
      max_bytes_per_image: Math.round((isNaN(maxBytesMb) ? 8 : maxBytesMb) * 1024 * 1024),
      max_total_mb: Math.max(1, isNaN(maxTotalMb) ? 400 : maxTotalMb),
      interval: interval,
    };
    if (venueIds !== null) {
      payload.venue_ids = venueIds;
    }

    try {
      showBanner(`Bắt đầu tải ảnh về máy cho ${targetCount} quán...`, 'info');
      const res = await apiPost('/api/media/images', payload);
      renderMediaTask(res.task);
      startMediaPolling(jobId);
    } catch (err) {
      showBanner(`Lỗi bắt đầu tải ảnh: ${err.message}`, 'danger');
    }
  }

  async function handleMediaOcr() {
    hideBanner();
    const jobId = state.viewingJobId;
    if (!jobId) {
      showBanner('Vui lòng chọn một phiên đã lưu.', 'warning');
      return;
    }
    const venueIds = await getMediaScopeVenueIds(jobId);
    if (venueIds !== null && venueIds.length === 0) {
      showBanner('Vui lòng chọn ít nhất một quán trong danh sách bên dưới.', 'warning');
      return;
    }
    const payload = { job_id: jobId, max_total_images: 200 };
    if (venueIds !== null) payload.venue_ids = venueIds;
    try {
      showBanner('Đang chạy OCR cục bộ trên ảnh thực đơn đã tải (không dùng mạng). Kết quả chỉ là ứng viên, cần kiểm tra.', 'info');
      const res = await apiPost('/api/media/ocr', payload);
      renderMediaTask(res.task);
      startMediaPolling(jobId);
    } catch (err) {
      showBanner(`Lỗi chạy OCR: ${err.message}`, 'danger');
    }
  }

  async function handleMediaControl(action) {
    const jobId = state.viewingJobId;
    if (!jobId) return;
    try {
      const res = await apiPost('/api/media/control', { job_id: jobId, action: action });
      renderMediaTask(res.task);
    } catch (err) {
      showBanner(`Thao tác ${action} thất bại: ${err.message}`, 'danger');
    }
  }

  async function handleMediaDownload(format) {
    const jobId = state.viewingJobId;
    if (!jobId) return;

    let url = `/api/media/download?job_id=${encodeURIComponent(jobId)}&format=${encodeURIComponent(format)}`;
    if (state.mediaScopeMode === 'selected' && state.mediaSelectedVenueIds.size > 0) {
      url += `&venue_ids=${encodeURIComponent(Array.from(state.mediaSelectedVenueIds).join(','))}`;
    }

    showBanner(`Đang chuẩn bị tải xuống ${format}...`, 'info');
    try {
      const res = await fetch(url);
      if (!res.ok) {
        let errDetail = `Lỗi HTTP ${res.status}`;
        try {
          const errJson = await res.json();
          if (errJson && errJson.error) {
            errDetail = errJson.error;
          }
        } catch (_) {}
        showBanner(`Không thể tải xuống: ${errDetail}`, 'warning');
        return;
      }

      const blob = await res.blob();
      let filename = 'download.dat';
      const disposition = res.headers.get('content-disposition');
      if (disposition) {
        const m = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
        if (m && m[1]) {
          filename = m[1].replace(/['"]/g, '').trim();
        }
      } else {
        if (format === 'archive') filename = 'foody_photos.zip';
        else if (format.endsWith('_csv')) filename = `${format.replace('_csv', '')}.csv`;
        else if (format.endsWith('_json')) filename = `${format.replace('_json', '')}.json`;
      }

      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
      showBanner(`Đã tải xuống thành công ${filename}!`, 'success');
    } catch (err) {
      showBanner(`Lỗi tải xuống: ${err.message}`, 'danger');
    }
  }

  // --- Bootstrapping ---
  function init() {
    handleModeChange();
    initEventListeners();
    startPolling();
    loadHistory();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
