import { HomePageClient } from "./HomePageClient";
import { parseAppLocation } from "@/lib/navigation";

type PageSearchParams = Promise<{
  view?: string | string[];
  section?: string | string[];
  results?: string | string[];
  testId?: string | string[];
}>;

/**
 * Server Component: resolve Next.js 15 searchParams once and pass the canonical
 * location into the client shell so SSR HTML matches the first client render.
 *
 * Pattern A — server page + client application. URL sync that needs
 * `useSearchParams` is isolated inside HomePageClient under a local Suspense
 * boundary (null fallback) so the shell is not duplicated.
 */
export default async function Page({ searchParams }: { searchParams: PageSearchParams }) {
  const query = await searchParams;
  const initialLocation = parseAppLocation(query);
  return <HomePageClient initialLocation={initialLocation} />;
}
