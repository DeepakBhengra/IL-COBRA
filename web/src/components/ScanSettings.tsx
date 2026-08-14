import { useEffect, useState } from "react";

import { getDefaults, runIngest, runScan } from "../api/client";

import type { DefaultConfig, ScanRequest } from "../types/findings";

import type { IngestRequest } from "../types/operationalDocs";



interface ScanSettingsProps {

  onScanComplete: () => void;

}



export function ScanSettings({ onScanComplete }: ScanSettingsProps) {

  const [defaults, setDefaults] = useState<DefaultConfig | null>(null);

  const [form, setForm] = useState<ScanRequest>({

    source_root: "",

    rules_path: "",

    out_dir: "",

    summarizer: "heuristic",

    error_code: "",

    error_field: "",

    corora_mappings: "",

  });

  const [ingestForm, setIngestForm] = useState<IngestRequest>({

    docs_root: "",

    out_dir: "",

    rules_path: "",

    resolver: "heuristic",

    error_code: "",

    error_field: "",

  });

  const [loading, setLoading] = useState(false);

  const [ingestLoading, setIngestLoading] = useState(false);

  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(

    null,

  );

  const [ingestMessage, setIngestMessage] = useState<{

    type: "success" | "error";

    text: string;

  } | null>(null);



  useEffect(() => {

    getDefaults().then((cfg) => {

      setDefaults(cfg);

      setForm({

        source_root: cfg.source_root,

        rules_path: cfg.rules_path,

        out_dir: cfg.out_dir,

        summarizer: "heuristic",

        error_code: "",

        error_field: "",

        corora_mappings: cfg.corora_mappings,

      });

      setIngestForm({

        docs_root: cfg.docs_root ?? "",

        out_dir: cfg.out_dir,

        rules_path: cfg.rules_path,

        resolver: "heuristic",

        error_code: "",

        error_field: "",

      });

    });

  }, []);



  const update = (field: keyof ScanRequest, value: string) => {

    setForm((prev) => ({ ...prev, [field]: value }));

  };



  const updateIngest = (field: keyof IngestRequest, value: string) => {

    setIngestForm((prev) => ({ ...prev, [field]: value }));

  };



  const handleSubmit = async (e: React.FormEvent) => {

    e.preventDefault();

    setLoading(true);

    setMessage(null);

    try {

      const result = await runScan(form);

      setMessage({

        type: "success",

        text: `Scanned ${result.program_count} program(s), found ${result.finding_count} finding(s). Wrote ${result.table_name}.`,

      });

      setIngestForm((prev) => ({ ...prev, out_dir: form.out_dir }));

      onScanComplete();

    } catch (err) {

      setMessage({

        type: "error",

        text: err instanceof Error ? err.message : "Scan failed",

      });

    } finally {

      setLoading(false);

    }

  };



  const handleIngestSubmit = async (e: React.FormEvent) => {

    e.preventDefault();

    setIngestLoading(true);

    setIngestMessage(null);

    try {

      const result = await runIngest({

        ...ingestForm,

        out_dir: ingestForm.out_dir || form.out_dir,

      });

      setIngestMessage({

        type: "success",

        text: `Ingested ${result.document_count} document(s); ${result.linked_count} linked to findings; ${result.resolution_count} resolution(s) written.`,

      });

      onScanComplete();

    } catch (err) {

      setIngestMessage({

        type: "error",

        text: err instanceof Error ? err.message : "Ingestion failed",

      });

    } finally {

      setIngestLoading(false);

    }

  };



  return (

    <div className="scan-form">

      <h2 style={{ marginTop: 0, fontSize: 18 }}>Scan Settings</h2>

      <p style={{ color: "var(--text-muted)", marginBottom: 24 }}>

        Configure and run a COBOL error-code scan. Results are written to the output folder and

        loaded into the findings table.

      </p>

      {message && (

        <div className={`alert alert-${message.type === "success" ? "success" : "error"}`}>

          {message.text}

        </div>

      )}

      <form onSubmit={handleSubmit}>

        <div className="form-group">

          <label htmlFor="source_root">COBOL source root</label>

          <input

            id="source_root"

            type="text"

            value={form.source_root}

            onChange={(e) => update("source_root", e.target.value)}

            required

          />

        </div>

        <div className="form-group">

          <label htmlFor="rules_path">Rules file</label>

          <input

            id="rules_path"

            type="text"

            value={form.rules_path}

            onChange={(e) => update("rules_path", e.target.value)}

            required

          />

        </div>

        <div className="form-group">

          <label htmlFor="out_dir">Output folder</label>

          <input

            id="out_dir"

            type="text"

            value={form.out_dir}

            onChange={(e) => {

              update("out_dir", e.target.value);

              updateIngest("out_dir", e.target.value);

            }}

            required

          />

        </div>

        <div className="form-group">

          <label htmlFor="error_code">Focused error code (optional)</label>

          <input

            id="error_code"

            type="text"

            placeholder="e.g. 1C"

            maxLength={8}

            value={form.error_code}

            onChange={(e) => update("error_code", e.target.value)}

          />

          <p className="hint">Exactly 2 characters when set.</p>

        </div>

        <div className="form-group">

          <label htmlFor="error_field">Focused error field (optional)</label>

          <input

            id="error_field"

            type="text"

            placeholder="e.g. ERR-NO-SEC-EDD-OVRD"

            maxLength={30}

            value={form.error_field}

            onChange={(e) => update("error_field", e.target.value)}

          />

          <p className="hint">Overrides focused error code when both are set. Max 30 characters.</p>

        </div>

        <div className="form-group">

          <label htmlFor="corora_mappings">Mapping folder</label>

          <input

            id="corora_mappings"

            type="text"

            value={form.corora_mappings}

            onChange={(e) => update("corora_mappings", e.target.value)}

          />

        </div>

        <div className="form-group">

          <label htmlFor="summarizer">Summarizer</label>

          <select

            id="summarizer"

            value={form.summarizer}

            onChange={(e) => update("summarizer", e.target.value)}

          >

            <option value="heuristic">heuristic</option>

            <option value="openai">openai</option>

            <option value="ollama">ollama</option>

          </select>

        </div>

        <button type="submit" className="primary-btn" disabled={loading || !defaults}>

          {loading ? "Scanning…" : "Run Scan"}

        </button>

      </form>



      <hr className="settings-divider" />



      <h2 style={{ fontSize: 18 }}>Operational Documents</h2>

      <p style={{ color: "var(--text-muted)", marginBottom: 24 }}>

        Ingest supporting documents from a server-side folder (PDF, DOCX, Confluence HTML exports,

        Jira ticket exports, chat logs, incidents, etc.) and link them to COBOL findings for

        resolution summaries. Documents are matched to the error code(s) in your current scan

        (<code>errors.jsonl</code>). After changing the focused scan code, run ingestion again so

        operational docs align with the new findings.

      </p>

      {ingestMessage && (

        <div className={`alert alert-${ingestMessage.type === "success" ? "success" : "error"}`}>

          {ingestMessage.text}

        </div>

      )}

      <form onSubmit={handleIngestSubmit}>

        <div className="form-group">

          <label htmlFor="docs_root">Documents folder</label>

          <input

            id="docs_root"

            type="text"

            placeholder="Path to operational documents on the server"

            value={ingestForm.docs_root}

            onChange={(e) => updateIngest("docs_root", e.target.value)}

            required

          />

        </div>

        <div className="form-group">

          <label htmlFor="ingest_out_dir">Output folder (scan artifacts)</label>

          <input

            id="ingest_out_dir"

            type="text"

            value={ingestForm.out_dir}

            onChange={(e) => updateIngest("out_dir", e.target.value)}

            required

          />

          <p className="hint">Must contain errors.jsonl from a prior COBOL scan.</p>

        </div>

        <div className="form-group">

          <label htmlFor="ingest_error_code">Focused error code (optional)</label>

          <input

            id="ingest_error_code"

            type="text"

            placeholder="e.g. EV"

            maxLength={8}

            value={ingestForm.error_code ?? ""}

            onChange={(e) => updateIngest("error_code", e.target.value)}

          />

          <p className="hint">
            Leave blank to use error code(s) from the current scan. Re-run ingestion after changing
            the focused scan code.
          </p>

        </div>

        <div className="form-group">

          <label htmlFor="ingest_error_field">Focused error field (optional)</label>

          <input

            id="ingest_error_field"

            type="text"

            placeholder="e.g. ERROR-SHIP-VIA"

            maxLength={30}

            value={ingestForm.error_field ?? ""}

            onChange={(e) => updateIngest("error_field", e.target.value)}

          />

        </div>

        <div className="form-group">

          <label htmlFor="ingest_resolver">Resolver</label>

          <select

            id="ingest_resolver"

            value={ingestForm.resolver}

            onChange={(e) => updateIngest("resolver", e.target.value)}

          >

            <option value="heuristic">heuristic</option>

            <option value="openai">openai</option>

            <option value="ollama">ollama</option>

          </select>

        </div>

        <button type="submit" className="primary-btn" disabled={ingestLoading || !defaults}>

          {ingestLoading ? "Ingesting…" : "Run Ingestion"}

        </button>

      </form>

    </div>

  );

}

