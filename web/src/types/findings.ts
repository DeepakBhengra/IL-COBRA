export type TabFilter = "all" | "two_char" | "patterns" | "mapped";

export interface FindingRow {
  program: string;
  file: string;
  error_code: string;
  error_field: string;
  line: number | string;
  paragraph: string | null;
  section: string | null;
  statement: string;
  condition: string;
  parameters: string;
  error_message: string;
  row_summary: string;
  mapping_detail: string;
  logic_context?: string;
  related?: Array<{ name: string; role: string; line: number }>;
  summary?: string;
  search_text?: string;
  _index?: number;
  _page_row?: number;
  program_summary?: string;
}

export interface FindingsResponse {
  rows: FindingRow[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface MetricsResponse {
  metrics: {
    findings: number;
    programs: number;
    error_codes: number;
    source_files: number;
  };
  tab_counts: Record<TabFilter, number>;
  programs: string[];
}

export interface DefaultConfig {
  source_root: string;
  rules_path: string;
  out_dir: string;
  corora_mappings: string;
  classic_ui_url: string;
  docs_root?: string;
}

export interface ScanRequest {
  source_root: string;
  rules_path: string;
  out_dir: string;
  summarizer: string;
  error_code: string;
  error_field: string;
  corora_mappings: string;
}

export interface ScanResponse {
  program_count: number;
  finding_count: number;
  table_name: string;
}

export interface FilterState {
  q: string;
  programs: string[];
  errorCodes: string;
  fieldContains: string;
  tab: TabFilter;
  page: number;
  pageSize: number;
}

export const DETAIL_FIELDS: Array<[string, keyof FindingRow]> = [
  ["Program", "program"],
  ["Error code", "error_code"],
  ["Error Field", "error_field"],
  ["File", "file"],
  ["Line", "line"],
  ["Paragraph", "paragraph"],
  ["Section", "section"],
  ["Condition", "condition"],
  ["Parameters", "parameters"],
  ["Error message", "error_message"],
  ["Statement", "statement"],
  ["Summary", "row_summary"],
  ["Mapping detail", "mapping_detail"],
];

export const TABLE_COLUMNS: Array<{ key: keyof FindingRow; label: string }> = [
  { key: "error_code", label: "Error Code" },
  { key: "error_field", label: "Error Field" },
  { key: "program", label: "Program" },
  { key: "line", label: "Line" },
  { key: "paragraph", label: "Paragraph" },
  { key: "condition", label: "Condition" },
  { key: "row_summary", label: "Summary" },
];
