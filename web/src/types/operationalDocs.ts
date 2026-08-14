export interface TechnicalResolutionRelated {

  name: string;

  role?: string;

}



export interface TechnicalResolution {

  program?: string;

  error_code?: string;

  error_field?: string;

  line?: number;

  paragraph?: string;

  section?: string;

  statement?: string;

  condition?: string;

  row_summary?: string;

  logic_context?: string;

  mapping_detail?: string;

  error_message?: string;

  file?: string;

  related?: TechnicalResolutionRelated[];

}



export interface OperationalDocumentRow {

  document_id: string;

  source_path: string;

  doc_type: string;

  title: string;

  body_preview: string;

  link_score: number;

  link_evidence: string;

  historical_resolution: string;

  technical_resolution: TechnicalResolution;

  resolution_summary: string;

  resolution_steps: string[];

  resolution_confidence: string;

  ingested_at: string;

}



export type ConfirmedResolutionSource = "historical" | "condition";

export interface ConfirmedResolution {
  selected_text: string;
  comment?: string;
  source: ConfirmedResolutionSource;
  error_code: string;
  reviewed_at?: string;
  reviewed_by?: string;
}

export interface ConfirmedResolutionRequest {
  selected_text: string;
  comment?: string;
  source: ConfirmedResolutionSource;
}

export interface OperationalDocsResponse {

  has_artifacts: boolean;

  finding_key: string;

  documents: OperationalDocumentRow[];

  summary: string;

  steps: string[];

  confidence: string;

  provider: string;

  document_count: number;

  last_ingested_at: string;

  confirmed_resolution?: ConfirmedResolution;

}



export interface IngestRequest {

  docs_root: string;

  out_dir: string;

  rules_path?: string;

  resolver: string;

  error_code?: string;

  error_field?: string;

  redact?: boolean;

}



export interface IngestResponse {

  document_count: number;

  linked_count: number;

  resolution_count: number;

}



export interface IngestStatus {

  has_documents: boolean;

  has_resolutions: boolean;

  document_count: number;

  resolution_count: number;

  last_ingested_at: string;

}


