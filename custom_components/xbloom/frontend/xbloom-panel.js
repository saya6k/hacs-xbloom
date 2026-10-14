/*
 * XBloom sidebar panel — a self-contained management UI modeled on the
 * official XBloom app (Brew / Recipes / Manual / Settings).
 *
 * Build-free on purpose: one vanilla web component, no dependencies, so
 * HACS ships it as-is. Live state comes from the entities (the `hass`
 * object the frontend hands every panel); actions go through the same
 * entities and services everything else uses. The one backend call is
 * `xbloom/machines` (panel.py) for the entity map and the full recipe
 * store.
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

// The app's temperature slider: 39-96 °C, with RT (20) / BP (98) at its ends.
const tempLabel = (t) => (Number(t) <= 20 ? "RT" : Number(t) >= 98 ? "BP" : `${num(t)}°`);
const tempToSlider = (t) => (t <= 20 ? 38 : t >= 98 ? 97 : Math.min(96, Math.max(39, t)));
const sliderToTemp = (s) => (s <= 38 ? 20 : s >= 97 ? 98 : s);

const PATTERN_ICON = {
  center: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>',
  circular: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  spiral: '<svg viewBox="0 0 24 24"><path d="M12 12m0 0a1.5 1.5 0 0 1 3 0a3 3 0 0 1-6 0a4.5 4.5 0 0 1 9 0a6 6 0 0 1-12 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
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
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
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
    root.addEventListener("pointerdown", () => { this._pointerDown = true; });
    window.addEventListener("pointerup", () => {
      this._pointerDown = false;
      setTimeout(() => {
        if (this._pendingRender && !this._hasFocus()) this._render();
      }, 0);
    });
    // A render deferred while a control had focus lands once it lets go.
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
        this._entryId = this._machines[0]?.entry_id || null;
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
    if (d.field || d.pour) this._onInput(ev, true);
    return undefined;
  }

  _onInput(ev, committed = false) {
    const el = ev.target;
    const d = el.dataset;
    if (d.search !== undefined) {
      this._filter.q = el.value;
      this._renderRecipeGrid();
      return;
    }
    if (d.rangeLabel) {
      const out = this.shadowRoot.querySelector(`[data-range-out="${d.rangeLabel}"]`);
      if (out) out.textContent = el.value;
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
        : `<div class="title">${esc(m?.title || "XBloom")}</div>`;
    const conn = m
      ? `<button class="chip ${this._connected ? "on" : ""}" data-action="toggle-connection">
           <span class="dot"></span>${esc(this._connected ? this._fmt("sensor.state") : this._t("offline"))}
         </button>`
      : "";
    return `
      <div class="toolbar">
        <ha-menu-button></ha-menu-button>
        ${picker}
        <div class="spacer"></div>
        ${conn}
      </div>
      ${m ? `<nav class="tabs">${tabs
        .map((t) => `<button class="tab ${this._tab === t ? "active" : ""}" data-action="tab" data-arg="${t}">${this._t(`tab_${t}`)}</button>`)
        .join("")}</nav>` : ""}
      <div class="content">${this._renderBody()}</div>`;
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
    return `
      ${alerts.map((a) => `<div class="alert">${esc(a)}</div>`).join("")}
      <section class="hero">
        <div class="ring" data-target="${target}">
          <svg viewBox="0 0 120 120">
            <circle class="track" cx="60" cy="60" r="52"/>
            <circle class="bar" cx="60" cy="60" r="52" data-live-ring
              stroke-dasharray="326.7" stroke-dashoffset="326.7"/>
          </svg>
          <div class="ring-center">
            <div class="big" data-live="sensor.weight">–</div>
            <div class="sub">${esc(this._fmt("sensor.state"))}</div>
            ${target ? `<div class="sub muted">${this._t("target")} ${num(target)} ml</div>` : ""}
          </div>
        </div>
        <div class="stats">
          <div><span class="label">${this._t("brewer_temp")}</span><span data-live="sensor.brewer_temperature">–</span></div>
          <div><span class="label">${this._t("flow")}</span><span data-live="sensor.flow_rate">–</span></div>
        </div>
      </section>

      <section class="card">
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

      ${armed ? `<div class="hint">${this._t("armed_hint")}</div>` : ""}
      <div class="actions">
        ${pausable
          ? `<button class="btn primary" data-action="press" data-arg="button.pause">${this._t(state === "paused" ? "resume" : "pause")}</button>`
          : `<button class="btn primary" data-action="press" data-arg="button.execute_recipe" ${!recipe || busy || (armed && state !== "armed_recipe") ? "disabled" : ""}>
               ${this._t(state === "armed_recipe" ? "start_brew" : "load_recipe")}</button>`}
        <button class="btn" data-action="press" data-arg="button.cancel" ${IDLE_STATES.has(state) ? "disabled" : ""}>${this._t("cancel")}</button>
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
            <div class="pour-vol">${num(p.volume_ml)} ml <span class="muted">→ ${num(acc)} ml</span></div>
            <div class="pour-meta">
              <span>${tempLabel(p.temperature_c)}</span>
              <span>${num(p.flow_rate ?? 3, 1)} ml/s</span>
              <span class="pat">${PATTERN_ICON[PATTERNS[p.pattern] ?? p.pattern] || ""}${this._t(PATTERNS[p.pattern] ?? p.pattern)}</span>
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
    const kinds = ["all", "coffee", "tea"];
    return `
      <div class="recipes-bar">
        <input class="search" type="search" data-search placeholder="${this._t("search")}" value="${esc(this._filter.q)}">
        <div class="segmented">${kinds
          .map((k) => `<button class="${this._filter.kind === k ? "active" : ""}" data-action="filter" data-arg="${k}">${this._t(k)}</button>`)
          .join("")}</div>
        <button class="btn primary small" data-action="new-recipe">+ ${this._t("new_recipe")}</button>
      </div>
      <div class="grid" id="recipe-grid">${this._recipeCards()}</div>`;
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
          <div class="rc-top"><span class="badge ${tea ? "tea" : ""}">${this._t(`cup_${r.cup_type}`)}</span></div>
          <div class="rc-name">${esc(r.name)}</div>
          <div class="rc-specs">
            ${tea ? "" : `<span>${num(r.dose_g, 1)}g</span><span>1:${num(r.ratio, 1)}</span>`}
            <span>${num(totalWater(r))}ml</span>
            <span>${tempLabel(r.pours?.[0]?.temperature_c)}</span>
            ${tea ? "" : `<span>#${num(r.grind_size)}</span>`}
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
      <section class="card detail">
        <div class="detail-head">
          <span class="badge ${isTea(r) ? "tea" : ""}">${this._t(`cup_${r.cup_type}`)}</span>
          <h1>${esc(r.name)}</h1>
          ${r.source ? `<div class="muted small">${this._t("source")}: ${esc(r.source)}</div>` : ""}
        </div>
        ${this._renderRecipeMetrics(r)}
        ${isTea(r) ? "" : `<div class="kv"><span>${this._t("rpm")}</span><span>${num(r.rpm)}</span></div>`}
        <h2>${this._t("pours")}</h2>
        ${this._renderPourTimeline(r)}
      </section>
      ${blocked ? `<div class="hint">${this._t("busy_hint")}</div>` : ""}
      <div class="actions">
        <button class="btn primary" data-action="brew" data-arg="${esc(r.uid)}" ${blocked ? "disabled" : ""}>${this._t("brew_this")}</button>
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
          <input type="range" data-pour="${i}:temperature_c" data-kind="temp" min="38" max="97" step="1" value="${tempToSlider(t)}">
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
    const unit = a.unit_of_measurement || "";
    return `
      <label class="field wide"><span>${this._t(label)} <b><span data-range-out="${key}">${Number.isFinite(v) ? num(v) : "–"}</span> ${esc(unit)}</b></span>
        <input type="range" data-number="${key}" data-range-label="${key}" min="${a.min}" max="${a.max}" step="${a.step}"
          value="${Number.isFinite(v) ? v : a.min}" ${s.state === "unavailable" ? "disabled" : ""}>
      </label>`;
  }

  _renderManual() {
    const state = this._state;
    const busy = BUSY_STATES.has(state) || ARMED_STATES.has(state);
    const patternState = this._st("select.pour_pattern");
    return `
      <div class="hint">${this._t("arm_hint")}</div>
      <section class="card">
        <h2>${this._t("grinder")}</h2>
        ${this._numberControl("number.grind_size", "grind_size")}
        ${this._numberControl("number.rpm", "rpm")}
        <div class="stats inline">
          <div><span class="label">${this._t("grind")}</span><span data-live="sensor.live_grind_size">–</span></div>
          <div><span class="label">${this._t("rpm")}</span><span data-live="sensor.live_grind_speed">–</span></div>
        </div>
        <div class="actions">
          <button class="btn primary" data-action="press" data-arg="button.grind" ${busy ? "disabled" : ""}>
            ${this._t(state === "standalone_grind" ? "start_grind" : "grind_btn")}</button>
          <button class="btn" data-action="press" data-arg="button.cancel" ${IDLE_STATES.has(state) ? "disabled" : ""}>${this._t("cancel")}</button>
        </div>
      </section>

      <section class="card">
        <h2>${this._t("brewer")}</h2>
        ${this._numberControl("number.volume", "volume")}
        ${this._numberControl("number.temperature", "temperature")}
        ${patternState ? `
        <div class="segmented wide">${(patternState.attributes.options || PATTERNS)
          .map((o) => `<button class="${patternState.state === o ? "active" : ""}" data-action="set-pattern" data-arg="${esc(o)}">${PATTERN_ICON[o] || ""}${this._t(o)}</button>`)
          .join("")}</div>` : ""}
        <div class="actions">
          <button class="btn primary" data-action="press" data-arg="button.pour" ${busy ? "disabled" : ""}>
            ${this._t(state === "standalone_pour" ? "start_pour" : "pour")}</button>
          <button class="btn" data-action="press" data-arg="button.pause" ${PAUSABLE_STATES.has(state) ? "" : "disabled"}>${this._t(state === "paused" ? "resume" : "pause")}</button>
        </div>
      </section>

      <section class="card">
        <h2>${this._t("scale")}</h2>
        <div class="big center" data-live="sensor.weight">–</div>
        <div class="actions">
          <button class="btn" data-action="press" data-arg="button.tare_scale">${this._t("tare")}</button>
          <button class="btn" data-action="press" data-arg="button.scale_mode">${this._t(state === "standalone_scale" ? "exit_scale" : "scale_mode")}</button>
        </div>
      </section>`;
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

      <section class="card">
        <h2>${this._t("device")}</h2>
        <div class="kv"><span>${this._t("mac")}</span><span>${esc(m.mac)}</span></div>
        <div class="kv"><span>${this._t("serial")}</span><span>${esc(this._fmt("sensor.serial_number"))}</span></div>
        <div class="kv"><span>${this._t("firmware")}</span><span>${esc(fw?.attributes.installed_version || "–")}</span></div>
      </section>`;
  }

  // ---------------------------------------------------------------- live

  _updateLive() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-live]").forEach((el) => {
      el.textContent = this._fmt(el.dataset.live);
    });
    const ring = root.querySelector("[data-live-ring]");
    if (ring) {
      const target = Number(ring.closest(".ring").dataset.target) || 0;
      const w = Number(this._val("sensor.weight"));
      const frac = target > 0 && Number.isFinite(w) ? Math.max(0, Math.min(1, w / target)) : 0;
      ring.setAttribute("stroke-dashoffset", String(326.7 * (1 - frac)));
    }
  }
}

const STYLE = `
  :host {
    --xb-accent: var(--primary-color, #b5764a);
    --xb-bg: var(--primary-background-color, #f6f4f1);
    --xb-card: var(--card-background-color, #fff);
    --xb-text: var(--primary-text-color, #1c1b1a);
    --xb-muted: var(--secondary-text-color, #7a756f);
    --xb-line: var(--divider-color, rgba(0,0,0,.08));
    --xb-tea: #6b8f5e;
    --xb-danger: var(--error-color, #c0392b);
    --xb-radius: 18px;
    display: block; min-height: 100vh; background: var(--xb-bg); color: var(--xb-text);
    font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
  }
  * { box-sizing: border-box; }
  button { font: inherit; color: inherit; cursor: pointer; }
  button:disabled { opacity: .4; cursor: default; }
  select, input { font: inherit; color: var(--xb-text); background: var(--xb-bg);
    border: 1px solid var(--xb-line); border-radius: 10px; padding: 8px 10px; min-width: 0; }
  input[type=range] { width: 100%; padding: 0; border: 0; background: none; accent-color: var(--xb-accent); }
  .toolbar { display: flex; align-items: center; gap: 8px; height: var(--header-height, 56px);
    padding: 0 12px; background: var(--app-header-background-color, var(--xb-card));
    color: var(--app-header-text-color, var(--xb-text)); border-bottom: 1px solid var(--xb-line);
    position: sticky; top: 0; z-index: 2; }
  .title { font-size: 20px; font-weight: 500; }
  .machine-picker { font-size: 16px; }
  .spacer { flex: 1; }
  .chip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--xb-line);
    border-radius: 999px; padding: 4px 12px; background: transparent; font-size: 13px; }
  .chip .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--xb-muted); }
  .chip.on .dot { background: var(--success-color, #43a047); }
  .tabs { display: flex; gap: 4px; padding: 8px 12px 0; max-width: 960px; margin: 0 auto; overflow-x: auto; }
  .tab { border: 0; background: none; padding: 10px 14px; font-size: 15px; color: var(--xb-muted);
    border-bottom: 2px solid transparent; white-space: nowrap; }
  .tab.active { color: var(--xb-text); border-bottom-color: var(--xb-text); font-weight: 600; }
  .content { max-width: 960px; margin: 0 auto; padding: 16px; display: flex; flex-direction: column; gap: 14px; }
  .card { background: var(--xb-card); border-radius: var(--xb-radius); padding: 16px;
    box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.06)); display: flex; flex-direction: column; gap: 12px; }
  h1 { font-size: 24px; font-weight: 600; margin: 4px 0 0; }
  h2 { font-size: 15px; font-weight: 600; margin: 4px 0; letter-spacing: .02em; }
  .label { font-size: 12px; color: var(--xb-muted); text-transform: uppercase; letter-spacing: .06em; }
  .muted { color: var(--xb-muted); }
  .small { font-size: 13px; }
  .empty { text-align: center; color: var(--xb-muted); padding: 48px 0; }
  .alert { background: color-mix(in srgb, var(--xb-danger) 12%, transparent); color: var(--xb-danger);
    border-radius: 12px; padding: 10px 14px; font-weight: 500; }
  .hint { background: color-mix(in srgb, var(--xb-accent) 12%, transparent); border-radius: 12px; padding: 10px 14px; font-size: 14px; }
  .warn { color: var(--xb-danger); font-size: 13px; margin-top: 4px; }
  .hero { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 8px 0; }
  .ring { position: relative; width: min(260px, 70vw); aspect-ratio: 1; }
  .ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
  .ring circle { fill: none; stroke-width: 6; }
  .ring .track { stroke: var(--xb-line); }
  .ring .bar { stroke: var(--xb-accent); stroke-linecap: round; transition: stroke-dashoffset .4s ease; }
  .ring-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; text-align: center; }
  .big { font-size: 44px; font-weight: 300; letter-spacing: -.02em; }
  .big.center { text-align: center; }
  .sub { font-size: 15px; }
  .stats { display: flex; gap: 32px; justify-content: center; }
  .stats > div { display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: 18px; }
  .stats.inline { justify-content: flex-start; }
  .card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .card-head select { flex: 1; max-width: 60%; }
  .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(72px, 1fr)); gap: 8px; }
  .metric { text-align: center; padding: 8px 4px; border-radius: 12px; background: var(--xb-bg); }
  .metric .value { font-size: 22px; font-weight: 400; }
  .metric small { font-size: 12px; margin-left: 2px; color: var(--xb-muted); }
  .timeline { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .timeline li { display: flex; gap: 12px; position: relative; padding-bottom: 14px; }
  .timeline li:not(:last-child)::before { content: ""; position: absolute; left: 13px; top: 28px; bottom: 0; width: 2px; background: var(--xb-line); }
  .timeline.compact li { padding-bottom: 8px; }
  .step { flex: none; width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center;
    background: var(--xb-text); color: var(--xb-card); font-size: 13px; font-weight: 600; }
  .bypass .step { background: var(--xb-muted); }
  .pour-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .pour-vol { font-weight: 500; }
  .pour-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--xb-muted); font-size: 13px; }
  .pat { display: inline-flex; align-items: center; gap: 4px; }
  svg { width: 16px; height: 16px; flex: none; }
  .ring svg { width: 100%; height: 100%; }
  .actions { display: flex; gap: 10px; flex-wrap: wrap; }
  .actions.sticky { position: sticky; bottom: 0; padding: 12px 0; background: var(--xb-bg); }
  .btn { flex: 1; min-width: 120px; border: 1px solid var(--xb-line); background: var(--xb-card);
    border-radius: 999px; padding: 12px 18px; font-weight: 500; }
  .btn.primary { background: var(--xb-text); color: var(--xb-card); border-color: var(--xb-text); }
  .btn.danger { color: var(--xb-danger); border-color: var(--xb-danger); }
  .btn.small { flex: none; min-width: 0; padding: 7px 14px; font-size: 14px; }
  .btn.dashed { border-style: dashed; background: transparent; }
  .link { align-self: flex-start; border: 0; background: none; color: var(--xb-muted); padding: 0; font-size: 15px; }
  .icon { border: 1px solid var(--xb-line); background: none; border-radius: 50%; width: 32px; height: 32px; }
  .icon.danger { color: var(--xb-danger); }
  .recipes-bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .search { flex: 1; min-width: 160px; border-radius: 999px; padding: 9px 16px; background: var(--xb-card); }
  .segmented { display: inline-flex; background: var(--xb-bg); border: 1px solid var(--xb-line); border-radius: 999px; padding: 3px; }
  .recipes-bar .segmented { background: var(--xb-card); }
  .segmented button { border: 0; background: none; border-radius: 999px; padding: 6px 14px; display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }
  .segmented button.active { background: var(--xb-text); color: var(--xb-card); }
  .segmented.wide { display: flex; }
  .segmented.wide button { flex: 1; justify-content: center; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
  .recipe-card { text-align: left; border: 1px solid transparent; background: var(--xb-card); border-radius: var(--xb-radius);
    padding: 14px; display: flex; flex-direction: column; gap: 8px; box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.06)); }
  .recipe-card.selected { border-color: var(--xb-accent); }
  .rc-name { font-size: 16px; font-weight: 600; line-height: 1.25; overflow-wrap: anywhere; }
  .rc-specs { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--xb-muted); font-size: 13px; }
  .badge { display: inline-block; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; padding: 3px 8px;
    border-radius: 999px; background: color-mix(in srgb, var(--xb-accent) 15%, transparent); color: var(--xb-accent); }
  .badge.tea { background: color-mix(in srgb, var(--xb-tea) 15%, transparent); color: var(--xb-tea); }
  .detail-head { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
  .kv, .row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 4px 0; }
  .kv span:first-child { color: var(--xb-muted); }
  .slot-row { display: flex; gap: 8px; }
  .field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--xb-muted); min-width: 0; }
  .field b { color: var(--xb-text); font-weight: 600; margin-left: 6px; }
  .field input, .field select { color: var(--xb-text); font-size: 15px; }
  .field-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
  .input-unit { display: flex; align-items: center; gap: 6px; }
  .input-unit input { flex: 1; width: 100%; }
  .input-unit em { font-style: normal; color: var(--xb-muted); font-size: 12px; }
  .summary { font-size: 14px; }
  .pour-head { display: flex; align-items: center; gap: 6px; }
  .slot { display: flex; gap: 12px; align-items: flex-start; padding: 6px 0; }
  .slot-letter { flex: none; width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center;
    background: var(--xb-text); color: var(--xb-card); font-weight: 700; }
  .slot-body { flex: 1; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .slot-name { font-weight: 500; }
  .slot-write { display: flex; gap: 8px; }
  .slot-write select { flex: 1; }
  .adv-row { display: flex; gap: 12px; align-items: flex-end; }
  .adv-row .field { flex: 1; }
  select:disabled { opacity: .6; }
  @media (max-width: 600px) {
    .content { padding: 12px; }
    .btn { min-width: 0; flex-basis: 40%; }
    .card-head select { max-width: 100%; }
  }
`;

customElements.define("xbloom-panel", XBloomPanel);
