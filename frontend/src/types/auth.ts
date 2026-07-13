export interface AuthUser {
  email: string;
  display_name?: string | null;
  role: string;
}

export interface AuthResponse {
  success: boolean;
  message?: string | null;
  user?: AuthUser | null;
}

export interface AuthMeResponse {
  authenticated: boolean;
  user?: AuthUser | null;
}


export interface AdminAccount {
  email: string;
  display_name?: string | null;
  role: string;
  whitelist_enabled: boolean;
  registered: boolean;
  is_active: boolean;
}

export interface AdminAccountsResponse {
  items: AdminAccount[];
}
