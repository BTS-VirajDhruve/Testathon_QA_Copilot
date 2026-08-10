import { Suspense } from "react";
import { AcceptInvitePageClient } from "./AcceptInvitePageClient";

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={null}>
      <AcceptInvitePageClient />
    </Suspense>
  );
}
