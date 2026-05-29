import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type { QueryClient } from '@tanstack/react-query';
import type { Session, User } from '@supabase/supabase-js';
import { supabase } from '@/lib/supabase';
import { config } from '@/lib/config';

interface AuthContextType {
  session: Session | null;
  user: User | null;
  loading: boolean;
  signInWithGoogle: (redirectPath?: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

interface AuthProviderProps {
  children: ReactNode;
  queryClient?: QueryClient;
}

export function AuthProvider({ children, queryClient }: AuthProviderProps) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const previousUserIdRef = useRef<string | null>(null);
  const hasReceivedFirstEventRef = useRef<boolean>(false);

  useEffect(() => {
    if (!config.supabase.isConfigured) {
      setLoading(false);
      return;
    }

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, nextSession) => {
      const nextUserId = nextSession?.user?.id ?? null;
      const identityChanged = nextUserId !== previousUserIdRef.current;
      const isFirstEvent = !hasReceivedFirstEventRef.current;

      // Skip the cache wipe on the first event of the page lifecycle. The first
      // event (INITIAL_SESSION on Supabase JS >= 2.27, or SIGNED_IN for a session
      // restored from localStorage on older minors) carries the baseline identity,
      // not a real identity change, so wiping here would orphan any in-flight
      // queries already registered by page components that mounted before the
      // auth listener resolved.
      if (queryClient && !isFirstEvent) {
        if (event === 'SIGNED_OUT') {
          queryClient.clear();
        } else if ((event === 'SIGNED_IN' || event === 'USER_UPDATED') && identityChanged) {
          queryClient.clear();
        }
      }

      hasReceivedFirstEventRef.current = true;
      previousUserIdRef.current = nextUserId;
      setSession(nextSession);
      setLoading(false);
    });

    supabase.auth.getSession().then(({ data: { session: initialSession } }) => {
      previousUserIdRef.current = initialSession?.user?.id ?? null;
      setSession(initialSession);
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, [queryClient]);

  const signInWithGoogle = async (redirectPath: string = '/dashboard') => {
    if (!config.supabase.isConfigured) {
      return { error: 'Authentication is not configured.' };
    }

    const redirectTo = new URL(redirectPath, window.location.origin).toString();
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo },
    });
    if (error) return { error: error.message };
    return { error: null };
  };

  const signOut = async () => {
    await supabase.auth.signOut();
    setSession(null);
  };

  return (
    <AuthContext.Provider value={{ session, user: session?.user ?? null, loading, signInWithGoogle, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
