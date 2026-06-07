"use client";

/*
 * CONTRACT: owns case intake — patient notes, file upload (PDF/image/CSV/TXT/
 *   JSON), and manual vitals entry — and kicks off the orchestration via
 *   store.runPipeline.
 * READS from store: status, caseId, validatedFieldCount, error.
 * WRITES via: lib/api.uploadFile (POST /cases/{id}/files) and
 *   store.runPipeline({ userVitals, fileIds, patientNotes }).
 *
 * Implements: a drag-and-drop dropzone that uploads each file through the api
 * client, a manual vitals form with inline physiological-range validation +
 * units (validateUserVitals / VITAL_BOUNDS), a one-click golden case, and live
 * per-stage status derived from the store's pipeline status. The mandatory
 * safety disclaimer stays visible inline above the run action.
 */

import { useCallback, useId, useMemo, useRef, useState } from "react";
import {
  CheckCircle,
  CircleNotch,
  FileArrowUp,
  FilePlus,
  Flask,
  Play,
  Sparkle,
  TrashSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/Panel";
import { uploadFile, ApiRequestError } from "@/lib/api";
import { useHeartTwinStore, type PipelineStatus } from "@/lib/store";
import { VITAL_BOUNDS, validateUserVitals, safeParseFloat } from "@/lib/validators";
import type { UploadedFile } from "@/types/api";

// ---------------------------------------------------------------------------
// Vitals form schema (field name -> label, unit, placeholder, required flag).
// Field names mirror python/hearttwin/schemas.py UserVitals.
// ---------------------------------------------------------------------------

type VitalKey =
  | "heart_rate_bpm"
  | "systolic_bp_mmhg"
  | "diastolic_bp_mmhg"
  | "edv_ml"
  | "esv_ml"
  | "qt_ms"
  | "height_cm"
  | "weight_kg";

interface VitalField {
  key: VitalKey;
  label: string;
  unit: string;
  placeholder: string;
  required: boolean;
}

const REQUIRED_VITALS: VitalField[] = [
  { key: "heart_rate_bpm", label: "Heart rate", unit: "bpm", placeholder: "88", required: true },
  { key: "systolic_bp_mmhg", label: "Systolic BP", unit: "mmHg", placeholder: "135", required: true },
  { key: "diastolic_bp_mmhg", label: "Diastolic BP", unit: "mmHg", placeholder: "85", required: true },
  { key: "edv_ml", label: "End-diastolic volume", unit: "mL", placeholder: "130", required: true },
  { key: "esv_ml", label: "End-systolic volume", unit: "mL", placeholder: "70", required: true },
];

const OPTIONAL_VITALS: VitalField[] = [
  { key: "qt_ms", label: "QT interval", unit: "ms", placeholder: "400", required: false },
  { key: "height_cm", label: "Height", unit: "cm", placeholder: "175", required: false },
  { key: "weight_kg", label: "Weight", unit: "kg", placeholder: "78", required: false },
];

const ALL_VITALS = [...REQUIRED_VITALS, ...OPTIONAL_VITALS];

const GOLDEN_CASE: Record<VitalKey, string> = {
  heart_rate_bpm: "88",
  systolic_bp_mmhg: "135",
  diastolic_bp_mmhg: "85",
  edv_ml: "130",
  esv_ml: "70",
  qt_ms: "",
  height_cm: "",
  weight_kg: "",
};

const EMPTY_FORM: Record<VitalKey, string> = {
  heart_rate_bpm: "",
  systolic_bp_mmhg: "",
  diastolic_bp_mmhg: "",
  edv_ml: "",
  esv_ml: "",
  qt_ms: "",
  height_cm: "",
  weight_kg: "",
};

const ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.webp,.gif,.csv,.txt,.json,application/pdf,image/*,text/csv,text/plain,application/json";

const MAX_FILE_BYTES = 50 * 1024 * 1024; // 50 MB

// ---------------------------------------------------------------------------
// Pipeline stage model: derive the 4 orchestration stages from store status.
// ---------------------------------------------------------------------------

type StageState = "pending" | "running" | "done" | "error";

interface StageView {
  key: string;
  label: string;
  state: StageState;
}

// Ordered progress ladder: the rank of a status tells us how far the run got.
const STAGE_ORDER: PipelineStatus[] = [
  "idle",
  "creating",
  "created",
  "extracting",
  "extracted",
  "operating",
  "operated",
  "simulating",
  "complete",
];

function rank(status: PipelineStatus): number {
  const i = STAGE_ORDER.indexOf(status);
  return i === -1 ? 0 : i;
}

interface StageDef {
  key: string;
  label: string;
  running: PipelineStatus;
  doneAt: number;
}

const STAGE_DEFS: StageDef[] = [
  { key: "create", label: "Create case", running: "creating", doneAt: rank("created") },
  { key: "extract", label: "Extract evidence", running: "extracting", doneAt: rank("extracted") },
  { key: "operate", label: "Build twin", running: "operating", doneAt: rank("operated") },
  { key: "recover", label: "Simulate recovery", running: "simulating", doneAt: rank("complete") },
];

/** Per-stage completion derived purely from store results (no local memory). */
interface StageProgress {
  create: boolean;
  extract: boolean;
  operate: boolean;
  recover: boolean;
}

function buildStages(status: PipelineStatus, done: StageProgress): StageView[] {
  const completed = [done.create, done.extract, done.operate, done.recover];
  const current = rank(status);

  return STAGE_DEFS.map((d, i): StageView => {
    if (status === "error") {
      // Stages whose results landed before the failure stay done; the first
      // incomplete stage carries the error; later stages remain pending.
      if (completed[i]) return { key: d.key, label: d.label, state: "done" };
      const firstIncomplete = completed.findIndex((c) => !c);
      if (i === firstIncomplete) return { key: d.key, label: d.label, state: "error" };
      return { key: d.key, label: d.label, state: "pending" };
    }
    if (status === d.running) return { key: d.key, label: d.label, state: "running" };
    if (current >= d.doneAt && current > rank("idle"))
      return { key: d.key, label: d.label, state: "done" };
    return { key: d.key, label: d.label, state: "pending" };
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function CaseIntakePanel() {
  const status = useHeartTwinStore((s) => s.status);
  const storeError = useHeartTwinStore((s) => s.error);
  const validatedFieldCount = useHeartTwinStore((s) => s.validatedFieldCount);
  const runPipeline = useHeartTwinStore((s) => s.runPipeline);
  // Result slices used to derive per-stage completion (and the failure marker).
  const caseId = useHeartTwinStore((s) => s.caseId);
  const visualization = useHeartTwinStore((s) => s.visualization);
  const scenarioCount = useHeartTwinStore((s) => s.scenarios.length);

  const reduce = useReducedMotion();
  const fieldsetId = useId();
  const inputRef = useRef<HTMLInputElement>(null);

  const [form, setForm] = useState<Record<VitalKey, string>>(EMPTY_FORM);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const busy =
    status === "creating" ||
    status === "extracting" ||
    status === "operating" ||
    status === "simulating" ||
    status === "improving" ||
    status === "created" ||
    status === "extracted" ||
    status === "operated";

  // ---- validation --------------------------------------------------------
  const { fieldErrors, formErrors, validVitals } = useMemo(() => {
    const fe: Partial<Record<VitalKey, string>> = {};
    // Per-field range / numeric check (only for fields the user has typed in).
    for (const f of ALL_VITALS) {
      const raw = form[f.key];
      if (raw === "") continue;
      const parsed = safeParseFloat(raw);
      if (parsed === null) {
        fe[f.key] = "Enter a number";
        continue;
      }
      const bounds = VITAL_BOUNDS[f.key];
      if (bounds && (parsed < bounds[0] || parsed > bounds[1])) {
        fe[f.key] = `Expected ${bounds[0]}-${bounds[1]} ${f.unit}`;
      }
    }
    const { valid } = validateUserVitals(form);
    return {
      fieldErrors: fe,
      formErrors: Object.keys(fe),
      validVitals: valid,
    };
  }, [form]);

  const missingRequired = REQUIRED_VITALS.filter((f) => form[f.key].trim() === "").map(
    (f) => f.key,
  );

  const hasInput = ALL_VITALS.some((f) => form[f.key] !== "") || notes !== "";

  const fileIds = useMemo(() => files.map((f) => f.file_id), [files]);

  const canRun =
    !busy &&
    formErrors.length === 0 &&
    (missingRequired.length === 0 || fileIds.length > 0);

  const stageProgress = useMemo<StageProgress>(
    () => ({
      create: Boolean(caseId),
      extract: validatedFieldCount > 0,
      operate: Boolean(visualization),
      recover: scenarioCount > 0,
    }),
    [caseId, validatedFieldCount, visualization, scenarioCount],
  );

  const stages = useMemo(
    () => buildStages(status, stageProgress),
    [status, stageProgress],
  );

  const showStages = status !== "idle";

  // ---- handlers ----------------------------------------------------------
  const setField = useCallback((key: VitalKey, value: string) => {
    // Allow only numeric-ish input (digits, one dot, optional leading minus).
    if (value !== "" && !/^-?\d*\.?\d*$/.test(value)) return;
    setForm((prev) => ({ ...prev, [key]: value }));
  }, []);

  const loadGolden = useCallback(() => {
    setForm({ ...GOLDEN_CASE });
    setTouched(
      Object.fromEntries(REQUIRED_VITALS.map((f) => [f.key, true])),
    );
    setUploadError(null);
  }, []);

  const clearForm = useCallback(() => {
    setForm({ ...EMPTY_FORM });
    setTouched({});
    setNotes("");
  }, []);

  const ingestFiles = useCallback(
    async (incoming: FileList | File[]) => {
      const list = Array.from(incoming);
      if (list.length === 0) return;

      const tooLarge = list.find((f) => f.size > MAX_FILE_BYTES);
      if (tooLarge) {
        setUploadError(
          `${tooLarge.name} is ${formatBytes(tooLarge.size)}. Limit is 50 MB.`,
        );
        return;
      }

      setUploadBusy(true);
      setUploadError(null);
      try {
        // Ensure a case exists so files attach to it; reuse the active case.
        let caseId = useHeartTwinStore.getState().caseId;
        if (!caseId) {
          const { createCase } = await import("@/lib/api");
          const created = await createCase({ patient_notes: notes || null });
          caseId = created.case_id;
          useHeartTwinStore.setState({
            caseId,
            safetyDisclaimer: created.safety_disclaimer,
          });
          if (created.weave) useHeartTwinStore.getState().setWeave(created.weave);
        }
        for (const file of list) {
          // uploadFile returns UploadedFile plus a safety_disclaimer; the extra
          // field is harmless to keep and assignable to UploadedFile.
          const uploaded: UploadedFile = await uploadFile(caseId, file);
          setFiles((prev) => [...prev, uploaded]);
        }
      } catch (cause) {
        const message =
          cause instanceof ApiRequestError
            ? cause.detail
            : cause instanceof Error
              ? cause.message
              : "Upload failed";
        setUploadError(message);
      } finally {
        setUploadBusy(false);
      }
    },
    [notes],
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      if (busy || uploadBusy) return;
      if (e.dataTransfer.files?.length) void ingestFiles(e.dataTransfer.files);
    },
    [busy, uploadBusy, ingestFiles],
  );

  const removeFile = useCallback((fileId: string) => {
    setFiles((prev) => prev.filter((f) => f.file_id !== fileId));
  }, []);

  const onRun = useCallback(async () => {
    if (!canRun) return;
    setUploadError(null);
    try {
      // Reuse the case the uploaded files were attached to; otherwise let
      // runPipeline create a fresh case. Passing a stale caseId for a manual-
      // only run would re-extract a prior case, so only reuse when files exist.
      const existingCaseId =
        files.length > 0 ? useHeartTwinStore.getState().caseId ?? undefined : undefined;
      await runPipeline({
        caseId: existingCaseId,
        userVitals: validVitals,
        fileIds,
        patientNotes: notes.trim() || undefined,
      });
    } catch {
      // Error is surfaced via store.error and the stage row (lastActiveStage
      // holds the step that was in flight when runPipeline threw).
    }
  }, [canRun, runPipeline, validVitals, fileIds, notes, files.length]);

  const runLabel = busy ? "Running pipeline" : "Run pipeline";

  return (
    // shrink-0 stops the surrounding flex column from compressing this panel
    // below its content (a sibling with h-full would otherwise clip the form
    // and live stages out of the panel's box).
    <Panel className="h-full">
      <PanelHeader
        icon={FileArrowUp}
        accent="accent"
        eyebrow="Stage 0"
        title="Case intake"
        actions={
          <button
            type="button"
            className="ht-btn ht-btn-ghost h-8 px-2.5 text-[0.78rem]"
            onClick={loadGolden}
            disabled={busy}
          >
            <Flask weight="duotone" className="size-4 text-ecg" />
            Golden case
          </button>
        }
      />
      <div className="ht-hairline" />

      <PanelBody className="flex flex-col gap-3 pt-3">
        {/* Imaging & files (collapsible) ----------------------------------- */}
        <details open className="group border border-[var(--ht-line)] bg-surface-2/40">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[0.8rem] font-medium text-ink-2 marker:hidden">
            <FileArrowUp weight="duotone" className="size-4 text-signal" />
            Imaging &amp; files
            {files.length > 0 ? (
              <span className="ht-mono text-[0.66rem] text-muted">{files.length}</span>
            ) : null}
            <span className="ml-auto text-faint transition-transform duration-150 group-open:rotate-90">
              ›
            </span>
          </summary>
          <div className="flex flex-col gap-3 border-t border-[var(--ht-line)] p-3">
        {/* Dropzone -------------------------------------------------------- */}
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload labs, ECG, or imaging files"
          aria-disabled={busy || uploadBusy}
          onClick={() => !busy && !uploadBusy && inputRef.current?.click()}
          onKeyDown={(e) => {
            if ((e.key === "Enter" || e.key === " ") && !busy && !uploadBusy) {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragEnter={(e) => {
            e.preventDefault();
            if (!busy && !uploadBusy) setDragging(true);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={(e) => {
            e.preventDefault();
            if (e.currentTarget === e.target) setDragging(false);
          }}
          onDrop={onDrop}
          className={[
            "group relative flex cursor-pointer flex-col items-center justify-center gap-2 rounded-[var(--ht-r-md)] border border-dashed px-5 py-6 text-center transition-colors duration-150",
            dragging
              ? "border-[var(--ht-accent-line)] bg-[var(--ht-accent-soft)]"
              : "border-[var(--ht-line)] bg-[color-mix(in_oklab,var(--ht-surface-2)_40%,transparent)] hover:border-[var(--ht-signal-line)]",
            busy || uploadBusy ? "cursor-not-allowed opacity-60" : "",
          ].join(" ")}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            tabIndex={-1}
            className="sr-only"
            onChange={(e) => {
              if (e.target.files?.length) void ingestFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <span
            aria-hidden
            className={[
              "grid size-10 place-items-center rounded-full border transition-colors duration-150",
              dragging
                ? "border-[var(--ht-accent-line)] text-accent-bright"
                : "border-[var(--ht-line)] bg-surface-2 text-signal-bright",
            ].join(" ")}
          >
            {uploadBusy ? (
              <CircleNotch
                weight="bold"
                className={`size-5 ${reduce ? "" : "animate-spin"}`}
              />
            ) : (
              <FilePlus weight="duotone" className="size-5" />
            )}
          </span>
          <p className="text-sm font-medium text-ink-2">
            {dragging
              ? "Release to attach evidence"
              : uploadBusy
                ? "Uploading evidence"
                : "Drop labs, ECG, or imaging"}
          </p>
          <p className="max-w-[36ch] text-[0.72rem] leading-relaxed text-muted">
            PDF, image, CSV, TXT, or JSON up to 50 MB. Or enter vitals below. The
            intake agent gates input safety before extraction runs.
          </p>
        </div>

        {/* Uploaded file list --------------------------------------------- */}
        {files.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {files.map((file, i) => (
              <motion.li
                key={file.file_id}
                initial={reduce ? false : { opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: i * 0.03, ease: [0.16, 1, 0.3, 1] }}
                className="flex items-center gap-2.5 rounded-[var(--ht-r-sm)] border border-[var(--ht-line)] bg-surface-2/60 px-2.5 py-2"
              >
                <CheckCircle weight="fill" className="size-4 flex-none text-ecg" />
                <span className="min-w-0 flex-1 truncate text-[0.78rem] text-ink-2">
                  {file.filename}
                </span>
                <span className="ht-mono flex-none text-[0.68rem] text-muted">
                  {formatBytes(file.size_bytes)}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${file.filename}`}
                  onClick={() => removeFile(file.file_id)}
                  disabled={busy}
                  className="ht-btn ht-btn-ghost size-7 min-h-0 flex-none p-0"
                >
                  <X weight="bold" className="size-3.5" />
                </button>
              </motion.li>
            ))}
          </ul>
        ) : null}

        {uploadError ? (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-[var(--ht-r-sm)] border border-[var(--ht-accent-line)] bg-[var(--ht-accent-soft)] px-2.5 py-2 text-[0.74rem] text-ink-2"
          >
            <WarningCircle weight="fill" className="mt-px size-4 flex-none text-accent-bright" />
            {uploadError}
          </p>
        ) : null}

          </div>
        </details>

        {/* Patient notes (collapsible) ------------------------------------- */}
        <details className="group border border-[var(--ht-line)] bg-surface-2/40">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[0.8rem] font-medium text-ink-2 marker:hidden">
            <Sparkle weight="duotone" className="size-4 text-signal" />
            Patient notes
            <span className="ml-auto text-faint transition-transform duration-150 group-open:rotate-90">
              ›
            </span>
          </summary>
          <div className="border-t border-[var(--ht-line)] p-3">
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Symptoms, history, and context. The AI reads vitals from your files and notes."
              className="w-full resize-none border border-[var(--ht-line)] bg-surface-2/60 px-2.5 py-2 text-[0.8rem] text-ink placeholder:text-faint focus-visible:border-[var(--ht-signal-line)]"
            />
          </div>
        </details>

        {/* Vitals — manual entry (fallback when the AI can't extract them) -- */}
        <details className="group border border-[var(--ht-line)] bg-surface-2/40">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[0.8rem] font-medium text-ink-2 marker:hidden">
            <Flask weight="duotone" className="size-4 text-signal" />
            Vitals — manual entry
            <span className="ml-auto text-faint transition-transform duration-150 group-open:rotate-90">
              ›
            </span>
          </summary>
          <fieldset
            className="flex flex-col gap-3 border-t border-[var(--ht-line)] p-3"
            disabled={busy}
          >
            <legend className="sr-only">Manual vitals</legend>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[0.7rem] leading-snug text-muted">
                Only needed if the AI can&apos;t read them from your files or notes.
              </span>
              <button
                type="button"
                onClick={clearForm}
                disabled={busy || !hasInput}
                className="ht-btn ht-btn-ghost h-6 flex-none px-2 text-[0.68rem]"
              >
                <TrashSimple className="size-3.5" />
                Clear
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2.5">
              {ALL_VITALS.map((f) => (
                <VitalInput
                  key={f.key}
                  field={f}
                  value={form[f.key]}
                  error={touched[f.key] ? fieldErrors[f.key] : undefined}
                  idBase={fieldsetId}
                  onChange={(v) => setField(f.key, v)}
                  onBlur={() => setTouched((t) => ({ ...t, [f.key]: true }))}
                />
              ))}
            </div>
          </fieldset>
        </details>

        {/* Live stage status ---------------------------------------------- */}
        {showStages ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="ht-eyebrow">Pipeline</span>
              <span className="ht-mono text-[0.68rem] text-muted">
                {validatedFieldCount > 0
                  ? `${validatedFieldCount} validated fields`
                  : "running"}
              </span>
            </div>
            <ol className="grid gap-1.5">
              {stages.map((s) => (
                <StageRow key={s.key} stage={s} reduce={Boolean(reduce)} />
              ))}
            </ol>
          </div>
        ) : null}

        {/* Pipeline error -------------------------------------------------- */}
        {status === "error" && storeError ? (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-[var(--ht-r-sm)] border border-[var(--ht-accent-line)] bg-[var(--ht-accent-soft)] px-2.5 py-2 text-[0.76rem] text-ink-2"
          >
            <WarningCircle weight="fill" className="mt-px size-4 flex-none text-accent-bright" />
            <span>
              <span className="font-medium text-accent-bright">Pipeline failed. </span>
              {storeError}
            </span>
          </p>
        ) : null}

        {/* Run action ------------------------------------------------------ */}
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={onRun}
            disabled={!canRun}
            aria-disabled={!canRun}
            className="ht-btn ht-btn-primary w-full"
          >
            {busy ? (
              <CircleNotch weight="bold" className={`size-4 ${reduce ? "" : "animate-spin"}`} />
            ) : (
              <Play weight="fill" className="size-4" />
            )}
            {runLabel}
          </button>
          {!busy && !canRun ? (
            <p className="text-center text-[0.7rem] text-muted">
              {formErrors.length > 0
                ? "Fix the highlighted vitals to run."
                : "Enter the five required vitals or attach a file."}
            </p>
          ) : null}
        </div>
      </PanelBody>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function VitalInput({
  field,
  value,
  error,
  idBase,
  onChange,
  onBlur,
}: {
  field: VitalField;
  value: string;
  error?: string;
  idBase: string;
  onChange: (value: string) => void;
  onBlur: () => void;
}) {
  const id = `${idBase}-${field.key}`;
  const errId = `${id}-err`;
  const invalid = Boolean(error);
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="flex items-baseline justify-between text-[0.7rem] text-muted">
        <span className="truncate">{field.label}</span>
        <span className="ht-mono ml-1.5 flex-none text-[0.64rem] text-faint">{field.unit}</span>
      </label>
      <input
        id={id}
        inputMode="decimal"
        autoComplete="off"
        value={value}
        placeholder={field.placeholder}
        aria-invalid={invalid}
        aria-describedby={invalid ? errId : undefined}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
        className={[
          "ht-mono h-9 w-full rounded-[var(--ht-r-sm)] border bg-surface-2/60 px-2.5 text-[0.85rem] text-ink tabular-nums placeholder:text-faint",
          invalid
            ? "border-[var(--ht-accent-line)] focus-visible:border-[var(--ht-accent-line)]"
            : "border-[var(--ht-line)] focus-visible:border-[var(--ht-signal-line)]",
        ].join(" ")}
      />
      {invalid ? (
        <span id={errId} className="text-[0.64rem] leading-tight text-accent-bright">
          {error}
        </span>
      ) : null}
    </div>
  );
}

function StageRow({ stage, reduce }: { stage: StageView; reduce: boolean }) {
  const dataStatus =
    stage.state === "done"
      ? "success"
      : stage.state === "running"
        ? "running"
        : stage.state === "error"
          ? "error"
          : "idle";

  return (
    <motion.li
      layout={!reduce}
      className="flex items-center gap-2.5 rounded-[var(--ht-r-sm)] border border-[var(--ht-line)] bg-surface-2/50 px-2.5 py-1.5"
    >
      <span
        className="grid size-5 flex-none place-items-center"
        aria-hidden
      >
        {stage.state === "done" ? (
          <CheckCircle weight="fill" className="size-4 text-ecg" />
        ) : stage.state === "running" ? (
          <CircleNotch weight="bold" className={`size-4 text-signal-bright ${reduce ? "" : "animate-spin"}`} />
        ) : stage.state === "error" ? (
          <WarningCircle weight="fill" className="size-4 text-accent-bright" />
        ) : (
          <span className="size-2 rounded-full bg-[var(--ht-faint)]" />
        )}
      </span>
      <span
        className={[
          "flex-1 text-[0.78rem]",
          stage.state === "pending" ? "text-muted" : "text-ink-2",
        ].join(" ")}
      >
        {stage.label}
      </span>
      <span className="ht-chip h-5 px-1.5 text-[0.62rem]" data-status={dataStatus}>
        {stage.state === "done"
          ? "done"
          : stage.state === "running"
            ? "live"
            : stage.state === "error"
              ? "failed"
              : "queued"}
      </span>
    </motion.li>
  );
}
