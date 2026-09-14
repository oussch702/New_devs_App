// Local authentication client to replace Supabase
interface AuthUser {
  id: string;
  email: string;
  name?: string;
  is_admin?: boolean;
  tenant_id?: string;
  app_metadata?: any;
  user_metadata?: any;
  created_at?: string;
}

interface AuthSession {
  access_token: string;
  refresh_token?: string;
  user: AuthUser;
  token_type: string;
  expires_in?: number;
}

interface AuthResponse {
  data: { user: AuthUser | null; session: AuthSession | null };
  error: Error | null;
}

interface SignInCredentials {
  email: string;
  password: string;
}

class LocalAuthClient {
  private subscribers: ((event: string, session: AuthSession | null) => void)[] = [];
  private session: AuthSession | null = null;
  private storageKey = 'base360-auth-token';
  private sessionVersion = 0;

  constructor() {
    this.loadSession();
  }

  private getApiUrl(): string {
    return import.meta.env.VITE_API_URL || import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';
  }

  private notifySubscribers(event: string, session: AuthSession | null) {
    console.log(`📣 [LocalAuth] Notifying ${this.subscribers.length} subscribers of event: ${event}`);
    this.subscribers.forEach((callback) => {
      try {
        callback(event, session);
      } catch (e) {
        console.error('📣 [LocalAuth] Error in subscriber callback:', e);
      }
    });
  }

  private saveSession(session: AuthSession | null) {
    this.sessionVersion += 1;
    this.session = session;
    if (session) {
      localStorage.setItem(this.storageKey, JSON.stringify(session));
      this.notifySubscribers('SIGNED_IN', session);
    } else {
      localStorage.removeItem(this.storageKey);
      this.notifySubscribers('SIGNED_OUT', null);
    }
  }

  private loadSession() {
    try {
      const stored = localStorage.getItem(this.storageKey);
      if (stored) {
        this.session = JSON.parse(stored);
      }
    } catch (error) {
      console.warn('[LocalAuth] Failed to load session from storage:', error);
      localStorage.removeItem(this.storageKey);
    }
  }

  async signInWithPassword(credentials: SignInCredentials): Promise<AuthResponse> {
    const version = ++this.sessionVersion;
    try {
      const response = await fetch(`${this.getApiUrl()}/api/v1/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(credentials),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.error || `HTTP ${response.status}`);
      }

      if (data.error) {
        throw new Error(data.error);
      }

      const session: AuthSession = {
        access_token: data.access_token,
        token_type: data.token_type || 'bearer',
        user: data.user,
      };

      if (version !== this.sessionVersion) {
        throw new Error('Sign-in was superseded by another session change');
      }
      this.saveSession(session);

      return {
        data: { user: data.user, session },
        error: null,
      };
    } catch (error: any) {
      console.error('[LocalAuth] Sign in failed:', error);
      return {
        data: { user: null, session: null },
        error: error,
      };
    }
  }

  async signOut(): Promise<{ error: Error | null }> {
    try {
      const token = this.session?.access_token;
      // Revoke local access synchronously; a slow logout must not retain a session.
      this.saveSession(null);
      // Call backend logout endpoint if needed
      if (token) {
        try {
          await fetch(`${this.getApiUrl()}/api/v1/auth/logout`, {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${token}`,
            },
          });
        } catch (logoutError) {
          console.warn('[LocalAuth] Backend logout failed (continuing):', logoutError);
        }
      }

      return { error: null };
    } catch (error: any) {
      console.error('[LocalAuth] Sign out failed:', error);
      return { error: error };
    }
  }

  async getSession(): Promise<{ data: { session: AuthSession | null }; error: Error | null }> {
    const session = this.session;
    const version = this.sessionVersion;
    // Check if current session is still valid
    if (session?.access_token) {
      try {
        // Verify token is still valid by calling a protected endpoint
        const response = await fetch(`${this.getApiUrl()}/api/v1/auth/me`, {
          headers: {
            'Authorization': `Bearer ${session.access_token}`,
          },
        });

        // A response from an earlier account cannot clear or restore the current one.
        if (version !== this.sessionVersion) {
          return { data: { session: this.session }, error: null };
        }
        if (response.ok) {
          return { data: { session }, error: null };
        } else if (response.status === 401 || response.status === 403) {
          // Session invalid, clear it
          this.saveSession(null);
        } else {
          return { data: { session: null }, error: new Error('Session validation unavailable') };
        }
      } catch (error) {
        console.warn('[LocalAuth] Session validation failed:', error);
        if (version !== this.sessionVersion) {
          return { data: { session: this.session }, error: null };
        }
        return { data: { session: null }, error: error instanceof Error ? error : new Error('Session validation failed') };
      }
    }

    return { data: { session: null }, error: null };
  }

  async getUser(token?: string): Promise<{ data: { user: AuthUser | null }; error: Error | null }> {
    const tokenToUse = token || this.session?.access_token;

    if (!tokenToUse) {
      return { data: { user: null }, error: null };
    }

    try {
      const response = await fetch(`${this.getApiUrl()}/api/v1/auth/me`, {
        headers: {
          'Authorization': `Bearer ${tokenToUse}`,
        },
      });

      if (response.ok) {
        const userData = await response.json();
        return { data: { user: userData }, error: null };
      } else {
        return { data: { user: null }, error: new Error(`User validation failed (${response.status})`) };
      }
    } catch (error) {
      console.error('[LocalAuth] Get user failed:', error);
      return { data: { user: null }, error: error instanceof Error ? error : new Error('User validation failed') };
    }
  }

  async setSession(session: AuthSession): Promise<{ error: Error | null }> {
    try {
      this.saveSession(session);
      return { error: null };
    } catch (error: any) {
      return { error: error };
    }
  }

  // Mock auth state change handler for compatibility
  onAuthStateChange(callback: (event: string, session: AuthSession | null) => void) {
    // Register subscriber
    this.subscribers.push(callback);

    // Call immediately with current state
    callback('INITIAL_SESSION', this.session);

    // Return unsubscribe function
    return {
      data: {
        subscription: {
          unsubscribe: () => {
            this.subscribers = this.subscribers.filter(cb => cb !== callback);
          }
        }
      }
    };
  }

  // Mock admin interface for compatibility
  get auth() {
    return {
      admin: {
        getUser: this.getUser.bind(this),
        getUserById: (id: string) => this.getUser(),
        listUsers: () => Promise.resolve([]), // Mock implementation
      },
      signInWithPassword: this.signInWithPassword.bind(this),
      signOut: this.signOut.bind(this),
      getSession: this.getSession.bind(this),
      getUser: this.getUser.bind(this),
      setSession: this.setSession.bind(this),
      onAuthStateChange: this.onAuthStateChange.bind(this),
    };
  }
}


export const localAuthClient = new LocalAuthClient();
export default localAuthClient;
