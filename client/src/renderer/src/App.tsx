import { QueryClientProvider } from '@tanstack/react-query';
import { useEffect, type ReactNode } from 'react';
import { installRealtimeInvalidation, queryClient } from '@/api/queries';
import { installTrainingLive } from '@/modules/training/live';
import { LoginScreen } from '@/auth/LoginScreen';
import { Shell } from '@/shell/Shell';
import { useSession } from '@/state/session';

export function App(): ReactNode {
  const loggedIn = useSession((s) => s.me !== null && s.api !== null && !s.me.must_change_password);

  useEffect(() => installRealtimeInvalidation(queryClient), []);
  useEffect(() => installTrainingLive(), []);
  useEffect(() => {
    if (!loggedIn) queryClient.clear(); // never show the previous user's data
  }, [loggedIn]);

  return <QueryClientProvider client={queryClient}>{loggedIn ? <Shell /> : <LoginScreen />}</QueryClientProvider>;
}
