import { HomePageClient } from "./HomePageClient";
import { parseAppLocation } from "@/lib/navigation";

const STATIC_INITIAL_LOCATION = parseAppLocation({});

/**
 * Static Server Component: keep `/` fully prerenderable by avoiding route-level
 * `searchParams` reads on the server. URL state is synchronized in the client
 * shell after hydration.
 *
 * Pattern A — server page + client application. URL sync that needs
 * `useSearchParams` is isolated inside HomePageClient under a local Suspense
 * boundary (null fallback) so the shell is not duplicated.
 */
export default function Page() {
  return <HomePageClient initialLocation={STATIC_INITIAL_LOCATION} />;
}
