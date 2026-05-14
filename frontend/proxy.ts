import { NextRequest, NextResponse } from "next/server";

const PUBLIC = ["/login"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get("seo_token")?.value;

  // Public routes: redirect logged-in users away from /login
  if (PUBLIC.some((p) => pathname.startsWith(p))) {
    if (token) return NextResponse.redirect(new URL("/", request.url));
    return NextResponse.next();
  }

  // All other routes: require token
  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Exclude Next.js internals and static assets
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
