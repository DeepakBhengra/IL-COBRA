export interface JiraStatus {
  configured: boolean;
  base_url: string;
  email: string;
  projects: string[];
  mock: boolean;
}

export interface JiraIssue {
  key: string;
  url: string;
  summary: string;
  status: string;
  status_category: string;
  is_resolved: boolean;
  resolution: string;
  resolution_excerpt: string;
  issue_type: string;
  priority: string;
  assignee: string;
  labels: string[];
  updated: string;
  comment_count: number;
}

export interface JiraSearchResponse {
  configured: boolean;
  mock: boolean;
  reachable?: boolean;
  base_url: string;
  query: {
    error_code: string;
    error_field: string;
    terms: string[];
    jql: string;
  };
  issues: JiraIssue[];
  issue_count: number;
  summary: string;
  insights: string[];
  error?: string;
}
