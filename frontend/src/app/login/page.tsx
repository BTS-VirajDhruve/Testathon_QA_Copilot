import { Suspense } from "react";
import { AuthSessionShimmer } from "@/components/AuthSessionShimmer";
import { LoginPageClient } from "./LoginPageClient";

export default function LoginPage() {
  return (
    <Suspense fallback={<AuthSessionShimmer />}>
      <LoginPageClient />
    </Suspense>
  );
}
