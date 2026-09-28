export interface DatadogStatus {
  configured: boolean;
  site: string;
  api_host: string;
  app_host: string;
  lookback: string;
  mock: boolean;
}

export interface DatadogLog {
  id: string;
  url: string;
  message: string;
  status: string;
  status_group: string;
  service: string;
  host: string;
  timestamp: string;
  tags: string[];
  matched_terms: string[];
}

export interface DatadogSearchResponse {
  configured: boolean;
  mock: boolean;
  reachable?: boolean;
  site: string;
  api_host: string;
  app_host: string;
  query: {
    error_code: string;
    error_field: string;
    terms: string[];
    log_query: string;
    lookback: string;
  };
  logs: DatadogLog[];
  log_count: number;
  total_matched?: number;
  filtered_out?: number;
  summary: string;
  insights: string[];
  error?: string;
}
