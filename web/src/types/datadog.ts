export interface DatadogServiceCount {
  name: string;
  count: number;
}

export interface DatadogCountryCount {
  code: string;
  count: number;
}

export interface DatadogAnalysisGroup {
  region: string;
  environment: string;
  host: string;
  service: string;
  services: DatadogServiceCount[];
  countries: DatadogCountryCount[];
  count: number;
}

export interface DatadogAnalysisSummary {
  production: number;
  test: number;
  north_america: number;
  emea: number;
  other: number;
  order_create_v6: number;
  order_create_v2: number;
}

export interface DatadogAnalysisReport {
  configured: boolean;
  site?: string;
  api_host?: string;
  auth?: string;
  mock?: boolean;
  error_code: string;
  window_days: number;
  services: string[];
  production_hosts: string[];
  matched: number;
  scanned: number;
  truncated: boolean;
  summary: DatadogAnalysisSummary;
  groups: DatadogAnalysisGroup[];
  error?: string;
}
