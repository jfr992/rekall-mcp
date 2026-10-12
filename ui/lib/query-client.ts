import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/client";

export const retryUnlessClientError = (failureCount: number, error: unknown) =>
  !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failureCount < 2;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: true,
        retry: retryUnlessClientError,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
      mutations: {
        retry: 0,
      },
    },
  });
}
