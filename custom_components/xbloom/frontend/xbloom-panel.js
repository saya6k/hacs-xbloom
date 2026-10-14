/*
 * XBloom sidebar panel — a self-contained management UI modeled on the
 * official XBloom app (Brew / Recipes / Manual / Settings).
 *
 * Build-free on purpose: one vanilla web component, no dependencies, so
 * HACS ships it as-is. Live state comes from the entities (the `hass`
 * object the frontend hands every panel); actions go through the same
 * entities and services everything else uses. The backend calls are
 * `xbloom/machines` (panel.py) for the entity map and the full recipe
 * store, and `xbloom/cloud_search` for the paged hub search.
 *
 * The look follows the official app (dark surfaces, gold accent,
 * dot-matrix glyphs, serif numerals) using only original CSS/SVG and the
 * integration's own brand images; no app assets are bundled.
 */

const STRINGS = {
  en: {
    tab_home: "Brew", tab_recipes: "Recipes", tab_manual: "Manual", tab_settings: "Settings",
    no_machines: "No XBloom machine is configured.",
    loading: "Loading…",
    offline: "Disconnected", connect: "Connect", disconnect: "Disconnect",
    selected_recipe: "Selected recipe", no_recipe: "No recipe selected",
    choose_recipe: "Choose a recipe",
    load_recipe: "Load recipe", start_brew: "Start brewing",
    pause: "Pause", resume: "Resume", cancel: "Cancel",
    armed_hint: "The recipe is loaded on the machine. Place your cup, then start.",
    busy_hint: "Finish or cancel the current operation first.",
    water_low: "Water tank is low", problem: "The machine reports a problem",
    weight: "Weight", brewer_temp: "Water temp", flow: "Flow",
    target: "Target",
    search: "Search recipes", all: "All", coffee: "Coffee", tea: "Tea",
    new_recipe: "New recipe", empty_recipes: "No recipes match.",
    dose: "Dose", ratio: "Ratio", water: "Water", grind: "Grind", rpm: "RPM",
    temp: "Temp", pours: "Pours", pour: "Pour", bypass: "Bypass",
    cup_type: "Cup", brew_this: "Brew this", edit: "Edit", duplicate: "Duplicate",
    delete: "Delete", confirm_delete: "Tap again to delete", back: "Back",
    write_slot: "Write to Easy slot", source: "Source",
    flow_rate: "Flow rate", pause_s: "Pause", pattern: "Pattern", vibration: "Vibration",
    center: "Center", circular: "Circular", spiral: "Spiral",
    vib_none: "None", vib_before: "Before", vib_after: "After", vib_both: "Both",
    cup_omni_dripper: "Omni Dripper", cup_x_pod: "X-Pod", cup_xpod: "X-Pod",
    cup_other: "Other", cup_tea: "Tea",
    name: "Name", save: "Save", add_pour: "Add pour", remove: "Remove",
    move_up: "Move up", move_down: "Move down",
    bypass_volume: "Bypass water", bypass_temperature: "Bypass temp",
    total_mismatch: "Pours + bypass ({sum} ml) differ from dose × ratio ({total} ml).",
    name_required: "A name is required.", pours_required: "Add at least one pour.",
    saved: "Recipe saved", deleted: "Recipe deleted", slot_written: "Written to slot {slot}",
    grinder: "Grinder", grind_size: "Grind size", grind_btn: "Grind", start_grind: "Start grinding",
    choose: "Choose…",
    brewer: "Pour", volume: "Volume", temperature: "Temperature", start_pour: "Start pouring",
    scale: "Scale", tare: "Tare", scale_mode: "Scale mode", exit_scale: "Exit scale mode",
    arm_hint: "First tap opens the page on the machine, second tap starts it.",
    connection: "Connection", mode: "Machine mode", pro: "PRO", easy: "Easy",
    easy_slots: "Easy Mode slots", slot: "Slot", empty_slot: "Empty", write: "Write",
    advanced: "Advanced", pour_radius: "Pour radius", vibration_amp: "Vibration strength",
    brightness: "Display brightness", apply: "Apply",
    maintenance: "Maintenance", calibrate_grinder: "Calibrate grinder",
    confirm_calibrate: "Tap again to calibrate", device: "Device",
    serial: "Serial number", firmware: "Firmware", mac: "Address",
    unavailable: "Unavailable",
    my_recipes: "My recipes", cloud: "Cloud",
    cloud_search: "Search the XBloom community", search_btn: "Search",
    official: "Official", community: "Community",
    sort_likes: "Most liked", sort_downloads: "Most downloaded", sort_date: "Newest",
    import: "Import", imported: "Imported", importing: "Importing…",
    import_done: "Imported “{name}”", load_more: "Load more",
    share_link: "Share link or recipe id", import_link: "Import link",
    cloud_hint: "Search XBloom's public recipe hub and import a copy into My recipes, which Home Assistant keeps for this machine — nothing is written to the xBloom machine itself. No account needed.",
    cloud_empty: "No recipes found.", results: "{n} results", by: "by {name}",
    buy_beans: "Buy the beans", uploaded: "Uploaded {date}",
    cloud_detail_failed: "Couldn't load the full details — showing the search summary.",
    pods: "Pods", pods_empty: "Insert a pod or recipe card into the machine — it shows up here.",
    last_scanned: "Last scanned {when}", scans: "{n}× scanned",
    save_to_mine: "Save to my recipes", saved_as: "Saved as “{name}”",
    already_saved: "Already in my recipes as “{name}”",
    bean_info: "Bean info", roast: "Roast", notes: "Notes", process: "Process",
    variety: "Variety", type: "Type", origin: "Origin",
    pod_no_info: "Couldn't load this pod's info from the XBloom cloud.", pod_retry: "Retry",
    pod_loaded: "Pod info loaded", pod_still_unavailable: "Still unavailable — try again later.",
    stage_beans: "Ready", stage_grind: "Grinding", stage_pour: "Pouring", stage_enjoy: "Enjoy",
    color: "Color", color_unknown: "Unknown (serial code not mapped yet)",
    color_midnight_black: "Midnight Black", color_moonlight_white: "Moonlight White",
    color_sage_green_green: "Sage Green · Green Knob", color_sage_green_gold: "Sage Green · Gold Knob",
    color_twilight: "Twilight", color_offline_blue: "Offline Blue",
  },
  ko: {
    tab_home: "브루", tab_recipes: "레시피", tab_manual: "수동", tab_settings: "설정",
    no_machines: "설정된 XBloom 머신이 없습니다.",
    loading: "불러오는 중…",
    offline: "연결 끊김", connect: "연결", disconnect: "연결 해제",
    selected_recipe: "선택한 레시피", no_recipe: "선택된 레시피 없음",
    choose_recipe: "레시피 선택",
    load_recipe: "레시피 불러오기", start_brew: "추출 시작",
    pause: "일시정지", resume: "재개", cancel: "취소",
    armed_hint: "머신에 레시피가 준비되었습니다. 컵을 놓은 뒤 시작하세요.",
    busy_hint: "진행 중인 작업을 끝내거나 취소한 뒤 사용하세요.",
    water_low: "물탱크가 부족합니다", problem: "머신이 문제를 보고했습니다",
    weight: "무게", brewer_temp: "물 온도", flow: "유량",
    target: "목표",
    search: "레시피 검색", all: "전체", coffee: "커피", tea: "차",
    new_recipe: "새 레시피", empty_recipes: "일치하는 레시피가 없습니다.",
    dose: "원두량", ratio: "비율", water: "물", grind: "분쇄도", rpm: "RPM",
    temp: "온도", pours: "푸어", pour: "푸어", bypass: "바이패스",
    cup_type: "컵", brew_this: "이 레시피로 추출", edit: "편집", duplicate: "복제",
    delete: "삭제", confirm_delete: "한 번 더 누르면 삭제", back: "뒤로",
    write_slot: "Easy 슬롯에 쓰기", source: "출처",
    flow_rate: "유속", pause_s: "대기", pattern: "패턴", vibration: "진동",
    center: "센터", circular: "원형", spiral: "나선",
    vib_none: "없음", vib_before: "전", vib_after: "후", vib_both: "전후",
    cup_omni_dripper: "Omni 드리퍼", cup_x_pod: "X-Pod", cup_xpod: "X-Pod",
    cup_other: "기타", cup_tea: "차",
    name: "이름", save: "저장", add_pour: "푸어 추가", remove: "삭제",
    move_up: "위로", move_down: "아래로",
    bypass_volume: "바이패스 물", bypass_temperature: "바이패스 온도",
    total_mismatch: "푸어 + 바이패스({sum} ml)가 원두량 × 비율({total} ml)과 다릅니다.",
    name_required: "이름을 입력하세요.", pours_required: "푸어를 하나 이상 추가하세요.",
    saved: "레시피를 저장했습니다", deleted: "레시피를 삭제했습니다", slot_written: "슬롯 {slot}에 썼습니다",
    grinder: "그라인더", grind_size: "분쇄도", grind_btn: "분쇄", start_grind: "분쇄 시작",
    choose: "선택…",
    brewer: "푸어", volume: "물량", temperature: "온도", start_pour: "푸어 시작",
    scale: "저울", tare: "영점", scale_mode: "저울 모드", exit_scale: "저울 모드 종료",
    arm_hint: "첫 번째 탭은 머신의 화면을 열고, 두 번째 탭에 시작합니다.",
    connection: "연결", mode: "머신 모드", pro: "PRO", easy: "Easy",
    easy_slots: "Easy 모드 슬롯", slot: "슬롯", empty_slot: "비어 있음", write: "쓰기",
    advanced: "고급", pour_radius: "푸어 반경", vibration_amp: "진동 세기",
    brightness: "화면 밝기", apply: "적용",
    maintenance: "유지보수", calibrate_grinder: "그라인더 보정",
    confirm_calibrate: "한 번 더 누르면 보정", device: "기기",
    serial: "시리얼 번호", firmware: "펌웨어", mac: "주소",
    unavailable: "사용 불가",
    my_recipes: "내 레시피", cloud: "클라우드",
    cloud_search: "XBloom 커뮤니티 검색", search_btn: "검색",
    official: "공식", community: "커뮤니티",
    sort_likes: "좋아요순", sort_downloads: "다운로드순", sort_date: "최신순",
    import: "가져오기", imported: "가져옴", importing: "가져오는 중…",
    import_done: "“{name}” 레시피를 가져왔습니다", load_more: "더 보기",
    share_link: "공유 링크 또는 레시피 ID", import_link: "링크로 가져오기",
    cloud_hint: "XBloom 공개 레시피 허브에서 검색해 내 레시피로 복사해 옵니다. 레시피는 Home Assistant에 이 기기용으로 저장되며, xBloom 기기 자체에는 저장되지 않습니다. 계정이 필요 없습니다.",
    cloud_empty: "검색 결과가 없습니다.", results: "{n}개 결과", by: "작성자 {name}",
    buy_beans: "원두 구매", uploaded: "{date} 업로드",
    cloud_detail_failed: "상세 정보를 불러오지 못해 검색 요약만 표시합니다.",
    pods: "팟", pods_empty: "기기에 팟이나 레시피 카드를 꽂으면 여기에 나타납니다.",
    last_scanned: "마지막 스캔 {when}", scans: "{n}회 스캔",
    save_to_mine: "내 레시피로 저장", saved_as: "“{name}”(으)로 저장했습니다",
    already_saved: "이미 내 레시피에 “{name}”(으)로 있습니다",
    bean_info: "원두 정보", roast: "로스팅", notes: "노트", process: "가공",
    variety: "품종", type: "유형", origin: "원산지",
    pod_no_info: "XBloom 클라우드에서 이 팟 정보를 불러오지 못했습니다.", pod_retry: "다시 불러오기",
    pod_loaded: "팟 정보를 불러왔습니다", pod_still_unavailable: "아직 불러올 수 없습니다. 잠시 후 다시 시도하세요.",
    stage_beans: "준비", stage_grind: "분쇄", stage_pour: "푸어", stage_enjoy: "완성",
    color: "색상", color_unknown: "알 수 없음 (시리얼 코드 미등록)",
    color_midnight_black: "미드나이트 블랙", color_moonlight_white: "문라이트 화이트",
    color_sage_green_green: "세이지 그린 · 그린 노브", color_sage_green_gold: "세이지 그린 · 골드 노브",
    color_twilight: "트와일라이트", color_offline_blue: "오프라인 블루",
  },
};

// sensor.state values, grouped the way the panel acts on them.
const BUSY_STATES = new Set([
  "starting", "grinding", "brewing", "paused", "calibrating_grinder",
  "descaling", "calibrating_scale",
]);
const PAUSABLE_STATES = new Set(["starting", "grinding", "brewing", "paused"]);
const ARMED_STATES = new Set(["armed_recipe", "recipe_loaded", "awaiting_confirm"]);
const IDLE_STATES = new Set(["idle", "ready", "sleeping", "unknown", "unavailable"]);
// Fast-moving telemetry — updated in place, never triggers a re-render.
const LIVE_KEYS = [
  "sensor.weight", "sensor.brewer_temperature", "sensor.flow_rate",
  "sensor.live_grind_size", "sensor.live_grind_speed", "sensor.voltage_raw",
];

const PATTERNS = ["center", "circular", "spiral"];
const VIBRATIONS = ["none", "before", "after", "both"];
const CUP_TYPES = ["omni_dripper", "x_pod", "other", "tea"];

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);

const num = (v, digits = 0) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return "–";
  return digits ? n.toFixed(digits).replace(/\.0+$/, "") : String(Math.round(n));
};

const isTea = (r) => String(r?.cup_type || "").toLowerCase() === "tea";

const pourSum = (r) => (r.pours || []).reduce((a, p) => a + Number(p.volume_ml || 0), 0);

// Mirrors schema.compute_total_water_ml.
const totalWater = (r) => {
  const dose = Number(r.dose_g || 0);
  return dose > 0 && r.ratio ? dose * Number(r.ratio) : pourSum(r);
};

// The app's temperature slider: 39-96, where the ends ARE RT (room
// temperature, 20 °C on the wire) and BP (boiling point, 98 °C) — the same
// mapping as the coordinator's _wire_temperature for the manual slider.
// Recipes store °C; shown in HA's own temperature unit (set in `set hass`).
let displayTempUnit = "°C";
const showTemp = (c) =>
  displayTempUnit === "°F" ? `${num((Number(c) * 9) / 5 + 32)}°F` : `${num(c)}°`;
const tempLabel = (t) => (Number(t) <= 20 ? "RT" : Number(t) >= 98 ? "BP" : showTemp(t));
// The manual temperature slider: its own ends are RT/BP (in any unit).
const endLabel = (v, min, max, unit) =>
  Number(v) <= Number(min) ? "RT" : Number(v) >= Number(max) ? "BP" : `${num(v)}${unit || "°"}`;
// An entity's temperature in °C, whatever unit HA shows it in (an
// imperial HA converts the °C entities to °F).
const toCelsius = (v, unit) => (unit === "°F" ? ((Number(v) - 32) * 5) / 9 : Number(v));
// Scale weight in grams, for comparing against a recipe's water (ml ≈ g).
const GRAMS_PER = { g: 1, kg: 1000, mg: 0.001, oz: 28.3495, lb: 453.592 };
const tempToSlider = (t) => (t <= 20 ? 39 : t >= 98 ? 96 : Math.min(95, Math.max(40, t)));
const sliderToTemp = (s) => (s <= 39 ? 20 : s >= 96 ? 98 : s);

const PATTERN_ICON = {
  center: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>',
  circular: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  spiral: '<svg viewBox="0 0 24 24"><path d="M12 12m0 0a1.5 1.5 0 0 1 3 0a3 3 0 0 1-6 0a4.5 4.5 0 0 1 9 0a6 6 0 0 1-12 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
};

// Dot-matrix glyphs in the spirit of the app's icon set ("#" = dot).
const dotIcon = (rows, cls = "dots") => {
  const w = Math.max(...rows.map((r) => r.length));
  const circles = rows
    .flatMap((r, y) => [...r].map((c, x) => (c === "#" ? `<circle cx="${x + 0.5}" cy="${y + 0.5}" r="0.36"/>` : "")))
    .join("");
  return `<svg class="${cls}" viewBox="0 0 ${w} ${rows.length}" fill="currentColor">${circles}</svg>`;
};

const ICONS = {
  home: dotIcon(["...#...", "..###..", ".#####.", "#######", "#######", ".#####.", "..###.."]),
  recipes: dotIcon(["##.####", ".......", "##.####", ".......", "##.####", ".......", "##.####"]),
  manual: dotIcon(["#######", ".#####.", "..###..", "...#...", "...#...", "..###..", ".#####."]),
  settings: dotIcon(["..#....", "#######", "..#....", ".......", "....#..", "#######", "....#.."]),
  beans: dotIcon(["..###..", ".##.##.", "##.####", "##.####", "###.###", ".##.##.", "..###.."]),
  grind: dotIcon(["#######", ".#####.", "..###..", "...#...", "..#.#..", ".#.#.#.", "#.#.#.#"]),
  pour: dotIcon(["#.#.#.#", ".......", ".#.#.#.", ".......", "..#.#..", ".......", "...#..."]),
  enjoy: dotIcon([".......", "#####..", "######.", "#####.#", "######.", "#####..", ".###..."]),
  scale: dotIcon([".......", ".......", "..###..", ".......", "#######", "#######", "......."]),
  tea: dotIcon(["....###", "..#####", ".######", ".#####.", "#####..", "#.#....", "#......"]),
};

// The brew stages the app's autopilot screen walks through.
const STAGES = ["beans", "grind", "pour", "enjoy"];
const STAGE_OF_STATE = {
  armed_recipe: 0, recipe_loaded: 0, awaiting_confirm: 0, starting: 0,
  grinding: 1, brewing: 2, paused: 2, ready: 3,
};

// Per-browser convenience only (which machine was last open); storage can
// be unavailable (private mode, blocked site data), so failures are ignored.
const loadPref = (key) => {
  try {
    return localStorage.getItem(`xbloom-panel:${key}`);
  } catch (_err) {
    return null;
  }
};
const savePref = (key, value) => {
  try {
    localStorage.setItem(`xbloom-panel:${key}`, value);
  } catch (_err) {
    // ignore
  }
};

const SAFE_IMAGE = /^https:\/\/[^\s"'()<>\\]+$/;
// Only XBloom's own store pages are offered as "buy the beans" links.
const SAFE_STORE_LINK = /^https:\/\/xbloom\.com\/products\/[a-z0-9-]+$/;
// A pod's own colour (PodsModel.theColor) — only plain hex goes into a style.
const POD_COLOR = /^#[0-9a-fA-F]{6}$/;

// XBloom's own product shots, one per Studio colour, loaded from their
// store CDN at view time — referenced, not bundled (the photos are
// XBloom's copyright). Same three-quarter view for every colour; hidden if
// one fails to load. Keys match panel.py's MACHINE_COLORS.
const SHOP_CDN = "https://cdn.shopify.com/s/files/1/0611/5704/8544/files/";
const MACHINE_IMAGES = {
  midnight_black: "xbloom_Studio_Midnight_Black_03.webp",
  moonlight_white: "Frame_34597300_2dd2d49b-c4db-4846-82c6-58bb66c24332.png",
  sage_green_green: "Frame_34598241.png",
  sage_green_gold: "Frame_34598234.png",
  twilight: "Frame_34598248.png",
  offline_blue: "xbloomofflinebluestudioproductimage-3.webp",
};
// The colour comes from the serial number only (panel.py's
// MACHINE_COLOR_CODES); an unknown code shows the black machine.
const machineColor = (m) => m?.detected_color || "midnight_black";
const machineImage = (m) => `${SHOP_CDN}${MACHINE_IMAGES[machineColor(m)] || MACHINE_IMAGES.midnight_black}?width=720`;

// A stable hue per recipe name, kept inside a warm (coffee) or green
// (tea) band, so generated card art is varied but consistent.
const nameHue = (name, tea) => {
  let h = 0;
  for (const ch of String(name)) h = (h * 31 + ch.codePointAt(0)) % 997;
  return tea ? 95 + (h % 50) : 18 + (h % 26);
};

const blankPour = () => ({
  volume_ml: 50, temperature_c: 93, flow_rate: 3.0, pause_seconds: 0,
  pattern: "spiral", vibration: "none",
});

const blankRecipe = () => ({
  name: "", cup_type: "omni_dripper", dose_g: 15, ratio: 16, grind_size: 50, rpm: 80,
  bypass_volume: 0, bypass_temperature: 0,
  pours: [
    { ...blankPour(), volume_ml: 40, pause_seconds: 30 },
    { ...blankPour(), volume_ml: 200 },
  ],
});

// Recipe fields the editor owns; everything else (uid/source/cloud ids)
// is store metadata the services refuse to take from user input anyway.
const EDIT_FIELDS = [
  "name", "cup_type", "dose_g", "ratio", "grind_size", "rpm",
  "bypass_volume", "bypass_temperature", "pours",
];

class XBloomPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "home";
    this._machines = null;
    this._entryId = null;
    this._recipeView = null; // uid of the open recipe detail
    this._editor = null; // { uid|null, recipe }
    this._filter = { q: "", kind: "all" };
    this._confirm = null; // key of a destructive action awaiting its 2nd tap
    this._sig = "";
    this._recipeSig = "";
    this._pendingRender = false;
    this._wired = false;
    this._recipesView = "mine"; // "mine" | "cloud"
    this._cloud = {
      q: "", category: "", src: "", sort: "likes",
      results: null, page: 0, totalPage: 0, total: null,
      loading: false, importing: null, imported: new Set(),
    };
    this._shareLink = "";
    // Pod library (see pods.py): list, the open pod, its selected recipe.
    this._pods = { list: null, open: null, recipe: 0, bean: false };
    this._podEventSig = "";
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    // Follow the user's light/dark choice; the palette is the app's either way.
    this.toggleAttribute("dark", !!hass.themes?.darkMode);
    displayTempUnit = hass.config?.unit_system?.temperature || "°C";
    if (first) this._loadMachines();
    this._onHassChanged();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    const btn = this.shadowRoot.querySelector("ha-menu-button");
    if (btn) btn.narrow = narrow;
  }

  set panel(_panel) {}
  set route(_route) {}

  connectedCallback() {
    if (this._wired) return;
    this._wired = true;
    const root = this.shadowRoot;
    root.addEventListener("click", (ev) => this._onClick(ev));
    root.addEventListener("change", (ev) => this._onChange(ev));
    root.addEventListener("input", (ev) => this._onInput(ev));
    root.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      if (ev.target.dataset.cloudQ !== undefined) this._cloudSearch();
      else if (ev.target.dataset.shareLink !== undefined) this._importCloud(this._shareLink.trim());
    });
    root.addEventListener("pointerdown", () => { this._pointerDown = true; });
    window.addEventListener("pointerup", () => {
      this._pointerDown = false;
      setTimeout(() => {
        if (this._pendingRender && !this._hasFocus()) this._render();
      }, 0);
    });
    // A render deferred while a control had focus lands once it lets go.
    // error doesn't bubble — capture it to drop a product shot that can't load.
    root.addEventListener("error", (ev) => {
      if (ev.target.classList?.contains("machine-img") || ev.target.classList?.contains("device-img")) {
        ev.target.remove();
      }
    }, true);
    root.addEventListener("focusout", () => {
      setTimeout(() => {
        if (this._pendingRender && !this._hasFocus()) this._render();
      }, 0);
    });
    this._render();
  }

  // ---------------------------------------------------------------- i18n

  _t(key, vars) {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").split("-")[0];
    let s = (STRINGS[lang] || STRINGS.en)[key] ?? STRINGS.en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
    return s;
  }

  // ---------------------------------------------------------------- data

  get _machine() {
    return this._machines?.find((m) => m.entry_id === this._entryId) || null;
  }

  _eid(key) {
    return this._machine?.entities?.[key];
  }

  _st(key) {
    const id = this._eid(key);
    return id ? this._hass?.states[id] : undefined;
  }

  _val(key) {
    const s = this._st(key);
    return s && s.state !== "unavailable" ? s.state : undefined;
  }

  _fmt(key) {
    const s = this._st(key);
    if (!s || s.state === "unavailable" || s.state === "unknown") return "–";
    return this._hass.formatEntityState ? this._hass.formatEntityState(s) : s.state;
  }

  get _state() {
    return this._val("sensor.state") || "unavailable";
  }

  get _connected() {
    return this._val("switch.connection") === "on";
  }

  async _loadMachines() {
    try {
      const res = await this._hass.callWS({ type: "xbloom/machines" });
      this._machines = res.machines || [];
      if (!this._machines.some((m) => m.entry_id === this._entryId)) {
        // Reopen on the machine this viewer last picked, if it still exists.
        const saved = loadPref("machine");
        this._entryId = this._machines.some((m) => m.entry_id === saved)
          ? saved
          : this._machines[0]?.entry_id || null;
      }
    } catch (err) {
      this._machines = [];
      this._toast(err.message || String(err));
    }
    this._recipeSig = this._computeRecipeSig();
    this._render();
  }

  // Changes on these entities mean the recipe store or the slots moved —
  // refetch, since the store itself isn't in any entity's state.
  _computeRecipeSig() {
    return (this._machines || [])
      .map((m) =>
        ["select.recipe", "sensor.easy_slot_a", "sensor.easy_slot_b", "sensor.easy_slot_c"]
          .map((k) => {
            const s = this._hass.states[m.entities?.[k]];
            return s ? `${s.state}|${(s.attributes.options || []).length}` : "";
          })
          .join(";"))
      .join("#");
  }

  // Everything the current screen renders, except the fast telemetry.
  _computeSig() {
    const m = this._machine;
    if (!m) return "";
    return Object.entries(m.entities)
      .filter(([k]) => !LIVE_KEYS.includes(k) && !k.startsWith("event."))
      .map(([, id]) => {
        const s = this._hass.states[id];
        if (!s) return "";
        const a = s.attributes;
        return `${s.state}|${a.min ?? ""}|${a.max ?? ""}|${a.installed_version ?? ""}`;
      })
      .join(";");
  }

  _onHassChanged() {
    if (!this._machines) return;
    // pod_detected fires after the scan was recorded in the pod library,
    // so a new notification event is the cue to refresh an open pod list.
    const podEventSig = this._val("event.notification_event") || "";
    if (podEventSig !== this._podEventSig) {
      this._podEventSig = podEventSig;
      if (this._tab === "recipes" && this._recipesView === "pods") this._loadPods();
    }
    const recipeSig = this._computeRecipeSig();
    if (recipeSig !== this._recipeSig) {
      this._recipeSig = recipeSig;
      this._loadMachines();
      return;
    }
    const sig = this._computeSig();
    if (sig !== this._sig) {
      this._render();
    } else {
      this._updateLive();
    }
  }

  // Re-rendering replaces the DOM, which would eat a half-typed value or a
  // slider mid-drag. Sliders and selects keep focus after they commit, so
  // they only count while actually being dragged / when editing a recipe.
  _hasFocus() {
    const a = this.shadowRoot.activeElement;
    if (!a) return false;
    if (a.type === "range") return this._pointerDown;
    if (a.tagName === "SELECT") return !!this._editor;
    return ["INPUT", "TEXTAREA"].includes(a.tagName);
  }

  // ---------------------------------------------------------------- actions

  _toast(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true })
    );
  }

  async _call(domain, service, data = {}, withResponse = false) {
    try {
      if (withResponse) {
        const res = await this._hass.callWS({
          type: "call_service", domain, service, service_data: data, return_response: true,
        });
        return res?.response ?? true;
      }
      await this._hass.callService(domain, service, data);
      return true;
    } catch (err) {
      this._toast(err.message || String(err));
      return false;
    }
  }

  _press(key) {
    const id = this._eid(key);
    return id ? this._call("button", "press", { entity_id: id }) : false;
  }

  _xb(service, data = {}) {
    return this._call("xbloom", service, { ...data, config_entry_id: this._entryId }, true);
  }

  async _brewRecipe(recipe) {
    const sel = this._eid("select.recipe");
    if (!sel) return;
    if (!(await this._call("select", "select_option", { entity_id: sel, option: recipe.name }))) return;
    if (await this._press("button.execute_recipe")) {
      this._recipeView = null;
      this._tab = "home";
      this._render();
    }
  }

  async _saveEditor() {
    const { uid, recipe } = this._editor;
    const r = { ...recipe, name: String(recipe.name || "").trim() };
    if (!r.name) return this._toast(this._t("name_required"));
    if (!r.pours?.length) return this._toast(this._t("pours_required"));
    if (isTea(r)) {
      r.dose_g = 0;
      r.ratio = null;
    }
    const body = {};
    for (const k of EDIT_FIELDS) body[k] = r[k];
    // JSON is valid YAML — the services parse it with yaml.safe_load.
    const res = uid
      ? await this._xb("edit_recipe", { recipe: uid, changes: JSON.stringify(body) })
      : await this._xb("create_recipe", { recipe_yaml: JSON.stringify(body) });
    if (!res) return;
    this._toast(this._t("saved"));
    this._editor = null;
    this._recipeView = res.uid || uid || null;
    await this._loadMachines();
  }

  async _deleteRecipe(uid) {
    if (this._confirm !== `delete:${uid}`) {
      this._confirm = `delete:${uid}`;
      return this._render();
    }
    this._confirm = null;
    if (await this._xb("delete_recipe", { recipe: uid })) {
      this._toast(this._t("deleted"));
      this._recipeView = null;
      await this._loadMachines();
    }
  }

  async _duplicateRecipe(recipe) {
    const body = {};
    for (const k of EDIT_FIELDS) body[k] = recipe[k];
    // create_recipe dedupes the name with a " (2)" suffix.
    const res = await this._xb("create_recipe", { recipe_yaml: JSON.stringify(body) });
    if (res) {
      this._recipeView = res.uid;
      await this._loadMachines();
    }
  }

  async _writeSlot(slot, uid) {
    if (!uid) return;
    if (await this._xb("write_recipe_to_easy_slot", { slot, recipe: uid })) {
      this._toast(this._t("slot_written", { slot }));
      await this._loadMachines();
    }
  }

  // page 1 replaces the results, later pages append ("load more").
  async _cloudSearch(page = 1) {
    const c = this._cloud;
    if (c.loading) return;
    c.loading = true;
    // The focused search box would otherwise hold the re-render back.
    this.shadowRoot.activeElement?.blur();
    this._render();
    try {
      const res = await this._hass.callWS({
        type: "xbloom/cloud_search",
        entry_id: this._entryId,
        sort: c.sort,
        page,
        ...(c.q.trim() ? { keyword: c.q.trim() } : {}),
        ...(c.category ? { category: c.category } : {}),
        ...(c.src ? { src: c.src } : {}),
      });
      c.results = page > 1 ? [...(c.results || []), ...res.recipes] : res.recipes;
      c.page = res.page;
      c.totalPage = res.total_page;
      c.total = res.total;
    } catch (err) {
      this._toast(err.message || String(err));
      if (c.results === null) c.results = [];
    }
    c.loading = false;
    this._render();
  }

  async _importCloud(identifier, item) {
    if (!identifier) return;
    const key = item ? this._cloudKey(item) : identifier;
    this._cloud.importing = key;
    this._render();
    const data = identifier.includes("://") ? { share_url: identifier } : { recipe_id: identifier };
    const res = await this._xb("cloud_import_recipe", data);
    this._cloud.importing = null;
    if (res) {
      this._cloud.imported.add(key);
      if (!item) this._shareLink = "";
      this._toast(this._t("import_done", { name: res.name }));
      await this._loadMachines();
    } else {
      this._render();
    }
  }

  async _loadPods() {
    try {
      const res = await this._hass.callWS({ type: "xbloom/pods", entry_id: this._entryId });
      this._pods.list = res.pods || [];
    } catch (err) {
      this._toast(err.message || String(err));
      if (this._pods.list === null) this._pods.list = [];
    }
    this._render();
  }

  get _openPod() {
    return this._pods.list?.find((p) => p.xid === this._pods.open) || null;
  }

  async _savePodRecipe() {
    const pod = this._openPod;
    if (!pod) return;
    try {
      const res = await this._hass.callWS({
        type: "xbloom/pods/save_recipe", entry_id: this._entryId, xid: pod.xid, index: this._pods.recipe,
      });
      this._toast(this._t(res.added ? "saved_as" : "already_saved", { name: res.name }));
      await this._loadMachines();
    } catch (err) {
      this._toast(err.message || String(err));
    }
  }

  // Retry the cloud lookup for a pod scanned while it failed.
  async _refreshPod() {
    const pod = this._openPod;
    if (!pod || this._pods.refreshing) return;
    this._pods.refreshing = true;
    this._render();
    try {
      const res = await this._hass.callWS({ type: "xbloom/pods/refresh", entry_id: this._entryId, xid: pod.xid });
      this._toast(this._t(res.updated ? "pod_loaded" : "pod_still_unavailable"));
    } catch (err) {
      this._toast(err.message || String(err));
    }
    this._pods.refreshing = false;
    await this._loadPods();
  }

  async _forgetPod() {
    const pod = this._openPod;
    if (!pod) return;
    if (this._confirm !== `forget:${pod.xid}`) {
      this._confirm = `forget:${pod.xid}`;
      return this._render();
    }
    this._confirm = null;
    try {
      await this._hass.callWS({ type: "xbloom/pods/delete", entry_id: this._entryId, xid: pod.xid });
    } catch (err) {
      return this._toast(err.message || String(err));
    }
    this._pods.open = null;
    return this._loadPods();
  }

  _cloudKey(item) {
    return String(item.community_recipe_id ?? item.share_url);
  }

  _onClick(ev) {
    const el = ev.target.closest("[data-action]");
    if (!el || el.disabled) return;
    const a = el.dataset.action;
    const arg = el.dataset.arg;
    const recipe = this._findRecipe(arg);
    switch (a) {
      case "tab":
        this._tab = arg;
        this._recipeView = null;
        this._editor = null;
        this._confirm = null;
        return this._render();
      case "press":
        return this._press(arg);
      // Segmented buttons standing in for a select entity.
      case "set-pattern":
        return this._call("select", "select_option", { entity_id: this._eid("select.pour_pattern"), option: arg });
      case "set-mode":
        return this._call("select", "select_option", { entity_id: this._eid("select.mode"), option: arg });
      case "toggle-connection":
        return this._call("switch", this._connected ? "turn_off" : "turn_on", {
          entity_id: this._eid("switch.connection"),
        });
      case "recipes-view":
        this._recipesView = arg;
        this._recipeView = null;
        this._editor = null;
        this._pods.open = null;
        this._render();
        if (arg === "cloud" && this._cloud.results === null) this._cloudSearch();
        if (arg === "pods") this._loadPods();
        return undefined;
      case "open-pod":
        this._pods = { ...this._pods, open: arg, recipe: 0, bean: false };
        this._confirm = null;
        return this._render();
      case "close-pod":
        this._pods.open = null;
        this._confirm = null;
        return this._render();
      case "pod-recipe":
        this._pods.recipe = Number(arg);
        return this._render();
      case "toggle-bean":
        this._pods.bean = !this._pods.bean;
        return this._render();
      case "save-pod-recipe":
        return this._savePodRecipe();
      case "forget-pod":
        return this._forgetPod();
      case "refresh-pod":
        return this._refreshPod();
      case "cloud-filter": {
        const [key, value] = arg.split(":");
        this._cloud[key] = value;
        return this._cloudSearch();
      }
      case "open-cloud":
        return this._openCloudDetail(Number(arg));
      case "close-cloud":
        this._cloud.open = null;
        this._cloud.detail = null;
        return this._render();
      case "cloud-search":
        return this._cloudSearch();
      case "cloud-more":
        return this._cloudSearch(this._cloud.page + 1);
      case "cloud-import": {
        const item = this._cloud.results?.[Number(arg)];
        return item && this._importCloud(item.share_url || String(item.community_recipe_id), item);
      }
      case "import-link":
        return this._importCloud(this._shareLink.trim());
      case "filter":
        this._filter.kind = arg;
        return this._render();
      case "open-recipe":
        this._recipeView = arg;
        this._confirm = null;
        return this._render();
      case "close-recipe":
        this._recipeView = null;
        this._editor = null;
        this._confirm = null;
        return this._render();
      case "brew":
        return recipe && this._brewRecipe(recipe);
      case "new-recipe":
        this._editor = { uid: null, recipe: blankRecipe() };
        return this._render();
      case "edit-recipe":
        if (recipe) this._editor = { uid: recipe.uid, recipe: structuredClone(recipe) };
        return this._render();
      case "duplicate-recipe":
        return recipe && this._duplicateRecipe(recipe);
      case "delete-recipe":
        return this._deleteRecipe(arg);
      case "write-slot":
        return this._writeSlot(arg, this._recipeView);
      case "write-slot-from":
        return this._writeSlot(arg, this.shadowRoot.querySelector(`#slot-${arg}`)?.value);
      case "add-pour":
        this._editor.recipe.pours.push(blankPour());
        return this._render();
      case "remove-pour":
        this._editor.recipe.pours.splice(Number(arg), 1);
        return this._render();
      case "move-pour": {
        const [i, d] = arg.split(":").map(Number);
        const p = this._editor.recipe.pours;
        if (i + d < 0 || i + d >= p.length) return;
        [p[i], p[i + d]] = [p[i + d], p[i]];
        return this._render();
      }
      case "save-recipe":
        return this._saveEditor();
      case "cancel-edit":
        this._editor = null;
        return this._render();
      case "advanced": {
        const v = Number(this.shadowRoot.querySelector(`#adv-${arg}`)?.value);
        return this._xb("advanced_settings", { [arg]: v });
      }
      case "calibrate":
        if (this._confirm !== "calibrate") {
          this._confirm = "calibrate";
          return this._render();
        }
        this._confirm = null;
        this._render();
        return this._press("button.calibrate_grinder");
      default:
        return undefined;
    }
  }

  _onChange(ev) {
    const el = ev.target;
    const d = el.dataset;
    if (d.machine !== undefined) {
      this._entryId = el.value;
      savePref("machine", el.value);
      this._recipeView = null;
      this._editor = null;
      return this._render();
    }
    if (d.number) {
      return this._call("number", "set_value", { entity_id: this._eid(d.number), value: Number(el.value) });
    }
    if (d.select) {
      return this._call("select", "select_option", { entity_id: this._eid(d.select), option: el.value });
    }
    if (d.cloudSort !== undefined) {
      this._cloud.sort = el.value;
      return this._cloudSearch();
    }
    if (d.field || d.pour) this._onInput(ev, true);
    return undefined;
  }

  _onInput(ev, committed = false) {
    const el = ev.target;
    const d = el.dataset;
    if (d.cloudQ !== undefined) {
      this._cloud.q = el.value;
      return;
    }
    if (d.shareLink !== undefined) {
      this._shareLink = el.value;
      return;
    }
    if (d.search !== undefined) {
      this._filter.q = el.value;
      this._renderRecipeGrid();
      return;
    }
    if (d.rangeLabel) {
      const out = this.shadowRoot.querySelector(`[data-range-out="${d.rangeLabel}"]`);
      if (out) out.textContent = d.rangeFmt === "temp" ? endLabel(el.value, el.min, el.max, d.unit) : el.value;
    }
    if (!this._editor) return;
    const r = this._editor.recipe;
    const parse = (v, kind) => (kind === "text" ? v : kind === "temp" ? sliderToTemp(Number(v)) : v === "" ? null : Number(v));
    if (d.field) {
      r[d.field] = parse(el.value, d.kind);
      if (d.field === "cup_type") return this._render();
    } else if (d.pour) {
      const [i, f] = d.pour.split(":");
      r.pours[Number(i)][f] = parse(el.value, d.kind);
      if (d.kind === "temp") {
        const out = this.shadowRoot.querySelector(`[data-temp-out="${i}"]`);
        if (out) out.textContent = tempLabel(r.pours[Number(i)][f]);
      }
    }
    if (committed || d.kind !== "text") this._updateEditorSummary();
  }

  _findRecipe(uid) {
    return uid ? this._machine?.recipes.find((r) => r.uid === uid) : undefined;
  }

  // ---------------------------------------------------------------- render

  _render() {
    if (!this.shadowRoot) return;
    if (this._hasFocus()) {
      this._pendingRender = true;
      return;
    }
    this._pendingRender = false;
    this._sig = this._computeSig();
    const scrollEl = this.shadowRoot.querySelector(".content");
    const scroll = scrollEl ? scrollEl.scrollTop : 0;
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>${this._renderShell()}`;
    const btn = this.shadowRoot.querySelector("ha-menu-button");
    if (btn) {
      btn.hass = this._hass;
      btn.narrow = this._narrow;
    }
    const content = this.shadowRoot.querySelector(".content");
    if (content) content.scrollTop = scroll;
    this._updateLive();
  }

  _renderShell() {
    const m = this._machine;
    const tabs = ["home", "recipes", "manual", "settings"];
    const picker =
      (this._machines?.length || 0) > 1
        ? `<select class="machine-picker" data-machine>${this._machines
            .map((x) => `<option value="${esc(x.entry_id)}" ${x.entry_id === this._entryId ? "selected" : ""}>${esc(x.title)}</option>`)
            .join("")}</select>`
        : `<div class="title">${esc(m?.title || "")}</div>`;
    const conn = m
      ? `<button class="chip ${this._connected ? "on" : ""}" data-action="toggle-connection">
           <span class="dot"></span>${esc(this._connected ? this._fmt("sensor.state") : this._t("offline"))}
         </button>`
      : "";
    // The bar sits under the header on wide screens and docks to the
    // bottom on phones, like the app's tab bar (CSS decides).
    return `
      <header class="toolbar">
        <ha-menu-button></ha-menu-button>
        <img class="logo light" src="/xbloom_brand/logo.png" alt="xbloom">
        <img class="logo dark" src="/xbloom_brand/dark_logo.png" alt="xbloom">
        ${picker}
        <div class="spacer"></div>
        ${conn}
      </header>
      ${m ? `<nav class="nav">${tabs
        .map((t) => `<button class="nav-item ${this._tab === t ? "active" : ""}" data-action="tab" data-arg="${t}">
            ${ICONS[t]}<span>${this._t(`tab_${t}`)}</span></button>`)
        .join("")}</nav>` : ""}
      <main class="content tab-${this._tab}">${this._renderBody()}</main>`;
  }

  _renderBody() {
    if (this._machines === null) return `<div class="empty">${this._t("loading")}</div>`;
    if (!this._machine) return `<div class="empty">${this._t("no_machines")}</div>`;
    switch (this._tab) {
      case "recipes":
        if (this._editor) return this._renderEditor();
        if (this._recipeView && this._findRecipe(this._recipeView)) return this._renderRecipeDetail();
        return this._renderRecipes();
      case "manual":
        return this._renderManual();
      case "settings":
        return this._renderSettings();
      default:
        return this._renderHome();
    }
  }

  // ---- Brew (home)

  _renderHome() {
    const m = this._machine;
    const state = this._state;
    const recipe = m.recipes.find((r) => r.name === this._val("select.recipe"));
    const armed = ARMED_STATES.has(state);
    const busy = BUSY_STATES.has(state);
    const pausable = PAUSABLE_STATES.has(state);
    const target = recipe ? totalWater(recipe) + Number(recipe.bypass_volume || 0) : 0;
    const alerts = [];
    if (this._val("binary_sensor.water_level") === "on" || state === "water_shortage") alerts.push(this._t("water_low"));
    if (this._val("binary_sensor.problem") === "on") alerts.push(this._t("problem"));

    const options = (this._st("select.recipe")?.attributes.options || [])
      .filter((o) => m.recipes.some((r) => r.name === o));
    const stage = STAGE_OF_STATE[state];
    return `
      ${alerts.map((a) => `<div class="alert">${esc(a)}</div>`).join("")}
      <div class="brew-grid">
        <section class="hero">
          ${stage === undefined
            // Idle: the machine itself, like the app's home screen.
            ? `<div class="machine">
                <img class="machine-img" src="${machineImage(m)}" alt="xBloom Studio">
                <div class="big" data-live="sensor.weight">–</div>
                <div class="sub">${esc(this._fmt("sensor.state"))}</div>
              </div>`
            : `<div class="ring" data-target="${target}">
                <svg viewBox="0 0 120 120">
                  <circle class="track" cx="60" cy="60" r="54"/>
                  <circle class="bar" cx="60" cy="60" r="54" data-live-ring
                    stroke-dasharray="339.3" stroke-dashoffset="339.3"/>
                </svg>
                <div class="ring-center">
                  <div class="big" data-live="sensor.weight">–</div>
                  <div class="sub">${esc(this._fmt("sensor.state"))}</div>
                  ${target ? `<div class="sub dim">${this._t("target")} ${num(target)} ml</div>` : ""}
                </div>
              </div>`}
          <ol class="stages">${STAGES
            .map((s, i) => `<li class="${stage === i ? "active" : stage > i ? "done" : ""}">${ICONS[s]}<span>${this._t(`stage_${s}`)}</span></li>`)
            .join("")}</ol>
          <div class="stats">
            <div><span class="label">${this._t("brewer_temp")}</span><span class="stat" data-live="sensor.brewer_temperature" data-live-fmt="temp">–</span></div>
            <div><span class="label">${this._t("flow")}</span><span class="stat" data-live="sensor.flow_rate">–</span></div>
          </div>
          ${armed ? `<div class="hint on-dark">${this._t("armed_hint")}</div>` : ""}
          <div class="actions">
            ${pausable
              ? `<button class="btn go" data-action="press" data-arg="button.pause">${this._t(state === "paused" ? "resume" : "pause")}</button>`
              : `<button class="btn go" data-action="press" data-arg="button.execute_recipe" ${!recipe || busy || (armed && state !== "armed_recipe") ? "disabled" : ""}>
                   <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>${this._t(state === "armed_recipe" ? "start_brew" : "load_recipe")}</button>`}
            <button class="btn ghost" data-action="press" data-arg="button.cancel" ${IDLE_STATES.has(state) ? "disabled" : ""}>${this._t("cancel")}</button>
          </div>
        </section>

        <section class="card recipe-panel">
          ${recipe ? this._recipeArt(recipe, "art-banner") : ""}
          <div class="card-head">
            <span class="label">${this._t("selected_recipe")}</span>
            <select data-select="select.recipe" ${busy || armed ? "disabled" : ""}>
              ${recipe ? "" : `<option selected disabled>${this._t("choose_recipe")}</option>`}
              ${options.map((o) => `<option ${recipe?.name === o ? "selected" : ""}>${esc(o)}</option>`).join("")}
            </select>
          </div>
          ${recipe ? this._renderRecipeMetrics(recipe) : `<div class="muted">${this._t("no_recipe")}</div>`}
          ${recipe ? this._renderPourTimeline(recipe, true) : ""}
        </section>
      </div>`;
  }

  // Card art: the hub's cover image when there is one, otherwise a
  // generated dot-matrix tile tinted per recipe.
  _recipeArt(r, cls = "art", image = null) {
    const tea = isTea(r) || /tea/i.test(String(r.cup_type || ""));
    if (image && SAFE_IMAGE.test(image)) {
      return `<div class="${cls} photo" style="background-image:url('${image}')"></div>`;
    }
    const h = nameHue(r.name, tea);
    const figure = tea ? `${num(totalWater(r))}<small>ml</small>` : `${num(r.dose_g, 1)}<small>g</small>`;
    return `<div class="${cls}" style="--h:${h}">
      ${tea ? ICONS.tea : ICONS.home}
      <div class="art-figure">${figure}</div>
    </div>`;
  }

  _renderRecipeMetrics(r) {
    const tea = isTea(r);
    const firstTemp = r.pours?.[0]?.temperature_c;
    const cells = tea
      ? [[this._t("water"), `${num(totalWater(r))}<small>ml</small>`],
         [this._t("temp"), tempLabel(firstTemp)],
         [this._t("pours"), num(r.pours?.length || 0)]]
      : [[this._t("dose"), `${num(r.dose_g, 1)}<small>g</small>`],
         [this._t("ratio"), `1:${num(r.ratio, 1)}`],
         [this._t("water"), `${num(totalWater(r))}<small>ml</small>`],
         [this._t("grind"), num(r.grind_size)],
         [this._t("temp"), tempLabel(firstTemp)]];
    return `<div class="metrics">${cells
      .map(([l, v]) => `<div class="metric"><div class="value">${v}</div><div class="label">${esc(l)}</div></div>`)
      .join("")}</div>`;
  }

  _renderPourTimeline(r, compact = false) {
    const pours = r.pours || [];
    let acc = 0;
    return `<ol class="timeline ${compact ? "compact" : ""}">${pours
      .map((p, i) => {
        acc += Number(p.volume_ml || 0);
        return `<li>
          <div class="step">${i + 1}</div>
          <div class="pour-main">
            <div class="pour-vol">${p.name ? `<span class="pour-name">${esc(p.name)}</span>` : ""}${num(p.volume_ml)} ml <span class="muted">→ ${num(acc)} ml</span></div>
            <div class="pour-meta">
              <span>${tempLabel(p.temperature_c)}</span>
              ${p.flow_rate != null ? `<span>${num(p.flow_rate, 1)} ml/s</span>` : ""}
              ${(PATTERNS[p.pattern] ?? p.pattern) ? `<span class="pat">${PATTERN_ICON[PATTERNS[p.pattern] ?? p.pattern] || ""}${this._t(PATTERNS[p.pattern] ?? p.pattern)}</span>` : ""}
              ${p.vibration && p.vibration !== "none" ? `<span>${this._t("vibration")}: ${this._t(`vib_${p.vibration}`)}</span>` : ""}
              ${Number(p.pause_seconds) ? `<span>⏱ ${num(p.pause_seconds)}s</span>` : ""}
            </div>
          </div>
        </li>`;
      })
      .join("")}
      ${Number(r.bypass_volume) ? `<li class="bypass"><div class="step">+</div><div class="pour-main"><div class="pour-vol">${this._t("bypass")} ${num(r.bypass_volume)} ml</div><div class="pour-meta"><span>${tempLabel(r.bypass_temperature)}</span></div></div></li>` : ""}
    </ol>`;
  }

  // ---- Recipes

  _renderRecipes() {
    const switcher = `<div class="segmented wide">${[["mine", "my_recipes"], ["pods", "pods"], ["cloud", "cloud"]]
      .map(([v, label]) => `<button class="${this._recipesView === v ? "active" : ""}" data-action="recipes-view" data-arg="${v}">${this._t(label)}</button>`)
      .join("")}</div>`;
    if (this._recipesView === "cloud") {
      return this._cloud.open != null ? this._renderCloudDetail() : switcher + this._renderCloud();
    }
    if (this._recipesView === "pods") {
      return this._openPod ? this._renderPodDetail(this._openPod) : switcher + this._renderPods();
    }
    const kinds = ["all", "coffee", "tea"];
    return `
      ${switcher}
      <div class="recipes-bar">
        <input class="search" type="search" data-search placeholder="${this._t("search")}" value="${esc(this._filter.q)}">
        <div class="segmented">${kinds
          .map((k) => `<button class="${this._filter.kind === k ? "active" : ""}" data-action="filter" data-arg="${k}">${this._t(k)}</button>`)
          .join("")}</div>
        <button class="btn primary small" data-action="new-recipe">+ ${this._t("new_recipe")}</button>
      </div>
      <div class="grid" id="recipe-grid">${this._recipeCards()}</div>`;
  }

  // ---- Pods (pod library — modeled on the app's PodsDetailActivity)

  _when(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const lang = this._hass?.locale?.language || "en";
    return d.toLocaleString(lang, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  _podArt(pod, cls = "art") {
    const image = SAFE_IMAGE.test(pod.image || "") ? pod.image : null;
    // The app tints the pod screen with the pod's own colour (theColor).
    const tint = POD_COLOR.test(pod.color || "") ? pod.color : null;
    const style = [tint && `--pod:${tint}`, image && `background-image:url('${image}')`]
      .filter(Boolean).join(";");
    return image
      ? `<div class="${cls} photo pod-art" style="${style}"></div>`
      : `<div class="${cls} pod-art" style="${style}">${ICONS.home}<div class="art-figure">${esc(pod.xid)}</div></div>`;
  }

  _renderPods() {
    const list = this._pods.list;
    if (list === null) return `<div class="empty">${this._t("loading")}</div>`;
    if (!list.length) return `<div class="empty">${this._t("pods_empty")}</div>`;
    return `<div class="grid">${list
      .map((pod) => `<button class="recipe-card" data-action="open-pod" data-arg="${esc(pod.xid)}">
          ${this._podArt(pod)}
          <div class="rc-body">
            <div class="rc-top">
              ${pod.type ? `<span class="badge">${esc(pod.type)}</span>` : ""}
              <span class="badge gold">${esc(pod.xid)}</span>
              ${pod.recipes?.length ? "" : `<span class="badge warn-badge">!</span>`}
            </div>
            <div class="rc-name"><span class="muted">xbloom｜</span>${esc(pod.name || pod.xid)}</div>
            ${pod.roaster ? `<div class="muted small">${esc(pod.roaster)}</div>` : ""}
            ${pod.origin ? `<div class="rc-specs"><span>${esc(pod.origin)}</span></div>` : ""}
            <div class="muted small">${esc(this._t("last_scanned", { when: this._when(pod.last_scanned) }))} · ${esc(this._t("scans", { n: pod.scans || 1 }))}</div>
          </div>
        </button>`)
      .join("")}</div>`;
  }

  _renderPodDetail(pod) {
    const recipes = pod.recipes || [];
    const index = Math.min(this._pods.recipe, Math.max(0, recipes.length - 1));
    const recipe = recipes[index];
    const confirmForget = this._confirm === `forget:${pod.xid}`;
    const roast = Number(pod.roast) || 0;
    const bean = [
      ["notes", pod.flavor], ["process", pod.process], ["variety", pod.varietal],
      ["type", pod.type], ["origin", pod.origin],
    ].filter(([, v]) => v);
    return `
      <button class="link" data-action="close-pod">‹ ${this._t("back")}</button>
      <div class="detail-grid">
      <section class="card pod-card">
        ${this._podArt(pod, "art-hero")}
        ${recipes.length ? "" : `<div class="alert">${this._t("pod_no_info")}</div>
          <button class="btn go" data-action="refresh-pod" ${this._pods.refreshing ? "disabled" : ""}>
            ${this._t(this._pods.refreshing ? "loading" : "pod_retry")}</button>`}
        ${recipes.length > 1 ? `<div class="segmented wide">${recipes
          .map((r, i) => `<button class="${i === index ? "active" : ""}" data-action="pod-recipe" data-arg="${i}">${esc(r.name)}</button>`)
          .join("")}</div>` : ""}
        <button class="pod-row" data-action="toggle-bean" aria-expanded="${this._pods.bean}">
          ${SAFE_IMAGE.test(pod.image || "") ? `<img class="pod-thumb" src="${pod.image}" alt="">` : ""}
          <span class="pod-row-text">
            <b><span class="muted">xbloom｜</span>${esc(pod.name || pod.xid)}</b>
            <span class="muted small">${esc(pod.roaster || pod.origin || "")}</span>
          </span>
          <span class="pod-arrow">${this._pods.bean ? "▾" : "▸"}</span>
        </button>
        ${this._pods.bean ? `
        <div class="bean-sheet">
          <h2>${this._t("bean_info")}</h2>
          ${pod.introduce ? `<p class="small">${esc(pod.introduce)}</p>` : ""}
          ${roast ? `<div class="kv"><span>${this._t("roast")}</span>
            <span class="roast">${[1, 2, 3, 4, 5].map((n) => `<i class="${n <= roast ? "on" : ""}"></i>`).join("")}</span></div>` : ""}
          ${bean.map(([k, v]) => `<div class="kv"><span>${this._t(k)}</span><span>${esc(v)}</span></div>`).join("")}
        </div>` : ""}
        ${recipe ? this._renderRecipeMetrics(recipe) : ""}
      </section>
      ${recipe ? `<section class="card"><h2>${this._t("pours")}</h2>${this._renderPourTimeline(recipe)}</section>` : ""}
      </div>
      <div class="actions">
        <button class="btn go" data-action="save-pod-recipe" ${recipe ? "" : "disabled"}>${this._t("save_to_mine")}</button>
        <button class="btn danger" data-action="forget-pod">${this._t(confirmForget ? "confirm_delete" : "delete")}</button>
      </div>`;
  }

  _renderCloud() {
    const c = this._cloud;
    const chips = (key, values) => `<div class="segmented">${values
      .map(([v, label]) => `<button class="${c[key] === v ? "active" : ""}" data-action="cloud-filter" data-arg="${key}:${v}" ${c.loading ? "disabled" : ""}>${this._t(label)}</button>`)
      .join("")}</div>`;
    const localShares = new Set(this._machine.recipes.map((r) => r.share_url).filter(Boolean));
    let list = "";
    if (c.results === null) {
      list = c.loading ? `<div class="empty">${this._t("loading")}</div>` : "";
    } else if (!c.results.length) {
      list = `<div class="empty">${this._t("cloud_empty")}</div>`;
    } else {
      list = `<div class="grid">${c.results.map((item, i) => this._cloudCard(item, i, localShares)).join("")}</div>`;
    }
    return `
      <div class="hint">${this._t("cloud_hint")}</div>
      <section class="card">
        <div class="label">${this._t("share_link")}</div>
        <div class="slot-write">
          <input type="text" data-share-link value="${esc(this._shareLink)}" placeholder="https://share-h5.xbloom.com/?id=…">
          <button class="btn small" data-action="import-link" ${c.importing ? "disabled" : ""}>${this._t("import_link")}</button>
        </div>
      </section>
      <div class="recipes-bar">
        <input class="search" type="search" data-cloud-q placeholder="${this._t("cloud_search")}" value="${esc(c.q)}">
        <button class="btn primary small" data-action="cloud-search" ${c.loading ? "disabled" : ""}>${this._t("search_btn")}</button>
      </div>
      <div class="recipes-bar">
        ${chips("category", [["", "all"], ["coffee", "coffee"], ["tea", "tea"]])}
        ${chips("src", [["", "all"], ["official", "official"], ["user", "community"]])}
        <select data-cloud-sort ${c.loading ? "disabled" : ""}>${["likes", "downloads", "date"]
          .map((s) => `<option value="${s}" ${c.sort === s ? "selected" : ""}>${this._t(`sort_${s}`)}</option>`)
          .join("")}</select>
      </div>
      ${c.total != null && c.results?.length ? `<div class="muted small">${this._t("results", { n: c.total })}</div>` : ""}
      ${list}
      ${c.results?.length && c.page < c.totalPage
        ? `<button class="btn dashed" data-action="cloud-more" ${c.loading ? "disabled" : ""}>${this._t(c.loading ? "loading" : "load_more")}</button>`
        : ""}`;
  }

  _cloudCard(item, i, localShares) {
    const key = this._cloudKey(item);
    const done = this._cloud.imported.has(key) || (item.share_url && localShares.has(item.share_url));
    const busy = this._cloud.importing === key;
    const tea = /tea/i.test(String(item.cup_type || ""));
    const tags = [...(item.origin || []), item.roast, ...(item.flavor || [])].filter(Boolean).slice(0, 4);
    // The card opens the recipe's detail page; its Import button keeps its
    // own action (the closest data-action wins).
    return `<div class="recipe-card clickable" data-action="open-cloud" data-arg="${i}" role="button" tabindex="0">
      ${this._recipeArt({ name: item.name, cup_type: item.cup_type, dose_g: item.dose_g, pours: [{ volume_ml: item.total_water_ml || 0 }] }, "art", item.image_url)}
      <div class="rc-body">
        <div class="rc-top">
          ${item.cup_type ? `<span class="badge ${tea ? "tea" : ""}">${esc(item.cup_type)}</span>` : ""}
          ${item.official ? `<span class="badge gold">${this._t("official")}</span>` : ""}
          ${item.likes_count != null ? `<span class="likes">♥ ${num(item.likes_count)}</span>` : ""}
        </div>
        <div class="rc-name">${esc(item.name)}</div>
        ${!item.official && item.user_name ? `<div class="muted small">${esc(this._t("by", { name: item.user_name }))}</div>` : ""}
        <div class="rc-specs">
          ${Number(item.dose_g) ? `<span>${num(item.dose_g, 1)}g</span>` : ""}
          ${Number(item.ratio) ? `<span>1:${num(item.ratio, 1)}</span>` : ""}
          ${Number(item.total_water_ml) ? `<span>${num(item.total_water_ml)}ml</span>` : ""}
          ${item.pour_count ? `<span>${this._t("pours")} ${num(item.pour_count)}</span>` : ""}
        </div>
        ${tags.length ? `<div class="rc-tags">${tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>` : ""}
        <button class="btn small ${done ? "" : "go"}" data-action="cloud-import" data-arg="${i}" ${done || busy || this._cloud.importing ? "disabled" : ""}>
          ${this._t(done ? "imported" : busy ? "importing" : "import")}</button>
      </div>
    </div>`;
  }

  // ---- Cloud recipe detail (what collective.xbloom.com/recipe/{id} shows)

  async _openCloudDetail(index) {
    const item = this._cloud.results?.[index];
    if (!item) return;
    this._cloud.open = index;
    this._cloud.detail = null;
    this._render();
    try {
      this._cloud.detail = await this._hass.callWS({
        type: "xbloom/cloud_detail", entry_id: this._entryId, community_recipe_id: item.community_recipe_id,
      });
    } catch (err) {
      this._toast(err.message || String(err));
      this._cloud.detail = { failed: true };
    }
    if (this._cloud.open === index) this._render();
  }

  _renderCloudDetail() {
    const item = this._cloud.results?.[this._cloud.open] || {};
    const d = this._cloud.detail;
    const back = `<button class="link" data-action="close-cloud">‹ ${this._t("back")}</button>`;
    if (!d) return `${back}<div class="empty">${this._t("loading")}</div>`;
    const r = d.failed ? item : d;
    const localShares = new Set(this._machine.recipes.map((x) => x.share_url).filter(Boolean));
    const key = this._cloudKey(item);
    const done = this._cloud.imported.has(key) || (item.share_url && localShares.has(item.share_url));
    const busy = this._cloud.importing === key;
    const tea = /tea/i.test(String(r.cup_type || ""));
    const roast = Number(r.roast) || 0;
    const rows = [["origin", r.origin], ["process", r.process], ["variety", r.varietal],
      ["type", r.type], ["notes", r.flavor]].filter(([, v]) => v && typeof v === "string");
    const product = SAFE_STORE_LINK.test(d.product_url || "") ? d.product_url : null;
    const recipe = { name: r.name, cup_type: tea ? "tea" : r.cup_type, dose_g: r.dose_g, ratio: r.ratio,
      grind_size: r.grind_size, pours: r.pours || [] };
    return `${back}
      <div class="detail-grid">
      <section class="card detail">
        <div class="detail-hero">
          ${this._recipeArt({ name: r.name, cup_type: r.cup_type, dose_g: r.dose_g, pours: [] }, "art-hero", r.image_url)}
          <div class="detail-head">
            <div class="rc-top">
              ${r.cup_type ? `<span class="badge ${tea ? "tea" : ""}">${esc(r.cup_type)}</span>` : ""}
              ${r.official ? `<span class="badge gold">${this._t("official")}</span>` : ""}
              ${r.likes_count != null ? `<span class="likes">♥ ${num(r.likes_count)}</span>` : ""}
            </div>
            <h1>${esc(r.name)}</h1>
            <div class="dim small">${esc([!r.official && r.user_name ? this._t("by", { name: r.user_name }) : "",
              r.upload_date ? this._t("uploaded", { date: r.upload_date }) : ""].filter(Boolean).join(" · "))}</div>
          </div>
        </div>
        ${d.failed ? `<div class="alert">${this._t("cloud_detail_failed")}</div>` : ""}
        ${r.introduce ? `<p class="intro">${esc(r.introduce)}</p>` : ""}
        ${roast || rows.length ? `<div class="bean-sheet">
          ${roast ? `<div class="kv"><span>${this._t("roast")}</span>
            <span class="roast">${[1, 2, 3, 4, 5].map((n) => `<i class="${n <= roast ? "on" : ""}"></i>`).join("")}</span></div>` : ""}
          ${rows.map(([k, v]) => `<div class="kv"><span>${this._t(k)}</span><span>${esc(v)}</span></div>`).join("")}
        </div>` : ""}
        ${r.dose_g != null ? this._renderRecipeMetrics(recipe) : ""}
        ${r.rpm ? `<div class="kv"><span>${this._t("rpm")}</span><span>${num(r.rpm)}</span></div>` : ""}
      </section>
      ${(r.pours || []).length ? `<section class="card"><h2>${this._t("pours")}</h2>${this._renderPourTimeline(recipe)}</section>` : ""}
      </div>
      <div class="actions">
        <button class="btn ${done ? "" : "go"}" data-action="cloud-import" data-arg="${this._cloud.open}" ${done || busy || this._cloud.importing ? "disabled" : ""}>
          ${this._t(done ? "imported" : busy ? "importing" : "import")}</button>
        ${product ? `<a class="btn" href="${product}" target="_blank" rel="noopener noreferrer">${this._t("buy_beans")} ↗</a>` : ""}
      </div>`;
  }

  _renderRecipeGrid() {
    const grid = this.shadowRoot.querySelector("#recipe-grid");
    if (grid) grid.innerHTML = this._recipeCards();
  }

  _recipeCards() {
    const q = this._filter.q.trim().toLowerCase();
    const list = this._machine.recipes
      .filter((r) => !q || r.name.toLowerCase().includes(q))
      .filter((r) => this._filter.kind === "all" || (this._filter.kind === "tea") === isTea(r))
      .sort((a, b) => a.name.localeCompare(b.name));
    if (!list.length) return `<div class="empty">${this._t("empty_recipes")}</div>`;
    const selected = this._val("select.recipe");
    return list
      .map((r) => {
        const tea = isTea(r);
        return `<button class="recipe-card ${r.name === selected ? "selected" : ""}" data-action="open-recipe" data-arg="${esc(r.uid)}">
          ${this._recipeArt(r)}
          <div class="rc-body">
            <div class="rc-top"><span class="badge ${tea ? "tea" : ""}">${this._t(`cup_${r.cup_type}`)}</span></div>
            <div class="rc-name">${esc(r.name)}</div>
            <div class="rc-specs">
              ${tea ? "" : `<span>1:${num(r.ratio, 1)}</span>`}
              <span>${num(totalWater(r))}ml</span>
              <span>${tempLabel(r.pours?.[0]?.temperature_c)}</span>
              ${tea ? "" : `<span>#${num(r.grind_size)}</span>`}
            </div>
          </div>
        </button>`;
      })
      .join("");
  }

  _renderRecipeDetail() {
    const r = this._findRecipe(this._recipeView);
    const state = this._state;
    const blocked = BUSY_STATES.has(state) || ARMED_STATES.has(state);
    const confirmDelete = this._confirm === `delete:${r.uid}`;
    return `
      <button class="link" data-action="close-recipe">‹ ${this._t("back")}</button>
      <div class="detail-grid">
      <section class="card detail">
        <div class="detail-hero">
          ${this._recipeArt(r, "art-hero")}
          <div class="detail-head">
            <span class="badge ${isTea(r) ? "tea" : ""}">${this._t(`cup_${r.cup_type}`)}</span>
            <h1>${esc(r.name)}</h1>
            ${r.source ? `<div class="dim small">${this._t("source")}: ${esc(r.source)}</div>` : ""}
          </div>
        </div>
        ${this._renderRecipeMetrics(r)}
        ${isTea(r) ? "" : `<div class="kv"><span>${this._t("rpm")}</span><span>${num(r.rpm)}</span></div>`}
      </section>
      <section class="card">
        <h2>${this._t("pours")}</h2>
        ${this._renderPourTimeline(r)}
      </section>
      </div>
      ${blocked ? `<div class="hint">${this._t("busy_hint")}</div>` : ""}
      <div class="actions">
        <button class="btn go" data-action="brew" data-arg="${esc(r.uid)}" ${blocked ? "disabled" : ""}><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>${this._t("brew_this")}</button>
        <button class="btn" data-action="edit-recipe" data-arg="${esc(r.uid)}">${this._t("edit")}</button>
        <button class="btn" data-action="duplicate-recipe" data-arg="${esc(r.uid)}">${this._t("duplicate")}</button>
        <button class="btn danger" data-action="delete-recipe" data-arg="${esc(r.uid)}">${this._t(confirmDelete ? "confirm_delete" : "delete")}</button>
      </div>
      ${isTea(r) ? "" : `
      <section class="card">
        <div class="label">${this._t("write_slot")}</div>
        <div class="slot-row">${["A", "B", "C"]
          .map((s) => `<button class="btn small" data-action="write-slot" data-arg="${s}">${this._t("slot")} ${s}</button>`)
          .join("")}</div>
      </section>`}`;
  }

  // ---- Editor

  _renderEditor() {
    const { recipe: r } = this._editor;
    const tea = isTea(r);
    const field = (key, label, attrs, unit = "") => `
      <label class="field"><span>${this._t(label)}</span>
        <span class="input-unit"><input type="number" data-field="${key}" value="${esc(r[key] ?? "")}" ${attrs}>${unit ? `<em>${unit}</em>` : ""}</span>
      </label>`;
    return `
      <button class="link" data-action="cancel-edit">‹ ${this._t("back")}</button>
      <section class="card">
        <label class="field wide"><span>${this._t("name")}</span>
          <input type="text" data-field="name" data-kind="text" value="${esc(r.name)}" maxlength="64">
        </label>
        <label class="field"><span>${this._t("cup_type")}</span>
          <select data-field="cup_type" data-kind="text">${CUP_TYPES
            .map((c) => `<option value="${c}" ${r.cup_type === c || (c === "x_pod" && r.cup_type === "xpod") ? "selected" : ""}>${this._t(`cup_${c}`)}</option>`)
            .join("")}</select>
        </label>
        <div class="field-grid">
          ${tea ? "" : field("dose_g", "dose", 'min="1" max="100" step="0.1"', "g")}
          ${tea ? "" : field("ratio", "ratio", 'min="1" max="50" step="0.1"', "1:x")}
          ${tea ? "" : field("grind_size", "grind", 'min="1" max="80" step="1"')}
          ${tea ? "" : field("rpm", "rpm", 'min="60" max="120" step="10"')}
          ${field("bypass_volume", "bypass_volume", 'min="0" max="200" step="1"', "ml")}
          ${field("bypass_temperature", "bypass_temperature", 'min="0" max="100" step="1"', "°C")}
        </div>
        <div class="summary" id="editor-summary">${this._editorSummary()}</div>
      </section>
      <h2>${this._t("pours")}</h2>
      ${r.pours.map((p, i) => this._renderPourEditor(p, i, r.pours.length)).join("")}
      <button class="btn dashed" data-action="add-pour">+ ${this._t("add_pour")}</button>
      <div class="actions sticky">
        <button class="btn primary" data-action="save-recipe">${this._t("save")}</button>
        <button class="btn" data-action="cancel-edit">${this._t("cancel")}</button>
      </div>`;
  }

  _renderPourEditor(p, i, count) {
    const pattern = PATTERNS[p.pattern] ?? p.pattern;
    const t = Number(p.temperature_c);
    return `
      <section class="card pour-edit">
        <div class="pour-head">
          <div class="step">${i + 1}</div>
          <div class="spacer"></div>
          <button class="icon" title="${this._t("move_up")}" data-action="move-pour" data-arg="${i}:-1" ${i === 0 ? "disabled" : ""}>↑</button>
          <button class="icon" title="${this._t("move_down")}" data-action="move-pour" data-arg="${i}:1" ${i === count - 1 ? "disabled" : ""}>↓</button>
          <button class="icon danger" title="${this._t("remove")}" data-action="remove-pour" data-arg="${i}" ${count <= 1 ? "disabled" : ""}>✕</button>
        </div>
        <div class="field-grid">
          <label class="field"><span>${this._t("volume")}</span>
            <span class="input-unit"><input type="number" data-pour="${i}:volume_ml" value="${esc(p.volume_ml)}" min="1" max="500" step="1"><em>ml</em></span></label>
          <label class="field"><span>${this._t("flow_rate")}</span>
            <span class="input-unit"><input type="number" data-pour="${i}:flow_rate" value="${esc(p.flow_rate ?? 3)}" min="0.5" max="5" step="0.1"><em>ml/s</em></span></label>
          <label class="field"><span>${this._t("pause_s")}</span>
            <span class="input-unit"><input type="number" data-pour="${i}:pause_seconds" value="${esc(p.pause_seconds ?? 0)}" min="0" max="600" step="1"><em>s</em></span></label>
        </div>
        <label class="field wide"><span>${this._t("temperature")} <b data-temp-out="${i}">${tempLabel(t)}</b></span>
          <input type="range" data-pour="${i}:temperature_c" data-kind="temp" min="39" max="96" step="1" value="${tempToSlider(t)}">
        </label>
        <div class="field-grid">
          <label class="field"><span>${this._t("pattern")}</span>
            <select data-pour="${i}:pattern" data-kind="text">${PATTERNS
              .map((x) => `<option value="${x}" ${pattern === x ? "selected" : ""}>${this._t(x)}</option>`).join("")}</select></label>
          <label class="field"><span>${this._t("vibration")}</span>
            <select data-pour="${i}:vibration" data-kind="text">${VIBRATIONS
              .map((x) => `<option value="${x}" ${(p.vibration || "none") === x ? "selected" : ""}>${this._t(`vib_${x}`)}</option>`).join("")}</select></label>
        </div>
      </section>`;
  }

  _editorSummary() {
    const r = this._editor.recipe;
    const sum = pourSum(r) + Number(r.bypass_volume || 0);
    if (isTea(r)) return `${this._t("water")}: <b>${num(sum)} ml</b>`;
    const total = Number(r.dose_g || 0) * Number(r.ratio || 0);
    const mismatch = Math.abs(sum - total) >= 1;
    return `${this._t("water")}: <b>${num(total)} ml</b> · ${this._t("pours")}: ${num(sum)} ml
      ${mismatch ? `<div class="warn">${esc(this._t("total_mismatch", { sum: num(sum), total: num(total) }))}</div>` : ""}`;
  }

  _updateEditorSummary() {
    const el = this.shadowRoot.querySelector("#editor-summary");
    if (el && this._editor) el.innerHTML = this._editorSummary();
  }

  // ---- Manual

  _numberControl(key, label) {
    const s = this._st(key);
    if (!s) return "";
    const a = s.attributes;
    const v = Number(s.state);
    // The pour temperature slider's ends are RT/BP. Judged by the slider's
    // own min/max, not 39/96, so it holds when HA shows the entity in °F.
    const isTemp = key === "number.temperature";
    const unit = isTemp ? "" : a.unit_of_measurement || "";
    const shown = !Number.isFinite(v)
      ? "–"
      : isTemp
        ? endLabel(v, a.min, a.max, a.unit_of_measurement)
        : num(v);
    return `
      <label class="field wide"><span>${this._t(label)} <b><span data-range-out="${key}">${shown}</span> ${esc(unit)}</b></span>
        <input type="range" data-number="${key}" data-range-label="${key}" ${isTemp ? `data-range-fmt="temp" data-unit="${esc(a.unit_of_measurement || "")}"` : ""} min="${a.min}" max="${a.max}"
          step="${isTemp && a.unit_of_measurement === "°F" ? "any" : a.step}"
          value="${Number.isFinite(v) ? v : a.min}" ${s.state === "unavailable" ? "disabled" : ""}>
      </label>`;
  }

  _renderManual() {
    const state = this._state;
    const busy = BUSY_STATES.has(state) || ARMED_STATES.has(state);
    const patternState = this._st("select.pour_pattern");
    return `
      <div class="hint">${this._t("arm_hint")}</div>
      <div class="cols">
      <section class="card">
        <h2 class="with-icon">${ICONS.grind}${this._t("grinder")}</h2>
        ${this._numberControl("number.grind_size", "grind_size")}
        ${this._numberControl("number.rpm", "rpm")}
        <div class="stats inline">
          <div><span class="label">${this._t("grind")}</span><span data-live="sensor.live_grind_size">–</span></div>
          <div><span class="label">${this._t("rpm")}</span><span data-live="sensor.live_grind_speed">–</span></div>
        </div>
        <div class="actions">
          <button class="btn go" data-action="press" data-arg="button.grind" ${busy ? "disabled" : ""}>
            ${this._t(state === "standalone_grind" ? "start_grind" : "grind_btn")}</button>
          <button class="btn" data-action="press" data-arg="button.cancel" ${IDLE_STATES.has(state) ? "disabled" : ""}>${this._t("cancel")}</button>
        </div>
      </section>

      <section class="card">
        <h2 class="with-icon">${ICONS.pour}${this._t("brewer")}</h2>
        ${this._numberControl("number.volume", "volume")}
        ${this._numberControl("number.temperature", "temperature")}
        ${patternState ? `
        <div class="segmented wide">${(patternState.attributes.options || PATTERNS)
          .map((o) => `<button class="${patternState.state === o ? "active" : ""}" data-action="set-pattern" data-arg="${esc(o)}">${PATTERN_ICON[o] || ""}${this._t(o)}</button>`)
          .join("")}</div>` : ""}
        <div class="actions">
          <button class="btn go" data-action="press" data-arg="button.pour" ${busy ? "disabled" : ""}>
            ${this._t(state === "standalone_pour" ? "start_pour" : "pour")}</button>
          <button class="btn" data-action="press" data-arg="button.pause" ${PAUSABLE_STATES.has(state) ? "" : "disabled"}>${this._t(state === "paused" ? "resume" : "pause")}</button>
        </div>
      </section>

      <section class="card">
        <h2 class="with-icon">${ICONS.scale}${this._t("scale")}</h2>
        <div class="big center" data-live="sensor.weight">–</div>
        <div class="actions">
          <button class="btn" data-action="press" data-arg="button.tare_scale">${this._t("tare")}</button>
          <button class="btn" data-action="press" data-arg="button.scale_mode">${this._t(state === "standalone_scale" ? "exit_scale" : "scale_mode")}</button>
        </div>
      </section>
      </div>`;
  }

  // ---- Settings

  _renderSettings() {
    const m = this._machine;
    const modeState = this._st("select.mode");
    const coffee = m.recipes.filter((r) => !isTea(r)).sort((a, b) => a.name.localeCompare(b.name));
    const level = (key, sensorKey, min, max, label) => {
      const cur = Number(this._val(sensorKey));
      const v = Number.isFinite(cur) ? cur : min;
      return `
        <div class="adv-row">
          <label class="field wide"><span>${this._t(label)} <b data-range-out="adv-${key}">${v}</b></span>
            <input type="range" id="adv-${key}" data-range-label="adv-${key}" min="${min}" max="${max}" step="1" value="${v}">
          </label>
          <button class="btn small" data-action="advanced" data-arg="${key}">${this._t("apply")}</button>
        </div>`;
    };
    const fw = this._st("update.firmware");
    return `
      <div class="cols">
      <section class="card">
        <div class="row">
          <span>${this._t("connection")}</span>
          <button class="btn small ${this._connected ? "" : "primary"}" data-action="toggle-connection">
            ${this._t(this._connected ? "disconnect" : "connect")}</button>
        </div>
        ${modeState ? `
        <div class="row">
          <span>${this._t("mode")}</span>
          <div class="segmented">${(modeState.attributes.options || ["pro", "easy"])
            .map((o) => `<button class="${modeState.state === o ? "active" : ""}" data-action="set-mode" data-arg="${esc(o)}">${this._t(o)}</button>`)
            .join("")}</div>
        </div>` : ""}
      </section>

      <section class="card">
        <h2>${this._t("easy_slots")}</h2>
        ${["A", "B", "C"].map((s) => {
          const cur = m.easy_slots?.[s];
          return `<div class="slot">
            <div class="slot-letter">${s}</div>
            <div class="slot-body">
              <div class="slot-name">${cur ? esc(cur.name) : `<span class="muted">${this._t("empty_slot")}</span>`}</div>
              <div class="slot-write">
                <select id="slot-${s}">${cur ? "" : `<option value="" selected disabled>${this._t("choose")}</option>`}${coffee
                  .map((r) => `<option value="${esc(r.uid)}" ${cur?.uid === r.uid ? "selected" : ""}>${esc(r.name)}</option>`)
                  .join("")}</select>
                <button class="btn small" data-action="write-slot-from" data-arg="${s}">${this._t("write")}</button>
              </div>
            </div>
          </div>`;
        }).join("")}
      </section>

      <section class="card">
        <h2>${this._t("advanced")}</h2>
        ${level("pour_radius_level", "sensor.pour_radius", 0, 4, "pour_radius")}
        ${level("vibration_amplitude_level", "sensor.vibration_amplitude", 0, 5, "vibration_amp")}
        ${level("display_brightness_level", "", 1, 3, "brightness")}
      </section>

      <section class="card">
        <h2>${this._t("maintenance")}</h2>
        <div class="row">
          <span>${this._t("calibrate_grinder")}</span>
          <button class="btn small ${this._confirm === "calibrate" ? "danger" : ""}" data-action="calibrate"
            ${BUSY_STATES.has(this._state) || !this._connected ? "disabled" : ""}>
            ${this._t(this._confirm === "calibrate" ? "confirm_calibrate" : "calibrate_grinder")}</button>
        </div>
      </section>

      <section class="card device-card">
        <div class="device-stage"><img class="device-img" src="${machineImage(m)}" alt="xBloom Studio"></div>
        <h2>${this._t("device")}</h2>
        <div class="kv"><span>${this._t("color")}</span>
          <span>${esc(this._t(m.detected_color ? `color_${m.detected_color}` : "color_unknown"))}</span></div>
        <div class="kv"><span>${this._t("mac")}</span><span>${esc(m.mac)}</span></div>
        <div class="kv"><span>${this._t("serial")}</span><span>${esc(this._fmt("sensor.serial_number"))}</span></div>
        <div class="kv"><span>${this._t("firmware")}</span><span>${esc(fw?.attributes.installed_version || "–")}</span></div>
      </section>
      </div>`;
  }

  // ---------------------------------------------------------------- live

  _updateLive() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-live]").forEach((el) => {
      el.textContent = this._fmt(el.dataset.live);
      // The brewer temperature is the knob setpoint the machine pushes
      // (literal °C), so its 39/96 °C ends are RT/BP just like the slider —
      // compared in °C even when HA shows the entity in °F.
      if (el.dataset.liveFmt === "temp") {
        const st = this._st(el.dataset.live);
        const c = toCelsius(st?.state, st?.attributes.unit_of_measurement);
        if (Number.isFinite(c) && (c <= 39.5 || c >= 95.5)) el.textContent = c <= 39.5 ? "RT" : "BP";
      }
    });
    const ring = root.querySelector("[data-live-ring]");
    if (ring) {
      const target = Number(ring.closest(".ring").dataset.target) || 0;
      // Target is the recipe's water in ml (≈ g); the scale may be shown in
      // oz/lb if the user changed the entity's unit.
      const ws = this._st("sensor.weight");
      const w = Number(this._val("sensor.weight")) * (GRAMS_PER[ws?.attributes.unit_of_measurement] ?? 1);
      const frac = target > 0 && Number.isFinite(w) ? Math.max(0, Math.min(1, w / target)) : 0;
      ring.setAttribute("stroke-dashoffset", String(339.3 * (1 - frac)));
    }
  }
}

// Palette taken from the official app's own colour resources (near-black
// surfaces, gold accent, pastel-blue start button); the light variant
// keeps the same accents on warm greys.
const STYLE = `
  :host {
    --xb-bg: #f3f2f0;
    --xb-card: #ffffff;
    --xb-card-2: #f0eeea;
    --xb-text: #18191b;
    --xb-muted: #7a838e;
    --xb-line: #e3e3e3;
    --xb-gold: #a8894a;
    --xb-go: #b3c7e0;
    --xb-go-text: #18191b;
    --xb-tea: #5b8c56;
    --xb-danger: #c4573f;
    --xb-ok: #2e9e62;
    --xb-shadow: 0 1px 2px rgba(24,25,27,.05), 0 8px 24px rgba(24,25,27,.06);
    --xb-hero: radial-gradient(120% 90% at 50% 0%, #2b2d31 0%, #18191b 60%, #101010 100%);
    --xb-radius: 22px;
    --xb-serif: "Iowan Old Style", "New York", ui-serif, "Palatino Linotype", Palatino, Georgia, serif;
    --xb-nav-h: 0px;
    display: block; min-height: 100vh; background: var(--xb-bg); color: var(--xb-text);
    font-family: var(--paper-font-body1_-_font-family, -apple-system, system-ui, "Segoe UI", Roboto, sans-serif);
    -webkit-font-smoothing: antialiased;
  }
  :host([dark]) {
    --xb-bg: #101112;
    --xb-card: #1b1c1f;
    --xb-card-2: #232426;
    --xb-text: #ededee;
    --xb-muted: #8b939d;
    --xb-line: #2e3135;
    --xb-gold: #c5af77;
    --xb-tea: #8fbf8a;
    --xb-danger: #e2745b;
    --xb-ok: #89e2ad;
    --xb-shadow: none;
  }
  * { box-sizing: border-box; }
  button { font: inherit; color: inherit; cursor: pointer; -webkit-tap-highlight-color: transparent; }
  button:disabled { opacity: .38; cursor: default; }
  select, input { font: inherit; color: var(--xb-text); background: var(--xb-card-2);
    border: 1px solid transparent; border-radius: 12px; padding: 9px 12px; min-width: 0; }
  select:focus, input:focus { outline: none; border-color: var(--xb-gold); }
  select:disabled { opacity: .6; }
  input[type=range] { width: 100%; padding: 0; border: 0; background: none; accent-color: var(--xb-gold); height: 28px; }
  svg { width: 16px; height: 16px; flex: none; }
  .dots { opacity: .95; }

  /* ---- header + navigation */
  .toolbar { display: flex; align-items: center; gap: 10px; height: var(--header-height, 56px);
    padding: 0 16px 0 8px; background: color-mix(in srgb, var(--xb-bg) 88%, transparent);
    backdrop-filter: saturate(1.4) blur(14px); -webkit-backdrop-filter: saturate(1.4) blur(14px);
    border-bottom: 1px solid var(--xb-line); position: sticky; top: 0; z-index: 3; }
  .logo { height: 20px; width: auto; display: block; }
  .logo.dark { display: none; height: 32px; margin: 0 -6px; }
  :host([dark]) .logo.light { display: none; }
  :host([dark]) .logo.dark { display: block; }
  .title { font-size: 14px; color: var(--xb-muted); padding-left: 10px; border-left: 1px solid var(--xb-line);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .machine-picker { font-size: 14px; }
  .spacer { flex: 1; }
  .chip { display: inline-flex; align-items: center; gap: 7px; border: 1px solid var(--xb-line);
    border-radius: 999px; padding: 5px 12px; background: var(--xb-card); font-size: 13px; white-space: nowrap; }
  .chip .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--xb-muted); }
  .chip.on .dot { background: var(--xb-ok); box-shadow: 0 0 0 3px color-mix(in srgb, var(--xb-ok) 25%, transparent); }
  .nav { display: flex; gap: 4px; justify-content: center; padding: 12px 16px 0; position: sticky; top: var(--header-height, 56px); z-index: 2; }
  .nav-item { display: inline-flex; align-items: center; gap: 8px; border: 0; background: transparent;
    padding: 9px 16px; border-radius: 999px; color: var(--xb-muted); font-size: 14px; font-weight: 500; }
  .nav-item svg { width: 14px; height: 14px; }
  .nav-item.active { background: var(--xb-text); color: var(--xb-bg); }
  .content { max-width: 1180px; margin: 0 auto; padding: 20px 24px 40px; display: flex; flex-direction: column; gap: 16px;
    padding-bottom: calc(40px + var(--xb-nav-h)); }

  /* ---- type + small parts */
  h1 { font-family: var(--xb-serif); font-size: 30px; font-weight: 500; line-height: 1.15; margin: 4px 0 0; letter-spacing: -.01em; }
  h2 { font-size: 13px; font-weight: 600; margin: 0; letter-spacing: .08em; text-transform: uppercase; color: var(--xb-muted); }
  h2.with-icon { display: flex; align-items: center; gap: 10px; }
  h2.with-icon svg { width: 20px; height: 20px; color: var(--xb-gold); }
  .label { font-size: 11px; color: var(--xb-muted); text-transform: uppercase; letter-spacing: .1em; }
  .muted { color: var(--xb-muted); }
  .small { font-size: 13px; }
  .empty { text-align: center; color: var(--xb-muted); padding: 56px 0; }
  .alert { background: color-mix(in srgb, var(--xb-danger) 14%, transparent); color: var(--xb-danger);
    border-radius: 14px; padding: 12px 16px; font-weight: 500; }
  .hint { background: color-mix(in srgb, var(--xb-gold) 14%, transparent); border-radius: 14px; padding: 12px 16px; font-size: 14px; line-height: 1.45; }
  .hint.on-dark { background: rgba(197,175,119,.14); color: #e3d9bf; text-align: center; }
  .warn { color: var(--xb-danger); font-size: 13px; margin-top: 4px; }
  .card { background: var(--xb-card); border-radius: var(--xb-radius); padding: 20px;
    box-shadow: var(--xb-shadow); display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .cols { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); align-items: start; }

  /* ---- brew (home) */
  .brew-grid { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); align-items: start; }
  .hero { background: var(--xb-hero); color: #f2f2f2; border-radius: 28px; padding: 28px 22px 22px;
    display: flex; flex-direction: column; align-items: center; gap: 20px; position: relative; overflow: hidden; }
  .hero::before { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: .35;
    background-image: radial-gradient(rgba(255,255,255,.18) 1px, transparent 1.4px); background-size: 14px 14px;
    mask-image: radial-gradient(70% 60% at 50% 30%, #000, transparent); -webkit-mask-image: radial-gradient(70% 60% at 50% 30%, #000, transparent); }
  .ring { position: relative; width: min(280px, 72vw); aspect-ratio: 1; }
  .machine { position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; text-align: center; }
  .machine::before { content: ""; position: absolute; top: 6%; left: 50%; width: 78%; aspect-ratio: 1; transform: translateX(-50%);
    border-radius: 50%; background: radial-gradient(circle, rgba(197,175,119,.16), transparent 68%); pointer-events: none; }
  .machine-img { position: relative; width: min(300px, 70vw); aspect-ratio: 1; object-fit: contain;
    filter: drop-shadow(0 28px 36px rgba(0,0,0,.55)); }
  .device-card { overflow: hidden; }
  .device-stage { margin: -20px -20px 0; height: 220px; display: flex; align-items: center; justify-content: center;
    background: var(--xb-hero); overflow: hidden; }
  .device-img { height: 200px; width: 200px; object-fit: contain; filter: drop-shadow(0 18px 24px rgba(0,0,0,.5)); }
  .ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
  .ring circle { fill: none; stroke-width: 3; }
  .ring .track { stroke: rgba(255,255,255,.1); }
  .ring .bar { stroke: #c5af77; stroke-linecap: round; transition: stroke-dashoffset .5s ease;
    filter: drop-shadow(0 0 6px rgba(197,175,119,.45)); }
  .ring-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; text-align: center; }
  .big { font-family: var(--xb-serif); font-size: 54px; font-weight: 400; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
  .card .big { font-size: 46px; }
  .big.center { text-align: center; }
  .sub { font-size: 15px; }
  .dim { color: rgba(255,255,255,.55); }
  .card .dim, .detail .dim { color: var(--xb-muted); }
  .stages { list-style: none; margin: 0; padding: 0; display: flex; gap: 6px; width: 100%; max-width: 380px; justify-content: space-between; }
  .stages li { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 6px; font-size: 11px;
    letter-spacing: .06em; text-transform: uppercase; color: rgba(255,255,255,.35); }
  .stages li svg { width: 30px; height: 30px; }
  .stages li.done { color: rgba(197,175,119,.6); }
  .stages li.active { color: #c5af77; }
  .stages li.active svg { animation: pulse 1.6s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .45; } }
  .stats { display: flex; gap: 40px; justify-content: center; }
  .stats > div { display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .hero .label { color: rgba(255,255,255,.45); }
  .stat { font-size: 20px; font-variant-numeric: tabular-nums; }
  .stats.inline { justify-content: flex-start; }
  .hero .actions { width: 100%; max-width: 420px; }
  .card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .card-head select { flex: 1; max-width: 65%; }
  .recipe-panel { padding-top: 0; overflow: hidden; }
  .recipe-panel .art-banner { margin: 0 -20px; }
  .recipe-panel > .card-head:first-child { margin-top: 20px; }

  /* ---- metrics + pour timeline */
  .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(76px, 1fr)); gap: 8px; }
  .metric { text-align: center; padding: 12px 4px 10px; border-radius: 16px; background: var(--xb-card-2); }
  .metric .value { font-family: var(--xb-serif); font-size: 24px; font-variant-numeric: tabular-nums; }
  .metric small { font-family: -apple-system, system-ui, sans-serif; font-size: 11px; margin-left: 2px; color: var(--xb-muted); }
  .metric .label { margin-top: 2px; }
  .timeline { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .timeline li { display: flex; gap: 14px; position: relative; padding-bottom: 16px; }
  .timeline li:not(:last-child)::before { content: ""; position: absolute; left: 13px; top: 30px; bottom: 2px;
    border-left: 2px dotted var(--xb-line); }
  .timeline.compact li { padding-bottom: 10px; }
  .step { flex: none; width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center;
    background: var(--xb-card-2); color: var(--xb-gold); font-size: 13px; font-weight: 700; border: 1px solid var(--xb-line); }
  .bypass .step { color: var(--xb-muted); }
  .pour-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .pour-vol { font-weight: 600; font-variant-numeric: tabular-nums; }
  .pour-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--xb-muted); font-size: 13px; }
  .pat { display: inline-flex; align-items: center; gap: 4px; }

  /* ---- buttons */
  .actions { display: flex; gap: 10px; flex-wrap: wrap; }
  .actions.sticky { position: sticky; bottom: var(--xb-nav-h); padding: 12px 0; background: var(--xb-bg); z-index: 1; }
  .btn { flex: 1; min-width: 120px; border: 1px solid var(--xb-line); background: var(--xb-card);
    border-radius: 999px; padding: 13px 20px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    transition: transform .08s ease, filter .15s ease; }
  .btn:not(:disabled):active { transform: scale(.98); }
  .btn.primary { background: var(--xb-text); color: var(--xb-bg); border-color: var(--xb-text); }
  .btn.go { background: var(--xb-go); color: var(--xb-go-text); border-color: transparent; letter-spacing: .04em; }
  .btn.go:not(:disabled):hover { filter: brightness(1.05); }
  .btn.ghost { background: transparent; color: inherit; border-color: rgba(255,255,255,.18); }
  .btn.danger { color: var(--xb-danger); border-color: color-mix(in srgb, var(--xb-danger) 60%, transparent); background: transparent; }
  .btn.small { flex: none; min-width: 0; padding: 8px 15px; font-size: 13px; }
  .btn.dashed { border-style: dashed; background: transparent; }
  .link { align-self: flex-start; border: 0; background: none; color: var(--xb-muted); padding: 0; font-size: 15px; }
  .icon { border: 1px solid var(--xb-line); background: none; border-radius: 50%; width: 34px; height: 34px; }
  .icon.danger { color: var(--xb-danger); }

  /* ---- recipes */
  .recipes-bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .search { flex: 1; min-width: 180px; border-radius: 999px; padding: 11px 18px; background: var(--xb-card); border-color: var(--xb-line); }
  .segmented { display: inline-flex; background: var(--xb-card); border: 1px solid var(--xb-line); border-radius: 999px; padding: 3px; }
  .segmented button { border: 0; background: none; border-radius: 999px; padding: 7px 15px; display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; color: var(--xb-muted); }
  .segmented button.active { background: var(--xb-text); color: var(--xb-bg); }
  .segmented.wide { display: flex; }
  .segmented.wide button { flex: 1; justify-content: center; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
  .recipe-card { text-align: left; border: 0; background: var(--xb-card); border-radius: var(--xb-radius);
    padding: 0; display: flex; flex-direction: column; overflow: hidden; box-shadow: var(--xb-shadow);
    outline: 2px solid transparent; outline-offset: -2px; transition: transform .15s ease, outline-color .15s ease; }
  button.recipe-card:hover { transform: translateY(-2px); }
  .recipe-card.selected { outline-color: var(--xb-gold); }
  .recipe-card.clickable { cursor: pointer; }
  .recipe-card.clickable:hover { transform: translateY(-2px); }
  .pour-name { color: var(--xb-gold); font-weight: 600; margin-right: 8px; }
  .intro { margin: 0; line-height: 1.6; color: var(--xb-muted); font-size: 14px; }
  a.btn { text-decoration: none; color: inherit; }
  .rc-body { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 8px; flex: 1; }
  .rc-name { font-family: var(--xb-serif); font-size: 19px; line-height: 1.2; overflow-wrap: anywhere; }
  .rc-specs { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--xb-muted); font-size: 13px; font-variant-numeric: tabular-nums; }
  .rc-top { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .likes { margin-left: auto; font-size: 12px; color: var(--xb-muted); }
  .rc-tags { display: flex; flex-wrap: wrap; gap: 4px; }
  .rc-tags span { font-size: 11px; padding: 3px 9px; border-radius: 999px; background: var(--xb-card-2); color: var(--xb-muted); }
  .recipe-card .btn { align-self: flex-start; margin-top: auto; }
  .badge { display: inline-block; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .1em; padding: 4px 9px;
    border-radius: 999px; background: var(--xb-card-2); color: var(--xb-muted); }
  .badge.gold { background: color-mix(in srgb, var(--xb-gold) 18%, transparent); color: var(--xb-gold); }
  .badge.tea { background: color-mix(in srgb, var(--xb-tea) 18%, transparent); color: var(--xb-tea); }
  .badge.warn-badge { background: color-mix(in srgb, var(--xb-danger) 16%, transparent); color: var(--xb-danger); }

  /* card art: generated tile or hub photo */
  .art, .art-banner, .art-hero { position: relative; overflow: hidden; color: rgba(255,255,255,.9);
    background:
      radial-gradient(90% 120% at 85% 10%, hsl(var(--h, 30) 45% 38% / .9), transparent 60%),
      linear-gradient(160deg, hsl(var(--h, 30) 30% 20%), hsl(var(--h, 30) 20% 8%)); }
  .art { aspect-ratio: 16 / 10; }
  .art-banner { height: 120px; }
  .art-hero { height: 180px; border-radius: 18px; }
  .art .dots, .art-banner .dots, .art-hero .dots { position: absolute; right: 6%; top: 50%; transform: translateY(-50%);
    height: 74%; width: auto; opacity: .22; }
  .art-figure { position: absolute; left: 16px; bottom: 12px; font-family: var(--xb-serif); font-size: 30px; letter-spacing: -.01em; }
  .art-figure small { font-family: -apple-system, system-ui, sans-serif; font-size: 12px; margin-left: 3px; opacity: .7; }
  .photo { background-size: cover; background-position: center; background-color: #18191b; }
  /* Pods: tinted with the pod's own colour, like the app's pod screen. */
  .pod-art { background-color: var(--pod, #18191b); }
  .pod-art:not(.photo) { background:
      radial-gradient(90% 120% at 85% 10%, color-mix(in srgb, var(--pod, #8a6a3a) 80%, white 10%), transparent 60%),
      linear-gradient(160deg, color-mix(in srgb, var(--pod, #3a2c1c) 70%, black), #101010); }
  .pod-card { background: linear-gradient(180deg, color-mix(in srgb, var(--xb-gold) 6%, var(--xb-card)), var(--xb-card)); }
  .pod-row { display: flex; align-items: center; gap: 12px; width: 100%; text-align: left;
    border: 1px solid var(--xb-line); background: var(--xb-card-2); border-radius: 16px; padding: 10px 12px; }
  .pod-thumb { width: 44px; height: 44px; border-radius: 10px; object-fit: cover; flex: none; }
  .pod-row-text { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
  .pod-row-text b { font-family: var(--xb-serif); font-weight: 500; font-size: 17px; }
  .pod-arrow { color: var(--xb-muted); font-size: 18px; }
  .bean-sheet { display: flex; flex-direction: column; gap: 6px; padding: 4px 2px; }
  .bean-sheet p { margin: 0 0 4px; line-height: 1.5; color: var(--xb-muted); }
  .roast { display: inline-flex; gap: 5px; }
  .roast i { width: 9px; height: 13px; border-radius: 50%; background: var(--xb-line); display: inline-block; }
  .roast i.on { background: #8a5a2b; }
  .photo::after { content: ""; position: absolute; inset: 0; background: linear-gradient(180deg, transparent 55%, rgba(0,0,0,.35)); }

  .detail-grid { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); align-items: start; }
  .detail-hero { display: flex; flex-direction: column; gap: 14px; }
  .detail-head { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
  .kv, .row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 4px 0; }
  .kv span:first-child { color: var(--xb-muted); flex: none; white-space: nowrap; }
  .kv span:last-child { font-variant-numeric: tabular-nums; text-align: right; overflow-wrap: anywhere; }
  .slot-row { display: flex; gap: 8px; flex-wrap: wrap; }

  /* ---- forms */
  .field { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--xb-muted); min-width: 0; letter-spacing: .02em; }
  .field b { color: var(--xb-text); font-weight: 600; margin-left: 6px; font-variant-numeric: tabular-nums; }
  .field input, .field select { color: var(--xb-text); font-size: 15px; }
  .field-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; }
  .input-unit { display: flex; align-items: center; gap: 6px; }
  .input-unit input { flex: 1; width: 100%; }
  .input-unit em { font-style: normal; color: var(--xb-muted); font-size: 12px; }
  .summary { font-size: 14px; }
  .pour-head { display: flex; align-items: center; gap: 6px; }

  /* ---- settings */
  .slot { display: flex; gap: 14px; align-items: flex-start; padding: 6px 0; }
  .slot-letter { flex: none; width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center;
    background: #18191b; color: #c5af77; font-family: var(--xb-serif); font-size: 20px; }
  .slot-body { flex: 1; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .slot-name { font-weight: 600; }
  .slot-write { display: flex; gap: 8px; }
  .slot-write select, .slot-write input { flex: 1; }
  .adv-row { display: flex; gap: 12px; align-items: flex-end; }
  .adv-row .field { flex: 1; }

  /* ---- wide screens: two-column brew and recipe detail */
  @media (min-width: 900px) {
    .brew-grid { grid-template-columns: minmax(360px, 5fr) minmax(0, 6fr); }
    .hero { position: sticky; top: calc(var(--header-height, 56px) + 64px); }
    .detail-grid { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  }

  /* ---- phones: app-style bottom tab bar */
  @media (max-width: 720px) {
    :host { --xb-nav-h: calc(64px + env(safe-area-inset-bottom, 0px)); }
    .nav { position: fixed; top: auto; bottom: 0; left: 0; right: 0; padding: 6px 8px env(safe-area-inset-bottom, 0px);
      height: var(--xb-nav-h); gap: 0; background: color-mix(in srgb, var(--xb-card) 92%, transparent);
      backdrop-filter: saturate(1.4) blur(16px); -webkit-backdrop-filter: saturate(1.4) blur(16px);
      border-top: 1px solid var(--xb-line); z-index: 4; }
    .nav-item { flex: 1; flex-direction: column; gap: 4px; padding: 6px 0; font-size: 11px; border-radius: 12px; }
    .nav-item svg { width: 20px; height: 20px; }
    .nav-item.active { background: none; color: var(--xb-text); }
    .nav-item.active svg { color: var(--xb-gold); }
    .content { padding: 14px 14px; padding-bottom: calc(24px + var(--xb-nav-h)); gap: 14px; }
    .card { padding: 16px; }
    .recipe-panel .art-banner { margin: 0 -16px; }
    .device-stage { margin: -16px -16px 0; height: 190px; }
    .device-img { height: 172px; width: 172px; }
    .recipe-panel > .card-head:first-child { margin-top: 16px; }
    .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .rc-body { padding: 10px 12px 12px; }
    .rc-name { font-size: 16px; }
    .art-figure { font-size: 22px; left: 12px; bottom: 8px; }
    .cols { grid-template-columns: minmax(0, 1fr); }
    .btn { min-width: 0; flex-basis: 40%; }
    .actions > .btn.go:first-child { flex-basis: 100%; }
    .card-head select { max-width: 100%; }
    .title { display: none; }
    .big { font-size: 48px; }
    h1 { font-size: 26px; }
  }
`;

customElements.define("xbloom-panel", XBloomPanel);
